import re
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, Final, Literal, Self, Unpack, cast

from module.adapters.campaign_live import (
    CampaignMapRuntime,
    CommittedCampaignUnit,
    build_existing_campaign_map_workflow,
)
from module.adapters.campaign_program_mumu12 import (
    Mumu12CampaignBattleProgramExecutor,
    Mumu12CommittedBattleProgramUnit,
    build_mumu12_battle_program_port,
    read_mumu12_battle_program_mode,
)
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
    RuntimeSessionContext,
    RuntimeSessionEntryKind,
    RuntimeSessionOutcome,
)
from module.adapters.gems_mumu12 import (
    GemsHardPreparationError,
    Mumu12GemsFleetReplacementExecutor,
    Mumu12GemsRuntimeBehavior,
)
from module.adapters.mumu12 import CancellationAwareMumu12Device, emotion_runtime_overlay
from module.application import SafeUnitCancellation
from module.base.decorator import cached_property
from module.base.failure import preserve_cleanup_failure, raise_cleanup_errors
from module.base.utils import location2node
from module.campaign.campaign_engine import CampaignEngine
from module.combat.emotion import Emotion
from module.config.config import AzurLaneConfig, name_to_function
from module.content.battle_policy import BattleFlag
from module.content.campaign_session import (
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
    CampaignSessionStatus,
)
from module.content.mechanic_rules import MapMutationPhase, MapMutationVariant, MapStructureRules
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
from module.exception import CampaignEnd, HardFleetRequirementsError, MapAchievementReached
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
    CampaignCheckpointUnavailable,
    CampaignGemsReplacementFailed,
    CampaignGuardEvidence,
    CampaignGuardPhase,
    CampaignLiveServices,
    CampaignMapAchievementReached,
)
from module.gameplay.encounter import HardBattleOutcome, HardSettings
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_ON
from module.hard import assets as hard_assets
from module.map.map_base import CampaignMap
from module.ocr.ocr import Digit, DigitCounter
from module.task_registry import command_to_config_name
from module.ui.assets import CAMPAIGN_MENU_NO_EVENT
from module.ui.page import page_campaign_menu
from module.war_archives.assets import OCR_DATA_KEY_CAMPAIGN, WAR_ARCHIVES_CAMPAIGN_CHECK

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from module.application import CancellationSource
    from module.base.button import Button
    from module.base.template import Template
    from module.base.type_alias import Area, ImageArray, Point
    from module.campaign.campaign_ocr import StageMatchOptions, StageMatchSettings
    from module.combat.combat import CombatEnd
    from module.config.config_generated import ConfigOverrides
    from module.content.battle_program import BattleProgramMode
    from module.content.cell import CellId
    from module.content.models import StageRef
    from module.content.stage_rules import MapCalibration, StageNavigation
    from module.gameplay.campaign_factories import CampaignSessionSource
    from module.map.camera import FullScanOptions
    from module.map.fleet import FleetLocation
    from module.map.map_grids import SelectedGrids
    from module.map.type_alias import GridLocation, GridMode
    from module.map_detection.grid import Grid
    from module.map_detection.grid_info import GridInfo


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


class _RuntimeActivationOwner:
    """activation 成功转交前，保证局部 runtime 不会成为 orphan。"""

    __slots__ = ("_cleanup", "_owned")

    def __init__(self, cleanup: Callable[[], None]) -> None:
        self._cleanup = cleanup
        self._owned = True

    def __enter__(self) -> Self:
        return self

    def transfer(self) -> None:
        """runtime 已发布给 provider 或已完整释放。"""

        self._owned = False

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, traceback
        if not self._owned:
            return False
        if error is None:
            self._cleanup()
        else:
            preserve_cleanup_failure(
                error,
                self._cleanup,
                message="campaign activation and runtime cleanup both failed",
            )
        return False


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
    """旧地图对象所需的结构数据；后续可按 normal/loop 分别编译。"""

    wall_data: str
    maze_data: tuple[tuple[str, ...], ...]
    fortress_data: tuple[tuple[str, ...], tuple[str, ...]]
    bouncing_enemy_data: tuple[tuple[str, ...], ...]


def _node(cell: object) -> str:
    typed = cast("CellId", cell)
    return location2node((typed.x, typed.y))


def _compile_wall_data(structures: MapStructureRules, *, columns: int, rows: int) -> str:
    if not structures.walls:
        return ""
    width = columns * 4 - 3
    canvas = [[" "] * width for _ in range(rows * 2 - 1)]
    for wall in structures.walls:
        source = wall.source
        target = wall.target
        if source.y == target.y:
            left = min(source.x, target.x)
            canvas[source.y * 2][left * 4 + 2] = "|"
        else:
            top = min(source.y, target.y)
            canvas[top * 2 + 1][source.x * 4] = "-"
    return "\n".join(f"    {''.join(line)}, " for line in canvas)


def _compile_map_structures(
    structures: MapStructureRules,
    *,
    columns: int,
    rows: int,
) -> _CompiledMapStructures:
    return _CompiledMapStructures(
        wall_data=_compile_wall_data(structures, columns=columns, rows=rows),
        maze_data=tuple(tuple(_node(cell) for cell in group) for group in structures.maze_groups),
        fortress_data=(
            tuple(_node(cell) for cell in structures.fortress_enemy_cells),
            tuple(_node(cell) for cell in structures.fortress_block_cells),
        ),
        bouncing_enemy_data=tuple(tuple(_node(cell) for cell in route) for route in structures.bouncing_enemy_routes),
    )


def _install_map_structures(compiled: CampaignMap, structures: _CompiledMapStructures) -> None:
    compiled.wall_data = structures.wall_data
    compiled.maze_data = structures.maze_data
    compiled.fortress_data = structures.fortress_data
    compiled.bouncing_enemy_data = structures.bouncing_enemy_data


def compile_campaign_map(definition: CampaignStageDefinition) -> CampaignMap:
    """把不可变关卡定义编译为旧地图引擎唯一需要的运行对象。"""

    if not isinstance(definition, CampaignStageDefinition):
        message = "campaign map compiler requires a CampaignStageDefinition"
        raise TypeError(message)
    source = definition.map
    compiled = CampaignMap(source.name)
    compiled.shape = location2node((source.shape.columns - 1, source.shape.rows - 1))
    compiled.map_covered = [location2node((cell.x, cell.y)) for cell in source.map_covered]
    compiled.map_data = _variant_text(source.normal, "token")
    compiled.map_data_loop = _variant_text(source.loop, "token")
    compiled.weight_data = _variant_text(source.normal, "weight")
    compiled.camera_data = [location2node((cell.x, cell.y)) for cell in source.camera_data]
    compiled.camera_data_spawn_point = [location2node((cell.x, cell.y)) for cell in source.camera_data_spawn_point]
    compiled.portal_data = [
        (
            location2node((portal.source.x, portal.source.y)),
            location2node((portal.target.x, portal.target.y)),
        )
        for portal in source.portals
    ]
    compiled.land_based_data = [
        (location2node((unit.cell_id.x, unit.cell_id.y)), unit.direction.value) for unit in source.land_based
    ]
    _install_map_structures(
        compiled,
        _compile_map_structures(
            definition.mechanics.map_structures,
            columns=source.shape.columns,
            rows=source.shape.rows,
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


class DeclarativeCampaignMapRuntime(CampaignEngine):  # ruff:ignore[too-many-public-methods] - CampaignEngine 框架回调仍集中在内部运行宿主；BattleProgram 已改走能力端口，其余消费者待迁移。
    """固定运行类型；关卡差异只来自已编译 definition，不生成 Campaign 子类。"""

    definition: CampaignStageDefinition
    session_state: CampaignSessionState | None
    session_variant: CampaignRunVariant
    fleet_destination: object | None
    _gems_behavior: Mumu12GemsRuntimeBehavior | None
    _runtime_profile: CampaignRuntimeProfileManager
    _runtime_profile_available: bool
    _runtime_profile_session_active: bool
    grid_class: type[Grid]
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD: float
    MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD: float
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
        self.MAP = compile_campaign_map(definition)
        self._runtime_profile.install_map_grid(self.MAP)
        camera_grid_class = self._runtime_profile.camera_grid_class
        if camera_grid_class is not None:
            self.grid_class = camera_grid_class
        self._runtime_profile.apply_config(config)
        self.ENEMY_FILTER = definition.enemy_filter
        self.session_state = None
        self.session_variant = CampaignRunVariant.NORMAL
        self.fleet_destination = None
        self._gems_behavior = None
        self._runtime_profile_available = True
        self._runtime_profile_session_active = False
        super().__init__(config=config, device=device)
        self._runtime_profile.apply_runtime_tunings(self)
        self._runtime_profile.bind(self, self.MAP)

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self._runtime_profile.invoke_super(operation, self, *args, **kwargs)

    @staticmethod
    def _missing_runtime_base(
        operation: RuntimeOperation,
        *args: object,
        **kwargs: object,
    ) -> object:
        del args, kwargs
        message = f"runtime operation has no fixed base implementation: {operation.value}"
        raise CampaignRuntimeProfileError(message)

    def _expected_end(self, expected: str) -> CombatEnd | None:
        result = self._runtime_profile.hard.invoke(
            RuntimeOperation.EXPECTED_END,
            self,
            lambda value: self._runtime_profile.engine.invoke(
                RuntimeOperation.EXPECTED_END,
                self,
                lambda inner: CampaignEngine._expected_end(self, inner),  # ruff:ignore[private-member-access] - 固定调用引擎基线。
                value,
            ),
            expected,
        )
        return cast("CombatEnd | None", result)

    def handle_clear_mode_config_cover(self) -> bool:
        result = self._runtime_profile.engine.invoke(
            RuntimeOperation.HANDLE_CLEAR_MODE_CONFIG_COVER,
            self,
            lambda: CampaignEngine.handle_clear_mode_config_cover(self),
        )
        return bool(result)

    def _declarative_map_data_init(self, map_: CampaignMap | None) -> None:
        CampaignEngine.map_data_init(self, map_)
        moving = self.definition.mechanics.moving_enemies
        for cell in moving.initial_enemy_cells:
            self.map[(cell.x, cell.y)].is_enemy = True
        for cell in moving.initial_siren_cells:
            self.map[(cell.x, cell.y)].is_siren = True
        self._apply_map_patches(MapMutationPhase.MAP_DATA_INIT)

    def map_data_init(self, map_: CampaignMap | None) -> None:
        self._runtime_profile.engine.invoke(
            RuntimeOperation.MAP_DATA_INIT,
            self,
            lambda value: self._runtime_profile.mechanic.invoke(
                RuntimeOperation.MAP_DATA_INIT,
                self,
                self._declarative_map_data_init,
                value,
            ),
            map_,
        )

    def clear_boss(self) -> bool:
        result = self._runtime_profile.hard.invoke(
            RuntimeOperation.CLEAR_BOSS,
            self,
            lambda: self._runtime_profile.mechanic.invoke(
                RuntimeOperation.CLEAR_BOSS,
                self,
                lambda: CampaignEngine.clear_boss(self),
            ),
        )
        return bool(result)

    def equipment_take_off_when_finished(self) -> bool:
        result = self._runtime_profile.hard.invoke(
            RuntimeOperation.EQUIPMENT_TAKE_OFF_WHEN_FINISHED,
            self,
            partial(
                self._missing_runtime_base,
                RuntimeOperation.EQUIPMENT_TAKE_OFF_WHEN_FINISHED,
            ),
        )
        return bool(result)

    def _map_swipe(
        self,
        vector: Point,
        box: Area = (123, 159, 1175, 628),
    ) -> bool:
        result = self._runtime_profile.mechanic.invoke(
            RuntimeOperation.MAP_SWIPE,
            self,
            lambda value, *, box: CampaignEngine._map_swipe(  # ruff:ignore[private-member-access] - 固定调用引擎基线。
                self,
                value,
                box=box,
            ),
            vector,
            box=box,
        )
        return bool(result)

    def fleet_preparation(self) -> bool:
        result = self._runtime_profile.mechanic.invoke(
            RuntimeOperation.FLEET_PREPARATION,
            self,
            self._base_fleet_preparation,
        )
        return bool(result)

    def handle_mystery_items(self, button: object = None) -> bool:
        result = self._runtime_profile.mechanic.invoke(
            RuntimeOperation.HANDLE_MYSTERY_ITEMS,
            self,
            lambda *, button=None: CampaignEngine.handle_mystery_items(self, button=button),
            button=button,
        )
        return bool(result)

    def handle_submarine_support_popup(self) -> bool:
        result = self._runtime_profile.mechanic.invoke(
            RuntimeOperation.HANDLE_SUBMARINE_SUPPORT_POPUP,
            self,
            CampaignEngine.handle_submarine_support_popup,
        )
        return bool(result)

    def map_init(self, map_: CampaignMap | None) -> None:
        self._runtime_profile.mechanic.invoke(
            RuntimeOperation.MAP_INIT,
            self,
            lambda value: CampaignEngine.map_init(self, value),
            map_,
        )

    def strategy_set_execute(
        self,
        formation: Literal["line_ahead", "double_line", "diamond"] | None = None,
        *,
        sub_view: bool | None = None,
        sub_hunt: bool | None = None,
    ) -> None:
        self._runtime_profile.mechanic.invoke(
            RuntimeOperation.STRATEGY_SET_EXECUTE,
            self,
            lambda value=None, *, sub_view=None, sub_hunt=None: CampaignEngine.strategy_set_execute(
                self,
                formation=value,
                sub_view=sub_view,
                sub_hunt=sub_hunt,
            ),
            formation,
            sub_view=sub_view,
            sub_hunt=sub_hunt,
        )

    def catch_camera_repositioning(self) -> bool:
        result = self._runtime_profile.observation.invoke(
            RuntimeOperation.CATCH_CAMERA_REPOSITIONING,
            self,
            lambda: CampaignEngine.catch_camera_repositioning(self),
        )
        return bool(result)

    def enemy_searching_appear(self) -> bool:
        result = self._runtime_profile.observation.invoke(
            RuntimeOperation.ENEMY_SEARCHING_APPEAR,
            self,
            lambda: CampaignEngine.enemy_searching_appear(self),
        )
        return bool(result)

    def find_current_fleet(self) -> FleetLocation:
        result = self._runtime_profile.observation.invoke(
            RuntimeOperation.FIND_CURRENT_FLEET,
            self,
            lambda: CampaignEngine.find_current_fleet(self),
        )
        return cast("FleetLocation", result)

    def full_scan(
        self,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        self._runtime_profile.observation.invoke(
            RuntimeOperation.FULL_SCAN,
            self,
            lambda options=None, queue=None, must_scan=None, mode="normal": CampaignEngine.full_scan(
                self,
                options=options,
                queue=queue,
                must_scan=must_scan,
                mode=mode,
            ),
            options,
            queue,
            must_scan,
            mode,
        )

    def full_scan_movable(self, *, enemy_cleared: bool = True) -> None:
        self._runtime_profile.observation.invoke(
            RuntimeOperation.FULL_SCAN_MOVABLE,
            self,
            lambda *, enemy_cleared=True: CampaignEngine.full_scan_movable(
                self,
                enemy_cleared=enemy_cleared,
            ),
            enemy_cleared=enemy_cleared,
        )

    def get_map_clear_percentage(self) -> float:
        result = self._runtime_profile.observation.invoke(
            RuntimeOperation.GET_MAP_CLEAR_PERCENTAGE,
            self,
            lambda: CampaignEngine.get_map_clear_percentage(self),
        )
        if not isinstance(result, int | float):
            message = "map clear percentage executor must return a number"
            raise CampaignRuntimeProfileError(message)
        return float(result) * self._runtime_profile.map_clear_percentage_multiplier

    def in_sight(
        self,
        location: GridInfo | str | Point,
        sight: tuple[int, int, int, int] | None = None,
    ) -> None:
        self._runtime_profile.observation.invoke(
            RuntimeOperation.IN_SIGHT,
            self,
            lambda value, sight=None: CampaignEngine.in_sight(self, value, sight=sight),
            location,
            sight=sight,
        )

    def map_get_info(self) -> None:
        self._runtime_profile.observation.invoke(
            RuntimeOperation.MAP_GET_INFO,
            self,
            lambda: CampaignEngine.map_get_info(self),
        )

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

    def ensure_no_stage_entrance(self, *, skip_first_screenshot: bool = True) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.ENSURE_NO_STAGE_ENTRANCE,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.ENSURE_NO_STAGE_ENTRANCE),
            skip_first_screenshot=skip_first_screenshot,
        )
        return bool(result)

    def event_20230817_story(self, *, skip_first_screenshot: bool = True) -> None:
        self._runtime_profile.event_ui.invoke(
            RuntimeOperation.EVENT_20230817_STORY,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.EVENT_20230817_STORY),
            skip_first_screenshot=skip_first_screenshot,
        )

    def event_animation_end(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.EVENT_ANIMATION_END,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.EVENT_ANIMATION_END),
        )
        return bool(result)

    def get_story_button(self) -> object | None:
        return self._runtime_profile.event_ui.invoke(
            RuntimeOperation.GET_STORY_BUTTON,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.GET_STORY_BUTTON),
        )

    def get_story_entrance(self) -> object | None:
        return self._runtime_profile.event_ui.invoke(
            RuntimeOperation.GET_STORY_ENTRANCE,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.GET_STORY_ENTRANCE),
        )

    def handle_campaign_ui_additional(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.HANDLE_CAMPAIGN_UI_ADDITIONAL,
            self,
            lambda: CampaignEngine.handle_campaign_ui_additional(self),
        )
        return bool(result)

    def handle_chapter_additional(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.HANDLE_CHAPTER_ADDITIONAL,
            self,
            CampaignEngine.handle_chapter_additional,
        )
        return bool(result)

    def handle_exp_info(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.HANDLE_EXP_INFO,
            self,
            lambda: CampaignEngine.handle_exp_info(self),
        )
        return bool(result)

    def handle_get_chapter_additional(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.HANDLE_GET_CHAPTER_ADDITIONAL,
            self,
            lambda: CampaignEngine.handle_get_chapter_additional(self),
        )
        return bool(result)

    def handle_in_stage(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.HANDLE_IN_STAGE,
            self,
            lambda: CampaignEngine.handle_in_stage(self),
        )
        return bool(result)

    def handle_story_entrance(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.HANDLE_STORY_ENTRANCE,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.HANDLE_STORY_ENTRANCE),
        )
        return bool(result)

    def is_event_animation(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.IS_EVENT_ANIMATION,
            self,
            CampaignEngine.is_event_animation,
        )
        return bool(result)

    def is_stage_page_has_entrance(self) -> bool:
        result = self._runtime_profile.event_ui.invoke(
            RuntimeOperation.IS_STAGE_PAGE_HAS_ENTRANCE,
            self,
            lambda: CampaignEngine.is_stage_page_has_entrance(self),
        )
        return bool(result)

    def ui_goto_event(self) -> bool:
        result = self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.UI_GOTO_EVENT,
            self,
            lambda: self._runtime_profile.event_ui.invoke(
                RuntimeOperation.UI_GOTO_EVENT,
                self,
                lambda: CampaignEngine.ui_goto_event(self),
            ),
        )
        return bool(result)

    def ui_goto_sp(self) -> bool:
        result = self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.UI_GOTO_SP,
            self,
            lambda: CampaignEngine.ui_goto_sp(self),
        )
        return bool(result)

    def _campaign_ball_get(self) -> object:
        return self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_BALL_GET,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.CAMPAIGN_BALL_GET),
        )

    def _campaign_ball_set(self, status: object) -> None:
        self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_BALL_SET,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.CAMPAIGN_BALL_SET),
            status,
        )

    def _campaign_ball_status(self, *args: object) -> object:
        return self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_BALL_STATUS,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.CAMPAIGN_BALL_STATUS),
            *args,
        )

    def _campaign_ensure_ball_mode(self, chapter: str) -> None:
        self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_ENSURE_BALL_MODE,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.CAMPAIGN_ENSURE_BALL_MODE),
            chapter,
        )

    def campaign_ensure_mode(self, mode: str = "normal") -> None:
        self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_ENSURE_MODE,
            self,
            lambda value="normal": CampaignEngine.campaign_ensure_mode(self, value),
            mode,
        )

    def campaign_get_chapter_index(self, name: str | int) -> int:
        result = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_GET_CHAPTER_INDEX,
            self,
            CampaignEngine.campaign_get_chapter_index,
            name,
        )
        if type(result) is not int:
            message = "campaign chapter index executor must return an integer"
            raise CampaignRuntimeProfileError(message)
        return result

    def campaign_get_entrance(self, name: str) -> Button:
        result = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_GET_ENTRANCE,
            self,
            lambda value: CampaignEngine.campaign_get_entrance(self, value),
            name,
        )
        return cast("Button", result)

    def campaign_match_multi(
        self,
        template: Template,
        image: ImageArray,
        stage_image: ImageArray | None = None,
        options: StageMatchOptions | None = None,
        **settings: Unpack[StageMatchSettings],
    ) -> list[Button]:
        result = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_MATCH_MULTI,
            self,
            lambda template, image, stage_image=None, options=None, **settings: CampaignEngine.campaign_match_multi(
                self,
                template,
                image,
                stage_image=stage_image,
                options=options,
                **settings,
            ),
            template,
            image,
            stage_image=stage_image,
            options=options,
            **settings,
        )
        if not isinstance(result, list):
            message = "campaign match executor must return a list"
            raise CampaignRuntimeProfileError(message)
        return cast("list[Button]", result)

    def campaign_ocr_result_process(self, result: str) -> str:
        normalized = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_OCR_RESULT_PROCESS,
            self,
            CampaignEngine.campaign_ocr_result_process,
            result,
        )
        if not isinstance(normalized, str):
            message = "campaign OCR executor must return a string"
            raise CampaignRuntimeProfileError(message)
        return normalized

    def campaign_separate_name(self, name: str) -> tuple[str, str]:
        separated = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_SEPARATE_NAME,
            self,
            CampaignEngine.campaign_separate_name,
            name,
        )
        if (
            not isinstance(separated, tuple)
            or len(separated) != 2
            or any(not isinstance(value, str) for value in separated)
        ):
            message = "campaign name executor must return two strings"
            raise CampaignRuntimeProfileError(message)
        return cast("tuple[str, str]", separated)

    def campaign_set_chapter(self, name: str, mode: str = "normal") -> None:
        self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_SET_CHAPTER,
            self,
            lambda value, mode="normal": CampaignEngine.campaign_set_chapter(self, value, mode),
            name,
            mode,
        )

    def campaign_set_chapter_20241219(
        self,
        chapter: str,
        stage: str,
        mode: str = "combat",
    ) -> bool:
        result = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_SET_CHAPTER_20241219,
            self,
            lambda chapter, stage, mode="combat": CampaignEngine.campaign_set_chapter_20241219(
                self,
                chapter,
                stage,
                mode,
            ),
            chapter,
            stage,
            mode,
        )
        return bool(result)

    def campaign_set_chapter_ball(self, chapter: str, stage: str) -> bool:
        result = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_SET_CHAPTER_BALL,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.CAMPAIGN_SET_CHAPTER_BALL),
            chapter,
            stage,
        )
        return bool(result)

    def campaign_set_chapter_event(self, chapter: str, mode: str = "normal") -> bool:
        result = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_SET_CHAPTER_EVENT,
            self,
            lambda chapter, mode="normal": CampaignEngine.campaign_set_chapter_event(
                self,
                chapter,
                mode,
            ),
            chapter,
            mode,
        )
        return bool(result)

    def campaign_set_chapter_main(self, chapter: str, mode: str = "normal") -> bool:
        result = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_SET_CHAPTER_MAIN,
            self,
            lambda chapter, mode="normal": CampaignEngine.campaign_set_chapter_main(
                self,
                chapter,
                mode,
            ),
            chapter,
            mode,
        )
        return bool(result)

    def campaign_set_chapter_sp(self, chapter: str, mode: str = "normal") -> bool:
        result = self._runtime_profile.navigation.invoke(
            RuntimeOperation.CAMPAIGN_SET_CHAPTER_SP,
            self,
            lambda chapter, mode="normal": CampaignEngine.campaign_set_chapter_sp(
                self,
                chapter,
                mode,
            ),
            chapter,
            mode,
        )
        return bool(result)

    def _advance_archives_scroll(self) -> bool:
        result = self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.ADVANCE_ARCHIVES_SCROLL,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.ADVANCE_ARCHIVES_SCROLL),
        )
        return bool(result)

    def _archives_loading_complete(self) -> bool:
        result = self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.ARCHIVES_LOADING_COMPLETE,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.ARCHIVES_LOADING_COMPLETE),
        )
        return bool(result)

    def _discard_archives_scroll_record(self) -> None:
        self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.DISCARD_ARCHIVES_SCROLL_RECORD,
            self,
            partial(
                self._missing_runtime_base,
                RuntimeOperation.DISCARD_ARCHIVES_SCROLL_RECORD,
            ),
        )

    def _ensure_archives_search_page(self) -> bool:
        result = self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.ENSURE_ARCHIVES_SEARCH_PAGE,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.ENSURE_ARCHIVES_SEARCH_PAGE),
        )
        return bool(result)

    def _get_archives_entrance(self, name: str) -> object | None:
        return self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.GET_ARCHIVES_ENTRANCE,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.GET_ARCHIVES_ENTRANCE),
            name,
        )

    def _search_archives_entrance(
        self,
        name: str,
        *,
        skip_first_screenshot: bool = True,
    ) -> object | None:
        return self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.SEARCH_ARCHIVES_ENTRANCE,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.SEARCH_ARCHIVES_ENTRANCE),
            name,
            skip_first_screenshot=skip_first_screenshot,
        )

    def _wait_archives_loaded(self) -> None:
        self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.WAIT_ARCHIVES_LOADED,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.WAIT_ARCHIVES_LOADED),
        )

    def ui_goto_archives_campaign(self, mode: str = "ex") -> bool:
        result = self._runtime_profile.war_archives_navigation.invoke(
            RuntimeOperation.UI_GOTO_ARCHIVES_CAMPAIGN,
            self,
            partial(self._missing_runtime_base, RuntimeOperation.UI_GOTO_ARCHIVES_CAMPAIGN),
            mode,
        )
        return bool(result)

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

    def _base_fleet_preparation(self) -> bool:
        try:
            return CampaignEngine.fleet_preparation(self)
        except HardFleetRequirementsError:
            behavior = self._gems_behavior
            if behavior is None:
                raise
            behavior.prepare_hard_fleet(self)
            try:
                return CampaignEngine.fleet_preparation(self)
            except HardFleetRequirementsError as retry_error:
                message = "hard fleet still does not satisfy its constraints after replacement"
                raise GemsHardPreparationError(message) from retry_error

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

    def _apply_map_patches(self, phase: MapMutationPhase, battle: int | None = None) -> None:
        for patch in self.definition.mechanics.map_mutations.patches:
            if patch.phase is not phase or patch.battle != battle:
                continue
            if patch.variant is MapMutationVariant.NORMAL and self.session_variant is not CampaignRunVariant.NORMAL:
                continue
            if patch.variant is MapMutationVariant.LOOP and self.session_variant is not CampaignRunVariant.LOOP:
                continue
            grid = self.map[(patch.cell.x, patch.cell.y)]
            setattr(grid, patch.attribute.value, patch.value)

    def _begin_runtime_session(
        self,
        variant: CampaignRunVariant,
        battle_index: int,
        entry_kind: RuntimeSessionEntryKind,
        state: CampaignSessionState | None = None,
    ) -> None:
        if not isinstance(variant, CampaignRunVariant):
            message = "campaign runtime variant must be a CampaignRunVariant"
            raise TypeError(message)
        if type(battle_index) is not int or battle_index < 0:
            message = "campaign runtime battle_index must be a non-negative integer"
            raise ValueError(message)
        if not isinstance(entry_kind, RuntimeSessionEntryKind):
            message = "campaign runtime entry_kind must be a RuntimeSessionEntryKind"
            raise TypeError(message)
        if state is not None and (not isinstance(state, CampaignSessionState) or state.variant is not variant):
            message = "campaign runtime state must match the selected variant"
            raise ValueError(message)
        if not self._runtime_profile_available:
            message = "campaign runtime profile has already been released"
            raise CampaignRuntimeProfileError(message)
        if self._runtime_profile_session_active:
            message = "campaign runtime profile session is already active"
            raise CampaignRuntimeProfileError(message)
        self.session_state = state
        self.session_variant = variant
        self.map_is_clear_mode = variant is CampaignRunVariant.LOOP
        self._runtime_profile.begin_session(RuntimeSessionContext(variant, battle_index, entry_kind))
        self._runtime_profile_session_active = True

    def initialize_session(
        self,
        variant: CampaignRunVariant,
        battle_index: int,
        entry_kind: RuntimeSessionEntryKind,
        state: CampaignSessionState | None = None,
    ) -> None:
        self._begin_runtime_session(variant, battle_index, entry_kind, state)
        try:
            self.map_init(self.MAP)
            self.battle_count = battle_index
            self._apply_map_patches(MapMutationPhase.MAP_INIT)
        except BaseException as error:
            preserve_cleanup_failure(
                error,
                partial(self.finish_runtime_session, RuntimeSessionOutcome.FAILED),
                message="campaign session initialization and cleanup both failed",
            )
            raise

    def resume_session(self, state: CampaignSessionState) -> None:
        if not isinstance(state, CampaignSessionState):
            message = "campaign runtime resume requires a CampaignSessionState"
            raise TypeError(message)
        if not self._runtime_profile_session_active:
            message = "campaign runtime profile session is not active"
            raise CampaignRuntimeProfileError(message)
        if state.variant is not self.session_variant:
            message = "campaign runtime resume variant must match the active runtime"
            raise ValueError(message)
        self.session_state = state
        self.battle_count = state.battle_index

    def finish_runtime_session(self, outcome: RuntimeSessionOutcome) -> None:
        if not isinstance(outcome, RuntimeSessionOutcome):
            message = "campaign runtime outcome must be a RuntimeSessionOutcome"
            raise TypeError(message)
        if not self._runtime_profile_session_active:
            message = "campaign runtime profile session is not active"
            raise CampaignRuntimeProfileError(message)
        self._runtime_profile_available = False
        self._runtime_profile_session_active = False
        errors: list[BaseException] = []
        for cleanup in (
            partial(self._runtime_profile.end_session, outcome),
            self._runtime_profile.reset,
        ):
            try:
                cleanup()
            except BaseException as error:  # ruff:ignore[blind-except] - end 与 reset 是独立的关闭阶段。
                errors.append(error)
        raise_cleanup_errors(errors, message="campaign runtime session cleanup failed")

    def discard_runtime(self) -> None:
        if self._runtime_profile_session_active:
            message = "active campaign runtime must finish its session before discard"
            raise CampaignRuntimeProfileError(message)
        if not self._runtime_profile_available:
            return
        self._runtime_profile_available = False
        self._runtime_profile.reset()

    @property
    def runtime_session_active(self) -> bool:
        return self._runtime_profile_session_active

    def prepare_battle(self, battle_index: int) -> None:
        if type(battle_index) is not int or battle_index < 0:
            message = "campaign battle_index must be a non-negative integer"
            raise ValueError(message)
        self._apply_map_patches(MapMutationPhase.BEFORE_BATTLE, battle_index)

    def is_event_entrance_available(self) -> bool:
        """只返回入口事实；调度变化由 CampaignTask effects 统一提交。"""

        return not self.appear(CAMPAIGN_MENU_NO_EVENT, offset=(20, 20))

    def handle_map_stop(self) -> None:
        """地图成就只产生事实；task disable/关卡推进由 typed workflow 提交。"""

    def _pause_auto_search(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        if not self.is_auto_search_running():
            return
        self.device.click(AUTO_SEARCH_MAP_OPTION_ON)
        for _ in range(20):
            cancellation.raise_if_requested()
            self.device.screenshot()
            if not self.is_auto_search_running():
                return
            self.device.sleep(0.2)
        message = "auto-search did not reach a paused map safe point"
        raise CampaignRuntimeEvidenceError(message)

    def _visible_targets(self, cancellation: CancellationSource) -> tuple[int, int, int]:
        cancellation.raise_if_requested()
        self.full_scan()
        cancellation.raise_if_requested()
        self.find_path_initial()
        grids = tuple(self.map)
        enemy = sum(grid.is_enemy and not grid.is_siren and not grid.is_boss for grid in grids)
        siren = sum(grid.is_siren for grid in grids)
        boss = sum(grid.is_boss for grid in grids)
        return enemy, siren, boss

    def _expected_visible_after(self, target: BattleTarget) -> tuple[int, int, int]:
        state = self.session_state
        if state is None:
            message = "auto-search battle requires a campaign session state"
            raise CampaignRuntimeEvidenceError(message)
        remaining = state.remaining.clear(target)
        next_index = state.battle_index + 1
        variant = (
            self.definition.map.normal
            if self.session_variant is CampaignRunVariant.NORMAL
            else self.definition.map.loop
        )
        if next_index < len(variant.spawn_waves):
            remaining = remaining.add_wave(variant.spawn_waves[next_index])
        return remaining.enemy, remaining.siren, remaining.boss

    def execute_auto_search_battle(
        self,
        battle_index: int,
        cancellation: CancellationSource,
    ) -> BattleTarget:
        """推进一次游戏自律 battle，并以暂停后的地图差分闭合实际目标。"""

        state = self.session_state
        if state is None or state.battle_index != battle_index:
            message = "auto-search battle does not match the active campaign safe point"
            raise CampaignRuntimeEvidenceError(message)
        before = self.battle_count
        ended = False
        try:
            cancellation.raise_if_requested()
            self.auto_search_execute_a_battle()
        except CampaignEnd:
            ended = True

        confirmed = self.battle_count - before
        if ended and confirmed == 0 and state.remaining.boss == 1:
            self.battle_count += 1
            return BattleTarget.BOSS
        if confirmed != 1:
            message = f"one auto-search action changed battle_count by {confirmed}, expected exactly one"
            raise CampaignRuntimeEvidenceError(message)

        self._pause_auto_search(cancellation)
        observed = self._visible_targets(cancellation)
        available = (
            (BattleTarget.ENEMY, state.remaining.enemy),
            (BattleTarget.SIREN, state.remaining.siren),
            (BattleTarget.BOSS, state.remaining.boss),
        )
        matched = tuple(
            target for target, count in available if count and self._expected_visible_after(target) == observed
        )
        if len(matched) != 1:
            message = f"auto-search battle target is ambiguous: observed={observed}, candidates={matched}"
            raise CampaignRuntimeEvidenceError(message)
        return matched[0]

    def execute_hard_attempt(self, cancellation: CancellationSource) -> None:
        """完成一次困难图结算；hard clear-mode 的一次 attempt 是最小可恢复业务单元。"""

        cancellation.raise_if_requested()
        self._begin_runtime_session(
            CampaignRunVariant.LOOP,
            0,
            RuntimeSessionEntryKind.FRESH,
        )
        try:
            self._execute_hard_attempt_body(cancellation)
        except BaseException as error:
            if self._runtime_profile_session_active:
                preserve_cleanup_failure(
                    error,
                    partial(self.finish_runtime_session, RuntimeSessionOutcome.FAILED),
                    message="hard campaign attempt and cleanup both failed",
                )
            raise
        self.finish_runtime_session(RuntimeSessionOutcome.COMPLETED)

    def _execute_hard_attempt_body(self, cancellation: CancellationSource) -> None:
        self.ENTRANCE.area = self.ENTRANCE.button
        self.enter_map(self.ENTRANCE, mode="hard")
        if not self.map_is_auto_search:
            message = "hard campaign attempt requires the game's clear-mode auto search"
            raise CampaignRuntimeEvidenceError(message)
        self.map = self.MAP
        self.battle_count = 0
        self.lv_reset()
        self.lv_get()
        for _ in range(20):
            cancellation.raise_if_requested()
            try:
                self.auto_search_execute_a_battle()
            except CampaignEnd:
                return
        message = "hard campaign attempt did not reach settlement within 20 battles"
        raise CampaignRuntimeEvidenceError(message)


class Mumu12CampaignRuntimeProvider:
    """一次 workflow turn 只暴露一个与 typed session 精确匹配的固定 runtime。"""

    __slots__ = (
        "_active_runtime",
        "_active_session",
        "_active_unit_cancellation",
        "_config",
        "_device",
        "_prepared_at_boundary",
        "_prepared_job",
        "_prepared_runtime",
        "_prepared_session",
        "_prepared_unit_cancellation",
        "_runtime_factory",
    )

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        *,
        runtime_factory: Callable[
            [AzurLaneConfig, Device, CampaignStageDefinition],
            DeclarativeCampaignMapRuntime,
        ] = DeclarativeCampaignMapRuntime,
    ) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "campaign provider config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "campaign provider device must be a Device"
            raise TypeError(message)
        if isinstance(runtime_factory, type) and not issubclass(runtime_factory, DeclarativeCampaignMapRuntime):
            message = "campaign runtime factory must build DeclarativeCampaignMapRuntime"
            raise TypeError(message)
        if not callable(runtime_factory):
            message = "campaign runtime factory must be callable"
            raise TypeError(message)
        self._config = config
        self._device = device
        self._runtime_factory = runtime_factory
        self._active_runtime: DeclarativeCampaignMapRuntime | None = None
        self._active_session: CampaignSession | None = None
        self._active_unit_cancellation: SafeUnitCancellation | None = None
        self._prepared_at_boundary = False
        self._prepared_job: CampaignJobSpec | None = None
        self._prepared_runtime: DeclarativeCampaignMapRuntime | None = None
        self._prepared_session: CampaignSession | None = None
        self._prepared_unit_cancellation: SafeUnitCancellation | None = None

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

    def _new_runtime(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> tuple[DeclarativeCampaignMapRuntime, SafeUnitCancellation]:
        cancellation.raise_if_requested()
        definition = compose_campaign_attempt_definition(session.definition, job.difficulty)
        self._activate_config(job, definition)
        runtime = self._runtime_factory(self._config, self._device, definition)
        if not isinstance(runtime, DeclarativeCampaignMapRuntime):
            message = "campaign runtime factory returned an invalid runtime"
            raise TypeError(message)
        try:
            unit_cancellation = self._refresh_runtime_cancellation(job, runtime, cancellation)
        except BaseException as error:
            preserve_cleanup_failure(
                error,
                runtime.discard_runtime,
                message="campaign runtime construction and cleanup both failed",
            )
            raise
        return runtime, unit_cancellation

    def _refresh_runtime_cancellation(
        self,
        job: CampaignJobSpec,
        runtime: DeclarativeCampaignMapRuntime,
        cancellation: CancellationSource,
    ) -> SafeUnitCancellation:
        unit_cancellation = SafeUnitCancellation(cancellation)
        runtime.device = cast("Device", CancellationAwareMumu12Device(self._device, unit_cancellation))
        if job.kind is CampaignJobKind.GEMS_FARMING:
            policy = job.gems_farming
            if policy is None:
                message = "gems-farming campaign requires GemsFarmingPolicy"
                raise ValueError(message)
            runtime.configure_gems_behavior(Mumu12GemsRuntimeBehavior(self._config, policy, unit_cancellation))
        return unit_cancellation

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

    def _discard_prepared_runtime(self) -> None:
        runtime = self._prepared_runtime
        self._prepared_at_boundary = False
        self._prepared_job = None
        self._prepared_runtime = None
        self._prepared_session = None
        self._prepared_unit_cancellation = None
        if runtime is not None and runtime is not self._active_runtime:
            runtime.discard_runtime()

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
        if self._active_runtime is not None:
            message = "fresh campaign entry cannot replace an active map runtime"
            raise CampaignRuntimeEvidenceError(message)
        self._discard_prepared_runtime()
        runtime, unit_cancellation = self._new_runtime(job, session, cancellation)
        self._prepared_job = job
        self._prepared_runtime = runtime
        self._prepared_session = session
        self._prepared_unit_cancellation = unit_cancellation
        progress = job.progress
        pending = None if progress is None else progress.pending_gems_replacement
        if pending is not None and pending.trigger is GemsFleetReplacementTrigger.HARD_PREPARATION:
            self._prepared_at_boundary = True
            return CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY)
        if job.progress is not None:
            cancellation.raise_if_requested()
            runtime.device.screenshot()
            cancellation.raise_if_requested()
            if runtime.is_in_map():
                self._prepared_job = job
                self._prepared_runtime = runtime
                self._prepared_session = session
                self._prepared_unit_cancellation = unit_cancellation
                return CampaignGuardEvidence(
                    CampaignGuardPhase.PRE_ENTRY,
                    resuming_checkpoint=True,
                )
        event_available: bool | None = None
        if self._is_event_stage(job, session):
            cancellation.raise_if_requested()
            runtime.ui_goto(page_campaign_menu)
            cancellation.raise_if_requested()
            event_available = runtime.is_event_entrance_available()
            if not event_available:
                return CampaignGuardEvidence(
                    CampaignGuardPhase.PRE_ENTRY,
                    event_available=False,
                )

        cancellation.raise_if_requested()
        runtime.ensure_campaign_ui(session.definition.ref.stage_id, mode=job.difficulty.value)
        self._prepared_at_boundary = job.progress is not None
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
        runtime = self._active_runtime
        if runtime is None or self._active_session != session:
            message = "campaign post-battle evidence requires the active runtime"
            raise CampaignRuntimeEvidenceError(message)
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

    def _take_prepared_runtime(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
    ) -> tuple[DeclarativeCampaignMapRuntime | None, bool, SafeUnitCancellation | None]:
        if self._prepared_job is not job or self._prepared_session != session:
            return None, False, None
        runtime = self._prepared_runtime
        at_boundary = self._prepared_at_boundary
        unit_cancellation = self._prepared_unit_cancellation
        self._prepared_at_boundary = False
        self._prepared_job = None
        self._prepared_runtime = None
        self._prepared_session = None
        self._prepared_unit_cancellation = None
        return runtime, at_boundary, unit_cancellation

    def _take_active_runtime(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> tuple[DeclarativeCampaignMapRuntime | None, SafeUnitCancellation | None]:
        runtime = self._active_runtime
        if runtime is None:
            return None, None
        if self._active_session != session:
            message = "campaign checkpoint does not match the retained map runtime"
            raise CampaignRuntimeEvidenceError(message)
        expected = compose_campaign_attempt_definition(session.definition, job.difficulty)
        if runtime.definition != expected or not runtime.runtime_session_active:
            message = "retained campaign runtime does not match the selected attempt"
            raise CampaignRuntimeEvidenceError(message)
        unit_cancellation = self._refresh_runtime_cancellation(job, runtime, cancellation)
        self._active_unit_cancellation = unit_cancellation
        return runtime, unit_cancellation

    def _release_active_runtime(self, outcome: RuntimeSessionOutcome) -> None:
        runtime = self._active_runtime
        self._active_runtime = None
        self._active_session = None
        self._active_unit_cancellation = None
        if runtime is None:
            return
        self._release_runtime(runtime, outcome)

    @staticmethod
    def _release_runtime(
        runtime: DeclarativeCampaignMapRuntime,
        outcome: RuntimeSessionOutcome,
    ) -> None:
        if runtime.runtime_session_active:
            runtime.finish_runtime_session(outcome)
        else:
            runtime.discard_runtime()

    def _release_activation_runtime(self, runtime: DeclarativeCampaignMapRuntime) -> None:
        if runtime is self._active_runtime:
            self._release_active_runtime(RuntimeSessionOutcome.FAILED)
        else:
            self._release_runtime(runtime, RuntimeSessionOutcome.FAILED)

    def _activate_checkpoint(
        self,
        session: CampaignSession,
        runtime: DeclarativeCampaignMapRuntime,
        progress_state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> CampaignSession | CampaignCheckpointUnavailable:
        cancellation.raise_if_requested()
        runtime.device.screenshot()
        cancellation.raise_if_requested()
        if not runtime.is_in_map():
            if runtime is self._active_runtime:
                self._release_active_runtime(RuntimeSessionOutcome.INTERRUPTED)
            else:
                runtime.discard_runtime()
            return CampaignCheckpointUnavailable("client is not inside the checkpoint map")
        if runtime.runtime_session_active:
            runtime.resume_session(progress_state)
        else:
            runtime.initialize_session(
                progress_state.variant,
                progress_state.battle_index,
                RuntimeSessionEntryKind.RESUME,
                progress_state,
            )
        runtime.prepare_battle(progress_state.battle_index)
        return session

    def _activate_fresh(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        runtime: DeclarativeCampaignMapRuntime,
        unit_cancellation: SafeUnitCancellation,
        *,
        prepared: bool,
    ) -> _ActivatedMap | CampaignMapAchievementReached | CampaignGemsReplacementFailed:
        if not prepared:
            runtime.ensure_campaign_ui(session.definition.ref.stage_id, mode=job.difficulty.value)
        runtime.ENTRANCE.area = runtime.ENTRANCE.button
        try:
            runtime.enter_map(runtime.ENTRANCE, mode=job.difficulty.value)
        except GemsHardPreparationError as error:
            self._active_runtime = runtime
            self._active_session = session
            self._active_unit_cancellation = unit_cancellation
            return CampaignGemsReplacementFailed(
                GemsFleetReplacementRequest(
                    GemsFleetReplacementTrigger.HARD_PREPARATION,
                    GemsFleetReplacementBoundary.PRE_ENTRY,
                ),
                str(error),
            )
        except MapAchievementReached:
            runtime.discard_runtime()
            return CampaignMapAchievementReached(
                full_clear=bool(runtime.map_is_100_percent_clear),
                three_stars=bool(runtime.map_is_3_stars),
                threat_safe=bool(runtime.map_is_threat_safe),
            )

        runtime.handle_map_fleet_lock()
        variant = CampaignRunVariant.LOOP if runtime.map_is_clear_mode else CampaignRunVariant.NORMAL
        activated = self._entered_session(job, session, variant)
        state = activated.initial_state()
        runtime.initialize_session(
            variant,
            state.battle_index,
            RuntimeSessionEntryKind.FRESH,
            state,
        )
        runtime.prepare_battle(state.battle_index)
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
    ) -> (
        CampaignSession | CampaignCheckpointUnavailable | CampaignMapAchievementReached | CampaignGemsReplacementFailed
    ):
        session = self._selected_session(job)
        runtime, prepared_at_boundary, unit_cancellation = self._take_prepared_runtime(job, session)
        prepared = runtime is not None
        progress = job.progress
        if runtime is None and progress is not None and not prepared_at_boundary:
            runtime, unit_cancellation = self._take_active_runtime(job, session, cancellation)
        if runtime is None:
            runtime, unit_cancellation = self._new_runtime(job, session, cancellation)
        with _RuntimeActivationOwner(partial(self._release_activation_runtime, runtime)) as owner:
            if unit_cancellation is None:
                message = "campaign runtime is missing its safe-unit cancellation gate"
                raise CampaignRuntimeEvidenceError(message)
            if progress is not None and not prepared_at_boundary:
                result = self._activate_checkpoint(
                    session,
                    runtime,
                    progress.session_state,
                    cancellation,
                )
                if isinstance(result, CampaignCheckpointUnavailable):
                    owner.transfer()
                    return result
                activated = result
            else:
                fresh = self._activate_fresh(
                    job,
                    session,
                    runtime,
                    unit_cancellation,
                    prepared=prepared,
                )
                if not isinstance(fresh, _ActivatedMap):
                    owner.transfer()
                    return fresh
                activated = fresh.session

            self._config.apply_runtime_overlay(
                Campaign_UseAutoSearch=job.execution.automation.use_auto_search,
            )
            self._active_runtime = runtime
            self._active_session = activated
            self._active_unit_cancellation = unit_cancellation
            owner.transfer()
            return activated

    def _active_runtime_for(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> DeclarativeCampaignMapRuntime:
        cancellation.raise_if_requested()
        if self._active_runtime is None or self._active_session != session:
            message = "requested campaign session is not the active MuMu12 runtime"
            raise CampaignRuntimeEvidenceError(message)
        return self._active_runtime

    def active_runtime(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CampaignMapRuntime:
        runtime = self._active_runtime_for(session, cancellation)
        return cast("CampaignMapRuntime", runtime)

    def battle_program_mode(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> BattleProgramMode:
        runtime = self._active_runtime_for(session, cancellation)
        return read_mumu12_battle_program_mode(
            runtime,
            runtime._runtime_profile,  # ruff:ignore[private-member-access] - provider owns runtime capability composition.
            cancellation,
        )

    def _commit_active_runtime(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> tuple[DeclarativeCampaignMapRuntime, SafeUnitCancellation]:
        cancellation.raise_if_requested()
        runtime = self._active_runtime
        unit_cancellation = self._active_unit_cancellation
        if runtime is None or self._active_session != session or unit_cancellation is None:
            message = "requested campaign session has no active safe unit"
            raise CampaignRuntimeEvidenceError(message)
        unit_cancellation.commit()
        return runtime, unit_cancellation

    def commit_battle_program_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CommittedBattleProgramUnit:
        runtime, unit_cancellation = self._commit_active_runtime(session, cancellation)
        port = build_mumu12_battle_program_port(
            runtime,
            runtime._runtime_profile,  # ruff:ignore[private-member-access] - provider owns runtime capability composition.
        )
        return Mumu12CommittedBattleProgramUnit(port, unit_cancellation)

    def commit_active_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CommittedCampaignUnit:
        runtime, unit_cancellation = self._commit_active_runtime(session, cancellation)
        return CommittedCampaignUnit(
            cast("CampaignMapRuntime", runtime),
            unit_cancellation,
        )

    def commit_replacement_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CommittedCampaignUnit:
        cancellation.raise_if_requested()
        if self._prepared_session == session:
            runtime = self._prepared_runtime
            unit_cancellation = self._prepared_unit_cancellation
        elif self._active_session == session:
            runtime = self._active_runtime
            unit_cancellation = self._active_unit_cancellation
        else:
            runtime = None
            unit_cancellation = None
        if runtime is None or unit_cancellation is None:
            message = "requested campaign session has no prepared gems replacement unit"
            raise CampaignRuntimeEvidenceError(message)
        unit_cancellation.commit()
        return CommittedCampaignUnit(
            cast("CampaignMapRuntime", runtime),
            unit_cancellation,
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
        """失效 checkpoint 不再拥有任何 prepared 或 active runtime。"""

        self._release_owned_runtimes(RuntimeSessionOutcome.INTERRUPTED)

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
            runtime = self._active_runtime
            if runtime is None or self._active_session != session or not runtime.runtime_session_active:
                message = "resumable campaign report requires the matching active runtime"
                raise CampaignRuntimeEvidenceError(message)
            if self._prepared_runtime is not None:
                message = "resumable campaign report cannot retain a prepared runtime"
                raise CampaignRuntimeEvidenceError(message)
            runtime.resume_session(state)
            return

        outcome = self._runtime_outcome(state, stop_reason)
        self._release_owned_runtimes(outcome)

    def _release_owned_runtimes(self, outcome: RuntimeSessionOutcome) -> None:
        errors: list[BaseException] = []
        for cleanup in (
            self._discard_prepared_runtime,
            partial(self._release_active_runtime, outcome),
        ):
            try:
                cleanup()
            except BaseException as error:  # ruff:ignore[blind-except] - 两个 owner 必须独立释放。
                errors.append(error)
        raise_cleanup_errors(errors, message="campaign runtime ownership cleanup failed")


class Mumu12HardCampaignPort:
    """用同一 declarative map runtime 执行困难图，不再加载 campaign Python module。"""

    __slots__ = (
        "_active_runtime",
        "_active_stage",
        "_config",
        "_device",
        "_remaining_reader",
        "_runtime_factory",
        "_sessions",
    )

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        sessions: HardCampaignSessionSource,
        *,
        runtime_factory: Callable[
            [AzurLaneConfig, Device, CampaignStageDefinition],
            DeclarativeCampaignMapRuntime,
        ] = DeclarativeCampaignMapRuntime,
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
        if isinstance(runtime_factory, type) and not issubclass(runtime_factory, DeclarativeCampaignMapRuntime):
            message = "hard campaign runtime factory must build DeclarativeCampaignMapRuntime"
            raise TypeError(message)
        if not callable(runtime_factory):
            message = "hard campaign runtime factory must be callable"
            raise TypeError(message)
        if remaining_reader is not None and not callable(remaining_reader):
            message = "hard remaining reader must be callable"
            raise TypeError(message)
        self._config = config
        self._device = device
        self._sessions = sessions
        self._runtime_factory = runtime_factory
        self._remaining_reader = _read_hard_remaining if remaining_reader is None else remaining_reader
        self._active_runtime: DeclarativeCampaignMapRuntime | None = None
        self._active_stage: StageRef | None = None

    def _stage_ref(self, settings: HardSettings) -> StageRef:
        return self._sessions.resolve_hard_stage_ref(settings.stage)

    def _require_active(self, settings: HardSettings) -> DeclarativeCampaignMapRuntime:
        stage = self._stage_ref(settings)
        if self._active_runtime is None or self._active_stage != stage:
            message = "hard campaign operation does not match the active stage"
            raise CampaignRuntimeEvidenceError(message)
        return self._active_runtime

    def remaining_attempts(
        self,
        settings: HardSettings,
        cancellation: CancellationSource,
    ) -> int:
        cancellation.raise_if_requested()
        if self._active_runtime is not None:
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
        runtime = self._runtime_factory(self._config, self._device, definition)
        if not isinstance(runtime, DeclarativeCampaignMapRuntime):
            message = "hard campaign runtime factory returned an invalid runtime"
            raise TypeError(message)
        runtime.device = cast("Device", CancellationAwareMumu12Device(self._device, cancellation))
        try:
            remaining = self._read_remaining_attempts(runtime, settings, cancellation)
        except BaseException as error:
            preserve_cleanup_failure(
                error,
                runtime.discard_runtime,
                message="hard campaign attempt discovery and cleanup both failed",
            )
            raise
        self._active_runtime = runtime
        self._active_stage = stage
        return remaining

    def _read_remaining_attempts(
        self,
        runtime: DeclarativeCampaignMapRuntime,
        settings: HardSettings,
        cancellation: CancellationSource,
    ) -> int:
        runtime.ensure_campaign_ui(settings.stage, mode="hard")
        cancellation.raise_if_requested()
        runtime.device.screenshot()
        cancellation.raise_if_requested()
        remaining = self._remaining_reader(runtime.device)
        if type(remaining) is not int or remaining < 0:
            message = "hard remaining reader must return a non-negative integer"
            raise TypeError(message)
        return remaining

    def advance_one(
        self,
        settings: HardSettings,
        cancellation: CancellationSource,
    ) -> HardBattleOutcome:
        runtime = self._require_active(settings)
        cancellation.raise_if_requested()
        runtime.execute_hard_attempt(cancellation)
        return HardBattleOutcome.SETTLED

    def exit_ui(
        self,
        settings: HardSettings,
        cancellation: CancellationSource,
    ) -> None:
        runtime = self._require_active(settings)
        cancellation.raise_if_requested()
        runtime.ensure_auto_search_exit()
        cancellation.raise_if_requested()

    def release(self) -> None:
        """无条件释放当前 turn 的 runtime，不依赖已可能取消的交互信号。"""

        runtime = self._active_runtime
        self._active_runtime = None
        self._active_stage = None
        if runtime is None:
            return
        if runtime.runtime_session_active:
            runtime.finish_runtime_session(RuntimeSessionOutcome.INTERRUPTED)
        else:
            runtime.discard_runtime()


def _read_hard_remaining(device: Device) -> int:
    return _OCR_HARD_REMAIN.ocr_single(device.image)


def build_mumu12_campaign_dependencies(
    config: AzurLaneConfig,
    device: Device,
    sessions: CampaignSessionSource,
) -> CampaignFactoryDependencies:
    """组装 Campaign factory 所需的 session source 与单 battle live workflow。"""

    provider = Mumu12CampaignRuntimeProvider(config, device)
    programs = Mumu12CampaignBattleProgramExecutor(provider)
    gems_fleets = Mumu12GemsFleetReplacementExecutor(provider)
    workflow = build_existing_campaign_map_workflow(
        provider,
        CampaignLiveServices(
            activator=provider,
            guards=provider,
            programs=programs,
            gems_fleets=gems_fleets,
            lifecycle=provider,
        ),
    )
    return CampaignFactoryDependencies(workflow=workflow, sessions=sessions)
