from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    Blocked,
    Cancelled,
    DailySchedule,
    Deferred,
    DelayRange,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
    RescheduleSelf,
    Retryable,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
    UpsertTaskState,
    WakePolicy,
    WakeTask,
)
from module.content.activity_catalog import ActivityCatalog
from module.content.manifest import load_event_manifests
from module.gameplay.activity import (
    ActivityCommand,
    ActivityDisposition,
    ActivityReport,
    ActivitySpec,
    ActivityTask,
    AssistSessionCommand,
    AssistSessionReport,
    AssistSessionSpec,
    AssistSessionState,
    AssistSessionTask,
    DaemonOptions,
    EncounterBalancerPolicy,
    EncounterCommand,
    EncounterPolicy,
    EncounterProgress,
    EncounterReport,
    EncounterSpec,
    EncounterStopReason,
    EncounterTask,
    MinigameProgress,
    OpsiDaemonOptions,
    RaidMode,
    RaidOptions,
)
from module.task_registry import TASK_SPECS

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_OBSERVED_AT = datetime(2026, 7, 13, 8, tzinfo=UTC)
_RUN_STARTED_AT = datetime(2026, 7, 13, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 14, 0, tzinfo=UTC)
_SERVER_UPDATE_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(8),))
_RESUME_AT = _OBSERVED_AT + timedelta(hours=2)
_ENCOUNTER_POLICY = EncounterPolicy(
    failure_retry_delay=DelayRange(300, 300),
    resource_retry_delay=timedelta(hours=2),
)
_ACTIVITY_CATALOG = ActivityCatalog(load_event_manifests(Path("content/events")))


def _progress(
    operations_completed: int,
    *,
    cycle_ends_at: datetime = _SERVER_UPDATE_AT,
    settings_revision: int = 1,
    content_revision: str = "content-1",
) -> MinigameProgress:
    return MinigameProgress(
        operations_completed=operations_completed,
        cycle_ends_at=cycle_ends_at,
        settings_revision=settings_revision,
        content_revision=content_revision,
    )


def _progress_effect(operations_completed: int) -> UpsertTaskState:
    return UpsertTaskState(
        namespace="minigame",
        key="progress",
        schema_version=1,
        payload={
            "operations_completed": operations_completed,
            "cycle_ends_at": _SERVER_UPDATE_AT.isoformat(),
            "settings_revision": 1,
            "content_revision": "content-1",
        },
    )


def _encounter_progress_effect(command: EncounterCommand, runs_completed: int) -> UpsertTaskState:
    return UpsertTaskState(
        namespace=command.value,
        key="progress",
        schema_version=1,
        payload={
            "runs_completed": runs_completed,
            "cycle_ends_at": None,
            "settings_revision": 1,
            "content_revision": "content-1",
        },
    )


class _ActivityWorkflow:
    def __init__(
        self,
        report: object,
        *,
        on_execute: Callable[[], None] | None = None,
    ) -> None:
        self._report = report
        self._on_execute = on_execute
        self.specs: list[ActivitySpec] = []

    def execute(
        self,
        spec: ActivitySpec,
        cancellation: CancellationSource,
    ) -> ActivityReport:
        cancellation.raise_if_requested()
        self.specs.append(spec)
        if self._on_execute is not None:
            self._on_execute()
        return cast("ActivityReport", self._report)


class _EncounterWorkflow:
    def __init__(
        self,
        report: object,
        *,
        on_execute: Callable[[], None] | None = None,
    ) -> None:
        self._report = report
        self._on_execute = on_execute
        self.specs: list[EncounterSpec] = []

    def execute(self, spec: EncounterSpec, cancellation: CancellationSource) -> EncounterReport:
        cancellation.raise_if_requested()
        self.specs.append(spec)
        if self._on_execute is not None:
            self._on_execute()
        return cast("EncounterReport", self._report)


class _AssistWorkflow:
    def __init__(
        self,
        reports: list[object],
        *,
        on_advance: Callable[[int], None] | None = None,
    ) -> None:
        self._reports = reports
        self._on_advance = on_advance
        self.specs: list[AssistSessionSpec] = []

    def advance_to_safe_point(
        self,
        spec: AssistSessionSpec,
        cancellation: CancellationSource,
    ) -> AssistSessionReport:
        cancellation.raise_if_requested()
        self.specs.append(spec)
        call = len(self.specs)
        if self._on_advance is not None:
            self._on_advance(call)
        index = min(call - 1, len(self._reports) - 1)
        return cast("AssistSessionReport", self._reports[index])


def _context(
    command: str,
    *,
    mode: ExecutionMode | None = None,
    abort: AbortToken | None = None,
) -> TaskContext:
    if mode is None:
        mode = TASK_SPECS[command].execution_mode
    return TaskContext(
        task_id=TaskId(command),
        started_at=_RUN_STARTED_AT,
        mode=mode,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def _encounter_spec(
    *,
    run_limit: int | None = None,
    balancer_task_id: TaskId | None = None,
    progress: EncounterProgress | None = None,
) -> EncounterSpec:
    return EncounterSpec(
        command=EncounterCommand.RAID,
        options=RaidOptions(
            activity=_ACTIVITY_CATALOG.resolve_raid("raid_20260212"),
            mode=RaidMode.HARD,
            use_ticket=False,
            policy=_ENCOUNTER_POLICY,
        ),
        run_limit=run_limit,
        balancer=(None if balancer_task_id is None else EncounterBalancerPolicy(balancer_task_id, coin_limit=10_000)),
        progress=progress,
    )


def _encounter_report(
    stop_reason: EncounterStopReason,
    *,
    runs_completed: int = 0,
    resume_at: datetime | None = None,
) -> EncounterReport:
    return EncounterReport(
        command=EncounterCommand.RAID,
        stop_reason=stop_reason,
        observed_at=_OBSERVED_AT,
        runs_completed=runs_completed,
        resume_at=resume_at,
    )


def _request_abort(abort: AbortToken, reason: str) -> None:
    abort.request(reason)


def _request_abort_on_second_step(abort: AbortToken, call: int) -> None:
    if call == 2:
        abort.request("operator stop")


@pytest.mark.parametrize(
    ("disposition", "operations_completed", "expected_outcome"),
    [
        (ActivityDisposition.COMPLETED, 1, Succeeded()),
        (ActivityDisposition.UNAVAILABLE, 0, Blocked("activity is unavailable")),
    ],
)
def test_minigame_dispositions_advance_to_the_next_server_update(
    disposition: ActivityDisposition,
    operations_completed: int,
    expected_outcome: Succeeded | Blocked,
) -> None:
    spec = ActivitySpec.minigame(schedule=_SERVER_UPDATE_SCHEDULE)
    report = ActivityReport(
        ActivityCommand.MINIGAME,
        disposition,
        observed_at=_OBSERVED_AT,
        operations_completed=operations_completed,
    )
    workflow = _ActivityWorkflow(report)

    result = ActivityTask(workflow, spec).run(_context("minigame"))

    assert workflow.specs == [spec]
    assert result == TaskResult(
        outcome=expected_outcome,
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(DeleteTaskState("minigame", "progress"),),
    )


def test_minigame_in_progress_commits_one_safe_unit_and_requeues_immediately() -> None:
    spec = ActivitySpec.minigame(schedule=_SERVER_UPDATE_SCHEDULE)
    report = ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.IN_PROGRESS, _OBSERVED_AT, 1)
    workflow = _ActivityWorkflow(report)

    result = ActivityTask(workflow, spec).run(_context("minigame"))

    assert workflow.specs == [spec]
    assert result == TaskResult(
        outcome=Deferred("activity batch is still in progress"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_progress_effect(1),),
    )


def test_minigame_resumes_the_current_cycle_and_enforces_the_cumulative_limit() -> None:
    progress = _progress(3)
    spec = ActivitySpec.minigame(
        schedule=_SERVER_UPDATE_SCHEDULE,
        operation_limit=5,
        progress=progress,
    )
    report = ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.IN_PROGRESS, _OBSERVED_AT, 1)
    workflow = _ActivityWorkflow(report)

    result = ActivityTask(workflow, spec).run(_context("minigame"))

    assert workflow.specs == [spec]
    assert workflow.specs[0].remaining_operations == 2
    assert result == TaskResult(
        outcome=Deferred("activity batch is still in progress"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_progress_effect(4),),
    )


def test_stale_minigame_progress_is_deleted_before_external_work() -> None:
    workflow = _ActivityWorkflow(
        ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.IN_PROGRESS, _OBSERVED_AT, 1)
    )

    result = ActivityTask(
        workflow,
        ActivitySpec.minigame(schedule=_SERVER_UPDATE_SCHEDULE, progress=_progress(2, settings_revision=2)),
    ).run(_context("minigame"))

    assert workflow.specs == []
    assert result == TaskResult(
        outcome=Deferred("stale activity progress was discarded"),
        effects=(RescheduleSelf(_RUN_STARTED_AT),),
        state_effects=(DeleteTaskState("minigame", "progress"),),
    )


def test_minigame_checkpoint_at_the_operation_cap_settles_without_external_work() -> None:
    workflow = _ActivityWorkflow(
        ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.COMPLETED, _OBSERVED_AT, 0)
    )
    spec = ActivitySpec.minigame(
        schedule=_SERVER_UPDATE_SCHEDULE,
        operation_limit=3,
        progress=_progress(3),
    )

    result = ActivityTask(workflow, spec).run(_context("minigame"))

    assert workflow.specs == []
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(DeleteTaskState("minigame", "progress"),),
    )


@pytest.mark.parametrize(
    ("disposition", "expected_outcome"),
    [
        (ActivityDisposition.COMPLETED, Succeeded()),
        (ActivityDisposition.UNAVAILABLE, Blocked("activity is unavailable")),
    ],
)
def test_event_story_is_a_direct_activity_without_scheduler_effects(
    disposition: ActivityDisposition,
    expected_outcome: Succeeded | Blocked,
) -> None:
    spec = ActivitySpec.event_story(
        activity=_ACTIVITY_CATALOG.resolve_event_story("event_20260625_cn"),
        skip_battle=True,
    )
    workflow = _ActivityWorkflow(ActivityReport(ActivityCommand.EVENT_STORY, disposition, _OBSERVED_AT, 0))

    result = ActivityTask(workflow, spec).run(_context("event_story"))

    assert result == TaskResult(outcome=expected_outcome)


def test_activity_abort_before_entry_prevents_external_work() -> None:
    abort = AbortToken()
    abort.request("stop before UI")
    workflow = _ActivityWorkflow(
        ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.COMPLETED, _OBSERVED_AT, 0)
    )

    with pytest.raises(AbortRequested, match="stop before UI"):
        ActivityTask(workflow, ActivitySpec.minigame(schedule=_SERVER_UPDATE_SCHEDULE)).run(
            _context("minigame", abort=abort)
        )

    assert workflow.specs == []


def test_activity_abort_during_work_checkpoints_the_returned_safe_point() -> None:
    abort = AbortToken()
    workflow = _ActivityWorkflow(
        ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.IN_PROGRESS, _OBSERVED_AT, 1),
        on_execute=lambda: _request_abort(abort, "stop after the current operation"),
    )
    task = ActivityTask(
        workflow,
        ActivitySpec.minigame(schedule=_SERVER_UPDATE_SCHEDULE, operation_limit=2),
    )

    result = task.run(_context("minigame", abort=abort))

    assert result == TaskResult(
        outcome=Deferred("activity batch is still in progress"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_progress_effect(1),),
    )
    assert len(workflow.specs) == 1
    with pytest.raises(AbortRequested, match="stop after the current operation"):
        task.run(_context("minigame", abort=abort))
    assert len(workflow.specs) == 1


def test_continuous_encounter_run_limit_disables_the_finished_task() -> None:
    command = EncounterCommand.RAID
    spec = _encounter_spec(
        run_limit=3,
        progress=EncounterProgress(2, None, 1, "content-1"),
    )
    report = _encounter_report(EncounterStopReason.RUN_LIMIT, runs_completed=1)

    result = EncounterTask(_EncounterWorkflow(report), spec).run(_context(command.value))

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(DisableTask(TaskId(command.value)),),
        state_effects=(DeleteTaskState(command.value, "progress"),),
    )


def test_continuous_encounter_checkpoints_one_safe_unit_and_requeues_immediately() -> None:
    command = EncounterCommand.RAID
    spec = _encounter_spec(run_limit=3)
    report = _encounter_report(EncounterStopReason.IN_PROGRESS, runs_completed=1)

    result = EncounterTask(_EncounterWorkflow(report), spec).run(_context(command.value))

    assert result == TaskResult(
        outcome=Deferred("encounter batch is still in progress"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_encounter_progress_effect(command, 1),),
    )


def test_raid_without_remaining_attempts_is_explicitly_deferred_and_disabled() -> None:
    command = EncounterCommand.RAID
    report = _encounter_report(EncounterStopReason.ATTEMPTS_EXHAUSTED)

    result = EncounterTask(_EncounterWorkflow(report), _encounter_spec()).run(_context(command.value))

    assert result == TaskResult(
        outcome=Deferred("encounter attempts are exhausted"),
        effects=(DisableTask(TaskId("raid")),),
    )


def test_resumable_encounter_stop_emits_retry_at_the_reported_time() -> None:
    command = EncounterCommand.RAID
    report = _encounter_report(EncounterStopReason.RESOURCE_LIMIT, resume_at=_RESUME_AT)

    result = EncounterTask(_EncounterWorkflow(report), _encounter_spec()).run(_context(command.value))

    assert result == TaskResult(
        outcome=Retryable("encounter resource limit was reached"),
        effects=(RescheduleSelf(_RESUME_AT),),
    )


def test_balancer_stop_defers_self_and_wakes_the_typed_target() -> None:
    command = EncounterCommand.RAID
    target = TaskId("main")
    spec = _encounter_spec(balancer_task_id=target)
    report = _encounter_report(EncounterStopReason.BALANCER_SWITCH, resume_at=_RESUME_AT)

    result = EncounterTask(_EncounterWorkflow(report), spec).run(_context(command.value))

    assert result == TaskResult(
        outcome=Deferred("encounter yielded to the configured balancing task"),
        effects=(
            RescheduleSelf(_RESUME_AT),
            WakeTask(target, _OBSERVED_AT, WakePolicy.FORCE_ENABLE),
        ),
    )


def test_encounter_abort_after_workflow_checkpoints_the_completed_run() -> None:
    abort = AbortToken()
    command = EncounterCommand.RAID
    report = _encounter_report(EncounterStopReason.IN_PROGRESS, runs_completed=1)
    workflow = _EncounterWorkflow(report, on_execute=lambda: _request_abort(abort, "stop after battle"))
    task = EncounterTask(workflow, _encounter_spec(run_limit=2))

    result = task.run(_context(command.value, abort=abort))

    assert result == TaskResult(
        outcome=Deferred("encounter batch is still in progress"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_encounter_progress_effect(command, 1),),
    )
    assert len(workflow.specs) == 1
    with pytest.raises(AbortRequested, match="stop after battle"):
        task.run(_context(command.value, abort=abort))
    assert len(workflow.specs) == 1


def test_normal_daemon_can_finish_only_after_a_complete_safe_point() -> None:
    spec = AssistSessionSpec(AssistSessionCommand.DAEMON, DaemonOptions(enter_map=True))
    workflow = _AssistWorkflow(
        [
            AssistSessionReport(AssistSessionCommand.DAEMON, AssistSessionState.CONTINUE),
            AssistSessionReport(AssistSessionCommand.DAEMON, AssistSessionState.COMPLETED),
        ]
    )

    result = AssistSessionTask(workflow, spec).run(_context("daemon"))

    assert workflow.specs == [spec, spec]
    assert result == TaskResult(outcome=Succeeded())


def test_opsi_daemon_honors_abort_only_after_the_current_safe_point() -> None:
    abort = AbortToken()
    spec = AssistSessionSpec(
        AssistSessionCommand.OPSI_DAEMON,
        OpsiDaemonOptions(repair_ship=True, select_enemy=True),
    )
    report = AssistSessionReport(AssistSessionCommand.OPSI_DAEMON, AssistSessionState.CONTINUE)
    workflow = _AssistWorkflow(
        [report],
        on_advance=lambda call: _request_abort_on_second_step(abort, call),
    )

    result = AssistSessionTask(workflow, spec).run(_context("opsi_daemon", abort=abort))

    assert len(workflow.specs) == 2
    assert result == TaskResult(outcome=Cancelled("operator stop"))


def test_assist_abort_before_the_first_step_has_no_external_side_effect() -> None:
    abort = AbortToken()
    abort.request("operator stop")
    spec = AssistSessionSpec(AssistSessionCommand.DAEMON, DaemonOptions(enter_map=False))
    workflow = _AssistWorkflow([AssistSessionReport(AssistSessionCommand.DAEMON, AssistSessionState.CONTINUE)])

    result = AssistSessionTask(workflow, spec).run(_context("daemon", abort=abort))

    assert workflow.specs == []
    assert result == TaskResult(outcome=Cancelled("operator stop"))
