from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar, Unpack, cast, override

import pytest
from config_factory import in_memory_config

import module.adapters.campaign_mumu12 as campaign_adapters
import module.adapters.encounter_mumu12 as encounter_adapters
from module.adapters.campaign_mumu12 import (
    CampaignRuntimeEvidenceError,
    DeclarativeCampaignMapRuntime,
    Mumu12CampaignRuntimeProvider,
    Mumu12HardCampaignPort,
    campaign_execution_overlay,
    campaign_stage_overlay,
    compile_campaign_map,
    compose_campaign_attempt_definition,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeSessionEntryKind,
    RuntimeSessionOutcome,
)
from module.adapters.gems_mumu12 import Mumu12GemsRuntimeBehavior
from module.application import AbortRequested, AbortToken, DailySchedule, DelayRange, SafeUnitCancellation, TaskId
from module.base.button import Button
from module.content.battle_policy import BossStrategy, ClearBoss, StagePolicy
from module.content.campaign_session import (
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionStatus,
    RemainingSpawns,
)
from module.content.campaign_session_source import CampaignStageSelection
from module.content.cell import CellId
from module.content.mechanic_rules import (
    MapCellAttribute,
    MapCellPatch,
    MapMutationPhase,
    MapMutationRules,
    MapMutationVariant,
    MapStructureRules,
    MovingEnemyRules,
    StageMechanicRules,
    WallEdge,
)
from module.content.models import StageRef
from module.content.runtime_profile import RuntimeExecutorKind
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.content.stage_definition import (
    CampaignStageDefinition,
    CellSpec,
    GridShape,
    LandBasedDirection,
    LandBasedSpec,
    MapDefinition,
    PortalSpec,
    RunVariant,
    SpawnWave,
)
from module.content.stage_loader import load_default_stage
from module.content.stage_rules import (
    CalibrationPoint,
    ChapterSwitch,
    EdgeInsightCorner,
    Homography,
    MapCalibration,
    MapFeatures,
    OneTimeCompletion,
    StageEntrance,
    StageEntrancePosition,
    StageEntranceRevision,
    StageNavigation,
    StageRules,
    StarRequirements,
    SwipeScale,
)
from module.device.device import Device
from module.exception import OilExhausted, ScriptEnd
from module.gameplay.campaign import (
    CampaignAutomationSettings,
    CampaignDifficulty,
    CampaignEmotionSettings,
    CampaignEnemyPrioritySettings,
    CampaignExecutionSettings,
    CampaignFleetEmotionSettings,
    CampaignFleetSettings,
    CampaignHpControlSettings,
    CampaignJobSpec,
    CampaignLimits,
    CampaignMapAchievement,
    CampaignProgress,
    CampaignStopReason,
    CampaignSubmarineSettings,
    EmotionControl,
    EmotionMode,
    EmotionRecoverLocation,
    EnemyPriorityMode,
    FleetMode,
    FleetOrder,
    GemsCommonCarrier,
    GemsCommonDestroyer,
    GemsFarmingPolicy,
    GemsFlagshipChange,
    GemsVanguardChange,
    SubmarineAutoSearchMode,
    SubmarineDistanceToBoss,
    SubmarineMode,
)
from module.gameplay.campaign_live import CampaignCheckpointUnavailable, CampaignMapAchievementReached
from module.gameplay.encounter import HardBattleOutcome, HardFleet, HardSettings, HardStopReason

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.application import CancellationSource
    from module.config.config import AzurLaneConfig
    from module.config.config_generated import ConfigOverrides


def _variant(tokens: tuple[str, ...]) -> RunVariant:
    return RunVariant(
        cells=tuple(
            CellSpec(CellId(index % 2, index // 2), token, float(index + 1)) for index, token in enumerate(tokens)
        ),
        spawn_waves=(SpawnWave(0, enemy=1), SpawnWave(1, boss=1)),
    )


def test_combat_stuck_detection_pause_is_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    @contextmanager
    def suspend_stuck_detection() -> Iterator[None]:
        events.append("disable")
        try:
            yield
        finally:
            events.append("enable")

    runtime = cast(
        "DeclarativeCampaignMapRuntime",
        SimpleNamespace(
            _runtime_profile=SimpleNamespace(combat_disable_stuck_detection_battle=4),
            battle_count=4,
            device=SimpleNamespace(suspend_stuck_detection=suspend_stuck_detection),
            map_is_clear_mode=False,
        ),
    )

    def combat_status(_runtime: object, expected_end: object = None) -> None:
        assert expected_end is None
        events.append("combat")

    monkeypatch.setattr(campaign_adapters.CampaignEngine, "combat_status", combat_status)

    DeclarativeCampaignMapRuntime.combat_status(runtime)

    assert events == ["disable", "combat", "enable"]


def _definition() -> CampaignStageDefinition:
    return CampaignStageDefinition(
        ref=StageRef("event_test", "t1"),
        map=MapDefinition(
            name="T1",
            shape=GridShape(2, 2),
            camera_data=(CellId(0, 0), CellId(1, 1)),
            camera_data_spawn_point=(CellId(1, 0),),
            normal=_variant(("SP", "ME", "--", "MB")),
            loop=_variant(("SP", "--", "ME", "MB")),
            map_covered=(CellId(0, 1),),
            portals=(PortalSpec(CellId(0, 1), CellId(1, 0)),),
            land_based=(LandBasedSpec(CellId(1, 1), LandBasedDirection.LEFT),),
        ),
        rules=StageRules(
            features=MapFeatures(
                siren_templates=("DD",),
                movable_enemy_turns=(2,),
                has_siren=True,
                has_movable_enemy=True,
                has_map_story=True,
                has_fleet_step=True,
                has_ambush=False,
                has_mystery=False,
                has_portal=True,
                has_land_based=True,
            ),
            completion=OneTimeCompletion(StarRequirements(1, 0, 3)),
            navigation=StageNavigation(
                chapter_switch=ChapterSwitch.SP_20241219,
                entrance=StageEntrance(
                    StageEntrancePosition.HALF,
                    StageEntranceRevision.EVENT_20240725,
                ),
                has_mode_switch=True,
            ),
            calibration=MapCalibration(
                swipe=SwipeScale(1.1, 1.2),
                minitouch_swipe=SwipeScale(0.9, 1.0),
                homography=Homography(
                    4,
                    3,
                    (
                        CalibrationPoint(1.0, 2.0),
                        CalibrationPoint(3.0, 4.0),
                        CalibrationPoint(5.0, 6.0),
                        CalibrationPoint(7.0, 8.0),
                    ),
                ),
                edge_insight_corner=EdgeInsightCorner.TOP_LEFT,
            ),
        ),
        enemy_filter="1L > 2L",
        battle_policies={1: StagePolicy((ClearBoss(BossStrategy.FLEET_BOSS),))},
    )


def _execution_settings() -> CampaignExecutionSettings:
    fleet_emotion = CampaignFleetEmotionSettings(
        control=EmotionControl.PREVENT_YELLOW_FACE,
        recover=EmotionRecoverLocation.DORMITORY_FLOOR_1,
        oath=True,
    )
    return CampaignExecutionSettings(
        automation=CampaignAutomationSettings(
            ambush_evade=True,
            use_2x_book=False,
            use_auto_search=True,
            use_clear_mode=True,
            use_fleet_lock=False,
        ),
        fleets=CampaignFleetSettings(
            1,
            FleetMode.COMBAT_AUTO,
            3,
            2,
            FleetMode.HIDE_IN_BOTTOM_LEFT,
            4,
            FleetOrder.FLEET1_MOB_FLEET2_BOSS,
        ),
        submarine=CampaignSubmarineSettings(
            1,
            SubmarineMode.BOSS_ONLY,
            SubmarineAutoSearchMode.AUTO_CALL,
            SubmarineDistanceToBoss.ONE_GRID_TO_BOSS,
        ),
        emotion=CampaignEmotionSettings(EmotionMode.CALCULATE, fleet_emotion, fleet_emotion),
        hp_control=CampaignHpControlSettings(
            use_hp_balance=True,
            use_emergency_repair=True,
            use_low_hp_retreat=False,
            hp_balance_threshold=0.3,
            hp_balance_weight=(1000, 800, 600),
            repair_use_single_threshold=0.25,
            repair_use_multi_threshold=0.5,
            low_hp_retreat_threshold=0.2,
        ),
        enemy_priority=CampaignEnemyPrioritySettings(EnemyPriorityMode.LARGE_ENEMY_FIRST),
    )


def _job(*, progress: CampaignProgress | None = None) -> CampaignJobSpec:
    definition = _definition()
    sessions = tuple(CampaignSession(definition, variant) for variant in CampaignRunVariant)
    return CampaignJobSpec(
        task_id=TaskId("main"),
        sessions=sessions,
        difficulty=CampaignDifficulty.NORMAL,
        execution=_execution_settings(),
        schedule=DailySchedule("Asia/Hong_Kong", (time(4),)),
        failure_retry_delay=DelayRange(1_800, 1_800),
        resource_retry_delay=timedelta(minutes=180),
        progress=progress,
    )


class _FakeDeclarativeRuntime(DeclarativeCampaignMapRuntime):
    created: ClassVar[list[object]] = []
    client_in_map: ClassVar[bool] = True
    oil: ClassVar[int] = 1_000
    trigger_map_stop: ClassVar[bool] = False
    full_clear: ClassVar[bool] = True
    three_stars: ClassVar[bool] = True
    threat_safe: ClassVar[bool] = True

    def __init__(self, config: AzurLaneConfig, device: Device, definition: CampaignStageDefinition) -> None:
        self.config = config
        self.device = device
        self.definition = definition
        self.ENTRANCE = Button(area=(), color=(), button=(1, 2, 3, 4), name="TEST_ENTRANCE")
        self.map_is_clear_mode = True
        self.map_is_100_percent_clear = type(self).full_clear
        self.map_is_3_stars = type(self).three_stars
        self.map_is_threat_safe = type(self).threat_safe
        self._gems_behavior = None
        self._runtime_session_active = False
        self._runtime_released = False
        self.calls: list[object] = []
        type(self).created.append(self)

    def ensure_campaign_ui(self, name: str, mode: str = "normal", **_kwargs: object) -> bool:
        self.calls.append(("ensure_campaign_ui", name, mode))
        return True

    def get_oil(self, *, skip_first_screenshot: bool = True) -> int:
        del skip_first_screenshot
        self.calls.append("get_oil")
        return type(self).oil

    def enter_map(
        self,
        button: Button,
        mode: str = "normal",
        *,
        skip_first_screenshot: bool = True,
    ) -> bool:
        del button, skip_first_screenshot
        self.calls.append(("enter_map", mode))
        if type(self).trigger_map_stop:
            message = "map achievement reached"
            raise ScriptEnd(message)
        return True

    def triggered_map_stop(self) -> bool:
        return type(self).trigger_map_stop

    def handle_map_fleet_lock(self, *, enable: bool | None = None) -> bool:
        del enable
        self.calls.append("handle_map_fleet_lock")
        return True

    def initialize_session(
        self,
        variant: CampaignRunVariant,
        battle_index: int,
        entry_kind: RuntimeSessionEntryKind,
        state: object | None = None,
    ) -> None:
        self._runtime_session_active = True
        self.calls.append(("initialize_session", variant, battle_index, entry_kind, state))

    def resume_session(self, state: object) -> None:
        if not self._runtime_session_active:
            message = "fake runtime session is not active"
            raise AssertionError(message)
        self.calls.append(("resume_session", state))

    @property
    def runtime_session_active(self) -> bool:
        return self._runtime_session_active

    def finish_runtime_session(self, outcome: RuntimeSessionOutcome) -> None:
        if not self._runtime_session_active:
            message = "fake runtime session is not active"
            raise AssertionError(message)
        self._runtime_session_active = False
        self._runtime_released = True
        self.calls.append(("finish_runtime_session", outcome))

    def discard_runtime(self) -> None:
        if self._runtime_session_active:
            message = "fake active runtime cannot be discarded"
            raise AssertionError(message)
        if not self._runtime_released:
            self._runtime_released = True
            self.calls.append("discard_runtime")

    def prepare_battle(self, battle_index: int) -> None:
        self.calls.append(("prepare_battle", battle_index))

    def is_in_map(self) -> bool:
        return type(self).client_in_map

    def execute_hard_attempt(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self.calls.append("execute_hard_attempt")

    def ensure_auto_search_exit(self, *, skip_first_screenshot: bool = True) -> bool:
        self.calls.append(("ensure_auto_search_exit", skip_first_screenshot))
        return True


class _FailingHardRuntime(_FakeDeclarativeRuntime):
    created: ClassVar[list[object]] = []
    failures: ClassVar[list[BaseException]] = []

    def execute_hard_attempt(self, cancellation: CancellationSource) -> None:
        super().execute_hard_attempt(cancellation)
        if type(self).failures:
            raise type(self).failures.pop(0)


class _FakeSessionSource:
    def __init__(
        self,
        definition: CampaignStageDefinition,
        *,
        hard_override_stages: frozenset[str] = frozenset(),
    ) -> None:
        self.definition = definition
        self.hard_override_stages = hard_override_stages
        self.requests: list[tuple[StageRef, CampaignRunVariant]] = []

    def resolve_hard_stage_ref(self, stage_id: str) -> StageRef:
        pack_id = "campaign_hard" if stage_id.lower() in self.hard_override_stages else "campaign_main"
        return StageRef(pack_id, stage_id.lower())

    def resolve(self, ref: StageRef, variant: CampaignRunVariant) -> CampaignSession:
        self.requests.append((ref, variant))
        return CampaignSession(self.definition, variant)

    @staticmethod
    def select(
        ref: StageRef,
        *,
        remaining_runs: int,
        preferred_ref: StageRef | None = None,
    ) -> CampaignStageSelection:
        del remaining_runs, preferred_ref
        return CampaignStageSelection(ref, ref)


def _hard_settings(stage: str = "11-4") -> HardSettings:
    return HardSettings(
        DailySchedule("Asia/Hong_Kong", (time(4),)),
        DelayRange(1_800, 1_800),
        timedelta(hours=2),
        stage,
        HardFleet.FLEET_1,
    )


class _HardClock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 7, 14, 12, tzinfo=UTC)


def _disable_hard_activation(monkeypatch: pytest.MonkeyPatch, device: Device) -> None:
    def activate(
        _config: AzurLaneConfig,
        _device: Device,
        _task_name: str,
        _overlay: object,
        cancellation: CancellationSource,
    ) -> Device:
        cancellation.raise_if_requested()
        return device

    monkeypatch.setattr(encounter_adapters, "_activate", activate)


def test_compiler_materializes_both_variants_and_map_structure() -> None:
    compiled = compile_campaign_map(_definition())

    assert compiled.name == "T1"
    assert compiled.shape == (1, 1)
    assert compiled.map_data == "SP ME\n-- MB"
    assert compiled.map_data_loop == "SP --\nME MB"
    assert compiled.weight_data == "1.0 2.0\n3.0 4.0"
    assert [str(grid) for grid in compiled.camera_data] == ["A1", "B2"]
    assert [str(grid) for grid in compiled.camera_data_spawn_point] == ["B1"]
    assert [str(grid) for grid in compiled.manual_map_covered] == ["A2"]
    assert compiled.portal_data == [((0, 1), (1, 0))]
    assert compiled.land_based_data == [("B2", "left")]
    assert compiled.spawn_data == [{"battle": 0, "enemy": 1}, {"battle": 1, "boss": 1}]
    assert compiled.spawn_data_loop == [{"battle": 0, "enemy": 1}, {"battle": 1, "boss": 1}]


def test_compiler_projects_typed_map_structures_into_legacy_mechanisms() -> None:
    definition = _definition()
    structures = MapStructureRules(
        walls=(
            WallEdge(CellId(0, 0), CellId(1, 0)),
            WallEdge(CellId(0, 0), CellId(0, 1)),
        ),
        maze_groups=((CellId(0, 0), CellId(1, 1)),),
        fortress_enemy_cells=(CellId(1, 0),),
        fortress_block_cells=(CellId(0, 1),),
        bouncing_enemy_routes=((CellId(0, 0), CellId(1, 0)),),
    )
    definition = replace(
        definition,
        mechanics=replace(definition.mechanics, map_structures=structures),
    )

    compiled = compile_campaign_map(definition)

    assert compiled.maze_data == [("A1", "B2")]
    assert tuple(grid.location for grid in compiled.fortress_data[0]) == ((1, 0),)
    assert tuple(grid.location for grid in compiled.fortress_data[1]) == ((0, 1),)
    assert [tuple(grid.location for grid in route) for route in compiled.bouncing_enemy_data] == [((0, 0), (1, 0))]

    compiled.load_map_data()
    compiled.grid_connection_initial(wall=True)
    compiled.load_mechanism(maze=True, fortress=True, bouncing_enemy=True)
    assert (1, 0) not in compiled.grid_connection[(0, 0)]
    assert (0, 1) not in compiled.grid_connection[(0, 0)]
    assert compiled[(0, 0)].is_maze is True
    assert compiled[(1, 0)].is_fortress is True
    assert compiled[(0, 1)].is_mechanism_block is True
    assert compiled[(0, 0)].may_bouncing_enemy is True


def test_stage_rules_compile_to_explicit_runtime_overlay() -> None:
    definition = replace(
        _definition(),
        mechanics=StageMechanicRules(moving_enemies=MovingEnemyRules(turns=(3,), normal_turns=(1, 2))),
    )
    overlay = campaign_stage_overlay(definition)

    assert overlay["MAP_SIREN_TEMPLATE"] == ("DD",)
    assert overlay["MOVABLE_ENEMY_TURN"] == (3,)
    assert overlay["MOVABLE_NORMAL_ENEMY_TURN"] == (1, 2)
    assert overlay["MAP_HAS_MOVABLE_NORMAL_ENEMY"] is True
    assert overlay["MAP_HAS_PORTAL"] is True
    assert overlay["MAP_HAS_LAND_BASED"] is True
    assert overlay["STAR_REQUIRE_2"] == 0
    assert overlay["MAP_IS_ONE_TIME_STAGE"] is True
    assert overlay["STAGE_ENTRANCE"] == ("half", "20240725")
    assert overlay["MAP_CHAPTER_SWITCH_20241219_SP"] is True
    assert overlay["MAP_CHAPTER_SWITCH_20241219"] is False
    assert overlay["MAP_SWIPE_MULTIPLY"] == (1.1, 1.2)
    assert overlay["HOMO_STORAGE"] == (
        (4, 3),
        ((1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)),
    )
    assert overlay["MAP_ENSURE_EDGE_INSIGHT_CORNER"] == "top-left"


def test_stage_overlay_enables_every_declared_map_structure() -> None:
    definition = _definition()
    definition = replace(
        definition,
        mechanics=replace(
            definition.mechanics,
            map_structures=MapStructureRules(
                walls=(WallEdge(CellId(0, 0), CellId(1, 0)),),
                maze_groups=((CellId(0, 0),),),
                fortress_enemy_cells=(CellId(1, 0),),
                bouncing_enemy_routes=((CellId(0, 0), CellId(1, 0)),),
            ),
        ),
    )

    overlay = campaign_stage_overlay(definition)

    assert overlay["MAP_HAS_WALL"] is True
    assert overlay["MAP_HAS_MAZE"] is True
    assert overlay["MAP_HAS_FORTRESS"] is True
    assert overlay["MAP_HAS_BOUNCING_ENEMY"] is True


def test_every_profile_operation_has_an_explicit_production_runtime_method() -> None:
    registry = load_default_campaign_runtime_profile_registry()
    grid_kinds = {
        RuntimeExecutorKind.MAP_GRID_RECOGNITION,
        RuntimeExecutorKind.CAMERA_GRID_RECOGNITION,
    }
    missing: set[str] = set()
    for extension in registry.extensions.values():
        for binding in extension.executors:
            if binding.kind in grid_kinds:
                continue
            operations = binding.options.get("operations", ())
            if isinstance(operations, tuple):
                missing.update(
                    operation
                    for operation in operations
                    if isinstance(operation, str) and operation not in DeclarativeCampaignMapRuntime.__dict__
                )

    assert missing == set()


def test_execution_settings_compile_to_legacy_campaign_primitives() -> None:
    settings = _execution_settings()
    overlay = campaign_execution_overlay(settings)

    assert overlay["Campaign_AmbushEvade"] is True
    assert overlay["Campaign_UseAutoSearch"] is True
    assert overlay["Fleet_Fleet1Mode"] == "combat_auto"
    assert overlay["Fleet_FleetOrder"] == "fleet1_mob_fleet2_boss"
    assert overlay["Submarine_Mode"] == "boss_only"
    assert overlay["Emotion_Fleet1Control"] == "prevent_yellow_face"
    assert overlay["Emotion_Fleet2Recover"] == "dormitory_floor_1"
    assert (
        not {
            "Emotion_Fleet1Value",
            "Emotion_Fleet1Record",
            "Emotion_Fleet2Value",
            "Emotion_Fleet2Record",
        }
        & overlay.keys()
    )
    assert overlay["HpControl_HpBalanceWeight"] == "1000, 800, 600"
    assert overlay["EnemyPriority_EnemyScaleBalanceWeight"] == "S3_enemy_first"


def test_campaign_runtime_does_not_reapply_stale_emotion_values_after_recording() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-emotion-ledger", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)

    config.set_record(Emotion_Fleet1Value=83, Emotion_Fleet2Value=71)
    provider.finish(activated, activated.initial_state(), CampaignStopReason.CANCELLED)

    assert (config.Emotion_Fleet1Value, config.Emotion_Fleet2Value) == (83, 71)


def test_refreshing_gems_cancellation_preserves_the_active_map_emotion_ledger() -> None:
    config = in_memory_config("campaign-gems-ledger", {})
    fallback = CampaignSession(
        replace(_definition(), ref=StageRef("campaign_main", "2-4")),
        CampaignRunVariant.NORMAL,
    )
    policy = GemsFarmingPolicy(
        fallback,
        GemsFlagshipChange.SHIP,
        GemsCommonCarrier.ANY,
        GemsVanguardChange.SHIP,
        GemsCommonDestroyer.ANY,
    )
    runtime = object.__new__(DeclarativeCampaignMapRuntime)
    runtime.config = config
    runtime._gems_behavior = None  # noqa: SLF001 - 构造最小 runtime 以验证跨 turn 账本。
    first = Mumu12GemsRuntimeBehavior(config, policy, SafeUnitCancellation(AbortToken()))
    runtime.configure_gems_behavior(first)
    ledger = runtime.emotion
    second = Mumu12GemsRuntimeBehavior(config, policy, SafeUnitCancellation(AbortToken()))

    runtime.configure_gems_behavior(second)

    assert second.emotion is ledger
    assert runtime.emotion is ledger


def test_runtime_applies_only_the_requested_before_battle_patches() -> None:
    definition = _definition()
    definition = replace(
        definition,
        mechanics=StageMechanicRules(
            map_mutations=MapMutationRules(
                (
                    MapCellPatch(
                        phase=MapMutationPhase.BEFORE_BATTLE,
                        cell=CellId(0, 1),
                        attribute=MapCellAttribute.IS_ENEMY,
                        value=True,
                        battle=0,
                    ),
                    MapCellPatch(
                        phase=MapMutationPhase.BEFORE_BATTLE,
                        cell=CellId(1, 0),
                        attribute=MapCellAttribute.IS_SIREN,
                        value=True,
                        battle=1,
                    ),
                )
            )
        ),
    )
    runtime = object.__new__(DeclarativeCampaignMapRuntime)
    runtime.definition = definition
    runtime.map = compile_campaign_map(definition)
    runtime.session_variant = CampaignRunVariant.NORMAL

    runtime.prepare_battle(0)

    assert runtime.map[(0, 1)].is_enemy is True
    assert runtime.map[(1, 0)].is_siren is False


def test_runtime_applies_map_patches_only_to_the_declared_variant() -> None:
    definition = _definition()
    definition = replace(
        definition,
        mechanics=StageMechanicRules(
            map_mutations=MapMutationRules(
                (
                    MapCellPatch(
                        phase=MapMutationPhase.MAP_DATA_INIT,
                        cell=CellId(0, 1),
                        attribute=MapCellAttribute.MAY_ENEMY,
                        value=True,
                        variant=MapMutationVariant.NORMAL,
                    ),
                )
            )
        ),
    )
    runtime = object.__new__(DeclarativeCampaignMapRuntime)
    runtime.definition = definition
    runtime.map = compile_campaign_map(definition)
    runtime.session_variant = CampaignRunVariant.LOOP

    runtime._apply_map_patches(MapMutationPhase.MAP_DATA_INIT)  # noqa: SLF001 - 精确验证内部 phase 过滤。

    assert runtime.map[(0, 1)].may_enemy is False
    runtime.session_variant = CampaignRunVariant.NORMAL
    runtime._apply_map_patches(MapMutationPhase.MAP_DATA_INIT)  # noqa: SLF001 - 精确验证内部 phase 过滤。
    assert runtime.map[(0, 1)].may_enemy is True


def test_campaign_14_4_normal_override_is_declarative_and_does_not_leak_into_loop() -> None:
    definition = load_default_stage(StageRef("campaign_main", "14-4"))
    patches = definition.mechanics.map_mutations.patches
    assert len(patches) == 21
    assert {patch.variant for patch in patches} == {MapMutationVariant.NORMAL}

    runtime = object.__new__(DeclarativeCampaignMapRuntime)
    runtime.definition = definition
    runtime.map = compile_campaign_map(definition)
    runtime.session_variant = CampaignRunVariant.NORMAL
    assert runtime.map[(7, 1)].may_enemy is False
    assert runtime.map[(5, 0)].may_enemy is True
    runtime._apply_map_patches(MapMutationPhase.MAP_DATA_INIT)  # noqa: SLF001 - 验证物化的关卡契约。
    assert runtime.map[(7, 1)].may_enemy is True
    assert runtime.map[(5, 0)].may_enemy is False

    runtime.map.load_map_data(use_loop=True)
    runtime.session_variant = CampaignRunVariant.LOOP
    runtime._apply_map_patches(MapMutationPhase.MAP_DATA_INIT)  # noqa: SLF001 - 验证 variant 隔离。
    assert runtime.map[(7, 1)].may_enemy is False
    assert runtime.map[(5, 0)].may_enemy is True


def test_runtime_rejects_invalid_battle_index_before_mutating_map() -> None:
    runtime = object.__new__(DeclarativeCampaignMapRuntime)

    with pytest.raises(ValueError, match="non-negative"):
        runtime.prepare_battle(-1)


def test_runtime_is_poisoned_before_session_cleanup_can_fail() -> None:
    cleanup_error = RuntimeError("session cleanup failed")
    calls: list[object] = []

    class _EndFailingProfile:
        @staticmethod
        def end_session(outcome: RuntimeSessionOutcome) -> None:
            calls.append(("end_session", outcome))
            raise cleanup_error

        @staticmethod
        def reset() -> None:
            calls.append("reset")

    runtime = object.__new__(DeclarativeCampaignMapRuntime)
    vars(runtime).update(
        _runtime_profile=_EndFailingProfile(),
        _runtime_profile_available=True,
        _runtime_profile_session_active=True,
    )

    with pytest.raises(RuntimeError) as raised:
        runtime.finish_runtime_session(RuntimeSessionOutcome.FAILED)

    assert raised.value is cleanup_error
    assert runtime._runtime_profile_available is False  # noqa: SLF001 - 验证失败后的所有权状态。
    assert runtime._runtime_profile_session_active is False  # noqa: SLF001 - 失败后不能再报告 active。
    assert calls == [("end_session", RuntimeSessionOutcome.FAILED), "reset"]
    with pytest.raises(CampaignRuntimeProfileError, match="already been released"):
        runtime.initialize_session(
            CampaignRunVariant.NORMAL,
            0,
            RuntimeSessionEntryKind.FRESH,
        )


def test_new_runtime_refresh_failure_cleans_the_factory_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_error = RuntimeError("runtime cancellation refresh failed")
    cleanup_error = OSError("runtime discard failed")

    class _RefreshCleanupFailingRuntime(_FakeDeclarativeRuntime):
        created: ClassVar[list[object]] = []

        @override
        def discard_runtime(self) -> None:
            self._runtime_released = True
            self.calls.append("discard_runtime")
            raise cleanup_error

    def fail_refresh(
        provider: Mumu12CampaignRuntimeProvider,
        job: CampaignJobSpec,
        runtime: DeclarativeCampaignMapRuntime,
        cancellation: CancellationSource,
    ) -> SafeUnitCancellation:
        del provider, job, runtime, cancellation
        raise refresh_error

    monkeypatch.setattr(Mumu12CampaignRuntimeProvider, "_refresh_runtime_cancellation", fail_refresh)
    provider = Mumu12CampaignRuntimeProvider(
        in_memory_config("campaign-refresh-cleanup-failure", {}),
        object.__new__(Device),
        runtime_factory=_RefreshCleanupFailingRuntime,
    )

    with pytest.raises(ExceptionGroup) as raised:
        provider.activate(_job(), AbortToken())

    assert raised.value.exceptions == (refresh_error, cleanup_error)
    runtime = cast("_RefreshCleanupFailingRuntime", _RefreshCleanupFailingRuntime.created[0])
    assert runtime.calls[-1] == "discard_runtime"


def test_fresh_activation_guard_cleans_runtime_when_entry_setup_fails() -> None:
    setup_error = RuntimeError("campaign UI setup failed")
    cleanup_error = OSError("runtime discard failed")

    class _SetupCleanupFailingRuntime(_FakeDeclarativeRuntime):
        created: ClassVar[list[object]] = []

        @override
        def ensure_campaign_ui(self, name: str, mode: str = "normal", **kwargs: object) -> bool:
            del name, mode, kwargs
            raise setup_error

        @override
        def discard_runtime(self) -> None:
            self._runtime_released = True
            self.calls.append("discard_runtime")
            raise cleanup_error

    provider = Mumu12CampaignRuntimeProvider(
        in_memory_config("campaign-entry-setup-cleanup-failure", {}),
        object.__new__(Device),
        runtime_factory=_SetupCleanupFailingRuntime,
    )

    with pytest.raises(ExceptionGroup) as raised:
        provider.activate(_job(), AbortToken())

    assert raised.value.exceptions == (setup_error, cleanup_error)


def test_activation_guard_releases_initialized_runtime_when_final_overlay_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlay_error = RuntimeError("final runtime overlay failed")
    config = in_memory_config("campaign-final-overlay-failure", {})
    original_apply_runtime_overlay = config.apply_runtime_overlay

    def fail_final_overlay(**kwargs: Unpack[ConfigOverrides]) -> None:
        if kwargs == {"Campaign_UseAutoSearch": True}:
            raise overlay_error
        original_apply_runtime_overlay(**kwargs)

    monkeypatch.setattr(config, "apply_runtime_overlay", fail_final_overlay)
    provider = Mumu12CampaignRuntimeProvider(
        config,
        object.__new__(Device),
        runtime_factory=_FakeDeclarativeRuntime,
    )

    with pytest.raises(RuntimeError) as raised:
        provider.activate(_job(), AbortToken())

    assert raised.value is overlay_error
    runtime = cast("_FakeDeclarativeRuntime", _FakeDeclarativeRuntime.created[-1])
    assert ("finish_runtime_session", RuntimeSessionOutcome.FAILED) in runtime.calls
    assert provider._active_runtime is None  # noqa: SLF001 - overlay 失败前不能发布 owner。


def test_provider_enters_once_and_exposes_only_the_exact_activated_variant() -> None:
    _FakeDeclarativeRuntime.created.clear()
    _FakeDeclarativeRuntime.client_in_map = True
    config = in_memory_config("campaign-provider", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)

    activated = provider.activate(_job(), AbortToken())

    assert isinstance(activated, CampaignSession)
    assert activated.variant is CampaignRunVariant.LOOP
    runtime = _FakeDeclarativeRuntime.created[-1]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert ("ensure_campaign_ui", "t1", "normal") in runtime.calls
    assert (
        "initialize_session",
        CampaignRunVariant.LOOP,
        0,
        RuntimeSessionEntryKind.FRESH,
        activated.initial_state(),
    ) in runtime.calls
    assert config.Campaign_UseAutoSearch is True
    assert provider.active_runtime(activated, AbortToken()) is runtime


def test_hard_attempt_overlay_is_immutable_and_idempotent() -> None:
    definition = _definition()

    effective = compose_campaign_attempt_definition(definition, CampaignDifficulty.HARD)

    assert effective is not definition
    assert definition.runtime_profile.extensions == ()
    assert [extension.extension_id.value for extension in effective.runtime_profile.extensions] == [
        "campaign_hard/campaign_hard/campaign"
    ]
    assert compose_campaign_attempt_definition(effective, CampaignDifficulty.HARD) is effective
    assert compose_campaign_attempt_definition(definition, CampaignDifficulty.NORMAL) is definition


def test_provider_composes_hard_runtime_profile_for_a_main_stage() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider-hard", {})
    device = object.__new__(Device)
    job = replace(_job(), difficulty=CampaignDifficulty.HARD)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)

    activated = provider.activate(job, AbortToken())

    assert isinstance(activated, CampaignSession)
    runtime = _FakeDeclarativeRuntime.created[-1]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert [extension.extension_id.value for extension in runtime.definition.runtime_profile.extensions] == [
        "campaign_hard/campaign_hard/campaign"
    ]
    assert job.sessions[0].definition.runtime_profile.extensions == ()
    provider.finish(activated, activated.initial_state(), CampaignStopReason.CANCELLED)


def test_provider_keeps_one_runtime_across_resumable_turns_then_releases_it() -> None:
    _FakeDeclarativeRuntime.created.clear()
    _FakeDeclarativeRuntime.client_in_map = True
    config = in_memory_config("campaign-provider-resume", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)
    state = activated.initial_state()

    provider.finish(activated, state, CampaignStopReason.IN_PROGRESS)
    progress = CampaignProgress(
        stage_ref=activated.definition.ref,
        variant=activated.variant,
        session_state=state,
        runs_completed=0,
        settings_revision=1,
        content_revision="content-current",
    )
    resumed = provider.activate(_job(progress=progress), AbortToken())

    assert resumed == activated
    assert len(_FakeDeclarativeRuntime.created) == 1
    runtime = _FakeDeclarativeRuntime.created[0]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert runtime.calls.count(("resume_session", state)) == 2

    provider.finish(activated, state, CampaignStopReason.CANCELLED)

    assert ("finish_runtime_session", RuntimeSessionOutcome.INTERRUPTED) in runtime.calls
    with pytest.raises(RuntimeError, match="not the active"):
        provider.active_runtime(activated, AbortToken())


def test_checkpoint_probe_failure_releases_the_retained_runtime() -> None:
    screenshot_error = RuntimeError("checkpoint screenshot failed")
    cleanup_error = OSError("runtime finish failed")

    class _CheckpointCleanupFailingRuntime(_FakeDeclarativeRuntime):
        created: ClassVar[list[object]] = []

        @override
        def finish_runtime_session(self, outcome: RuntimeSessionOutcome) -> None:
            self._runtime_session_active = False
            self._runtime_released = True
            self.calls.append(("finish_runtime_session", outcome))
            raise cleanup_error

    def fail_screenshot() -> None:
        raise screenshot_error

    config = in_memory_config("campaign-checkpoint-probe-failure", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = fail_screenshot
    provider = Mumu12CampaignRuntimeProvider(
        config,
        device,
        runtime_factory=_CheckpointCleanupFailingRuntime,
    )
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)
    state = activated.initial_state()
    provider.finish(activated, state, CampaignStopReason.IN_PROGRESS)
    progress = CampaignProgress(
        stage_ref=activated.definition.ref,
        variant=activated.variant,
        session_state=state,
        runs_completed=0,
        settings_revision=1,
        content_revision="content-current",
    )

    with pytest.raises(ExceptionGroup) as raised:
        provider.activate(_job(progress=progress), AbortToken())

    assert raised.value.exceptions == (screenshot_error, cleanup_error)
    assert provider._active_runtime is None  # noqa: SLF001 - probe 失败后 active owner 必须清空。


def test_provider_discards_retained_checkpoint_runtime_as_interrupted() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider-stale", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)
    provider.finish(activated, activated.initial_state(), CampaignStopReason.IN_PROGRESS)
    stale_runtime = _FakeDeclarativeRuntime.created[-1]
    fresh_job = _job()

    with pytest.raises(CampaignRuntimeEvidenceError, match="fresh campaign entry cannot replace"):
        provider.before_entry(
            fresh_job,
            fresh_job.sessions[0],
            fresh_job.sessions[0].initial_state(),
            AbortToken(),
        )

    provider.discard_checkpoint()
    fresh = provider.activate(fresh_job, AbortToken())

    assert isinstance(stale_runtime, _FakeDeclarativeRuntime)
    assert ("finish_runtime_session", RuntimeSessionOutcome.INTERRUPTED) in stale_runtime.calls
    assert isinstance(fresh, CampaignSession)
    assert len(_FakeDeclarativeRuntime.created) == 2


def test_provider_discards_prepared_checkpoint_runtime() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider-stale-prepared", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    job = _job()
    session = job.sessions[0]

    provider.before_entry(job, session, session.initial_state(), AbortToken())
    prepared_runtime = _FakeDeclarativeRuntime.created[-1]
    provider.discard_checkpoint()

    assert isinstance(prepared_runtime, _FakeDeclarativeRuntime)
    assert "discard_runtime" in prepared_runtime.calls


def test_provider_attempts_prepared_and_active_cleanup_after_each_failure() -> None:
    calls: list[str] = []
    prepared_error = RuntimeError("prepared cleanup failed")
    active_error = OSError("active cleanup failed")

    class _ResetFailingProfile:
        def __init__(self, label: str, error: BaseException) -> None:
            self._label = label
            self._error = error

        def reset(self) -> None:
            calls.append(self._label)
            raise self._error

    def failing_runtime(label: str, error: BaseException) -> DeclarativeCampaignMapRuntime:
        runtime = object.__new__(DeclarativeCampaignMapRuntime)
        vars(runtime).update(
            _runtime_profile=_ResetFailingProfile(label, error),
            _runtime_profile_available=True,
            _runtime_profile_session_active=False,
        )
        return runtime

    prepared_runtime = failing_runtime("prepared", prepared_error)
    active_runtime = failing_runtime("active", active_error)
    config = in_memory_config("campaign-provider-cleanup-failure", {})
    provider = Mumu12CampaignRuntimeProvider(config, object.__new__(Device))
    provider._prepared_runtime = prepared_runtime  # noqa: SLF001 - 构造双 owner 失败状态。
    provider._active_runtime = active_runtime  # noqa: SLF001 - 构造双 owner 失败状态。

    with pytest.raises(ExceptionGroup) as raised:
        provider.discard_checkpoint()

    assert raised.value.exceptions == (prepared_error, active_error)
    assert calls == ["prepared", "active"]
    assert provider._prepared_runtime is None  # noqa: SLF001 - 验证失败后 owner 已释放。
    assert provider._active_runtime is None  # noqa: SLF001 - 验证失败后 owner 已释放。
    assert prepared_runtime._runtime_profile_available is False  # noqa: SLF001 - 验证 prepared owner 已失效。
    assert active_runtime._runtime_profile_available is False  # noqa: SLF001 - 验证 active owner 已失效。


def test_in_progress_completed_state_closes_the_finished_map_runtime() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider-completed-map", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)
    completed = replace(
        activated.initial_state(),
        status=CampaignSessionStatus.COMPLETED,
        battle_index=len(activated.run_variant.spawn_waves),
        remaining=RemainingSpawns(),
    )

    provider.finish(activated, completed, CampaignStopReason.IN_PROGRESS)

    runtime = _FakeDeclarativeRuntime.created[-1]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert ("finish_runtime_session", RuntimeSessionOutcome.COMPLETED) in runtime.calls


def test_completed_map_remains_completed_when_post_map_fleet_replacement_fails() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider-post-map-gems-failure", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)
    completed = replace(
        activated.initial_state(),
        status=CampaignSessionStatus.COMPLETED,
        battle_index=len(activated.run_variant.spawn_waves),
        remaining=RemainingSpawns(),
    )

    provider.finish(activated, completed, CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED)

    runtime = _FakeDeclarativeRuntime.created[-1]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert ("finish_runtime_session", RuntimeSessionOutcome.COMPLETED) in runtime.calls


def test_active_map_fleet_replacement_failure_marks_runtime_failed() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider-pre-map-gems-failure", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)

    provider.finish(
        activated,
        activated.initial_state(),
        CampaignStopReason.GEMS_HARD_PREPARATION_FAILED,
    )

    runtime = _FakeDeclarativeRuntime.created[-1]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert ("finish_runtime_session", RuntimeSessionOutcome.FAILED) in runtime.calls


def test_provider_reports_failed_domain_state_to_runtime_lifecycle() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider-failed", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)
    failed = replace(
        activated.initial_state(),
        status=CampaignSessionStatus.FAILED,
        reason="battle failed",
    )

    provider.finish(activated, failed, CampaignStopReason.FAILED)

    runtime = _FakeDeclarativeRuntime.created[-1]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert ("finish_runtime_session", RuntimeSessionOutcome.FAILED) in runtime.calls


def test_provider_commits_program_io_as_one_non_interruptible_safe_unit() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    cancellation = AbortToken()
    activated = provider.activate(_job(), cancellation)
    assert isinstance(activated, CampaignSession)

    unit = provider.commit_active_unit(activated, cancellation)
    cancellation.request("defer until campaign checkpoint")

    unit.cancellation.raise_if_requested()
    assert unit.runtime is _FakeDeclarativeRuntime.created[-1]
    with pytest.raises(AbortRequested, match="defer until campaign checkpoint"):
        cancellation.raise_if_requested()


def test_provider_returns_typed_map_achievement_evidence_from_entry_stop() -> None:
    _FakeDeclarativeRuntime.created.clear()
    _FakeDeclarativeRuntime.trigger_map_stop = True
    _FakeDeclarativeRuntime.full_clear = True
    _FakeDeclarativeRuntime.three_stars = False
    _FakeDeclarativeRuntime.threat_safe = True
    config = in_memory_config("campaign-provider", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)

    try:
        result = provider.activate(
            replace(
                _job(),
                limits=CampaignLimits(map_achievement=CampaignMapAchievement.THREAT_SAFE_WITHOUT_THREE_STARS),
            ),
            AbortToken(),
        )
    finally:
        _FakeDeclarativeRuntime.trigger_map_stop = False
        _FakeDeclarativeRuntime.three_stars = True

    assert result == CampaignMapAchievementReached(full_clear=True, three_stars=False, threat_safe=True)
    runtime = _FakeDeclarativeRuntime.created[-1]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert "handle_map_fleet_lock" not in runtime.calls
    assert not any(call[0] == "initialize_session" for call in runtime.calls if isinstance(call, tuple))


def test_provider_preserves_rejected_map_stop_and_discard_failure() -> None:
    cleanup_error = OSError("runtime discard failed")

    class _RejectedStopRuntime(_FakeDeclarativeRuntime):
        created: ClassVar[list[object]] = []
        trigger_map_stop = True

        @override
        def triggered_map_stop(self) -> bool:
            return False

        def discard_runtime(self) -> None:
            self.calls.append("discard_runtime")
            raise cleanup_error

    provider = Mumu12CampaignRuntimeProvider(
        in_memory_config("campaign-map-stop-cleanup-failure", {}),
        object.__new__(Device),
        runtime_factory=_RejectedStopRuntime,
    )

    with pytest.raises(ExceptionGroup) as raised:
        provider.activate(_job(), AbortToken())

    stop_error, observed_cleanup_error = raised.value.exceptions
    assert isinstance(stop_error, ScriptEnd)
    assert observed_cleanup_error is cleanup_error


def test_provider_preserves_map_stop_inspection_and_discard_failures() -> None:
    inspection_error = RuntimeError("map-stop inspection failed")
    cleanup_error = OSError("runtime discard failed")

    class _InspectionFailingStopRuntime(_FakeDeclarativeRuntime):
        created: ClassVar[list[object]] = []
        trigger_map_stop = True

        @override
        def triggered_map_stop(self) -> bool:
            raise inspection_error

        def discard_runtime(self) -> None:
            self.calls.append("discard_runtime")
            raise cleanup_error

    provider = Mumu12CampaignRuntimeProvider(
        in_memory_config("campaign-map-stop-inspection-failure", {}),
        object.__new__(Device),
        runtime_factory=_InspectionFailingStopRuntime,
    )

    with pytest.raises(ExceptionGroup) as raised:
        provider.activate(_job(), AbortToken())

    handling_error, observed_cleanup_error = raised.value.exceptions
    assert isinstance(handling_error, ExceptionGroup)
    stop_error, observed_inspection_error = handling_error.exceptions
    assert isinstance(stop_error, ScriptEnd)
    assert observed_inspection_error is inspection_error
    assert observed_cleanup_error is cleanup_error


def test_resource_free_selection_projects_exact_completion_runtime_policy() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    base = _job()
    ref = base.stage_refs[0]
    job = replace(
        base,
        stage_selections=(CampaignStageSelection(ref, ref, resource_free=True),),
    )
    session = job.sessions[0]

    provider.before_entry(job, session, session.initial_state(), AbortToken())

    assert config.Emotion_Mode == "ignore"
    assert config.Fleet_Fleet2 == 0
    assert config.Submarine_Fleet == 0
    assert config.StopCondition_MapAchievement == "100_percent_clear"
    assert config.StopCondition_StageIncrease is False


@pytest.mark.parametrize(
    ("vanguard_change", "expected_emotion_mode"),
    [
        (GemsVanguardChange.SHIP_AND_EQUIPMENT, "calculate"),
        (GemsVanguardChange.DISABLED, "ignore"),
    ],
)
def test_gems_policy_projects_runtime_configuration_without_overwriting_live_equipment_codes(
    vanguard_change: GemsVanguardChange,
    expected_emotion_mode: str,
) -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config(
        "campaign-provider",
        {"GemsFarming": {"EquipmentCode": {"Config": "DD: live-code"}}},
    )
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    base = _job()
    fallback_definition = replace(
        base.sessions[0].definition,
        ref=StageRef("campaign_main", "2-4"),
    )
    fallback = CampaignSession(fallback_definition, CampaignRunVariant.NORMAL)
    job = replace(
        base,
        task_id=TaskId("gems_farming"),
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP_AND_EQUIPMENT,
            GemsCommonCarrier.RANGER,
            vanguard_change,
            GemsCommonDestroyer.CASSIN_OR_DOWNES,
        ),
    )
    session = job.sessions[0]

    provider._activate_config(job, session.definition)  # noqa: SLF001 - 验证单一配置投影边界。

    assert config.GemsFarming_ChangeFlagship == "ship_equip"
    assert config.GemsFarming_CommonCV == "ranger"
    assert config.GemsFarming_ChangeVanguard == vanguard_change.value
    assert config.GemsFarming_CommonDD == "cassin_or_downes"
    assert config.EquipmentCode_Config == "DD: live-code"
    assert config.EnemyPriority_EnemyScaleBalanceWeight == "S1_enemy_first"
    assert config.Emotion_Mode == expected_emotion_mode
    assert config.STOP_IF_REACH_LV32 is True


def test_provider_reuses_pre_entry_evidence_runtime_for_activation() -> None:
    _FakeDeclarativeRuntime.created.clear()
    _FakeDeclarativeRuntime.client_in_map = True
    config = in_memory_config("campaign-provider", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)
    job = _job()
    session = job.sessions[0]

    evidence = provider.before_entry(job, session, session.initial_state(), AbortToken())
    activated = provider.activate(job, AbortToken())

    assert evidence.oil == 1_000
    assert len(_FakeDeclarativeRuntime.created) == 1
    runtime = _FakeDeclarativeRuntime.created[0]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert runtime.calls.count(("ensure_campaign_ui", "t1", "normal")) == 1
    assert isinstance(activated, CampaignSession)


def test_provider_restarts_an_initial_checkpoint_after_evidence_proves_a_map_boundary() -> None:
    _FakeDeclarativeRuntime.created.clear()
    _FakeDeclarativeRuntime.client_in_map = False
    config = in_memory_config("campaign-provider", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    base_job = _job()
    normal = base_job.session_for(base_job.stage_refs[0], CampaignRunVariant.NORMAL)
    assert normal is not None
    progress = CampaignProgress(
        stage_ref=normal.definition.ref,
        variant=normal.variant,
        session_state=normal.initial_state(),
        runs_completed=2,
        settings_revision=1,
        content_revision="content-current",
    )
    job = _job(progress=progress)
    selected = job.session_for(progress.stage_ref, progress.variant)
    assert selected is not None
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)

    evidence = provider.before_entry(job, selected, progress.session_state, AbortToken())
    runtime = _FakeDeclarativeRuntime.created[0]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    runtime.map_is_clear_mode = False
    activated = provider.activate(job, AbortToken())

    assert evidence.resuming_checkpoint is False
    assert len(_FakeDeclarativeRuntime.created) == 1
    assert activated == selected
    assert ("enter_map", "normal") in runtime.calls


def test_provider_rejects_a_checkpoint_when_the_client_left_its_map() -> None:
    _FakeDeclarativeRuntime.created.clear()
    _FakeDeclarativeRuntime.client_in_map = False
    config = in_memory_config("campaign-provider", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    job = _job()
    normal = job.session_for(job.stage_refs[0], CampaignRunVariant.NORMAL)
    assert normal is not None
    progress = CampaignProgress(
        stage_ref=normal.definition.ref,
        variant=normal.variant,
        session_state=normal.initial_state(),
        runs_completed=2,
        settings_revision=1,
        content_revision="content-current",
    )
    provider = Mumu12CampaignRuntimeProvider(config, device, runtime_factory=_FakeDeclarativeRuntime)

    result = provider.activate(_job(progress=progress), AbortToken())

    assert isinstance(result, CampaignCheckpointUnavailable)
    assert "not inside" in result.reason


@pytest.mark.parametrize(
    ("stage", "hard_override_stages", "expected_ref"),
    [
        ("12-4", frozenset({"12-4"}), StageRef("campaign_hard", "12-4")),
        ("11-4", frozenset(), StageRef("campaign_main", "11-4")),
    ],
)
def test_hard_port_uses_explicit_override_or_main_map_and_settles_one_attempt(
    stage: str,
    hard_override_stages: frozenset[str],
    expected_ref: StageRef,
) -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("hard-port", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    vars(device)["image"] = object()
    source = _FakeSessionSource(_definition(), hard_override_stages=hard_override_stages)
    port = Mumu12HardCampaignPort(
        config,
        device,
        source,
        runtime_factory=_FakeDeclarativeRuntime,
        remaining_reader=lambda _device: 2,
    )
    settings = _hard_settings(stage)
    cancellation = AbortToken()

    assert port.remaining_attempts(settings, cancellation) == 2
    assert source.requests == [(expected_ref, CampaignRunVariant.LOOP)]
    runtime = _FakeDeclarativeRuntime.created[-1]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    assert [extension.extension_id.value for extension in runtime.definition.runtime_profile.extensions][-1] == (
        "campaign_hard/campaign_hard/campaign"
    )
    assert ("ensure_campaign_ui", stage, "hard") in runtime.calls
    assert port.advance_one(settings, cancellation) is HardBattleOutcome.SETTLED
    port.exit_ui(settings, cancellation)
    port.release()

    assert "execute_hard_attempt" in runtime.calls
    assert ("ensure_auto_search_exit", True) in runtime.calls
    assert "discard_runtime" in runtime.calls


def test_hard_workflow_closes_each_real_runtime_across_three_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("hard-workflow", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    vars(device)["image"] = object()
    source = _FakeSessionSource(_definition())
    remaining = iter((3, 2, 1))
    port = Mumu12HardCampaignPort(
        config,
        device,
        source,
        runtime_factory=_FakeDeclarativeRuntime,
        remaining_reader=lambda _device: next(remaining),
    )
    _disable_hard_activation(monkeypatch, device)
    workflow = encounter_adapters.Mumu12HardWorkflow(config, device, port, _HardClock())
    settings = _hard_settings()

    reports = tuple(workflow.execute(settings, AbortToken()) for _ in range(3))

    assert tuple(report.stop_reason for report in reports) == (
        HardStopReason.IN_PROGRESS,
        HardStopReason.IN_PROGRESS,
        HardStopReason.COMPLETED,
    )
    assert tuple(report.attempts_available for report in reports) == (3, 2, 1)
    assert len(_FakeDeclarativeRuntime.created) == 3
    runtimes = tuple(cast("_FakeDeclarativeRuntime", runtime) for runtime in _FakeDeclarativeRuntime.created)
    for runtime in runtimes:
        assert "execute_hard_attempt" in runtime.calls
        assert "discard_runtime" in runtime.calls
    assert ("ensure_auto_search_exit", True) not in runtimes[0].calls
    assert ("ensure_auto_search_exit", True) not in runtimes[1].calls
    assert ("ensure_auto_search_exit", True) in runtimes[2].calls


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OilExhausted(), HardStopReason.RESOURCE_LIMIT),
        (ScriptEnd(), HardStopReason.FAILED),
    ],
)
def test_hard_workflow_releases_real_runtime_before_retry(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    expected: HardStopReason,
) -> None:
    _FailingHardRuntime.created.clear()
    _FailingHardRuntime.failures = [failure]
    config = in_memory_config("hard-retry", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    vars(device)["image"] = object()
    remaining = iter((2, 1))
    port = Mumu12HardCampaignPort(
        config,
        device,
        _FakeSessionSource(_definition()),
        runtime_factory=_FailingHardRuntime,
        remaining_reader=lambda _device: next(remaining),
    )
    _disable_hard_activation(monkeypatch, device)
    workflow = encounter_adapters.Mumu12HardWorkflow(config, device, port, _HardClock())
    settings = _hard_settings()

    first = workflow.execute(settings, AbortToken())
    retried = workflow.execute(settings, AbortToken())

    assert first.stop_reason is expected
    assert retried.stop_reason is HardStopReason.COMPLETED
    assert len(_FailingHardRuntime.created) == 2
    first_runtime = cast("_FailingHardRuntime", _FailingHardRuntime.created[0])
    retried_runtime = cast("_FailingHardRuntime", _FailingHardRuntime.created[1])
    assert "discard_runtime" in first_runtime.calls
    assert "discard_runtime" in retried_runtime.calls


def test_hard_workflow_releases_real_runtime_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("hard-cancel", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    vars(device)["image"] = object()
    cancelled = AbortToken()
    remaining = iter((2, 1))

    def read_remaining(_device: Device) -> int:
        value = next(remaining)
        if value == 2:
            cancelled.request("test cancellation")
        return value

    port = Mumu12HardCampaignPort(
        config,
        device,
        _FakeSessionSource(_definition()),
        runtime_factory=_FakeDeclarativeRuntime,
        remaining_reader=read_remaining,
    )
    _disable_hard_activation(monkeypatch, device)
    workflow = encounter_adapters.Mumu12HardWorkflow(config, device, port, _HardClock())
    settings = _hard_settings()

    with pytest.raises(AbortRequested, match="test cancellation"):
        workflow.execute(settings, cancelled)
    retried = workflow.execute(settings, AbortToken())

    assert retried.stop_reason is HardStopReason.COMPLETED
    assert len(_FakeDeclarativeRuntime.created) == 2
    cancelled_runtime = cast("_FakeDeclarativeRuntime", _FakeDeclarativeRuntime.created[0])
    retried_runtime = cast("_FakeDeclarativeRuntime", _FakeDeclarativeRuntime.created[1])
    assert "execute_hard_attempt" not in cancelled_runtime.calls
    assert "discard_runtime" in cancelled_runtime.calls
    assert "discard_runtime" in retried_runtime.calls


def test_hard_workflow_releases_real_runtime_after_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FailingHardRuntime.created.clear()
    _FailingHardRuntime.failures = [RuntimeError("unexpected hard runtime failure")]
    config = in_memory_config("hard-error", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    vars(device)["image"] = object()
    remaining = iter((2, 1))
    port = Mumu12HardCampaignPort(
        config,
        device,
        _FakeSessionSource(_definition()),
        runtime_factory=_FailingHardRuntime,
        remaining_reader=lambda _device: next(remaining),
    )
    _disable_hard_activation(monkeypatch, device)
    workflow = encounter_adapters.Mumu12HardWorkflow(config, device, port, _HardClock())
    settings = _hard_settings()

    with pytest.raises(RuntimeError, match="unexpected hard runtime failure"):
        workflow.execute(settings, AbortToken())
    retried = workflow.execute(settings, AbortToken())

    assert retried.stop_reason is HardStopReason.COMPLETED
    assert len(_FailingHardRuntime.created) == 2
    failed_runtime = cast("_FailingHardRuntime", _FailingHardRuntime.created[0])
    retried_runtime = cast("_FailingHardRuntime", _FailingHardRuntime.created[1])
    assert "discard_runtime" in failed_runtime.calls
    assert "discard_runtime" in retried_runtime.calls


def test_hard_port_preserves_attempt_discovery_and_cleanup_failures() -> None:
    discovery_error = RuntimeError("attempt discovery failed")
    cleanup_error = OSError("runtime cleanup failed")

    class _CleanupFailingRuntime(_FakeDeclarativeRuntime):
        created: ClassVar[list[object]] = []

        def discard_runtime(self) -> None:
            self.calls.append("discard_runtime")
            raise cleanup_error

    def fail_remaining(_device: Device) -> int:
        raise discovery_error

    config = in_memory_config("hard-cleanup-failure", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    vars(device)["image"] = object()
    port = Mumu12HardCampaignPort(
        config,
        device,
        _FakeSessionSource(_definition()),
        runtime_factory=_CleanupFailingRuntime,
        remaining_reader=fail_remaining,
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        port.remaining_attempts(_hard_settings(), AbortToken())

    assert raised.value.exceptions == (discovery_error, cleanup_error)
    runtime = cast("_CleanupFailingRuntime", _CleanupFailingRuntime.created[0])
    assert runtime.calls[-1] == "discard_runtime"


def test_hard_port_stage_mismatch_can_be_released_without_cancellation() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("hard-stage-mismatch", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    vars(device)["image"] = object()
    port = Mumu12HardCampaignPort(
        config,
        device,
        _FakeSessionSource(_definition()),
        runtime_factory=_FakeDeclarativeRuntime,
        remaining_reader=lambda _device: 1,
    )
    first = _hard_settings("11-4")
    second = _hard_settings("12-4")

    assert port.remaining_attempts(first, AbortToken()) == 1
    with pytest.raises(CampaignRuntimeEvidenceError, match="does not match the active stage"):
        port.exit_ui(second, AbortToken())
    port.release()
    first_runtime = cast("_FakeDeclarativeRuntime", _FakeDeclarativeRuntime.created[0])
    assert "discard_runtime" in first_runtime.calls

    assert port.remaining_attempts(second, AbortToken()) == 1
    port.release()
    second_runtime = cast("_FakeDeclarativeRuntime", _FakeDeclarativeRuntime.created[1])
    assert "discard_runtime" in second_runtime.calls
