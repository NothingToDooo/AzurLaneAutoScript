from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import pytest

import module.adapters.opsi_mumu12 as opsi_adapters
from module.adapters.opsi_live import LiveOperationSirenWorkflow, LiveOpsiStep, OpsiLiveClock
from module.adapters.opsi_mumu12 import (
    CancellationAwareMumu12Device,
    Mumu12OperationSirenSession,
    apply_world_task_spec,
)
from module.application import AbortRequested, AbortToken, PreemptionRequest, TaskId
from module.config.config import AzurLaneConfig
from module.config.deep import deep_set
from module.device.device import Device
from module.gameplay.opsi import (
    WORLD_TASK_DEFINITIONS,
    AbyssalSettings,
    ArchiveSettings,
    AshAssistSettings,
    AshBeaconAttackMode,
    AshBeaconSettings,
    CrossMonthSettings,
    ExploreSettings,
    FleetSettings,
    Hazard1LevelingSettings,
    MeowfficerFarmingSettings,
    MonthBossMode,
    MonthBossSettings,
    ObscureSettings,
    OpsiDailySettings,
    OpsiShopPreset,
    ShopSettings,
    StrongholdSettings,
    VoucherSettings,
    WorldGeneralSettings,
    WorldOperation,
    WorldSchedule,
    WorldTaskSpec,
    WorldTaskStatus,
    world_task_spec,
)
from module.gameplay.opsi_progress import WorldProgress, WorldZoneCursor

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.gameplay.opsi import WorldTaskSettings
    from module.interaction import CancellationSignal
    from module.os.globe_zone import Zone


_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SCHEDULE = WorldSchedule(
    next_server_update_at=_NOW + timedelta(days=1),
    next_month_reset_at=_NOW + timedelta(days=18),
    next_archive_refresh_at=_NOW + timedelta(days=2),
)
_GENERAL = WorldGeneralSettings(
    use_logger=True,
    buy_action_point_limit=2,
    oil_preserve=1200,
    repair_threshold=0.4,
    random_map_events=True,
    akashi_shop_filter="ActionPoint",
)
_FLEET = FleetSettings(fleet_index=2, use_submarine=True)


def _settings(operation: WorldOperation) -> WorldTaskSettings:
    settings: dict[WorldOperation, WorldTaskSettings] = {
        WorldOperation.ASH_ASSIST: AshAssistSettings(minimum_tier=10),
        WorldOperation.ASH_BEACON: AshBeaconSettings(
            attack_mode=AshBeaconAttackMode.CURRENT,
            one_hit_mode=True,
            dossier_auto_attack=False,
            request_assist=True,
            ensure_fully_collected=True,
        ),
        WorldOperation.EXPLORE: ExploreSettings(
            _GENERAL,
            _FLEET,
            special_radar=False,
            force_run=False,
            last_zone=0,
        ),
        WorldOperation.SHOP: ShopSettings(_GENERAL, OpsiShopPreset.MAX_BENEFIT, "ActionPoint"),
        WorldOperation.VOUCHER: VoucherSettings(_GENERAL, "LoggerAbyssal"),
        WorldOperation.DAILY: OpsiDailySettings(
            _GENERAL,
            _FLEET,
            do_missions=True,
            use_tuning_samples=True,
        ),
        WorldOperation.OBSCURE: ObscureSettings(_GENERAL, _FLEET, force_run=False),
        WorldOperation.ABYSSAL: AbyssalSettings(_GENERAL, "Fleet-1", force_run=False),
        WorldOperation.ARCHIVE: ArchiveSettings(_GENERAL, _FLEET, "LoggerArchive"),
        WorldOperation.STRONGHOLD: StrongholdSettings(_GENERAL, "Fleet-1", force_run=False),
        WorldOperation.MONTH_BOSS: MonthBossSettings(
            _GENERAL,
            "Fleet-1",
            MonthBossMode.NORMAL_HARD,
            check_adaptability=True,
            force_run=False,
        ),
        WorldOperation.MEOWFFICER_FARMING: MeowfficerFarmingSettings(
            _GENERAL,
            _FLEET,
            1000,
            5,
            0,
            ensure_ash_fully_collected=True,
        ),
        WorldOperation.HAZARD1_LEVELING: Hazard1LevelingSettings(
            _GENERAL,
            _FLEET,
            22,
            ensure_ash_fully_collected=True,
        ),
        WorldOperation.CROSS_MONTH: CrossMonthSettings(
            _GENERAL,
            _FLEET,
            FleetSettings(3, use_submarine=False),
            "Fleet-4",
            FleetSettings(4, use_submarine=False),
        ),
    }
    return settings[operation]


def _spec(operation: WorldOperation) -> WorldTaskSpec:
    return world_task_spec(TaskId(operation.value), _settings(operation))


class _Clock(OpsiLiveClock):
    @override
    def now(self) -> datetime:
        return _NOW


class _ScheduleSource:
    calls: list[datetime]

    def __init__(self) -> None:
        self.calls = []

    def snapshot(self, observed_at: datetime) -> WorldSchedule:
        self.calls.append(observed_at)
        return _SCHEDULE


class _Driver:
    calls: list[tuple[WorldTaskSpec, WorldProgress | None, CancellationSignal]]

    def __init__(self, step: LiveOpsiStep, after: Callable[[], None] | None = None) -> None:
        self.step = step
        self.after = after
        self.calls = []

    def execute_step(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSignal,
    ) -> LiveOpsiStep:
        self.calls.append((spec, progress, cancellation))
        if self.after is not None:
            self.after()
        return self.step


@pytest.mark.parametrize("operation", tuple(WorldOperation))
def test_live_workflow_accepts_every_typed_operation(operation: WorldOperation) -> None:
    driver = _Driver(LiveOpsiStep(operation, WorldTaskStatus.EMPTY))
    schedule = _ScheduleSource()
    workflow = LiveOperationSirenWorkflow(driver, schedule, _Clock())
    abort = AbortToken()

    report = workflow.execute(_spec(operation), None, abort, PreemptionRequest())

    assert report.status is WorldTaskStatus.EMPTY
    assert driver.calls == [(_spec(operation), None, abort)]
    assert schedule.calls == [_NOW]


def test_live_workflow_turns_post_step_preemption_into_resumable_report() -> None:
    preemption = PreemptionRequest()
    step = LiveOpsiStep(
        WorldOperation.EXPLORE,
        WorldTaskStatus.IN_PROGRESS,
        completed_units=1,
        cursor=WorldZoneCursor(7),
    )

    def request_preemption() -> None:
        preemption.request("higher priority task")

    workflow = LiveOperationSirenWorkflow(
        _Driver(step, after=request_preemption),
        _ScheduleSource(),
        _Clock(),
    )

    report = workflow.execute(_spec(WorldOperation.EXPLORE), None, AbortToken(), preemption)

    assert report.status is WorldTaskStatus.PREEMPTED
    assert report.completed_units == 1
    assert report.cursor == WorldZoneCursor(7)


def test_live_workflow_rejects_partial_progress_from_one_shot_driver() -> None:
    step = LiveOpsiStep(WorldOperation.SHOP, WorldTaskStatus.IN_PROGRESS, completed_units=1)
    workflow = LiveOperationSirenWorkflow(_Driver(step), _ScheduleSource(), _Clock())

    with pytest.raises(ValueError, match="one-shot operation cannot expose partial progress"):
        workflow.execute(_spec(WorldOperation.SHOP), None, AbortToken(), PreemptionRequest())


def test_live_workflow_checks_cancellation_before_entering_driver() -> None:
    abort = AbortToken()
    abort.request("manual stop")
    driver = _Driver(LiveOpsiStep(WorldOperation.EXPLORE, WorldTaskStatus.EMPTY))
    workflow = LiveOperationSirenWorkflow(driver, _ScheduleSource(), _Clock())

    with pytest.raises(AbortRequested, match="manual stop"):
        workflow.execute(_spec(WorldOperation.EXPLORE), None, abort, PreemptionRequest())

    assert driver.calls == []


def test_mumu12_executor_binds_each_task_before_schedule_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AzurLaneConfig.from_snapshot("opsi-task-binding", {}, task="OpsiDaily")
    deep_set(config.data, "OpsiDaily.Scheduler.ServerUpdate", "13:00")
    deep_set(config.data, "OpsiExplore.Scheduler.ServerUpdate", "01:00")
    config.bind(config.task)
    device = object.__new__(Device)

    class _Session:
        def __init__(self, _config: AzurLaneConfig, _device: Device) -> None:
            pass

        @staticmethod
        def prepare_live_step() -> None:
            pass

        @staticmethod
        def execute_live_step(spec: WorldTaskSpec) -> LiveOpsiStep:
            return LiveOpsiStep(spec.operation, WorldTaskStatus.EMPTY)

    monkeypatch.setattr(opsi_adapters, "Mumu12OperationSirenSession", _Session)
    workflow = opsi_adapters.build_mumu12_operation_siren_workflow(config, device)

    explore = workflow.execute(
        _spec(WorldOperation.EXPLORE),
        None,
        AbortToken(),
        PreemptionRequest(),
    )
    daily = workflow.execute(
        _spec(WorldOperation.DAILY),
        None,
        AbortToken(),
        PreemptionRequest(),
    )

    assert explore.schedule.next_server_update_at.hour == 1
    assert daily.schedule.next_server_update_at.hour == 13
    assert config.task.command == "OpsiDaily"


class _IoTarget:
    calls: list[str]

    def __init__(self) -> None:
        self.calls = []

    def screenshot(self) -> None:
        self.calls.append("screenshot")


def test_mumu12_io_proxy_honors_cancellation_before_next_call() -> None:
    target = _IoTarget()
    abort = AbortToken()
    proxy = CancellationAwareMumu12Device(target, abort)
    screenshot = cast("Callable[[], None]", proxy.screenshot)

    screenshot()
    abort.request("manual stop")
    with pytest.raises(AbortRequested, match="manual stop"):
        screenshot()

    assert target.calls == ["screenshot"]


class _Config:
    overrides: dict[str, object]
    OpsiFleet_Fleet: int
    OpsiFleet_Submarine: bool
    OpsiGeneral_UseLogger: bool

    def __init__(self) -> None:
        self.overrides = {}

    def apply_runtime_overlay(self, **kwargs: object) -> None:
        self.overrides.update(kwargs)

    def replace_runtime_overlay(self, **kwargs: object) -> None:
        self.overrides = dict(kwargs)


def test_typed_explore_settings_and_checkpoint_drive_mumu12_overlay() -> None:
    config = _Config()
    spec = _spec(WorldOperation.EXPLORE)
    progress = WorldProgress(
        task_id=TaskId(WorldOperation.EXPLORE.value),
        operation=WorldOperation.EXPLORE,
        completed_units=3,
        cycle_anchor=_NOW + timedelta(days=18),
        settings_revision=1,
        content_revision="test-content",
        cursor=WorldZoneCursor(42),
    )

    apply_world_task_spec(cast("AzurLaneConfig", config), spec, progress)

    assert config.overrides == {
        "OpsiGeneral_UseLogger": True,
        "OpsiGeneral_BuyActionPointLimit": 2,
        "OpsiGeneral_OilLimit": 1200,
        "OpsiGeneral_RepairThreshold": 0.4,
        "OpsiGeneral_DoRandomMapEvent": True,
        "OpsiGeneral_AkashiShopFilter": "ActionPoint",
        "OpsiFleet_Fleet": 2,
        "OpsiFleet_Submarine": True,
        "OpsiExplore_SpecialRadar": False,
        "OpsiExplore_ForceRun": False,
        "OpsiExplore_LastZone": 42,
    }


def test_live_prepare_does_not_run_implicit_auto_search(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(Mumu12OperationSirenSession)
    calls: list[str] = []
    config = _Config()
    runner.config = cast("AzurLaneConfig", config)
    monkeypatch.setattr(runner, "_os_init_ensure_page", lambda: calls.append("ensure_page"))
    monkeypatch.setattr(runner, "_os_init_prepare_current_zone", lambda: calls.append("prepare_zone"))
    monkeypatch.setattr(runner, "_os_init_clear_current_zone", lambda: calls.append("auto_search"))

    runner.prepare_live_step()

    assert calls == ["ensure_page", "prepare_zone"]


def test_explore_live_step_processes_only_first_observed_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(Mumu12OperationSirenSession)
    processed: list[int] = []
    monkeypatch.setattr(runner, "_os_explore_order", lambda: [7, 8])
    monkeypatch.setattr(runner, "_skip_cleared_os_explore_zone", lambda _zone: False)
    monkeypatch.setattr(runner, "_run_os_explore_zone", processed.append)

    result = runner.execute_live_step(_spec(WorldOperation.EXPLORE))

    assert processed == [7]
    assert result.completed_units == 1
    assert result.cursor == WorldZoneCursor(7)
    assert result.status is WorldTaskStatus.IN_PROGRESS


def test_obscure_non_force_mode_finishes_after_one_confirmed_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(Mumu12OperationSirenSession)
    config = _Config()
    config.OpsiGeneral_UseLogger = True
    config.OpsiFleet_Fleet = 2
    config.OpsiFleet_Submarine = True
    runner.config = cast("AzurLaneConfig", config)
    runner.zone = cast("Zone", SimpleNamespace(zone_id=77))
    calls: list[str] = []
    monkeypatch.setattr(runner, "cl1_ap_preserve", lambda: None)
    monkeypatch.setattr(runner, "storage_get_next_item", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "zone_init", lambda: None)
    monkeypatch.setattr(runner, "fleet_set", lambda _fleet: True)
    monkeypatch.setattr(runner, "os_order_execute", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "run_auto_search", lambda **_kwargs: calls.append("zone"))
    monkeypatch.setattr(runner, "map_exit", lambda: None)
    monkeypatch.setattr(runner, "handle_after_auto_search", lambda: None)

    result = runner.execute_live_step(_spec(WorldOperation.OBSCURE))

    assert calls == ["zone"]
    assert result.status is WorldTaskStatus.COMPLETED
    assert result.completed_units == 1
    assert result.cursor is None


def test_live_step_rejects_more_than_one_safe_unit() -> None:
    with pytest.raises(ValueError, match="at most one safe unit"):
        LiveOpsiStep(WorldOperation.EXPLORE, WorldTaskStatus.IN_PROGRESS, completed_units=2)


def test_live_step_requires_one_confirmed_unit_for_in_progress() -> None:
    with pytest.raises(ValueError, match="exactly one safe unit"):
        LiveOpsiStep(WorldOperation.EXPLORE, WorldTaskStatus.IN_PROGRESS)


def test_live_step_requires_an_aware_absolute_retry_time() -> None:
    with pytest.raises(ValueError, match="retry_at must be timezone-aware"):
        LiveOpsiStep(
            WorldOperation.EXPLORE,
            WorldTaskStatus.EMPTY,
            retry_at=datetime(2026, 7, 14),
        )


@pytest.mark.parametrize("retry_after", [timedelta(), timedelta(seconds=-1)])
def test_live_step_requires_a_positive_relative_retry_time(retry_after: timedelta) -> None:
    with pytest.raises(ValueError, match="retry_after must be positive"):
        LiveOpsiStep(
            WorldOperation.EXPLORE,
            WorldTaskStatus.EMPTY,
            retry_after=retry_after,
        )


def test_live_step_accepts_only_one_retry_representation() -> None:
    with pytest.raises(ValueError, match="retry_at and retry_after are mutually exclusive"):
        LiveOpsiStep(
            WorldOperation.EXPLORE,
            WorldTaskStatus.EMPTY,
            retry_at=_NOW,
            retry_after=timedelta(minutes=1),
        )


def test_definition_coverage_matches_live_settings_fixture() -> None:
    assert {definition.operation for definition in WORLD_TASK_DEFINITIONS.values()} == set(WorldOperation)
    assert {_spec(operation).operation for operation in WorldOperation} == set(WorldOperation)
