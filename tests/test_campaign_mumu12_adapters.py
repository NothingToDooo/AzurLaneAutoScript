from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar, cast, override

import pytest
from config_factory import in_memory_config

import module.adapters.campaign_mumu12 as campaign_adapters
import module.adapters.encounter_mumu12 as encounter_adapters
from module.adapters.campaign_map_data_mumu12 import apply_normal_enemy_candidate_mask
from module.adapters.campaign_map_initialization import CampaignMapInitializationService
from module.adapters.campaign_mumu12 import (
    DeclarativeCampaignMapRuntime,
    DeclarativeCampaignRuntimeFactory,
    Mumu12CampaignAttempt,
    Mumu12CampaignRuntimeProvider,
    Mumu12HardCampaignPort,
    compile_campaign_map,
    compose_campaign_attempt_definition,
)
from module.adapters.campaign_program_capabilities import CampaignProgramCapabilityReader
from module.adapters.campaign_runtime_hard import CampaignClearModeExecutor
from module.adapters.campaign_runtime_profile import (
    RuntimeSessionOutcome,
)
from module.adapters.campaign_runtime_session import RuntimeProfileLease, RuntimeProfileLeaseState
from module.adapters.campaign_submarine import STANDARD_CAMPAIGN_SUBMARINE_SERVICES
from module.adapters.gems_mumu12 import (
    GemsHardRetryFleetPreparationService,
    Mumu12GemsRuntimeBehavior,
)
from module.application import AbortRequested, AbortToken, DailySchedule, DelayRange, SafeUnitCancellation, TaskId
from module.base.button import Button
from module.content.battle_policy import BossStrategy, ClearBoss, StagePolicy
from module.content.campaign_session import (
    BattlefieldObservation,
    BattleSucceeded,
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
    CampaignSessionStatus,
    RemainingSpawns,
)
from module.content.campaign_session_source import CampaignStageSelection
from module.content.cell import CellId
from module.content.models import StageRef
from module.content.runtime_profile import RuntimeExecutorKind
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
from module.exception import CampaignEnd, MapAchievementReached
from module.gameplay.campaign import (
    CampaignAutomationSettings,
    CampaignDifficulty,
    CampaignEnemyPrioritySettings,
    CampaignExecutionSettings,
    CampaignFleetSettings,
    CampaignHpControlSettings,
    CampaignJobSpec,
    CampaignLimits,
    CampaignMapAchievement,
    CampaignProgress,
    CampaignStopReason,
    CampaignSubmarineSettings,
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
from module.gameplay.campaign_live import (
    CampaignCheckpointReset,
    CampaignMapAchievementReached,
)
from module.gameplay.emotion import (
    EmotionControl,
    EmotionMode,
    EmotionRecoverLocation,
    EmotionSettings,
    FleetEmotionSettings,
)
from module.gameplay.encounter import HardFleet, HardSettings, HardStopReason
from module.map.map_fleet_preparation import STANDARD_FLEET_PREPARATION_SERVICE
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER
from module.map.map_scanner import (
    MovableEnemyRules,
    MovableEnemySnapshot,
    MovableScanRequest,
)
from module.map.map_spawn_gap import MapSpawnProgress
from module.ui.page import page_campaign_menu

if TYPE_CHECKING:
    from module.adapters.campaign_runtime_profile import CampaignRuntimeProfileManager
    from module.application import CancellationSource
    from module.config.config import AzurLaneConfig
    from module.handler.map_transition_ui import MapTransitionUi
    from module.map.map_base import CampaignMap


def _variant(tokens: tuple[str, ...]) -> RunVariant:
    return RunVariant(
        cells=tuple(
            CellSpec(CellId(index % 2, index // 2), token, float(index + 1)) for index, token in enumerate(tokens)
        ),
        spawn_waves=(SpawnWave(0, enemy=1), SpawnWave(1, boss=1)),
    )


def test_provider_runs_real_runtime_profile_map_initialization_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = in_memory_config("campaign-map-initialization-wiring", {})
    device = object.__new__(Device)
    definition = load_default_stage(StageRef("event_20221222_cn", "a1"))
    sessions = tuple(CampaignSession(definition, variant) for variant in CampaignRunVariant)
    job = replace(
        _job(),
        sessions=sessions,
        stage_selections=(),
        transition_sessions=(),
    )
    session = job.session_for(definition.ref, CampaignRunVariant.NORMAL)
    assert session is not None

    provider = Mumu12CampaignRuntimeProvider(config, device)
    attempt = provider._new_attempt(job, session, AbortToken())  # ruff:ignore[private-member-access]
    runtime = attempt.runtime
    initialization = runtime._map_initialization_service  # ruff:ignore[private-member-access]
    assert attempt._initialization is initialization  # ruff:ignore[private-member-access]
    observed_weights: list[str] = []

    def map_data_init(_runtime: DeclarativeCampaignMapRuntime, map_: CampaignMap | None) -> None:
        assert map_ is runtime.MAP

    def map_control_init(_runtime: DeclarativeCampaignMapRuntime) -> None:
        observed_weights.append(runtime.config.EnemyPriority_EnemyScaleBalanceWeight)

    monkeypatch.setattr(DeclarativeCampaignMapRuntime, "map_data_init", map_data_init)
    monkeypatch.setattr(DeclarativeCampaignMapRuntime, "map_control_init", map_control_init)

    assert config.EnemyPriority_EnemyScaleBalanceWeight == "S3_enemy_first"
    try:
        attempt.initialize(CampaignRunVariant.NORMAL)
        assert observed_weights == ["default_mode"]
    finally:
        attempt.release(RuntimeSessionOutcome.COMPLETED)


def test_declarative_runtime_wires_t4_map_observer_to_the_real_fortress_grid() -> None:
    config = in_memory_config("campaign-map-observer-wiring", {})
    definition = load_default_stage(StageRef("event_20211125_cn", "t4"))
    runtime = DeclarativeCampaignMapRuntime(config, object.__new__(Device), definition)
    runtime.MAP.load_mechanism(fortress=True)
    destination = runtime.MAP[(2, 1)]
    sleeps: list[float] = []
    runtime.device = cast("Device", SimpleNamespace(sleep=sleeps.append))
    runtime.map = runtime.MAP
    runtime.battle_count = 1
    runtime.map_is_clear_mode = False

    assert destination.is_fortress
    assert runtime._map_observer.combat.camera_repositioned_after_combat(  # ruff:ignore[private-member-access] - 删除 profile wiring 时必须失败。
        runtime,
        destination,
    )
    assert sleeps == [3]


def test_declarative_runtime_wires_real_preserve_enemy_genre_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[object, MovableScanRequest]] = []

    def standard_movable(
        _scanner: object,
        observed_runtime: object,
        request: MovableScanRequest,
    ) -> None:
        observed.append((observed_runtime, request))
        cast("DeclarativeCampaignMapRuntime", observed_runtime).map[(0, 0)].wipe_out()

    monkeypatch.setattr(
        type(STANDARD_CAMPAIGN_MAP_OBSERVER.scanner),
        "full_scan_movable",
        standard_movable,
    )
    config = in_memory_config("campaign-map-scanner-wiring", {})
    definition = load_default_stage(StageRef("event_20210325_cn", "a1"))
    runtime = DeclarativeCampaignMapRuntime(config, object.__new__(Device), definition)
    runtime.map = runtime.MAP
    grid = runtime.map[(0, 0)]
    grid.is_siren = True
    grid.enemy_genre = "Siren_Dace"
    request = MovableScanRequest(
        snapshot=MovableEnemySnapshot.capture(runtime.map),
        progress=MapSpawnProgress(),
        rules=MovableEnemyRules(
            siren=True,
            normal_enemy=False,
            enemy_template=False,
            wall=False,
            portal=False,
            ambush=False,
            siren_step=2,
        ),
        enemy_cleared=False,
    )

    runtime._map_observer.scanner.full_scan_movable(  # ruff:ignore[private-member-access] - 验证 profile observer 的真实组合顺序。
        runtime,
        request,
    )

    assert observed == [(runtime, request)]
    assert grid.is_siren
    assert grid.enemy_genre == "Siren_Dace"


class _ExpectedEndTransitionProbe:
    def __init__(self, override: object | None) -> None:
        self.override = override
        self.calls = 0

    @staticmethod
    def handle_stage_return(runtime: object) -> bool:
        del runtime
        raise AssertionError

    @staticmethod
    def stage_page_ready(runtime: object) -> bool:
        del runtime
        raise AssertionError

    @staticmethod
    def event_animation_visible(runtime: object) -> bool:
        del runtime
        raise AssertionError

    def combat_end_override(self, runtime: object) -> object | None:
        del runtime
        self.calls += 1
        return self.override


def test_real_hard_runtime_wires_and_applies_the_manager_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = in_memory_config("campaign-hard-behavior-wiring", {})
    config.replace_runtime_overlay(MAP_HAS_AMBUSH=True)
    assert config.MAP_HAS_AMBUSH is True
    definition = compose_campaign_attempt_definition(
        load_default_stage(StageRef("campaign_main", "8-1")),
        CampaignDifficulty.HARD,
    )
    runtime = DeclarativeCampaignMapRuntime(config, object.__new__(Device), definition)
    transition = _ExpectedEndTransitionProbe(lambda: True)
    runtime._map_transition_ui = cast(  # ruff:ignore[private-member-access] - hard behavior 必须绕过 transition。
        "MapTransitionUi",
        transition,
    )
    baseline_calls: list[str] = []

    def baseline(_runtime: object, expected: str) -> str:
        baseline_calls.append(expected)
        return "with_searching"

    monkeypatch.setattr(campaign_adapters.CampaignEngine, "navigation_expected_end", baseline)

    assert runtime._hard_behavior is runtime._runtime_profile.executor_instance(  # ruff:ignore[private-member-access] - 必须复用 manager 编译出的同一实例。
        RuntimeExecutorKind.HARD_MODE
    )
    assert runtime.config.MAP_HAS_AMBUSH is False
    assert runtime.navigation_expected_end("no_searching") == "in_stage"
    assert transition.calls == 0
    assert baseline_calls == []


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
    fleet_emotion = FleetEmotionSettings(
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
        emotion=EmotionSettings(EmotionMode.CALCULATE, fleet_emotion, fleet_emotion),
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


def _after_first_battle(session: CampaignSession) -> CampaignSessionState:
    initial = session.initial_state()
    decision = session.decide(
        initial,
        BattlefieldObservation(initial.battle_index, enemy=1),
    )
    assert decision.command is not None
    return session.reduce(
        decision.state,
        BattleSucceeded(decision.command, BattleTarget.ENEMY),
    )


class _FakeUI:
    calls: ClassVar[list[tuple[object, bool]]] = []
    devices: ClassVar[list[Device]] = []

    def __init__(self, config: AzurLaneConfig, device: Device) -> None:
        del config
        self.device = device
        type(self).devices.append(device)

    def ui_goto(self, destination: object, *, skip_first_screenshot: bool = True) -> None:
        type(self).calls.append((destination, skip_first_screenshot))


@pytest.fixture(autouse=True)
def _replace_campaign_boundary_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeUI.calls.clear()
    _FakeUI.devices.clear()
    monkeypatch.setattr(campaign_adapters, "UI", _FakeUI)


class _FakeDeclarativeRuntime(DeclarativeCampaignMapRuntime):
    created: ClassVar[list[object]] = []
    client_in_map: ClassVar[bool] = True
    oil: ClassVar[int] = 1_000
    trigger_map_stop: ClassVar[bool] = False
    full_clear: ClassVar[bool] = True
    three_stars: ClassVar[bool] = True
    threat_safe: ClassVar[bool] = True
    cleanup_error: ClassVar[BaseException | None] = None
    close_error: ClassVar[BaseException | None] = None

    def __init__(self, config: AzurLaneConfig, device: Device, definition: CampaignStageDefinition) -> None:
        self.config = config
        self.device = device
        self.definition = definition
        self.selected_entrance = Button(area=(), color=(), button=(1, 2, 3, 4), name="TEST_ENTRANCE")
        self.stage_navigator = self
        self._hard_behavior = (
            object.__new__(CampaignClearModeExecutor)
            if any(
                extension.extension_id.value == "campaign_hard/campaign_hard/campaign"
                for extension in definition.runtime_profile.extensions
            )
            else None
        )
        self.map_is_clear_mode = True
        self.map_is_auto_search = True
        self.map_is_100_percent_clear = type(self).full_clear
        self.map_is_3_stars = type(self).three_stars
        self.map_is_threat_safe = type(self).threat_safe
        self._gems_behavior = None
        self._profile_fleet_preparation_service = STANDARD_FLEET_PREPARATION_SERVICE
        self._fleet_preparation_service = self._profile_fleet_preparation_service
        self._submarine_services = STANDARD_CAMPAIGN_SUBMARINE_SERVICES
        self._map_initialization_service = CampaignMapInitializationService()
        self._runtime_profile = cast(
            "CampaignRuntimeProfileManager",
            SimpleNamespace(
                use_single_fleet_override=lambda _cancellation: None,
                use_support_fleet=lambda _cancellation: False,
            ),
        )
        self._program_capabilities = CampaignProgramCapabilityReader()
        self._runtime_released = False
        self.calls: list[object] = []
        self.session_variant = CampaignRunVariant.NORMAL
        self.battle_count = 0
        self.MAP = compile_campaign_map(definition)
        self.map = self.MAP
        self._runtime_profile_lease = RuntimeProfileLease(_FakeRuntimeProfileSessionManager(self))
        type(self).created.append(self)

    def select(
        self,
        name: str,
        mode: str = "normal",
        *,
        skip_first_screenshot: bool = True,
    ) -> Button:
        del skip_first_screenshot
        self.calls.append(("select_stage", name, mode))
        return self.selected_entrance

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
        assert button is self.selected_entrance
        del skip_first_screenshot
        self.calls.append(("enter_map", mode))
        if type(self).trigger_map_stop:
            message = "map achievement reached"
            raise MapAchievementReached(message)
        return True

    def triggered_map_stop(self) -> bool:
        return type(self).trigger_map_stop

    def handle_map_fleet_lock(self, *, enable: bool | None = None) -> bool:
        del enable
        self.calls.append("handle_map_fleet_lock")
        return True

    def map_data_init(self, map_: CampaignMap | None) -> None:
        assert map_ is self.MAP
        self.map = self.MAP
        self.calls.append("map_data_init")

    def map_control_init(self) -> None:
        self.calls.append("map_control_init")

    def is_in_map(self) -> bool:
        return type(self).client_in_map

    def lv_reset(self) -> None:
        self.calls.append("lv_reset")

    def lv_get(self, *, after_battle: bool = False) -> None:
        del after_battle
        self.calls.append("lv_get")

    def auto_search_execute_a_battle(self) -> None:
        self.calls.append("auto_search_execute_a_battle")
        raise CampaignEnd

    def ensure_auto_search_exit(self, *, skip_first_screenshot: bool = True) -> bool:
        self.calls.append(("ensure_auto_search_exit", skip_first_screenshot))
        return True


class _FakeRuntimeProfileSessionManager:
    def __init__(self, runtime: _FakeDeclarativeRuntime) -> None:
        self._runtime = runtime
        self._started = False

    def begin_session(self) -> None:
        self._started = True
        self._runtime.calls.append("initialize_session")
        events = getattr(self._runtime, "lifecycle_events", None)
        if isinstance(events, list):
            events.append(("lease.start", self._runtime.session_variant))

    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        self._runtime.calls.append(("finish_runtime_session", outcome))
        error = type(self._runtime).close_error
        if error is not None:
            raise error

    def reset(self) -> None:
        self._runtime.calls.append("reset_runtime")
        if not self._started:
            self._runtime.calls.append("discard_runtime")
        self._runtime._runtime_released = True  # ruff:ignore[private-member-access] - fake manager 记录唯一 lease 的释放。
        error = type(self._runtime).cleanup_error
        if error is not None:
            raise error


def test_runtime_factory_builds_complete_attempt_before_publication() -> None:
    _FakeDeclarativeRuntime.created.clear()
    factory = DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime)
    job = _job()
    session = job.sessions[0]

    attempt = factory.build_attempt(
        in_memory_config("campaign-attempt", {}),
        object.__new__(Device),
        job,
        session,
        AbortToken(),
    )

    runtime = cast("_FakeDeclarativeRuntime", attempt.runtime)
    assert attempt.profile_state is RuntimeProfileLeaseState.READY
    assert attempt.prepared
    attempt.release(RuntimeSessionOutcome.INTERRUPTED)
    attempt.release(RuntimeSessionOutcome.INTERRUPTED)
    assert runtime.calls.count("reset_runtime") == 1
    assert runtime.calls.count("discard_runtime") == 1


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

    monkeypatch.setattr(encounter_adapters, "activate_mumu12_task", activate)


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
    runtime._gems_behavior = None  # ruff:ignore[private-member-access] - 构造最小 runtime 以验证跨 turn 账本。
    runtime._profile_fleet_preparation_service = STANDARD_FLEET_PREPARATION_SERVICE  # ruff:ignore[private-member-access] - 构造完整 Gems 准备链。
    runtime._fleet_preparation_service = STANDARD_FLEET_PREPARATION_SERVICE  # ruff:ignore[private-member-access] - Gems wrapper 从标准链开始。
    first = Mumu12GemsRuntimeBehavior(config, policy, SafeUnitCancellation(AbortToken()))
    runtime.configure_gems_behavior(first)
    ledger = runtime.emotion
    second = Mumu12GemsRuntimeBehavior(config, policy, SafeUnitCancellation(AbortToken()))

    runtime.configure_gems_behavior(second)

    assert second.emotion is ledger
    assert runtime.emotion is ledger
    service = runtime._fleet_preparation_service  # ruff:ignore[private-member-access] - 刷新 cancellation 必须替换而非嵌套 wrapper。
    assert isinstance(service, GemsHardRetryFleetPreparationService)
    assert service.inner is runtime._profile_fleet_preparation_service  # ruff:ignore[private-member-access] - wrapper 始终围绕稳定 profile 链。
    assert service.replace_hard_fleet == second.prepare_hard_fleet


def test_campaign_14_4_normal_enemy_candidate_mask_is_complete_and_preserves_ambush() -> None:
    definition = load_default_stage(StageRef("campaign_main", "14-4"))
    expected = tuple(
        CellId.parse(node)
        for node in (
            "A1",
            "G1",
            "B2",
            "C2",
            "F2",
            "H2",
            "D3",
            "D4",
            "G4",
            "K4",
            "C5",
            "D5",
            "F5",
            "K5",
            "B6",
            "C6",
            "G6",
            "C7",
            "I7",
            "B8",
            "E8",
            "G8",
            "H8",
            "I8",
            "J9",
        )
    )
    assert definition.map.normal_enemy_spawn_candidates == expected

    map_ = compile_campaign_map(definition)
    expected_locations = frozenset((cell.x, cell.y) for cell in expected)
    for grid in map_:
        grid.may_enemy = grid.location not in expected_locations
    map_[(7, 1)].may_ambush = True
    map_[(5, 0)].may_ambush = False

    apply_normal_enemy_candidate_mask(
        map_,
        definition.map.normal_enemy_spawn_candidates,
        CampaignRunVariant.NORMAL,
    )

    assert frozenset(grid.location for grid in map_ if grid.may_enemy) == expected_locations
    assert map_[(7, 1)].may_enemy is True
    assert map_[(7, 1)].may_ambush is True
    assert map_[(5, 0)].may_enemy is False
    assert map_[(5, 0)].may_ambush is False


def test_campaign_attempt_maps_map_initialization_abort_to_interrupted() -> None:
    abort = AbortRequested("map initialization cancelled")

    class _AbortingMapDataInitRuntime(_FakeDeclarativeRuntime):
        created: ClassVar[list[object]] = []

        @override
        def map_data_init(self, map_: CampaignMap | None) -> None:
            del map_
            raise abort

    runtime = _AbortingMapDataInitRuntime(
        in_memory_config("campaign-map-init-abort", {}),
        device := object.__new__(Device),
        _definition(),
    )
    job = _job()
    session = CampaignSession(runtime.definition, CampaignRunVariant.NORMAL)
    attempt = Mumu12CampaignAttempt(runtime, runtime.take_profile_lease(), job, session, device, AbortToken())

    with pytest.raises(AbortRequested) as raised:
        attempt.initialize(session.variant)

    assert raised.value is abort
    assert ("finish_runtime_session", RuntimeSessionOutcome.INTERRUPTED) in runtime.calls
    assert attempt.profile_state is RuntimeProfileLeaseState.CLOSED
    assert attempt.active is False


def test_provider_keeps_one_runtime_across_resumable_turns_then_releases_it() -> None:
    _FakeDeclarativeRuntime.created.clear()
    _FakeDeclarativeRuntime.client_in_map = True
    config = in_memory_config("campaign-provider-resume", {})
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    provider = Mumu12CampaignRuntimeProvider(
        config, device, runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime)
    )
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)
    state = _after_first_battle(activated)

    provider.finish(activated, state, CampaignStopReason.IN_PROGRESS)
    progress = CampaignProgress(
        stage_ref=activated.definition.ref,
        variant=activated.variant,
        session_state=state,
        runs_completed=0,
        settings_revision=1,
        content_revision="content-current",
    )
    runtime = _FakeDeclarativeRuntime.created[0]
    assert isinstance(runtime, _FakeDeclarativeRuntime)
    runtime.battle_count = state.battle_index + 7
    resumed = provider.activate(_job(progress=progress), AbortToken())

    assert resumed == activated
    assert len(_FakeDeclarativeRuntime.created) == 1
    assert runtime.calls.count("initialize_session") == 1
    assert runtime.battle_count == state.battle_index + 7

    provider.finish(activated, state, CampaignStopReason.CANCELLED)

    assert ("finish_runtime_session", RuntimeSessionOutcome.INTERRUPTED) in runtime.calls
    with pytest.raises(RuntimeError, match="not the active"):
        provider.active_runtime(activated, AbortToken())


def test_checkpoint_activation_abort_closes_the_active_attempt_as_interrupted() -> None:
    _FakeDeclarativeRuntime.created.clear()
    abort = AbortRequested("checkpoint activation cancelled")
    config = in_memory_config("campaign-checkpoint-abort", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(
        config, device, runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime)
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

    def abort_screenshot() -> None:
        raise abort

    vars(device)["screenshot"] = abort_screenshot

    with pytest.raises(AbortRequested) as raised:
        provider.activate(_job(progress=progress), AbortToken())

    assert raised.value is abort
    runtime = cast("_FakeDeclarativeRuntime", _FakeDeclarativeRuntime.created[0])
    assert ("finish_runtime_session", RuntimeSessionOutcome.INTERRUPTED) in runtime.calls
    assert provider._attempt is None  # ruff:ignore[private-member-access] - 取消清理后不得保留 active attempt。


def test_in_progress_completed_state_closes_the_finished_map_runtime() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider-completed-map", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(
        config, device, runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime)
    )
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
    provider = Mumu12CampaignRuntimeProvider(
        config, device, runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime)
    )
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


def test_provider_reuses_one_committed_cancellation_until_campaign_checkpoint() -> None:
    _FakeDeclarativeRuntime.created.clear()
    config = in_memory_config("campaign-provider", {})
    device = object.__new__(Device)
    provider = Mumu12CampaignRuntimeProvider(
        config, device, runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime)
    )
    cancellation = AbortToken()
    activated = provider.activate(_job(), cancellation)
    assert isinstance(activated, CampaignSession)

    standard_unit = provider.commit_active_unit(activated, cancellation)
    auto_search_unit = provider.commit_active_unit(activated, cancellation)
    cancellation.request("defer until campaign checkpoint")

    assert auto_search_unit.cancellation is standard_unit.cancellation
    standard_unit.cancellation.raise_if_requested()
    auto_search_unit.cancellation.raise_if_requested()
    assert standard_unit.runtime is _FakeDeclarativeRuntime.created[-1]
    assert auto_search_unit.runtime is standard_unit.runtime
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
    provider = Mumu12CampaignRuntimeProvider(
        config, device, runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime)
    )

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


def test_provider_resets_a_retained_checkpoint_when_the_client_left_its_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeDeclarativeRuntime.created.clear()
    monkeypatch.setattr(_FakeDeclarativeRuntime, "client_in_map", True)
    device = object.__new__(Device)
    vars(device)["screenshot"] = lambda: None
    provider = Mumu12CampaignRuntimeProvider(
        in_memory_config("campaign-missing-retained-map", {}),
        device,
        runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime),
    )
    activated = provider.activate(_job(), AbortToken())
    assert isinstance(activated, CampaignSession)
    state = _after_first_battle(activated)
    provider.finish(activated, state, CampaignStopReason.IN_PROGRESS)
    progress = CampaignProgress(
        stage_ref=activated.definition.ref,
        variant=activated.variant,
        session_state=state,
        runs_completed=2,
        settings_revision=1,
        content_revision="content-current",
    )
    _FakeUI.calls.clear()
    monkeypatch.setattr(_FakeDeclarativeRuntime, "client_in_map", False)

    result = provider.activate(_job(progress=progress), AbortToken())

    assert isinstance(result, CampaignCheckpointReset)
    runtime = cast("_FakeDeclarativeRuntime", _FakeDeclarativeRuntime.created[0])
    assert ("finish_runtime_session", RuntimeSessionOutcome.INTERRUPTED) in runtime.calls
    assert _FakeUI.calls == [(page_campaign_menu, False)]
    assert len(_FakeDeclarativeRuntime.created) == 1
    assert provider._attempt is None  # ruff:ignore[private-member-access] - physical mismatch 经统一 reset 释放 attempt。


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
        runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime),
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
        assert "auto_search_execute_a_battle" in runtime.calls
        assert runtime.calls.count(("finish_runtime_session", RuntimeSessionOutcome.COMPLETED)) == 1
        assert runtime.calls.count("reset_runtime") == 1
        assert runtime.calls.count("discard_runtime") == 0
    assert ("ensure_auto_search_exit", True) not in runtimes[0].calls
    assert ("ensure_auto_search_exit", True) not in runtimes[1].calls
    assert ("ensure_auto_search_exit", True) in runtimes[2].calls


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
        runtime_factory=DeclarativeCampaignRuntimeFactory(_FakeDeclarativeRuntime),
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
    assert "auto_search_execute_a_battle" not in cancelled_runtime.calls
    assert "initialize_session" not in cancelled_runtime.calls
    assert "discard_runtime" in cancelled_runtime.calls
    assert retried_runtime.calls.count("reset_runtime") == 1
    assert "discard_runtime" not in retried_runtime.calls
