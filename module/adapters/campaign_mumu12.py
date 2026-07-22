import re
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, Final, cast

from module.adapters.campaign_auto_search_mumu12 import (
    Mumu12AutoSearchRuntime,
    Mumu12CampaignAutoSearchExecutor,
    Mumu12CommittedAutoSearchUnit,
)
from module.adapters.campaign_live import (
    CampaignMapRuntime,
    CommittedCampaignUnit,
    build_existing_campaign_map_workflow,
)
from module.adapters.campaign_map_data_mumu12 import apply_normal_enemy_candidate_mask
from module.adapters.campaign_profile_services import compile_campaign_profile_services
from module.adapters.campaign_program_mumu12 import (
    Mumu12CampaignBattleProgramExecutor,
    Mumu12CommittedBattleProgramUnit,
    build_mumu12_battle_program_port,
    read_mumu12_battle_program_mode,
)
from module.adapters.campaign_runtime_hard import CampaignClearModeExecutor
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeSessionOutcome,
)
from module.adapters.campaign_runtime_session import RuntimeProfileLease, RuntimeProfileLeaseState
from module.adapters.campaign_stage_navigator import build_campaign_stage_navigator
from module.adapters.gems_mumu12 import (
    GemsHardPreparationError,
    GemsHardRetryFleetPreparationService,
    Mumu12GemsFleetReplacementExecutor,
    Mumu12GemsRuntimeBehavior,
)
from module.adapters.mumu12 import CancellationAwareMumu12Device, emotion_runtime_overlay
from module.application import AbortRequested, SafeUnitCancellation
from module.base.decorator import cached_property
from module.base.failure import preserve_cleanup_failure
from module.base.utils import location2node
from module.campaign.campaign_engine import CampaignEngine
from module.combat.emotion import Emotion
from module.config.config import AzurLaneConfig, name_to_function
from module.content.battle_policy import BattleFlag
from module.content.campaign_session import (
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
    CampaignSessionStatus,
)
from module.content.runtime_profile import (
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
)
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.content.stage_definition import CampaignStageDefinition, RunVariant
from module.content.stage_rules import (
    ChapterSwitch,
    OneTimeCompletion,
    StageEntrance,
    StageEntrancePreset,
)
from module.device.device import Device
from module.exception import CampaignEnd, MapAchievementReached
from module.gameplay.campaign import (
    CampaignDifficulty,
    CampaignExecutionSettings,
    CampaignJobKind,
    CampaignJobSpec,
    CampaignStopReason,
    GemsFleetReplacementBoundary,
    GemsFleetReplacementRequest,
    GemsFleetReplacementTrigger,
)
from module.gameplay.campaign_factories import CampaignFactoryDependencies, HardCampaignSessionSource
from module.gameplay.campaign_live import (
    CampaignCheckpointReset,
    CampaignGemsReplacementFailed,
    CampaignGuardEvidence,
    CampaignGuardPhase,
    CampaignLiveServices,
    CampaignMapAchievementReached,
)
from module.gameplay.encounter import HardBattleOutcome, HardSettings
from module.hard import assets as hard_assets
from module.logger import logger
from module.map.map_base import CampaignMap
from module.map.map_layout import CampaignMapLayout
from module.map_detection.grid_info import GridInfo
from module.ocr.ocr import Digit, DigitCounter
from module.task_registry import command_to_config_name
from module.ui.assets import CAMPAIGN_MENU_NO_EVENT
from module.ui.page import page_campaign_menu
from module.ui.ui import UI
from module.war_archives.assets import OCR_DATA_KEY_CAMPAIGN, WAR_ARCHIVES_CAMPAIGN_CHECK

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.adapters.battle_program_read_mumu12 import RuntimeProgramState
    from module.adapters.campaign_clear_mode_config import CampaignClearModeConfigService
    from module.adapters.campaign_event_ui import CampaignEventUiServices
    from module.adapters.campaign_map_initialization import CampaignMapInitializationService
    from module.adapters.campaign_profile_services import CampaignProfileServices
    from module.adapters.campaign_program_capabilities import CampaignProgramCapabilityReader
    from module.adapters.campaign_submarine import CampaignSubmarineServices
    from module.application import CancellationSource
    from module.base.button import Button
    from module.combat.combat import CombatEnd
    from module.config.config_generated import ConfigOverrides
    from module.content.battle_program import BattleProgramMode
    from module.content.cell import CellId
    from module.content.mechanic_rules import MapStructureRules
    from module.content.models import StageRef
    from module.content.stage_rules import MapCalibration, StageNavigation
    from module.gameplay.campaign_factories import CampaignSessionSource
    from module.map.map_fleet_preparation import FleetPreparationService
    from module.map.type_alias import GridLocation
    from module.map_detection.grid import Grid


_CHAPTER_SWITCH_FIELDS = {
    ChapterSwitch.EVENT_20241219: "MAP_CHAPTER_SWITCH_20241219",
    ChapterSwitch.SP_20241219: "MAP_CHAPTER_SWITCH_20241219_SP",
    ChapterSwitch.SPEX_20241219: "MAP_CHAPTER_SWITCH_20241219_SPEX",
}
_ENTRANCE_PROFILES = {
    StageEntrancePreset.BLUE: ("blue",),
    StageEntrancePreset.GREEN: ("green",),
    StageEntrancePreset.NORMAL_HALF: ("normal", "half"),
}
_OCR_HARD_REMAIN = Digit(
    hard_assets.OCR_HARD_REMAIN,
    letter=(123, 227, 66),
    threshold=128,
    alphabet="0123",
)
_HARD_RUNTIME_EXTENSION_ID: Final = CampaignRuntimeExtensionId("campaign_hard/campaign_hard/campaign")
_RUNTIME_EXECUTOR_REGISTRY: Final = load_default_campaign_runtime_executor_registry()
_HARD_RUNTIME_EXTENSION: Final = load_default_campaign_runtime_profile_registry().extensions[_HARD_RUNTIME_EXTENSION_ID]


class _DataKeyOcr(DigitCounter):
    @staticmethod
    def normalize_text(result: str) -> str:
        normalized = DigitCounter.normalize_text(result)
        return re.sub(r"(\d{1,2})60$", r"\1/60", normalized)


_OCR_DATA_KEY = _DataKeyOcr(OCR_DATA_KEY_CAMPAIGN, letter=(255, 247, 247), threshold=64)


class CampaignRuntimeEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ActivatedMap:
    session: CampaignSession
    state: CampaignSessionState


def _variant_text(variant: RunVariant, attribute: str) -> str:
    rows: dict[int, list[str]] = {}
    for cell in variant.cells:
        value = getattr(cell, attribute)
        rows.setdefault(cell.cell_id.y, []).append(str(value))
    return "\n".join(" ".join(rows[y]) for y in sorted(rows))


def _spawn_data(variant: RunVariant) -> list[dict[str, int]]:
    return [
        {
            key: value
            for key, value in {
                "battle": wave.battle,
                "enemy": wave.enemy,
                "siren": wave.siren,
                "mystery": wave.mystery,
                "boss": wave.boss,
            }.items()
            if key == "battle" or value
        }
        for wave in variant.spawn_waves
    ]


@dataclass(frozen=True, slots=True)
class _CompiledMapStructures:
    """地图运行时所需的结构数据；后续可按 normal/loop 分别编译。"""

    walls: tuple[tuple[GridLocation, GridLocation], ...]
    maze_data: tuple[tuple[str, ...], ...]
    fortress_data: tuple[tuple[str, ...], tuple[str, ...]]
    bouncing_enemy_data: tuple[tuple[str, ...], ...]


def _node(cell: object) -> str:
    typed = cast("CellId", cell)
    return location2node((typed.x, typed.y))


def _location(cell: object) -> GridLocation:
    typed = cast("CellId", cell)
    return typed.x, typed.y


def _compile_map_structures(structures: MapStructureRules) -> _CompiledMapStructures:
    return _CompiledMapStructures(
        walls=tuple((_location(wall.source), _location(wall.target)) for wall in structures.walls),
        maze_data=tuple(tuple(_node(cell) for cell in group) for group in structures.maze_groups),
        fortress_data=(
            tuple(_node(cell) for cell in structures.fortress_enemy_cells),
            tuple(_node(cell) for cell in structures.fortress_block_cells),
        ),
        bouncing_enemy_data=tuple(tuple(_node(cell) for cell in route) for route in structures.bouncing_enemy_routes),
    )


def _install_map_structures(
    compiled: CampaignMap,
    structures: _CompiledMapStructures,
    *,
    portals: tuple[tuple[GridLocation, GridLocation], ...],
) -> None:
    compiled.topology.configure(walls=structures.walls, portals=portals)
    compiled.maze_data = structures.maze_data
    compiled.fortress_data = structures.fortress_data
    compiled.bouncing_enemy_data = structures.bouncing_enemy_data


def compile_campaign_map(
    definition: CampaignStageDefinition,
    *,
    grid_class: type[GridInfo] = GridInfo,
) -> CampaignMap:
    """把不可变关卡定义编译为旧地图引擎唯一需要的运行对象。"""

    if not isinstance(definition, CampaignStageDefinition):
        message = "campaign map compiler requires a CampaignStageDefinition"
        raise TypeError(message)
    source = definition.map
    compiled = CampaignMap(source.name, layout=CampaignMapLayout(grid_class=grid_class))
    compiled.layout.initialize(location2node((source.shape.columns - 1, source.shape.rows - 1)))
    compiled.layout.set_manual_coverage([location2node((cell.x, cell.y)) for cell in source.map_covered])
    compiled.map_data = _variant_text(source.normal, "token")
    compiled.map_data_loop = _variant_text(source.loop, "token")
    compiled.layout.apply_weights(_variant_text(source.normal, "weight"))
    compiled.layout.set_camera_data([location2node((cell.x, cell.y)) for cell in source.camera_data])
    compiled.layout.set_camera_data_spawn_point(
        [location2node((cell.x, cell.y)) for cell in source.camera_data_spawn_point]
    )
    compiled.land_based_data = [
        (location2node((unit.cell_id.x, unit.cell_id.y)), unit.direction.value) for unit in source.land_based
    ]
    _install_map_structures(
        compiled,
        _compile_map_structures(definition.mechanics.map_structures),
        portals=tuple(
            (
                (portal.source.x, portal.source.y),
                (portal.target.x, portal.target.y),
            )
            for portal in source.portals
        ),
    )
    compiled.spawn_data = _spawn_data(source.normal)
    compiled.spawn_data_loop = _spawn_data(source.loop)
    return compiled


def _navigation_overlay(navigation: StageNavigation | None) -> dict[str, object]:
    values: dict[str, object] = {
        "STAGE_ENTRANCE": ("normal",),
        "MAP_HAS_MODE_SWITCH": False,
        "MAP_CHAPTER_SWITCH_20241219": False,
        "MAP_CHAPTER_SWITCH_20241219_SP": False,
        "MAP_CHAPTER_SWITCH_20241219_SPEX": False,
    }
    if navigation is None:
        return values
    entrance = navigation.entrance
    if isinstance(entrance, StageEntrance):
        values["STAGE_ENTRANCE"] = (entrance.position.value, entrance.revision.value)
    else:
        values["STAGE_ENTRANCE"] = _ENTRANCE_PROFILES[entrance]
    values["MAP_HAS_MODE_SWITCH"] = navigation.has_mode_switch
    if navigation.chapter_switch is not None:
        values[_CHAPTER_SWITCH_FIELDS[navigation.chapter_switch]] = True
    return values


def _calibration_overlay(calibration: MapCalibration | None) -> dict[str, object]:
    if calibration is None:
        return {}
    homography = calibration.homography
    return {
        "MAP_SWIPE_MULTIPLY": (calibration.swipe.horizontal, calibration.swipe.vertical),
        "MAP_SWIPE_MULTIPLY_MINITOUCH": (
            calibration.minitouch_swipe.horizontal,
            calibration.minitouch_swipe.vertical,
        ),
        "HOMO_STORAGE": (
            None
            if homography is None
            else (
                (homography.reference_columns, homography.reference_rows),
                tuple((point.x, point.y) for point in homography.corners),
            )
        ),
        "MAP_ENSURE_EDGE_INSIGHT_CORNER": (
            "" if calibration.edge_insight_corner is None else calibration.edge_insight_corner.value
        ),
    }


def campaign_stage_overlay(definition: CampaignStageDefinition) -> ConfigOverrides:
    """把 typed stage rules 投影到旧地图引擎，不读取关卡 Python Config 类。"""

    if not isinstance(definition, CampaignStageDefinition):
        message = "campaign stage overlay requires a CampaignStageDefinition"
        raise TypeError(message)
    rules = definition.rules
    features = rules.features
    moving = definition.mechanics.moving_enemies
    structures = definition.mechanics.map_structures
    stars = rules.completion.star_requirements
    values: dict[str, object] = {
        "MAP_SIREN_TEMPLATE": features.siren_templates,
        "MAP_HAS_SIREN": features.has_siren,
        "MOVABLE_ENEMY_TURN": moving.turns or features.movable_enemy_turns,
        "MOVABLE_NORMAL_ENEMY_TURN": moving.normal_turns,
        "MAP_HAS_MOVABLE_ENEMY": features.has_movable_enemy or bool(moving.turns),
        "MAP_HAS_MOVABLE_NORMAL_ENEMY": bool(moving.normal_turns),
        "MAP_HAS_MAP_STORY": features.has_map_story,
        "MAP_HAS_FLEET_STEP": features.has_fleet_step,
        "MAP_HAS_AMBUSH": features.has_ambush,
        "MAP_HAS_MYSTERY": features.has_mystery,
        "MAP_HAS_PORTAL": features.has_portal,
        "MAP_HAS_LAND_BASED": features.has_land_based,
        "MAP_HAS_WALL": bool(structures.walls),
        "MAP_HAS_MAZE": bool(structures.maze_groups),
        "MAP_HAS_FORTRESS": bool(structures.fortress_enemy_cells or structures.fortress_block_cells),
        "MAP_HAS_BOUNCING_ENEMY": bool(structures.bouncing_enemy_routes),
        "STAR_REQUIRE_1": stars.first,
        "STAR_REQUIRE_2": stars.second,
        "STAR_REQUIRE_3": stars.third,
        "MAP_IS_ONE_TIME_STAGE": isinstance(rules.completion, OneTimeCompletion),
        **_navigation_overlay(rules.navigation),
        **_calibration_overlay(rules.calibration),
    }
    return cast("ConfigOverrides", values)


def campaign_execution_overlay(settings: CampaignExecutionSettings) -> ConfigOverrides:
    """把领域玩法设置显式投影到旧战斗 primitive，不暴露通用 config bag。"""

    if not isinstance(settings, CampaignExecutionSettings):
        message = "campaign execution overlay requires CampaignExecutionSettings"
        raise TypeError(message)
    automation = settings.automation
    fleets = settings.fleets
    submarine = settings.submarine
    emotion = settings.emotion
    hp = settings.hp_control
    values: dict[str, object] = {
        "Campaign_AmbushEvade": automation.ambush_evade,
        "Campaign_Use2xBook": automation.use_2x_book,
        "Campaign_UseAutoSearch": automation.use_auto_search,
        "Campaign_UseClearMode": automation.use_clear_mode,
        "Campaign_UseFleetLock": automation.use_fleet_lock,
        "Fleet_Fleet1": fleets.fleet1,
        "Fleet_Fleet1Mode": fleets.fleet1_mode.value,
        "Fleet_Fleet1Step": fleets.fleet1_step,
        "Fleet_Fleet2": fleets.fleet2,
        "Fleet_Fleet2Mode": fleets.fleet2_mode.value,
        "Fleet_Fleet2Step": fleets.fleet2_step,
        "Fleet_FleetOrder": fleets.order.value,
        "Submarine_Fleet": submarine.fleet,
        "Submarine_Mode": submarine.mode.value,
        "Submarine_AutoSearchMode": submarine.auto_search_mode.value,
        "Submarine_DistanceToBoss": submarine.distance_to_boss.value,
        "HpControl_UseHpBalance": hp.use_hp_balance,
        "HpControl_UseEmergencyRepair": hp.use_emergency_repair,
        "HpControl_UseLowHpRetreat": hp.use_low_hp_retreat,
        "HpControl_HpBalanceThreshold": hp.hp_balance_threshold,
        "HpControl_HpBalanceWeight": ", ".join(str(weight) for weight in hp.hp_balance_weight),
        "HpControl_RepairUseSingleThreshold": hp.repair_use_single_threshold,
        "HpControl_RepairUseMultiThreshold": hp.repair_use_multi_threshold,
        "HpControl_LowHpRetreatThreshold": hp.low_hp_retreat_threshold,
        "EnemyPriority_EnemyScaleBalanceWeight": settings.enemy_priority.scale_balance_weight.value,
    }
    values.update(emotion_runtime_overlay(emotion))
    return cast("ConfigOverrides", values)


def compose_campaign_attempt_definition(
    definition: CampaignStageDefinition,
    difficulty: CampaignDifficulty,
) -> CampaignStageDefinition:
    """为一次运行组合难度 overlay，不修改 catalog 中的关卡定义。"""

    if not isinstance(definition, CampaignStageDefinition):
        message = "campaign attempt definition requires a CampaignStageDefinition"
        raise TypeError(message)
    if not isinstance(difficulty, CampaignDifficulty):
        message = "campaign attempt difficulty must be a CampaignDifficulty"
        raise TypeError(message)
    if difficulty is CampaignDifficulty.NORMAL:
        return definition
    profile = definition.runtime_profile
    if _HARD_RUNTIME_EXTENSION_ID in {extension.extension_id for extension in profile.extensions}:
        return definition
    effective_profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId(f"{profile.profile_id.value}/hard"),
        (*profile.extensions, _HARD_RUNTIME_EXTENSION),
        profile.tunings,
    )
    return replace(definition, runtime_profile=effective_profile)


class DeclarativeCampaignMapRuntime(CampaignEngine):
    """固定运行类型；关卡差异只来自已编译 definition，不生成 Campaign 子类。"""

    definition: CampaignStageDefinition
    session_variant: CampaignRunVariant
    _gems_behavior: Mumu12GemsRuntimeBehavior | None
    _event_ui_services: CampaignEventUiServices
    _clear_mode_config_service: CampaignClearModeConfigService
    _hard_behavior: CampaignClearModeExecutor | None
    _map_initialization_service: CampaignMapInitializationService
    _configured_boss_fleet: int
    _profile_fleet_preparation_service: FleetPreparationService
    _program_capabilities: CampaignProgramCapabilityReader
    _profile_services: CampaignProfileServices
    _submarine_services: CampaignSubmarineServices
    _runtime_profile: CampaignRuntimeProfileManager
    _runtime_profile_lease: RuntimeProfileLease
    grid_class: type[Grid]
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD: float
    MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD: float
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD: float

    def __init__(self, config: AzurLaneConfig, device: Device, definition: CampaignStageDefinition) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "campaign runtime config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "campaign runtime device must be a Device"
            raise TypeError(message)
        if not isinstance(definition, CampaignStageDefinition):
            message = "campaign runtime definition must be a CampaignStageDefinition"
            raise TypeError(message)
        self.definition = definition
        self._runtime_profile = CampaignRuntimeProfileManager(
            definition.runtime_profile,
            _RUNTIME_EXECUTOR_REGISTRY,
        )
        self._profile_services = compile_campaign_profile_services(self._runtime_profile)
        self._hard_behavior = self._profile_services.hard_behavior
        self.MAP = compile_campaign_map(
            definition,
            grid_class=self._runtime_profile.map_grid_class or GridInfo,
        )
        camera_grid_class = self._runtime_profile.camera_grid_class
        if camera_grid_class is not None:
            self.grid_class = camera_grid_class
        self._runtime_profile.apply_config(config)
        self._clear_mode_config_service = self._profile_services.clear_mode_config
        profile_boss_fleet = self._runtime_profile.configured_boss_fleet
        self._configured_boss_fleet = config.fleet_boss if profile_boss_fleet is None else profile_boss_fleet.index
        self.ENEMY_FILTER = definition.enemy_filter
        self.session_variant = CampaignRunVariant.NORMAL
        self._gems_behavior = None
        super().__init__(config=config, device=device)
        self._runtime_profile.apply_runtime_thresholds(self)
        lease: RuntimeProfileLease | None = None
        try:
            self._runtime_profile.bind(self, self.MAP)
            if self._hard_behavior is not None:
                self._hard_behavior.apply_runtime_config(self)
            lease = RuntimeProfileLease(self._runtime_profile)
            self._runtime_profile_lease = lease
            self._map_initialization_service = self._profile_services.map_initialization
            self._profile_fleet_preparation_service = self._profile_services.fleet_preparation
            self._fleet_preparation_service = self._profile_fleet_preparation_service
            self._submarine_services = self._profile_services.submarine
            self._strategy_set_service = self._profile_services.strategy_set
            self._program_capabilities = self._profile_services.program_capabilities
            self._map_observer = self._profile_services.map_observer
            self._map_swipe_service = self._profile_services.map_swipe
            self._mystery_item_service = self._profile_services.mystery_item
            self._event_ui_services = self._profile_services.event_ui
            self._combat_result_ui = self._event_ui_services.combat_result
            self._map_transition_ui = self._event_ui_services.map_transition
            self.stage_navigator = build_campaign_stage_navigator(
                self,
                self._runtime_profile,
                self._event_ui_services,
            )
        except BaseException as error:
            cleanup = self._runtime_profile.reset if lease is None else lease.discard
            preserve_cleanup_failure(
                error,
                cleanup,
                message="campaign runtime construction and profile cleanup both failed",
            )
            raise

    @property
    def configured_boss_fleet(self) -> int:
        return self._configured_boss_fleet

    def _map_transition_expected_end(self, expected: str) -> CombatEnd | None:
        transition_override = self._map_transition_ui.combat_end_override(self)
        if transition_override is not None:
            return transition_override
        return CampaignEngine.navigation_expected_end(self, expected)

    def navigation_expected_end(self, expected: str) -> CombatEnd | None:
        behavior = self._hard_behavior
        if behavior is not None:
            return behavior.expected_end(expected)
        return self._map_transition_expected_end(expected)

    def handle_clear_mode_config_cover(self) -> bool:
        handled = CampaignEngine.handle_clear_mode_config_cover(self)
        self._clear_mode_config_service.apply(self, handled=handled)
        return handled

    def map_data_init(self, map_: CampaignMap | None) -> None:
        CampaignEngine.map_data_init(self, map_)
        moving = self.definition.mechanics.moving_enemies
        for cell in moving.initial_enemy_cells:
            self.map[(cell.x, cell.y)].is_enemy = True
        for cell in moving.initial_siren_cells:
            self.map[(cell.x, cell.y)].is_siren = True
        apply_normal_enemy_candidate_mask(
            self.map,
            self.definition.map.normal_enemy_spawn_candidates,
            self.session_variant,
        )

    def clear_boss(self) -> bool:
        behavior = self._hard_behavior
        if behavior is not None:
            return behavior.clear_boss(self)
        return CampaignEngine.clear_boss(self)

    def handle_submarine_support_popup(self) -> bool:
        return self._submarine_services.popup.handle(self)

    def handle_boss_appear_refocus(self, preset: GridLocation | None = None) -> None:
        selected = self._runtime_profile.boss_appear_refocus_preset if preset is None else preset
        CampaignEngine.handle_boss_appear_refocus(self, preset=selected)

    def combat_status(self, expected_end: CombatEnd | None = None) -> None:
        threshold = self._runtime_profile.combat_disable_stuck_detection_battle
        if threshold is not None and not self.map_is_clear_mode and self.battle_count >= threshold:
            with self.device.suspend_stuck_detection():
                CampaignEngine.combat_status(self, expected_end=expected_end)
            return
        CampaignEngine.combat_status(self, expected_end=expected_end)

    def configure_gems_behavior(self, behavior: Mumu12GemsRuntimeBehavior) -> None:
        if not isinstance(behavior, Mumu12GemsRuntimeBehavior):
            message = "campaign gems behavior must be a Mumu12GemsRuntimeBehavior"
            raise TypeError(message)
        current = self._gems_behavior
        if current is not None:
            if current.policy != behavior.policy:
                message = "active campaign runtime cannot change its gems policy"
                raise CampaignRuntimeEvidenceError(message)
            # workflow 每轮会刷新 SafeUnitCancellation，但同一地图的心情账本必须连续。
            behavior.emotion = current.emotion
            if "emotion" in self.__dict__:
                self.__dict__["emotion"] = behavior.emotion
        self._gems_behavior = behavior
        self._fleet_preparation_service = GemsHardRetryFleetPreparationService(
            self._profile_fleet_preparation_service,
            behavior.prepare_hard_fleet,
        )

    @cached_property
    def emotion(self) -> Emotion:
        behavior = self._gems_behavior
        return Emotion(config=self.config) if behavior is None else behavior.emotion

    def gems_emotion_replacement_required(self) -> bool:
        behavior = self._gems_behavior
        return False if behavior is None else behavior.replacement_required_before_entry(self.map_battle_count)

    def handle_combat_low_emotion(self) -> bool:
        behavior = self._gems_behavior
        if behavior is None:
            return super().handle_combat_low_emotion()
        return behavior.handle_low_emotion(self)

    def read_battle_flag(self, flag: BattleFlag) -> bool:
        """只暴露 StagePolicy 条件需要的稳定事实；关卡局部状态由 BattleProgram 持有。"""

        if flag is BattleFlag.CLEAR_MODE:
            return self.map_is_clear_mode
        if flag is BattleFlag.MAP_HAS_MOB_MOVE:
            moving = self.definition.mechanics.moving_enemies
            return bool(moving.turns or moving.normal_turns)
        if flag is BattleFlag.USE_SINGLE_FLEET:
            return "standby" in self.config.Fleet_FleetOrder
        message = f"unsupported battle flag: {flag!r}"
        raise CampaignRuntimeEvidenceError(message)

    def is_event_entrance_available(self) -> bool:
        """只返回入口事实；调度变化由 CampaignTask effects 统一提交。"""

        return not self.appear(CAMPAIGN_MENU_NO_EVENT, offset=(20, 20))

    def handle_map_stop(self) -> None:
        """地图成就只产生事实；task disable/关卡推进由 typed workflow 提交。"""


class Mumu12CampaignAttempt:
    """持有一次普通 Campaign 地图尝试的全部可变运行状态。"""

    __slots__ = (
        "_at_boundary",
        "_cancellation",
        "_checkpoint",
        "_device",
        "_entrance",
        "_fresh_combat",
        "_initialization",
        "_job",
        "_lease",
        "_program_capabilities",
        "_program_state",
        "_session",
        "runtime",
    )

    def __init__(
        self,
        runtime: DeclarativeCampaignMapRuntime,
        job: CampaignJobSpec,
        session: CampaignSession,
        device: Device,
        cancellation: CancellationSource,
    ) -> None:
        self.runtime = runtime
        self._job = job
        self._session = session
        self._checkpoint: CampaignSessionState | None = None
        self._at_boundary = False
        self._entrance: Button | None = None
        self._device = device
        self._lease = runtime._runtime_profile_lease  # ruff:ignore[private-member-access] - attempt 接管 runtime 的唯一 lease。
        self._fresh_combat = runtime._submarine_services.fresh_combat  # ruff:ignore[private-member-access] - attempt 固化 profile hook。
        self._initialization = runtime._map_initialization_service  # ruff:ignore[private-member-access] - attempt 固化初始化服务。
        self._program_state = runtime._runtime_profile  # ruff:ignore[private-member-access] - attempt 只暴露窄 program state。
        self._program_capabilities = runtime._program_capabilities  # ruff:ignore[private-member-access] - attempt 只暴露已编译能力。
        self.refresh_cancellation(cancellation)

    @property
    def job(self) -> CampaignJobSpec:
        return self._job

    @property
    def session(self) -> CampaignSession:
        return self._session

    @property
    def checkpoint(self) -> CampaignSessionState | None:
        return self._checkpoint

    @property
    def at_boundary(self) -> bool:
        return self._at_boundary

    @property
    def entrance(self) -> Button | None:
        return self._entrance

    @property
    def cancellation(self) -> SafeUnitCancellation:
        return self._cancellation

    @property
    def program_state(self) -> RuntimeProgramState:
        return self._program_state

    @property
    def program_capabilities(self) -> CampaignProgramCapabilityReader:
        return self._program_capabilities

    @property
    def profile_state(self) -> RuntimeProfileLeaseState:
        return self._lease.state

    @property
    def prepared(self) -> bool:
        return self._checkpoint is None and self._lease.state is RuntimeProfileLeaseState.READY

    @property
    def active(self) -> bool:
        return self._checkpoint is not None and self._lease.active

    def prepare(self, *, at_boundary: bool, entrance: Button | None = None) -> None:
        if not self.prepared:
            message = "active campaign attempt cannot return to prepared ownership"
            raise CampaignRuntimeEvidenceError(message)
        self._at_boundary = at_boundary
        self._entrance = entrance

    def refresh_cancellation(self, cancellation: CancellationSource) -> None:
        unit_cancellation = SafeUnitCancellation(cancellation)
        self.runtime.device = cast("Device", CancellationAwareMumu12Device(self._device, unit_cancellation))
        if self._job.kind is CampaignJobKind.GEMS_FARMING:
            policy = self._job.gems_farming
            if policy is None:
                message = "gems-farming campaign requires GemsFarmingPolicy"
                raise ValueError(message)
            self.runtime.configure_gems_behavior(
                Mumu12GemsRuntimeBehavior(self.runtime.config, policy, unit_cancellation)
            )
        self._cancellation = unit_cancellation

    def initialize(self, variant: CampaignRunVariant) -> None:
        if not isinstance(variant, CampaignRunVariant):
            message = "campaign attempt initialization requires a CampaignRunVariant"
            raise TypeError(message)
        runtime = self.runtime
        runtime.session_variant = variant
        runtime.map_is_clear_mode = variant is CampaignRunVariant.LOOP
        self._lease.start()
        try:
            self._fresh_combat.start(runtime)
            logger.hr("Map init")
            runtime.map_data_init(runtime.MAP)
            self._initialization.pre_control(runtime)
            runtime.map_control_init()
            self._initialization.post_control(runtime)
        except BaseException as error:
            outcome = (
                RuntimeSessionOutcome.INTERRUPTED if isinstance(error, AbortRequested) else RuntimeSessionOutcome.FAILED
            )
            preserve_cleanup_failure(
                error,
                lambda: self.release(outcome),
                message="campaign attempt initialization and cleanup both failed",
            )
            raise

    def mark_active(self, session: CampaignSession, checkpoint: CampaignSessionState) -> None:
        self._session = session
        self._checkpoint = checkpoint
        self._at_boundary = False
        self._entrance = None

    def update_checkpoint(self, checkpoint: CampaignSessionState) -> None:
        if not self.active:
            message = "campaign checkpoint update requires the active attempt"
            raise CampaignRuntimeEvidenceError(message)
        self._checkpoint = checkpoint

    def release(self, outcome: RuntimeSessionOutcome) -> None:
        if self._lease.active:
            self._lease.close(outcome)
            return
        self._lease.discard()


class Mumu12HardCampaignSession:
    """持有一次困难图 workflow turn 的完整 runtime 生命周期。"""

    __slots__ = ("_consumed", "_entrance", "_lease", "_remaining", "_runtime", "_stage")

    def __init__(
        self,
        runtime: DeclarativeCampaignMapRuntime,
        lease: RuntimeProfileLease,
        stage: StageRef,
        entrance: Button,
        remaining: int,
    ) -> None:
        self._runtime = runtime
        self._lease = lease
        self._stage = stage
        self._entrance = entrance
        self._remaining = remaining
        self._consumed = False

    @classmethod
    def open(
        cls,
        runtime: DeclarativeCampaignMapRuntime,
        device: Device,
        stage: StageRef,
        cancellation: CancellationSource,
        remaining_reader: Callable[[Device], int],
    ) -> Mumu12HardCampaignSession:
        lease = runtime._runtime_profile_lease  # ruff:ignore[private-member-access] - session 接管 runtime 的唯一 lease。
        try:
            cls._require_hard_behavior(runtime)
            cls._require_cancellation(cancellation)
            runtime.device = cast(
                "Device",
                CancellationAwareMumu12Device(device, cancellation),
            )
            entrance = runtime.stage_navigator.select(stage.stage_id, mode="hard")
            cancellation.raise_if_requested()
            runtime.device.screenshot()
            cancellation.raise_if_requested()
            remaining = cls._read_remaining(runtime.device, remaining_reader)
        except BaseException as error:
            preserve_cleanup_failure(
                error,
                lease.discard,
                message="hard campaign session opening and cleanup both failed",
            )
            raise
        return cls(runtime, lease, stage, entrance, remaining)

    @property
    def stage(self) -> StageRef:
        return self._stage

    @property
    def remaining(self) -> int:
        return self._remaining

    @staticmethod
    def _require_hard_behavior(runtime: DeclarativeCampaignMapRuntime) -> None:
        if not isinstance(
            runtime._hard_behavior,  # ruff:ignore[private-member-access] - capability 必须在任何交互前验证。
            CampaignClearModeExecutor,
        ):
            message = "hard campaign session requires the typed clear-mode behavior"
            raise CampaignRuntimeProfileError(message)

    @staticmethod
    def _require_cancellation(cancellation: CancellationSource) -> None:
        if isinstance(cancellation, type) or not callable(getattr(cancellation, "raise_if_requested", None)):
            message = "hard campaign session requires a cancellation source"
            raise TypeError(message)

    @staticmethod
    def _read_remaining(device: Device, remaining_reader: Callable[[Device], int]) -> int:
        remaining = remaining_reader(device)
        if type(remaining) is not int or remaining < 0:
            message = "hard remaining reader must return a non-negative integer"
            raise TypeError(message)
        return remaining

    def execute(self, cancellation: CancellationSource) -> None:
        if self._consumed or self._lease.state is not RuntimeProfileLeaseState.READY:
            message = "hard campaign session can execute only once"
            raise CampaignRuntimeEvidenceError(message)
        self._require_cancellation(cancellation)
        cancellation.raise_if_requested()
        self._consumed = True
        runtime = self._runtime
        runtime.session_variant = CampaignRunVariant.LOOP
        runtime.map_is_clear_mode = True
        self._lease.start()
        try:
            self._execute_body(cancellation)
        except AbortRequested as error:
            preserve_cleanup_failure(
                error,
                partial(self._lease.close, RuntimeSessionOutcome.INTERRUPTED),
                message="cancelled hard campaign session and cleanup both failed",
            )
            raise
        except BaseException as error:
            preserve_cleanup_failure(
                error,
                partial(self._lease.close, RuntimeSessionOutcome.FAILED),
                message="hard campaign session and cleanup both failed",
            )
            raise
        self._lease.close(RuntimeSessionOutcome.COMPLETED)

    def _execute_body(self, cancellation: CancellationSource) -> None:
        runtime = self._runtime
        self._entrance.area = self._entrance.button
        runtime.enter_map(self._entrance, mode="hard")
        if not runtime.map_is_auto_search:
            message = "hard campaign session requires the game's clear-mode auto search"
            raise CampaignRuntimeEvidenceError(message)
        runtime.map = runtime.MAP
        runtime.battle_count = 0
        runtime.lv_reset()
        runtime.lv_get()
        for _ in range(20):
            cancellation.raise_if_requested()
            try:
                runtime.auto_search_execute_a_battle()
            except CampaignEnd:
                return
        message = "hard campaign session did not reach settlement within 20 battles"
        raise CampaignRuntimeEvidenceError(message)

    def exit_ui(self, cancellation: CancellationSource) -> None:
        self._require_cancellation(cancellation)
        cancellation.raise_if_requested()
        self._runtime.ensure_auto_search_exit()
        cancellation.raise_if_requested()

    def close(self) -> None:
        self._consumed = True
        if self._lease.active:
            self._lease.close(RuntimeSessionOutcome.INTERRUPTED)
            return
        self._lease.discard()


class DeclarativeCampaignRuntimeFactory:
    """构造完整 runtime，并把唯一 profile lease 原子移交给运行期产品。"""

    __slots__ = ("_runtime_builder",)

    def __init__(
        self,
        runtime_builder: Callable[
            [AzurLaneConfig, Device, CampaignStageDefinition],
            DeclarativeCampaignMapRuntime,
        ] = DeclarativeCampaignMapRuntime,
    ) -> None:
        if isinstance(runtime_builder, type) and not issubclass(runtime_builder, DeclarativeCampaignMapRuntime):
            message = "campaign runtime builder must build DeclarativeCampaignMapRuntime"
            raise TypeError(message)
        if not callable(runtime_builder):
            message = "campaign runtime builder must be callable"
            raise TypeError(message)
        self._runtime_builder = runtime_builder

    def _build_runtime(
        self,
        config: AzurLaneConfig,
        device: Device,
        definition: CampaignStageDefinition,
    ) -> DeclarativeCampaignMapRuntime:
        runtime = self._runtime_builder(config, device, definition)
        if not isinstance(runtime, DeclarativeCampaignMapRuntime):
            message = "campaign runtime builder returned an invalid runtime"
            raise TypeError(message)
        return runtime

    def build_attempt(
        self,
        config: AzurLaneConfig,
        device: Device,
        job: CampaignJobSpec,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CampaignAttempt:
        definition = compose_campaign_attempt_definition(session.definition, job.difficulty)
        runtime = self._build_runtime(config, device, definition)
        lease = runtime._runtime_profile_lease  # ruff:ignore[private-member-access] - factory 接管 runtime 构造的唯一 lease。
        try:
            return Mumu12CampaignAttempt(
                runtime,
                job,
                session,
                device,
                cancellation,
            )
        except BaseException as error:
            preserve_cleanup_failure(
                error,
                lease.discard,
                message="campaign attempt construction and cleanup both failed",
            )
            raise

    def open_hard_session(  # ruff:ignore[too-many-arguments] - 原子 open 同时覆盖 runtime 构造和 discovery 边界。
        self,
        config: AzurLaneConfig,
        device: Device,
        definition: CampaignStageDefinition,
        *,
        stage: StageRef,
        cancellation: CancellationSource,
        remaining_reader: Callable[[Device], int],
    ) -> Mumu12HardCampaignSession:
        runtime = self._build_runtime(config, device, definition)
        return Mumu12HardCampaignSession.open(
            runtime,
            device,
            stage,
            cancellation,
            remaining_reader,
        )


_DECLARATIVE_CAMPAIGN_RUNTIME_FACTORY: Final = DeclarativeCampaignRuntimeFactory()


class Mumu12CampaignRuntimeProvider:
    """一次 workflow turn 只暴露一个与 typed session 精确匹配的固定 runtime。"""

    __slots__ = (
        "_attempt",
        "_config",
        "_device",
        "_runtime_factory",
    )

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        *,
        runtime_factory: DeclarativeCampaignRuntimeFactory = _DECLARATIVE_CAMPAIGN_RUNTIME_FACTORY,
    ) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "campaign provider config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "campaign provider device must be a Device"
            raise TypeError(message)
        if not isinstance(runtime_factory, DeclarativeCampaignRuntimeFactory):
            message = "campaign provider requires DeclarativeCampaignRuntimeFactory"
            raise TypeError(message)
        self._config = config
        self._device = device
        self._runtime_factory = runtime_factory
        self._attempt: Mumu12CampaignAttempt | None = None

    @staticmethod
    def _selected_session(job: CampaignJobSpec) -> CampaignSession:
        progress = job.progress
        if progress is not None:
            session = job.session_for(progress.stage_ref, progress.variant)
            if session is None:
                message = "campaign checkpoint does not belong to the selected job"
                raise ValueError(message)
            return session
        if not job.stage_refs:
            message = "campaign activation requires a selected stage"
            raise ValueError(message)
        session = job.session_for(job.stage_refs[0], CampaignRunVariant.NORMAL)
        if session is None:
            message = "campaign activation requires a normal session"
            raise ValueError(message)
        return session

    def _activate_config(self, job: CampaignJobSpec, definition: CampaignStageDefinition) -> None:
        task = name_to_function(command_to_config_name(job.task_id.value))
        self._config.task = task
        self._config.bind(task)
        values = dict(campaign_execution_overlay(job.execution))
        completion = job.completion_for(definition.ref)
        if completion.resource_free:
            values.update(
                {
                    "Emotion_Mode": "ignore",
                    "Fleet_Fleet2": 0,
                    "Submarine_Fleet": 0,
                }
            )
        values["Campaign_UseAutoSearch"] = False
        values["StopCondition_MapAchievement"] = completion.achievement.value
        values["StopCondition_StageIncrease"] = False
        values["STOP_IF_REACH_LV32"] = job.kind is CampaignJobKind.GEMS_FARMING
        if job.kind is CampaignJobKind.GEMS_FARMING:
            policy = job.gems_farming
            if policy is None:
                message = "gems-farming campaign requires GemsFarmingPolicy"
                raise ValueError(message)
            values.update(
                {
                    "GemsFarming_ChangeFlagship": policy.flagship_change.value,
                    "GemsFarming_CommonCV": policy.common_carrier.value,
                    "GemsFarming_ChangeVanguard": policy.vanguard_change.value,
                    "GemsFarming_CommonDD": policy.common_destroyer.value,
                    "EnemyPriority_EnemyScaleBalanceWeight": "S1_enemy_first",
                }
            )
            if not policy.changes_vanguard:
                values["Emotion_Mode"] = "ignore"
        self._config.replace_runtime_overlay(**cast("ConfigOverrides", values))
        self._config.apply_runtime_overlay(**campaign_stage_overlay(definition))
        self._config.apply_runtime_overlay(
            Campaign_Name=definition.ref.stage_id,
            Campaign_Event=definition.ref.pack_id,
            Campaign_Mode=job.difficulty.value,
        )
        self._device.config = self._config

    def _reset_to_map_boundary(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> None:
        """不构造地图 runtime，仅通过通用 UI 把客户端收口到选图页。"""

        cancellation.raise_if_requested()
        definition = compose_campaign_attempt_definition(session.definition, job.difficulty)
        self._activate_config(job, definition)
        device = cast("Device", CancellationAwareMumu12Device(self._device, cancellation))
        UI(config=self._config, device=device).ui_goto(
            page_campaign_menu,
            skip_first_screenshot=False,
        )
        cancellation.raise_if_requested()

    def _new_attempt(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CampaignAttempt:
        cancellation.raise_if_requested()
        definition = compose_campaign_attempt_definition(session.definition, job.difficulty)
        self._activate_config(job, definition)
        return self._runtime_factory.build_attempt(
            self._config,
            self._device,
            job,
            session,
            cancellation,
        )

    def _release_attempt(self, outcome: RuntimeSessionOutcome) -> None:
        attempt = self._attempt
        self._attempt = None
        if attempt is None:
            return
        attempt.release(outcome)

    def _release_attempt_after_error(
        self,
        error: BaseException,
        outcome: RuntimeSessionOutcome,
        *,
        message: str,
    ) -> None:
        preserve_cleanup_failure(
            error,
            partial(self._release_attempt, outcome),
            message=message,
        )

    @staticmethod
    def _is_event_stage(job: CampaignJobSpec, session: CampaignSession) -> bool:
        return (
            job.kind
            in (
                CampaignJobKind.EVENT,
                CampaignJobKind.EVENT_SP,
                CampaignJobKind.EVENT_DAILY,
                CampaignJobKind.GEMS_FARMING,
            )
            and session.definition.ref.pack_id != "campaign_main"
        )

    @staticmethod
    def _known_resource(value: int) -> int | None:
        if type(value) is not int or value < 0:
            message = "campaign resource reader must return a non-negative integer"
            raise TypeError(message)
        return value if value > 0 else None

    def before_entry(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> CampaignGuardEvidence:
        if self._selected_session(job) != session or state != session.initial_state():
            message = "campaign pre-entry evidence requires the selected map boundary"
            raise ValueError(message)
        attempt = self._attempt
        if attempt is not None and attempt.active:
            message = "fresh campaign entry cannot replace an active map runtime"
            raise CampaignRuntimeEvidenceError(message)
        if attempt is not None:
            self._release_attempt(RuntimeSessionOutcome.INTERRUPTED)
        self._reset_to_map_boundary(job, session, cancellation)
        attempt = self._new_attempt(job, session, cancellation)
        self._attempt = attempt
        runtime = attempt.runtime
        progress = job.progress
        pending = None if progress is None else progress.pending_gems_replacement
        if pending is not None and pending.trigger is GemsFleetReplacementTrigger.HARD_PREPARATION:
            attempt.prepare(at_boundary=True)
            return CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY)
        event_available: bool | None = None
        if self._is_event_stage(job, session):
            cancellation.raise_if_requested()
            event_available = runtime.is_event_entrance_available()
            if not event_available:
                return CampaignGuardEvidence(
                    CampaignGuardPhase.PRE_ENTRY,
                    event_available=False,
                )

        cancellation.raise_if_requested()
        entrance = runtime.stage_navigator.select(
            session.definition.ref.stage_id,
            mode=job.difficulty.value,
        )
        attempt.prepare(
            at_boundary=job.progress is not None,
            entrance=entrance,
        )
        return self._read_pre_entry_evidence(
            job,
            runtime,
            cancellation,
            event_available=event_available,
        )

    def _read_pre_entry_evidence(
        self,
        job: CampaignJobSpec,
        runtime: DeclarativeCampaignMapRuntime,
        cancellation: CancellationSource,
        *,
        event_available: bool | None,
    ) -> CampaignGuardEvidence:
        cancellation.raise_if_requested()
        oil = self._known_resource(runtime.get_oil())
        event_points = None
        event_stage = (
            job.kind
            in (
                CampaignJobKind.EVENT,
                CampaignJobKind.EVENT_SP,
                CampaignJobKind.EVENT_DAILY,
                CampaignJobKind.GEMS_FARMING,
            )
            and runtime.definition.ref.pack_id != "campaign_main"
        )
        if event_stage and job.limits.event_points:
            event_points = self._known_resource(runtime.get_event_pt())
        coin = None
        runs_completed = 0 if job.progress is None else job.progress.runs_completed
        if job.task_balancer is not None and runs_completed >= 1:
            coin = self._known_resource(runtime.get_coin())
        gems_emotion_limit = job.kind is CampaignJobKind.GEMS_FARMING and runtime.gems_emotion_replacement_required()
        data_keys_remaining = None
        if job.kind is CampaignJobKind.WAR_ARCHIVES and runtime.appear(
            WAR_ARCHIVES_CAMPAIGN_CHECK,
            offset=(20, 20),
        ):
            _current, remaining, total = _OCR_DATA_KEY.ocr(runtime.device.image)
            if total > 0:
                data_keys_remaining = remaining
        return CampaignGuardEvidence(
            CampaignGuardPhase.PRE_ENTRY,
            oil=oil,
            event_points=event_points,
            event_available=event_available,
            data_keys_remaining=data_keys_remaining,
            coin=coin,
            gems_emotion_limit=gems_emotion_limit,
        )

    def after_battle(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
    ) -> CampaignGuardEvidence:
        del job
        if state.status is not CampaignSessionStatus.COMPLETED:
            message = "campaign post-battle evidence requires a completed map"
            raise ValueError(message)
        attempt = self._attempt
        if attempt is None or not attempt.active or attempt.session != session:
            message = "campaign post-battle evidence requires the active runtime"
            raise CampaignRuntimeEvidenceError(message)
        runtime = attempt.runtime
        emotion = runtime.emotion
        emotion_bug = not emotion.is_ignore and emotion.total_reduced >= emotion.bug_threshold
        return CampaignGuardEvidence(
            CampaignGuardPhase.POST_BATTLE,
            reach_level_limit=bool(runtime.config.LV_TRIGGERED),
            new_ship=bool(runtime.config.GET_SHIP_TRIGGERED),
            auto_search_oil_limit=bool(runtime.auto_search_oil_limit_triggered),
            auto_search_coin_limit=bool(runtime.auto_search_coin_limit_triggered),
            emotion_bug=emotion_bug,
            gems_level_limit=bool(runtime.config.LV32_TRIGGERED),
            gems_emotion_limit=bool(runtime.config.GEMS_EMOTION_TRIGGERED),
            map_is_100_percent_clear=bool(runtime.map_is_100_percent_clear),
            map_is_3_stars=bool(runtime.map_is_3_stars),
            map_is_threat_safe=bool(runtime.map_is_threat_safe),
        )

    def _attempt_for_activation(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CampaignAttempt:
        attempt = self._attempt
        if attempt is None:
            attempt = self._new_attempt(job, session, cancellation)
            self._attempt = attempt
            return attempt
        if attempt.prepared:
            if attempt.job is not job or attempt.session != session:
                message = "prepared campaign runtime does not match the selected attempt"
                raise CampaignRuntimeEvidenceError(message)
            attempt.refresh_cancellation(cancellation)
            return attempt
        if job.progress is None:
            message = "fresh campaign entry cannot replace an active map runtime"
            raise CampaignRuntimeEvidenceError(message)
        if attempt.session != session:
            message = "campaign checkpoint does not match the retained map runtime"
            raise CampaignRuntimeEvidenceError(message)
        progress_state = job.progress.session_state
        expected = compose_campaign_attempt_definition(session.definition, job.difficulty)
        if (
            attempt.runtime.definition != expected
            or not attempt.active
            or attempt.runtime.session_variant is not progress_state.variant
            or attempt.checkpoint != progress_state
        ):
            message = "retained campaign runtime does not match the selected attempt"
            raise CampaignRuntimeEvidenceError(message)
        attempt.refresh_cancellation(cancellation)
        return attempt

    def _prepare_activation_attempt(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CampaignAttempt | CampaignCheckpointReset:
        progress = job.progress
        attempt_missing = self._attempt is None
        if attempt_missing:
            self._reset_to_map_boundary(job, session, cancellation)
            if progress is not None and progress.session_state != session.initial_state():
                return CampaignCheckpointReset("cold checkpoint was reset to the campaign map boundary")
        attempt = self._attempt_for_activation(job, session, cancellation)
        if not attempt_missing or progress is None:
            return attempt
        if not attempt.prepared:
            message = "cold campaign activation did not create a prepared runtime"
            raise CampaignRuntimeEvidenceError(message)
        attempt.prepare(at_boundary=True)
        return attempt

    def _activate_checkpoint(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        attempt: Mumu12CampaignAttempt,
        progress_state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> _ActivatedMap | CampaignCheckpointReset:
        runtime = attempt.runtime
        cancellation.raise_if_requested()
        runtime.device.screenshot()
        cancellation.raise_if_requested()
        if not runtime.is_in_map():
            self._release_attempt(RuntimeSessionOutcome.INTERRUPTED)
            self._reset_to_map_boundary(job, session, cancellation)
            return CampaignCheckpointReset("client left the retained checkpoint map")
        return _ActivatedMap(session, progress_state)

    def _activate_fresh(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        attempt: Mumu12CampaignAttempt,
        *,
        entrance: Button | None,
    ) -> _ActivatedMap | CampaignMapAchievementReached | CampaignGemsReplacementFailed:
        runtime = attempt.runtime
        if entrance is None:
            entrance = runtime.stage_navigator.select(
                session.definition.ref.stage_id,
                mode=job.difficulty.value,
            )
        entrance.area = entrance.button
        try:
            runtime.enter_map(entrance, mode=job.difficulty.value)
        except GemsHardPreparationError as error:
            return CampaignGemsReplacementFailed(
                GemsFleetReplacementRequest(
                    GemsFleetReplacementTrigger.HARD_PREPARATION,
                    GemsFleetReplacementBoundary.PRE_ENTRY,
                ),
                str(error),
            )
        except MapAchievementReached:
            result = CampaignMapAchievementReached(
                full_clear=bool(runtime.map_is_100_percent_clear),
                three_stars=bool(runtime.map_is_3_stars),
                threat_safe=bool(runtime.map_is_threat_safe),
            )
            self._release_attempt(RuntimeSessionOutcome.COMPLETED)
            return result

        runtime.handle_map_fleet_lock()
        variant = CampaignRunVariant.LOOP if runtime.map_is_clear_mode else CampaignRunVariant.NORMAL
        activated = self._entered_session(job, session, variant)
        state = activated.initial_state()
        attempt.initialize(activated.variant)
        return _ActivatedMap(activated, state)

    @staticmethod
    def _entered_session(
        job: CampaignJobSpec,
        requested: CampaignSession,
        variant: CampaignRunVariant,
    ) -> CampaignSession:
        activated = job.session_for(requested.definition.ref, variant)
        if activated is None:
            message = "entered campaign variant was not compiled"
            raise ValueError(message)
        return activated

    def activate(
        self,
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> CampaignSession | CampaignCheckpointReset | CampaignMapAchievementReached | CampaignGemsReplacementFailed:
        session = self._selected_session(job)
        try:
            progress = job.progress
            prepared = self._prepare_activation_attempt(job, session, cancellation)
            if isinstance(prepared, CampaignCheckpointReset):
                return prepared
            attempt = prepared
            if progress is not None and not attempt.at_boundary:
                result = self._activate_checkpoint(
                    job,
                    session,
                    attempt,
                    progress.session_state,
                    cancellation,
                )
                if isinstance(result, CampaignCheckpointReset):
                    return result
                activated = result
            else:
                fresh = self._activate_fresh(
                    job,
                    session,
                    attempt,
                    entrance=attempt.entrance,
                )
                if not isinstance(fresh, _ActivatedMap):
                    return fresh
                activated = fresh

            self._config.apply_runtime_overlay(
                Campaign_UseAutoSearch=job.execution.automation.use_auto_search,
            )
        except BaseException as error:
            outcome = (
                RuntimeSessionOutcome.INTERRUPTED if isinstance(error, AbortRequested) else RuntimeSessionOutcome.FAILED
            )
            self._release_attempt_after_error(
                error,
                outcome,
                message="campaign activation and runtime cleanup both failed",
            )
            raise
        else:
            attempt.mark_active(activated.session, activated.state)
            return activated.session

    def _active_attempt_for(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CampaignAttempt:
        cancellation.raise_if_requested()
        attempt = self._attempt
        if attempt is None or not attempt.active or attempt.session != session:
            message = "requested campaign session is not the active MuMu12 runtime"
            raise CampaignRuntimeEvidenceError(message)
        return attempt

    def active_runtime(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CampaignMapRuntime:
        attempt = self._active_attempt_for(session, cancellation)
        return cast("CampaignMapRuntime", attempt.runtime)

    def battle_program_mode(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> BattleProgramMode:
        attempt = self._active_attempt_for(session, cancellation)
        return read_mumu12_battle_program_mode(
            attempt.runtime,
            attempt.program_state,
            attempt.program_capabilities,
            cancellation,
        )

    def _commit_active_runtime(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CampaignAttempt:
        cancellation.raise_if_requested()
        attempt = self._attempt
        if attempt is None or not attempt.active or attempt.session != session:
            message = "requested campaign session has no active safe unit"
            raise CampaignRuntimeEvidenceError(message)
        attempt.cancellation.commit()
        return attempt

    def commit_battle_program_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CommittedBattleProgramUnit:
        attempt = self._commit_active_runtime(session, cancellation)
        port = build_mumu12_battle_program_port(
            attempt.runtime,
            attempt.program_state,
            attempt.program_capabilities,
        )
        return Mumu12CommittedBattleProgramUnit(port, attempt.cancellation)

    def commit_auto_search_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CommittedAutoSearchUnit:
        attempt = self._commit_active_runtime(session, cancellation)
        return Mumu12CommittedAutoSearchUnit(
            cast("Mumu12AutoSearchRuntime", attempt.runtime),
            attempt.cancellation,
        )

    def commit_active_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CommittedCampaignUnit:
        attempt = self._commit_active_runtime(session, cancellation)
        return CommittedCampaignUnit(
            cast("CampaignMapRuntime", attempt.runtime),
            attempt.cancellation,
        )

    def commit_replacement_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CommittedCampaignUnit:
        cancellation.raise_if_requested()
        attempt = self._attempt
        if attempt is None or attempt.session != session:
            message = "requested campaign session has no prepared gems replacement unit"
            raise CampaignRuntimeEvidenceError(message)
        attempt.cancellation.commit()
        return CommittedCampaignUnit(
            cast("CampaignMapRuntime", attempt.runtime),
            attempt.cancellation,
        )

    @staticmethod
    def _runtime_outcome(
        state: CampaignSessionState,
        stop_reason: CampaignStopReason,
    ) -> RuntimeSessionOutcome:
        # 地图领域状态优先：地图已完成后换船失败，不应把已完成地图回滚成 runtime failure。
        if state.status is CampaignSessionStatus.COMPLETED:
            return RuntimeSessionOutcome.COMPLETED
        if state.status in (CampaignSessionStatus.FAILED, CampaignSessionStatus.BLOCKED) or stop_reason in (
            CampaignStopReason.FAILED,
            CampaignStopReason.BLOCKED,
            CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_HARD_PREPARATION_FAILED,
        ):
            return RuntimeSessionOutcome.FAILED
        if stop_reason in (
            CampaignStopReason.COMPLETED,
            CampaignStopReason.ONE_TIME_STAGE,
            CampaignStopReason.MAP_ACHIEVEMENT,
            CampaignStopReason.STAGE_INCREASE,
        ):
            return RuntimeSessionOutcome.COMPLETED
        return RuntimeSessionOutcome.INTERRUPTED

    def discard_checkpoint(self) -> None:
        """失效 checkpoint 不再拥有 runtime attempt。"""

        self._release_attempt(RuntimeSessionOutcome.INTERRUPTED)

    def finish(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        stop_reason: CampaignStopReason,
    ) -> None:
        """在 workflow 报告边界闭合 runtime；可恢复报告保留同一地图会话。"""

        if not isinstance(session, CampaignSession):
            message = "campaign runtime finish requires a CampaignSession"
            raise TypeError(message)
        session.validate_state(state)
        if not isinstance(stop_reason, CampaignStopReason):
            message = "campaign runtime finish requires a CampaignStopReason"
            raise TypeError(message)
        resumable = state.status is CampaignSessionStatus.ACTIVE and stop_reason in (
            CampaignStopReason.IN_PROGRESS,
            CampaignStopReason.PROGRAM_CONTINUE,
        )
        if resumable:
            attempt = self._attempt
            if attempt is None or not attempt.active or attempt.session != session:
                message = "resumable campaign report requires the matching active runtime"
                raise CampaignRuntimeEvidenceError(message)
            attempt.update_checkpoint(state)
            return

        outcome = self._runtime_outcome(state, stop_reason)
        self._release_attempt(outcome)


class Mumu12HardCampaignPort:
    """用同一 declarative map runtime 执行困难图，不再加载 campaign Python module。"""

    __slots__ = (
        "_config",
        "_device",
        "_remaining_reader",
        "_runtime_factory",
        "_session",
        "_sessions",
    )

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        sessions: HardCampaignSessionSource,
        *,
        runtime_factory: DeclarativeCampaignRuntimeFactory = _DECLARATIVE_CAMPAIGN_RUNTIME_FACTORY,
        remaining_reader: Callable[[Device], int] | None = None,
    ) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "hard campaign port config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "hard campaign port device must be a Device"
            raise TypeError(message)
        if not isinstance(sessions, HardCampaignSessionSource):
            message = "hard campaign port sessions must implement the hard campaign content contract"
            raise TypeError(message)
        if not isinstance(runtime_factory, DeclarativeCampaignRuntimeFactory):
            message = "hard campaign port requires DeclarativeCampaignRuntimeFactory"
            raise TypeError(message)
        if remaining_reader is not None and not callable(remaining_reader):
            message = "hard remaining reader must be callable"
            raise TypeError(message)
        self._config = config
        self._device = device
        self._sessions = sessions
        self._runtime_factory = runtime_factory
        self._remaining_reader = _read_hard_remaining if remaining_reader is None else remaining_reader
        self._session: Mumu12HardCampaignSession | None = None

    def _stage_ref(self, settings: HardSettings) -> StageRef:
        return self._sessions.resolve_hard_stage_ref(settings.stage)

    def _require_session(self, settings: HardSettings) -> Mumu12HardCampaignSession:
        stage = self._stage_ref(settings)
        session = self._session
        if session is None or session.stage != stage:
            message = "hard campaign operation does not match the active stage"
            raise CampaignRuntimeEvidenceError(message)
        return session

    def remaining_attempts(
        self,
        settings: HardSettings,
        cancellation: CancellationSource,
    ) -> int:
        cancellation.raise_if_requested()
        if self._session is not None:
            message = "hard campaign already has an active runtime"
            raise CampaignRuntimeEvidenceError(message)
        stage = self._stage_ref(settings)
        session = self._sessions.resolve(stage, CampaignRunVariant.LOOP)
        definition = compose_campaign_attempt_definition(session.definition, CampaignDifficulty.HARD)
        self._config.apply_runtime_overlay(**campaign_stage_overlay(definition))
        self._config.apply_runtime_overlay(
            Campaign_Name=definition.ref.stage_id,
            Campaign_Event=definition.ref.pack_id,
            Campaign_Mode=CampaignDifficulty.HARD.value,
        )
        self._device.config = self._config
        session = self._runtime_factory.open_hard_session(
            self._config,
            self._device,
            definition,
            stage=stage,
            cancellation=cancellation,
            remaining_reader=self._remaining_reader,
        )
        self._session = session
        return session.remaining

    def advance_one(
        self,
        settings: HardSettings,
        cancellation: CancellationSource,
    ) -> HardBattleOutcome:
        session = self._require_session(settings)
        session.execute(cancellation)
        return HardBattleOutcome.SETTLED

    def exit_ui(
        self,
        settings: HardSettings,
        cancellation: CancellationSource,
    ) -> None:
        session = self._require_session(settings)
        session.exit_ui(cancellation)

    def release(self) -> None:
        """无条件释放当前 turn 的 runtime，不依赖已可能取消的交互信号。"""

        session = self._session
        self._session = None
        if session is None:
            return
        session.close()


def _read_hard_remaining(device: Device) -> int:
    return _OCR_HARD_REMAIN.ocr_single(device.image)


def build_mumu12_campaign_dependencies(
    config: AzurLaneConfig,
    device: Device,
    sessions: CampaignSessionSource,
) -> CampaignFactoryDependencies:
    """组装 Campaign factory 所需的 session source 与单 battle live workflow。"""

    provider = Mumu12CampaignRuntimeProvider(config, device)
    auto_search = Mumu12CampaignAutoSearchExecutor(provider)
    programs = Mumu12CampaignBattleProgramExecutor(provider)
    gems_fleets = Mumu12GemsFleetReplacementExecutor(provider)
    workflow = build_existing_campaign_map_workflow(
        provider,
        auto_search,
        CampaignLiveServices(
            activator=provider,
            guards=provider,
            programs=programs,
            gems_fleets=gems_fleets,
            lifecycle=provider,
        ),
    )
    return CampaignFactoryDependencies(workflow=workflow, sessions=sessions)
