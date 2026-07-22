from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast, override

import pytest
from config_factory import in_memory_config

import module.adapters.opsi_mumu12 as opsi_adapters
from module.adapters.opsi_live import LiveOperationSirenWorkflow, LiveOpsiStep, LiveScheduleDelay, OpsiLiveClock
from module.adapters.opsi_mumu12 import (
    CancellationAwareMumu12Device,
    Mumu12OperationSirenSession,
    apply_world_task_spec,
)
from module.application import AbortRequested, AbortToken, TaskId
from module.config.deep import deep_set
from module.device.device import Device
from module.gameplay.opsi import (
    ExploreSettings,
    FleetSettings,
    ObscureSettings,
    OpsiDailySettings,
    WorldGeneralSettings,
    WorldOperation,
    WorldSchedule,
    WorldScheduleDelay,
    WorldTaskSpec,
    WorldTaskStatus,
    world_task_spec,
)
from module.gameplay.opsi_progress import WorldProgress, WorldZoneCursor

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource
    from module.config.config import AzurLaneConfig
    from module.gameplay.opsi import WorldTaskSettings


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
        WorldOperation.EXPLORE: ExploreSettings(
            _GENERAL,
            _FLEET,
            special_radar=False,
            force_run=False,
        ),
        WorldOperation.DAILY: OpsiDailySettings(
            _GENERAL,
            _FLEET,
            do_missions=True,
            use_tuning_samples=True,
        ),
        WorldOperation.OBSCURE: ObscureSettings(_GENERAL, _FLEET, force_run=False),
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
    calls: list[tuple[WorldTaskSpec, WorldProgress | None, CancellationSource]]

    def __init__(self, step: LiveOpsiStep) -> None:
        self.step = step
        self.calls = []

    def execute_step(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSource,
    ) -> LiveOpsiStep:
        self.calls.append((spec, progress, cancellation))
        return self.step


def test_live_workflow_preserves_resumable_in_progress_report() -> None:
    step = LiveOpsiStep(
        WorldOperation.EXPLORE,
        WorldTaskStatus.IN_PROGRESS,
        completed_units=1,
        cursor=WorldZoneCursor(7),
    )

    workflow = LiveOperationSirenWorkflow(
        _Driver(step),
        _ScheduleSource(),
        _Clock(),
    )

    report = workflow.execute(_spec(WorldOperation.EXPLORE), None, AbortToken())

    assert report.status is WorldTaskStatus.IN_PROGRESS
    assert report.completed_units == 1
    assert report.cursor == WorldZoneCursor(7)


def test_live_workflow_binds_relative_schedule_intents_to_one_observed_at() -> None:
    delayed = (TaskId("opsi_obscure"), TaskId("opsi_stronghold"))
    step = LiveOpsiStep(
        WorldOperation.EXPLORE,
        WorldTaskStatus.EMPTY,
        schedule_delays=(LiveScheduleDelay(timedelta(minutes=27), delayed),),
        wake_task_ids=(TaskId("opsi_ash_beacon"),),
    )
    workflow = LiveOperationSirenWorkflow(_Driver(step), _ScheduleSource(), _Clock())

    report = workflow.execute(_spec(WorldOperation.EXPLORE), None, AbortToken())

    assert report.schedule_delays == (WorldScheduleDelay(_NOW + timedelta(minutes=27), delayed),)
    assert report.wake_task_ids == (TaskId("opsi_ash_beacon"),)


def test_live_workflow_checks_cancellation_before_entering_driver() -> None:
    abort = AbortToken()
    abort.request("manual stop")
    driver = _Driver(LiveOpsiStep(WorldOperation.EXPLORE, WorldTaskStatus.EMPTY))
    workflow = LiveOperationSirenWorkflow(driver, _ScheduleSource(), _Clock())

    with pytest.raises(AbortRequested, match="manual stop"):
        workflow.execute(_spec(WorldOperation.EXPLORE), None, abort)

    assert driver.calls == []


def test_mumu12_executor_binds_each_task_before_schedule_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = in_memory_config("opsi-task-binding", {}, task="OpsiDaily")
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
    )
    daily = workflow.execute(
        _spec(WorldOperation.DAILY),
        None,
        AbortToken(),
    )

    assert explore.schedule.next_server_update_at.hour == 1
    assert daily.schedule.next_server_update_at.hour == 13
    assert config.task.command == "OpsiDaily"


def test_mumu12_executor_maps_action_point_limit_to_typed_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = in_memory_config("opsi-action-point", {}, task="OpsiObscure")
    deep_set(config.data, "OpsiObscure.Scheduler.ServerUpdate", "04:00")
    config.bind(config.task)
    device = object.__new__(Device)

    class _Session:
        def __init__(self, bound_config: AzurLaneConfig, _device: Device) -> None:
            self.config = bound_config

        @staticmethod
        def prepare_live_step() -> None:
            pass

        @staticmethod
        def execute_live_step(_spec: WorldTaskSpec) -> LiveOpsiStep:
            raise opsi_adapters.ActionPointLimit

        @staticmethod
        def attach_live_intents(step: LiveOpsiStep) -> LiveOpsiStep:
            return step

    monkeypatch.setattr(opsi_adapters, "Mumu12OperationSirenSession", _Session)
    workflow = opsi_adapters.build_mumu12_operation_siren_workflow(config, device)

    report = workflow.execute(_spec(WorldOperation.OBSCURE), None, AbortToken())

    assert report.status is WorldTaskStatus.ACTION_POINT_LIMIT


def test_mumu12_session_reports_order_cooldowns_without_writing_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = in_memory_config("opsi-order-cooldown", {}, task="OpsiExplore")
    deep_set(config.data, "OpsiExplore.OpsiFleet.Submarine", value=True)
    deep_set(config.data, "OpsiObscure.OpsiFleet.Submarine", value=True)
    deep_set(config.data, "OpsiObscure.OpsiObscure.ForceRun", value=True)
    deep_set(config.data, "OpsiStronghold.OpsiExplore.SpecialRadar", value=True)
    deep_set(config.data, "OpsiMonthBoss.OpsiFleetFilter.Filter", "Fleet-1 > submarine")
    runner = object.__new__(Mumu12OperationSirenSession)
    runner.config = config
    runner._live_schedule_delays = []  # ruff:ignore[private-member-access] - 构造最小 live session，隔离 UI 初始化。
    runner._live_wake_task_ids = []  # ruff:ignore[private-member-access] - 构造最小 live session，隔离 UI 初始化。
    monkeypatch.setattr(
        opsi_adapters.OperationSiren,
        "os_order_execute",
        lambda _self, **_kwargs: (True, True),
    )

    result = runner.os_order_execute()

    assert result == (True, True)
    step = runner.attach_live_intents(LiveOpsiStep(WorldOperation.EXPLORE, WorldTaskStatus.EMPTY))
    assert step.schedule_delays == (
        LiveScheduleDelay(timedelta(minutes=27), (TaskId("opsi_explore"),)),
        LiveScheduleDelay(
            timedelta(minutes=60),
            (
                TaskId("opsi_explore"),
                TaskId("opsi_abyssal"),
                TaskId("opsi_stronghold"),
                TaskId("opsi_month_boss"),
            ),
        ),
    )
    assert config.modified == {}


def test_mumu12_session_reports_cl1_preserve_before_propagating_action_point_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(Mumu12OperationSirenSession)
    runner._live_schedule_delays = []  # ruff:ignore[private-member-access] - 构造最小 live session，隔离 UI 初始化。
    runner._live_wake_task_ids = []  # ruff:ignore[private-member-access] - 构造最小 live session，隔离 UI 初始化。

    def action_point_limit(_self: object) -> None:
        raise opsi_adapters.ActionPointLimit

    monkeypatch.setattr(opsi_adapters.OperationSiren, "cl1_ap_preserve", action_point_limit)

    with pytest.raises(opsi_adapters.ActionPointLimit):
        runner.cl1_ap_preserve()

    step = runner.attach_live_intents(LiveOpsiStep(WorldOperation.OBSCURE, WorldTaskStatus.EMPTY))
    assert step.schedule_delays == (
        LiveScheduleDelay(
            timedelta(hours=6),
            (
                TaskId("opsi_obscure"),
                TaskId("opsi_abyssal"),
                TaskId("opsi_stronghold"),
                TaskId("opsi_meowfficer_farming"),
            ),
        ),
    )


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


def test_explore_without_checkpoint_keeps_persisted_last_zone_out_of_overlay() -> None:
    config = _Config()

    apply_world_task_spec(cast("AzurLaneConfig", config), _spec(WorldOperation.EXPLORE), None)

    assert "OpsiExplore_LastZone" not in config.overrides
