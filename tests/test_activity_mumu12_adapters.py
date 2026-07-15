from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from config_factory import in_memory_config

import module.adapters.activity_mumu12 as adapters
from module.application import AbortRequested, AbortToken, DailySchedule, DelayRange
from module.coalition.profile import (
    CoalitionClientSession,
    CoalitionPageMode,
    UnknownCoalitionProfileError,
)
from module.config.config import AzurLaneConfig
from module.content.activity_catalog import ActivityCatalog, CoalitionActivity, RaidActivity
from module.content.activity_profile import (
    CoalitionDefinition,
    CoalitionFleetRule,
    CoalitionProfileId,
    CoalitionStageDefinition,
    CoalitionStageId,
    RaidDefinition,
    RaidProfileId,
)
from module.content.errors import ContentValidationError
from module.content.manifest import load_event_manifests
from module.content.models import ContentId
from module.device.device import Device
from module.eventstory.profile import (
    ALCHEMIST_EVENT_STORY_PROFILE,
    RPG_STATUS_EVENT_STORY_PROFILE,
    SP_EVENT_STORY_PROFILE,
    STANDARD_EVENT_STORY_PROFILE,
    EventStoryClientProfile,
)
from module.gameplay.activity import (
    ActivityCommand,
    ActivityDisposition,
    ActivityReport,
    ActivitySpec,
    AssistSessionCommand,
    AssistSessionSpec,
    AssistSessionState,
    CoalitionFleetMode,
    CoalitionOptions,
    DaemonOptions,
    EncounterCommand,
    EncounterPolicy,
    EncounterSpec,
    EncounterStopReason,
    HospitalOptions,
    MaritimeEscortOptions,
    OpsiDaemonOptions,
    RaidDailyOptions,
    RaidMode,
    RaidOptions,
)
from module.maritime_escort.result import MaritimeEscortExecutionResult, MaritimeEscortExecutionStatus
from module.raid.profile import (
    RaidAttemptSource,
    RaidRunPlan,
    ResolvedRaidProfile,
    UnknownRaidProfileError,
)
from module.raid.result import RaidAttemptStatus, RaidExecutionResult

if TYPE_CHECKING:
    from module.config.config_generated import ConfigOverrides
    from module.interaction import CancellationSignal


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
        cancellation: CancellationSignal,
    ) -> Device:
        cancellation.raise_if_requested()
        _config.apply_runtime_overlay(**overlay)
        return device

    monkeypatch.setattr(adapters, "_activate", activate)
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


class _AppDevice:
    @staticmethod
    def app_is_running() -> bool:
        return True


class _EventStoryRunner:
    def __init__(self) -> None:
        self.device = _AppDevice()
        self.calls: list[str] = []
        self.states = ["story", "finish"]

    def ui_goto_event_story(self) -> str:
        self.calls.append("goto")
        return self.states.pop(0)

    def event_story(self) -> str:
        self.calls.append("story")
        return "finish"


@pytest.mark.parametrize(
    ("content_id", "expected_profile"),
    [
        ("event_20260625_cn", STANDARD_EVENT_STORY_PROFILE),
        ("event_20250724_cn", ALCHEMIST_EVENT_STORY_PROFILE),
        ("event_20250814_cn", RPG_STATUS_EVENT_STORY_PROFILE),
        ("event_20251023_cn", SP_EVENT_STORY_PROFILE),
    ],
)
def test_event_story_resolves_client_profile_and_executes_bounded_units(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
    content_id: str,
    expected_profile: EventStoryClientProfile,
) -> None:
    config, device = runtime
    runner = _EventStoryRunner()
    constructed_profiles: list[EventStoryClientProfile] = []

    def build_runner(
        *_args: object,
        profile: EventStoryClientProfile,
        **_kwargs: object,
    ) -> _EventStoryRunner:
        constructed_profiles.append(profile)
        return runner

    monkeypatch.setattr(adapters, "EventStory", build_runner)

    report = adapters.Mumu12EventStoryWorkflow(config, device, _Clock()).execute(
        ActivitySpec.event_story(
            activity=_ACTIVITY_CATALOG.resolve_event_story(content_id),
            skip_battle=True,
        ),
        AbortToken(),
    )

    assert report == ActivityReport(ActivityCommand.EVENT_STORY, ActivityDisposition.COMPLETED, _NOW, 0)
    assert runner.calls == ["goto", "story", "goto"]
    assert constructed_profiles == [expected_profile]
    assert config.Campaign_Event == content_id


def test_event_story_activation_applies_typed_overlay_after_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_id = "event_20260625_cn"
    config = in_memory_config("event-story-activation", {})
    device = object.__new__(Device)
    runner = _EventStoryRunner()
    activated: list[tuple[str, str, bool, bool]] = []

    def build_runner(
        activated_config: AzurLaneConfig,
        *,
        profile: EventStoryClientProfile,
        device: Device,
    ) -> _EventStoryRunner:
        del profile, device
        activated.append(
            (
                activated_config.task.command,
                activated_config.Campaign_Event,
                activated_config.EventStory_SkipBattle,
                activated_config.STORY_ALLOW_SKIP,
            )
        )
        return runner

    monkeypatch.setattr(adapters, "EventStory", build_runner)

    adapters.Mumu12EventStoryWorkflow(config, device, _Clock()).execute(
        ActivitySpec.event_story(
            activity=_ACTIVITY_CATALOG.resolve_event_story(content_id),
            skip_battle=True,
        ),
        AbortToken(),
    )

    assert activated == [("EventStory", content_id, True, True)]


def test_unavailable_event_story_returns_before_constructing_a_client(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    construction_calls = 0

    def build_runner(*_args: object, **_kwargs: object) -> _EventStoryRunner:
        nonlocal construction_calls
        construction_calls += 1
        return _EventStoryRunner()

    monkeypatch.setattr(adapters, "EventStory", build_runner)

    report = adapters.Mumu12EventStoryWorkflow(config, device, _Clock()).execute(
        ActivitySpec.event_story(
            activity=_ACTIVITY_CATALOG.resolve_event_story("event_20260226_cn"),
            skip_battle=True,
        ),
        AbortToken(),
    )

    assert report == ActivityReport(ActivityCommand.EVENT_STORY, ActivityDisposition.UNAVAILABLE, _NOW, 0)
    assert construction_calls == 0


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


def test_raid_profile_resolution_precedes_runtime_activation(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    activity = RaidActivity(
        ContentId("raid_unknown_profile"),
        RaidDefinition(
            RaidProfileId("unknown"),
            modes=(RaidMode.HARD,),
            daily_modes=(),
            ticket_modes=(),
        ),
    )
    spec = EncounterSpec(
        EncounterCommand.RAID,
        RaidOptions(activity, RaidMode.HARD, use_ticket=False, policy=_POLICY),
    )
    activation_calls = 0

    def activate(
        _config: AzurLaneConfig,
        _device: Device,
        _task_name: str,
        _cancellation: CancellationSignal,
    ) -> Device:
        nonlocal activation_calls
        activation_calls += 1
        return device

    monkeypatch.setattr(adapters, "_activate", activate)

    with pytest.raises(UnknownRaidProfileError, match="unknown raid client profile"):
        adapters.Mumu12RaidWorkflow(config, device, _Clock()).execute(spec, AbortToken())

    assert activation_calls == 0


def test_raid_plan_validation_precedes_runtime_activation(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    spec = EncounterSpec(
        EncounterCommand.RAID,
        RaidOptions(
            _ACTIVITY_CATALOG.resolve_raid("raid_20260212"),
            RaidMode.HARD,
            use_ticket=True,
            policy=_POLICY,
        ),
    )
    activation_calls = 0

    def activate(
        _config: AzurLaneConfig,
        _device: Device,
        _task_name: str,
        _cancellation: CancellationSignal,
    ) -> Device:
        nonlocal activation_calls
        activation_calls += 1
        return device

    monkeypatch.setattr(adapters, "_activate", activate)

    with pytest.raises(ContentValidationError, match="tickets are not supported"):
        adapters.Mumu12RaidWorkflow(config, device, _Clock()).execute(spec, AbortToken())

    assert activation_calls == 0


def test_rpg_unmetered_ex_does_not_report_attempts_exhausted(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _RaidRunner(
        {
            RaidMode.EX: RaidAttemptStatus(
                RaidMode.EX,
                RaidAttemptSource.UNMETERED,
                remaining=None,
            )
        }
    )
    _install_raid_runner(monkeypatch, runner)
    _allow_event(monkeypatch, adapters.Mumu12RaidWorkflow)
    spec = EncounterSpec(
        EncounterCommand.RAID,
        RaidOptions(
            _ACTIVITY_CATALOG.resolve_raid("raid_20240328"),
            RaidMode.EX,
            use_ticket=False,
            policy=_POLICY,
        ),
    )

    report = adapters.Mumu12RaidWorkflow(config, device, _Clock()).execute(spec, AbortToken())

    assert report.stop_reason is EncounterStopReason.IN_PROGRESS
    status_call = next(call for call in runner.calls if isinstance(call, tuple) and call[0] == "status")
    plan = status_call[1]
    assert isinstance(plan, RaidRunPlan)
    assert plan.mode_profile.attempt_source is RaidAttemptSource.UNMETERED
    assert [call[0] for call in runner.calls if isinstance(call, tuple)].count("execute") == 1


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


def test_raid_daily_scans_order_but_executes_only_one_battle(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _RaidRunner(
        {
            RaidMode.HARD: RaidAttemptStatus(RaidMode.HARD, RaidAttemptSource.METERED, remaining=0),
            RaidMode.EX: RaidAttemptStatus(RaidMode.EX, RaidAttemptSource.METERED, remaining=1),
        }
    )
    _install_raid_runner(monkeypatch, runner)
    _allow_event(monkeypatch, adapters.Mumu12RaidDailyWorkflow)
    reward_calls: list[tuple[bool, bool]] = []

    class _Reward:
        @staticmethod
        def reward_mission(*, daily: bool, weekly: bool) -> None:
            reward_calls.append((daily, weekly))

    monkeypatch.setattr(adapters, "Reward", lambda *_args, **_kwargs: _Reward())
    spec = EncounterSpec(
        EncounterCommand.RAID_DAILY,
        RaidDailyOptions(
            activity=_ACTIVITY_CATALOG.resolve_raid("raid_20260212"),
            stages=(RaidMode.HARD, RaidMode.EX),
            use_ticket=True,
            collect_daily_mission=True,
            policy=_POLICY,
        ),
        schedule=_SCHEDULE,
    )

    report = adapters.Mumu12RaidDailyWorkflow(config, device, _Clock()).execute(spec, AbortToken())

    assert report.stop_reason is EncounterStopReason.IN_PROGRESS
    assert report.runs_completed == 1
    status_plans = [
        call[1]
        for call in runner.calls
        if isinstance(call, tuple) and call[0] == "status" and isinstance(call[1], RaidRunPlan)
    ]
    assert [plan.mode for plan in status_plans] == [RaidMode.HARD, RaidMode.EX]
    assert [plan.use_ticket for plan in status_plans] == [False, True]
    execute_calls = [call for call in runner.calls if isinstance(call, tuple) and call[0] == "execute"]
    assert len(execute_calls) == 1
    assert execute_calls[0][1] is status_plans[1]
    assert reward_calls == [(True, False)]


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


def test_maritime_escort_rejects_the_removed_boolean_contract(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _EscortRunner()
    monkeypatch.setattr(runner, "execute_once", lambda: True)
    monkeypatch.setattr(adapters, "MaritimeEscort", lambda *_args, **_kwargs: runner)
    monkeypatch.setattr(adapters, "OCR_REMAIN", _RemainOcr())
    spec = EncounterSpec(
        EncounterCommand.MARITIME_ESCORT,
        MaritimeEscortOptions(_POLICY),
        schedule=_SCHEDULE,
    )

    with pytest.raises(TypeError, match=r"must return MaritimeEscortExecutionResult"):
        adapters.Mumu12MaritimeEscortWorkflow(config, device, _Clock()).execute(spec, AbortToken())


class _HospitalRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.emotion = _Emotion(self.calls)

    def ui_goto(self, _page: object) -> None:
        self.calls.append("goto")

    def daily_reward_receive(self) -> bool:
        self.calls.append("daily")
        return False

    def clue_enter(self) -> None:
        self.calls.append("clue")

    def select_aside(self) -> bool:
        self.calls.append("select")
        return True

    def execute_selected_investigation_once(self) -> bool:
        self.calls.append(("execute",))
        return True


class _HospitalTab:
    @staticmethod
    def set(tab: str, *, main: _HospitalRunner) -> None:
        main.calls.append(("tab", tab))


def test_hospital_executes_one_selected_investigation(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _HospitalRunner()
    monkeypatch.setattr(adapters, "Hospital", lambda *_args, **_kwargs: runner)
    monkeypatch.setattr(adapters, "HOSPITAL_TAB", _HospitalTab())
    _allow_event(monkeypatch, adapters.Mumu12HospitalWorkflow)
    spec = EncounterSpec(
        EncounterCommand.HOSPITAL,
        HospitalOptions(use_recommended_fleet=True, policy=_POLICY),
        schedule=_SCHEDULE,
    )

    report = adapters.Mumu12HospitalWorkflow(config, device, _Clock()).execute(spec, AbortToken())

    assert report.stop_reason is EncounterStopReason.IN_PROGRESS
    assert report.runs_completed == 1
    assert runner.calls.count("select") == 1
    assert ("execute",) in runner.calls


class _CoalitionDevice:
    def __init__(self, calls: list[object]) -> None:
        self._calls = calls

    def stuck_record_clear(self) -> None:
        self._calls.append("stuck_clear")

    def click_record_clear(self) -> None:
        self._calls.append("click_clear")


class _CoalitionRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.device = _CoalitionDevice(self.calls)
        self.emotion = _Emotion(self.calls)

    def ui_goto_coalition(self) -> None:
        self.calls.append("goto")

    def coalition_ensure_mode(self, mode: CoalitionPageMode) -> None:
        self.calls.append(("mode", mode))

    def coalition_execute_once(self) -> None:
        self.calls.append(("execute",))


@pytest.mark.parametrize(
    ("command", "stage", "expected_stop"),
    [
        (EncounterCommand.COALITION, CoalitionStageId("hard"), EncounterStopReason.IN_PROGRESS),
        (EncounterCommand.COALITION_SP, CoalitionStageId("sp"), EncounterStopReason.COMPLETED),
    ],
)
def test_coalition_variants_execute_one_atomic_coalition_run(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
    command: EncounterCommand,
    stage: CoalitionStageId,
    expected_stop: EncounterStopReason,
) -> None:
    config, device = runtime
    runner = _CoalitionRunner()
    clients: list[CoalitionClientSession] = []

    def build_coalition(*_args: object, client: CoalitionClientSession, **_kwargs: object) -> _CoalitionRunner:
        clients.append(client)
        return runner

    monkeypatch.setattr(adapters, "Coalition", build_coalition)
    _allow_event(monkeypatch, adapters.Mumu12CoalitionWorkflow)
    spec = EncounterSpec(
        command,
        CoalitionOptions(
            _ACTIVITY_CATALOG.resolve_coalition("coalition_20260122"),
            stage,
            CoalitionFleetMode.MULTI if command is EncounterCommand.COALITION_SP else CoalitionFleetMode.SINGLE,
            _POLICY,
        ),
        schedule=_SCHEDULE if command is EncounterCommand.COALITION_SP else None,
        run_limit=1 if command is EncounterCommand.COALITION_SP else None,
    )

    report = adapters.Mumu12CoalitionWorkflow(config, device, command, _Clock()).execute(spec, AbortToken())

    assert report.stop_reason is expected_stop
    assert report.runs_completed == 1
    assert len(clients) == 1
    assert clients[0].stage.stage_id == stage
    assert ("mode", CoalitionPageMode.BATTLE) in runner.calls
    assert ("emotion", clients[0].stage.battle_count) in runner.calls
    assert runner.calls.count(("execute",)) == 1


def test_coalition_profile_resolution_precedes_runtime_activation(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    activity = CoalitionActivity(
        ContentId("coalition_unknown_profile"),
        CoalitionDefinition(
            CoalitionProfileId("unknown"),
            (
                CoalitionStageDefinition(
                    CoalitionStageId("hard"),
                    battle_count=3,
                    fleet_rule=CoalitionFleetRule.SELECTABLE,
                ),
            ),
        ),
    )
    spec = EncounterSpec(
        EncounterCommand.COALITION,
        CoalitionOptions(
            activity,
            CoalitionStageId("hard"),
            CoalitionFleetMode.SINGLE,
            _POLICY,
        ),
    )
    constructed = False

    def build_coalition(*_args: object, **_kwargs: object) -> _CoalitionRunner:
        nonlocal constructed
        constructed = True
        return _CoalitionRunner()

    monkeypatch.setattr(adapters, "Coalition", build_coalition)

    with pytest.raises(UnknownCoalitionProfileError, match="unknown coalition client profile"):
        adapters.Mumu12CoalitionWorkflow(config, device, EncounterCommand.COALITION, _Clock()).execute(
            spec,
            AbortToken(),
        )

    assert not constructed


@pytest.mark.parametrize(
    ("content_id", "expected_calls"),
    [
        (
            "coalition_20260122",
            [
                "oil",
                "stuck_clear",
                "click_clear",
                "goto",
                ("mode", CoalitionPageMode.BATTLE),
                ("emotion", 3),
                ("execute",),
            ],
        ),
        (
            "coalition_20240627",
            [
                "stuck_clear",
                "click_clear",
                "goto",
                ("mode", CoalitionPageMode.BATTLE),
                "oil",
                ("emotion", 3),
                ("execute",),
            ],
        ),
    ],
)
def test_coalition_profile_places_oil_check_on_the_declared_page(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
    content_id: str,
    expected_calls: list[object],
) -> None:
    config, device = runtime
    runner = _CoalitionRunner()
    monkeypatch.setattr(adapters, "Coalition", lambda *_args, **_kwargs: runner)
    monkeypatch.setattr(adapters.Mumu12CoalitionWorkflow, "_event_available", staticmethod(lambda *_args: True))

    def oil_limited(selected: _CoalitionRunner, *_args: object) -> bool:
        selected.calls.append("oil")
        return False

    monkeypatch.setattr(adapters.Mumu12CoalitionWorkflow, "_oil_limited", staticmethod(oil_limited))
    spec = EncounterSpec(
        EncounterCommand.COALITION,
        CoalitionOptions(
            _ACTIVITY_CATALOG.resolve_coalition(content_id),
            CoalitionStageId("hard"),
            CoalitionFleetMode.SINGLE,
            _POLICY,
        ),
    )

    report = adapters.Mumu12CoalitionWorkflow(
        config,
        device,
        EncounterCommand.COALITION,
        _Clock(),
    ).execute(spec, AbortToken())

    assert report.stop_reason is EncounterStopReason.IN_PROGRESS
    assert runner.calls == expected_calls


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


def test_activity_builder_covers_all_ten_workflows_and_cancel_before_io(
    runtime: tuple[AzurLaneConfig, Device],
) -> None:
    config, device = runtime
    workflows = adapters.build_mumu12_activity_workflows(config, device, clock=_Clock())

    assert isinstance(workflows.minigame, adapters.Mumu12MinigameWorkflow)
    assert isinstance(workflows.event_story, adapters.Mumu12EventStoryWorkflow)
    assert isinstance(workflows.raid_daily, adapters.Mumu12RaidDailyWorkflow)
    assert isinstance(workflows.maritime_escort, adapters.Mumu12MaritimeEscortWorkflow)
    assert isinstance(workflows.raid, adapters.Mumu12RaidWorkflow)
    assert isinstance(workflows.hospital, adapters.Mumu12HospitalWorkflow)
    assert isinstance(workflows.coalition, adapters.Mumu12CoalitionWorkflow)
    assert isinstance(workflows.coalition_sp, adapters.Mumu12CoalitionWorkflow)
    assert isinstance(workflows.daemon, adapters.Mumu12DaemonWorkflow)
    assert isinstance(workflows.opsi_daemon, adapters.Mumu12OpsiDaemonWorkflow)

    cancelled = AbortToken()
    cancelled.request("stop before UI")
    with pytest.raises(AbortRequested, match="stop before UI"):
        workflows.minigame.execute(
            ActivitySpec.minigame(schedule=_SCHEDULE),
            cancelled,
        )
