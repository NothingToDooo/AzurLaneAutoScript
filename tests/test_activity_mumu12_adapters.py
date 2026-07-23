from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import module.adapters.activity_mumu12 as adapters
from module.application import AbortRequested, AbortToken, DailySchedule, DelayRange
from module.config.config import AzurLaneConfig
from module.content.activity_catalog import ActivityCatalog
from module.content.manifest import load_event_manifests
from module.device.device import Device
from module.gameplay.activity import (
    ActivityCommand,
    ActivityDisposition,
    ActivityReport,
    ActivitySpec,
    AssistSessionCommand,
    AssistSessionSpec,
    AssistSessionState,
    DaemonOptions,
    EncounterCommand,
    EncounterPolicy,
    EncounterSpec,
    EncounterStopReason,
    MaritimeEscortOptions,
    OpsiDaemonOptions,
    RaidMode,
    RaidOptions,
)
from module.maritime_escort.result import MaritimeEscortExecutionResult, MaritimeEscortExecutionStatus
from module.raid.profile import (
    RaidAttemptSource,
    RaidRunPlan,
    ResolvedRaidProfile,
)
from module.raid.result import RaidAttemptStatus, RaidExecutionResult

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.config.config_generated import ConfigOverrides


_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)
_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(8),))
_POLICY = EncounterPolicy(
    failure_retry_delay=DelayRange(300, 300),
    resource_retry_delay=timedelta(hours=2),
    oil_limit=1_000,
)
_ACTIVITY_CATALOG = ActivityCatalog(load_event_manifests(Path("content/events")))


class _Clock:
    @staticmethod
    def now() -> datetime:
        return _NOW


class _Emotion:
    def __init__(self, calls: list[object]) -> None:
        self._calls = calls

    def recovery_at(self, battles: int) -> None:
        self._calls.append(("emotion", battles))


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[AzurLaneConfig, Device]:
    config = object.__new__(AzurLaneConfig)
    device = object.__new__(Device)

    def activate(
        _config: AzurLaneConfig,
        _device: Device,
        _task_name: str,
        overlay: ConfigOverrides,
        cancellation: CancellationSource,
    ) -> Device:
        cancellation.raise_if_requested()
        _config.apply_runtime_overlay(**overlay)
        return device

    monkeypatch.setattr(adapters, "activate_mumu12_task", activate)
    return config, device


def _allow_event(monkeypatch: pytest.MonkeyPatch, workflow_type: type[object]) -> None:
    monkeypatch.setattr(workflow_type, "_event_available", staticmethod(lambda *_args: True))
    monkeypatch.setattr(workflow_type, "_oil_limited", staticmethod(lambda *_args: False))
    monkeypatch.setattr(workflow_type, "_points_limited", staticmethod(lambda *_args: False))
    monkeypatch.setattr(workflow_type, "_balancer_limited", staticmethod(lambda *_args: False))


class _MinigameRunner:
    def __init__(self, device: Device) -> None:
        self.device = device
        self.calls: list[object] = []

    def minigame_enter_game_room(self) -> None:
        self.calls.append("enter")

    def go_to_main_page(self) -> None:
        self.calls.append("main")

    def get_coin_amount(self, *, skip_first_screenshot: bool = True) -> int:
        self.calls.append(("coins", skip_first_screenshot))
        return 5

    def collect_coin(self) -> bool:
        self.calls.append("collect")
        return False


class _MinigamePlayer:
    def __init__(self) -> None:
        self.calls = 0

    def minigame_run(self) -> bool:
        self.calls += 1
        return True


def test_minigame_executes_exactly_one_typed_operation(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _MinigameRunner(device)
    player = _MinigamePlayer()
    monkeypatch.setattr(adapters, "Minigame", lambda *_args, **_kwargs: runner)
    monkeypatch.setattr(adapters, "NewYearChallenge", lambda *_args, **_kwargs: player)

    report = adapters.Mumu12MinigameWorkflow(config, device, _Clock()).execute(
        ActivitySpec.minigame(schedule=_SCHEDULE, operation_limit=3),
        AbortToken(),
    )

    assert report == ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.IN_PROGRESS, _NOW, 1)
    assert player.calls == 1
    assert runner.calls == ["enter", "main", ("coins", True), "collect"]


class _RaidRunner:
    def __init__(self, statuses: dict[RaidMode, RaidAttemptStatus] | None = None) -> None:
        self.calls: list[object] = []
        self.emotion = _Emotion(self.calls)
        self.device: Device | None = None
        self._statuses = {} if statuses is None else statuses

    def ensure_landing(self) -> None:
        self.calls.append(("landing",))

    def ui_goto_main(self) -> None:
        self.calls.append(("main",))

    def get_attempt_status(self, plan: RaidRunPlan) -> RaidAttemptStatus:
        self.calls.append(("status", plan))
        return self._statuses.get(
            plan.mode,
            RaidAttemptStatus(plan.mode, RaidAttemptSource.METERED, remaining=1),
        )

    def execute_once(self, plan: RaidRunPlan) -> RaidExecutionResult:
        self.calls.append(("execute", plan))
        return RaidExecutionResult(plan.mode, runs_completed=1)


def _install_raid_runner(
    monkeypatch: pytest.MonkeyPatch,
    runner: _RaidRunner,
) -> list[ResolvedRaidProfile]:
    constructed_profiles: list[ResolvedRaidProfile] = []

    def build_runner(
        _config: AzurLaneConfig,
        *,
        profile: ResolvedRaidProfile,
        device: Device,
        **_kwargs: object,
    ) -> _RaidRunner:
        constructed_profiles.append(profile)
        runner.device = device
        return runner

    monkeypatch.setattr(adapters, "RaidRun", build_runner)
    return constructed_profiles


@pytest.mark.parametrize(
    ("run_limit", "expected_stop"),
    [(3, EncounterStopReason.IN_PROGRESS), (1, EncounterStopReason.RUN_LIMIT)],
)
def test_raid_one_safe_unit_preserves_cumulative_run_limit(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
    run_limit: int,
    expected_stop: EncounterStopReason,
) -> None:
    config, device = runtime
    runner = _RaidRunner()
    profiles = _install_raid_runner(monkeypatch, runner)
    _allow_event(monkeypatch, adapters.Mumu12RaidWorkflow)
    spec = EncounterSpec(
        EncounterCommand.RAID,
        RaidOptions(
            activity=_ACTIVITY_CATALOG.resolve_raid("raid_20260212"),
            mode=RaidMode.HARD,
            use_ticket=False,
            policy=_POLICY,
        ),
        run_limit=run_limit,
    )

    report = adapters.Mumu12RaidWorkflow(config, device, _Clock()).execute(spec, AbortToken())

    assert report.stop_reason is expected_stop
    assert report.runs_completed == 1
    assert [call[0] for call in runner.calls if isinstance(call, tuple)].count("execute") == 1
    execute = next(call for call in runner.calls if isinstance(call, tuple) and call[0] == "execute")
    plan = execute[1]
    assert isinstance(plan, RaidRunPlan)
    assert plan.mode is RaidMode.HARD
    assert plan.use_ticket is False
    assert len(profiles) == 1
    assert profiles[0] is plan.profile
    assert config.Campaign_Event == "raid_20260212"
    assert config.Raid_Mode == "hard"
    assert config.StopCondition_OilLimit == 1_000


def test_regular_exhausted_ex_returns_before_atomic_execution(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _RaidRunner({RaidMode.EX: RaidAttemptStatus(RaidMode.EX, RaidAttemptSource.METERED, remaining=0)})
    _install_raid_runner(monkeypatch, runner)
    _allow_event(monkeypatch, adapters.Mumu12RaidWorkflow)
    spec = EncounterSpec(
        EncounterCommand.RAID,
        RaidOptions(
            _ACTIVITY_CATALOG.resolve_raid("raid_20260212"),
            RaidMode.EX,
            use_ticket=True,
            policy=_POLICY,
        ),
    )

    report = adapters.Mumu12RaidWorkflow(config, device, _Clock()).execute(spec, AbortToken())

    assert report.stop_reason is EncounterStopReason.ATTEMPTS_EXHAUSTED
    assert report.runs_completed == 0
    assert not [call for call in runner.calls if isinstance(call, tuple) and call[0] == "execute"]


class _EscortRunner:
    def __init__(
        self,
        status: MaritimeEscortExecutionStatus = MaritimeEscortExecutionStatus.WITHDRAWAL_COMPLETED,
    ) -> None:
        self.device = type("DeviceImage", (), {"image": object()})()
        self.calls: list[str] = []
        self.status = status

    def ui_goto_main(self) -> None:
        self.calls.append("main")

    def ui_click(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("click")

    def execute_once(self) -> MaritimeEscortExecutionResult:
        self.calls.append("escort")
        return MaritimeEscortExecutionResult(self.status)


class _RemainOcr:
    @staticmethod
    def ocr(_image: object) -> tuple[int, int, int]:
        return 1, 1, 0


@pytest.mark.parametrize(
    ("status", "runs_completed"),
    [
        (MaritimeEscortExecutionStatus.WITHDRAWAL_COMPLETED, 1),
        (MaritimeEscortExecutionStatus.ATTEMPTS_EXHAUSTED, 0),
    ],
)
def test_maritime_escort_projects_one_atomic_result(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
    status: MaritimeEscortExecutionStatus,
    runs_completed: int,
) -> None:
    config, device = runtime
    runner = _EscortRunner(status)
    monkeypatch.setattr(adapters, "MaritimeEscort", lambda *_args, **_kwargs: runner)
    monkeypatch.setattr(adapters, "OCR_REMAIN", _RemainOcr())
    spec = EncounterSpec(
        EncounterCommand.MARITIME_ESCORT,
        MaritimeEscortOptions(_POLICY),
        schedule=_SCHEDULE,
    )

    report = adapters.Mumu12MaritimeEscortWorkflow(config, device, _Clock()).execute(spec, AbortToken())

    assert report.stop_reason is EncounterStopReason.COMPLETED
    assert report.runs_completed == runs_completed
    assert runner.calls == ["main", "click", "escort"]


class _DaemonRunner:
    def __init__(self, *, completed: bool = False) -> None:
        self.completed = completed
        self.calls: list[str] = []

    def advance_once(self) -> bool:
        self.calls.append("advance")
        return self.completed

    def prepare_os_daemon_config(self) -> None:
        self.calls.append("prepare")


def test_assist_workflows_advance_exactly_one_safe_point(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    daemon = _DaemonRunner()
    opsi = _DaemonRunner()
    monkeypatch.setattr(adapters, "StandardDaemon", lambda *_args, **_kwargs: daemon)
    monkeypatch.setattr(adapters, "OpsiDaemon", lambda *_args, **_kwargs: opsi)

    daemon_report = adapters.Mumu12DaemonWorkflow(config, device, _Clock()).advance_to_safe_point(
        AssistSessionSpec(AssistSessionCommand.DAEMON, DaemonOptions(enter_map=True)),
        AbortToken(),
    )
    opsi_report = adapters.Mumu12OpsiDaemonWorkflow(config, device, _Clock()).advance_to_safe_point(
        AssistSessionSpec(
            AssistSessionCommand.OPSI_DAEMON,
            OpsiDaemonOptions(repair_ship=True, select_enemy=False),
        ),
        AbortToken(),
    )

    assert daemon_report.state is AssistSessionState.CONTINUE
    assert opsi_report.state is AssistSessionState.CONTINUE
    assert daemon.calls == ["advance"]
    assert opsi.calls == ["prepare", "advance"]


def test_activity_builder_honors_cancel_before_io(
    runtime: tuple[AzurLaneConfig, Device],
) -> None:
    config, device = runtime
    workflows = adapters.build_mumu12_activity_workflows(config, device, clock=_Clock())

    cancelled = AbortToken()
    cancelled.request("stop before UI")
    with pytest.raises(AbortRequested, match="stop before UI"):
        workflows.minigame.execute(
            ActivitySpec.minigame(schedule=_SCHEDULE),
            cancelled,
        )
