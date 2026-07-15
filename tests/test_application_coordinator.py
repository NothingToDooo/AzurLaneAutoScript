from datetime import UTC, datetime
from typing import cast, override

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    Cancelled,
    Deferred,
    DisableTask,
    ExecutionMode,
    Faulted,
    PreemptionRequest,
    RescheduleSelf,
    RescheduleTask,
    RunCoordinator,
    RunId,
    RunMetadata,
    RunRepository,
    RunStart,
    ScheduledTaskDidNotAdvanceError,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
    UpsertTaskState,
    WakePolicy,
    WakeTask,
)


def _metadata() -> RunMetadata:
    return RunMetadata(
        settings_revision=8,
        content_revision="content-20260713",
        client_ui_revision="cn-ui-v3",
    )


class _RecordingRepository(RunRepository):
    def __init__(
        self,
        events: list[str],
        *,
        run_start: RunStart | None = None,
        begin_error: Exception | None = None,
        finalize_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.run_start = RunStart(RunId("run-1"), datetime(2026, 7, 13, tzinfo=UTC)) if run_start is None else run_start
        self.begin_error = begin_error
        self.finalize_error = finalize_error
        self.begin_calls: list[tuple[TaskId, ExecutionMode, RunMetadata]] = []
        self.finalize_calls: list[tuple[RunId, TaskResult]] = []

    @override
    def begin_run(self, task_id: TaskId, mode: ExecutionMode, metadata: RunMetadata) -> RunStart:
        self.events.append("begin")
        self.begin_calls.append((task_id, mode, metadata))
        if self.begin_error is not None:
            raise self.begin_error
        return self.run_start

    @override
    def finalize_run(self, run_id: RunId, result: TaskResult) -> None:
        self.events.append("finalize")
        self.finalize_calls.append((run_id, result))
        if self.finalize_error is not None:
            raise self.finalize_error


class _ReturningTask(Task):
    def __init__(self, result: TaskResult, events: list[str]) -> None:
        self.result = result
        self.events = events
        self.contexts: list[TaskContext] = []

    @override
    def run(self, context: TaskContext) -> TaskResult:
        self.events.append("task")
        self.contexts.append(context)
        return self.result


class _RaisingTask(Task):
    def __init__(self, error: BaseException, events: list[str]) -> None:
        self.error = error
        self.events = events
        self.calls = 0

    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        self.events.append("task")
        self.calls += 1
        raise self.error


class _InvalidResultTask(Task):
    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        return cast("TaskResult", object())


class _StopRun(BaseException):
    pass


class _NoTaskRun:
    pass


def test_execute_begins_runs_and_finalizes_in_order() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    expected = TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(datetime(2026, 7, 14, tzinfo=UTC)),),
    )
    task = _ReturningTask(expected, events)
    task_id = TaskId("research")
    metadata = _metadata()

    result = RunCoordinator(repository).execute(task_id, ExecutionMode.SCHEDULED_JOB, metadata, task)

    assert result is expected
    assert events == ["begin", "task", "finalize"]
    assert repository.begin_calls == [(task_id, ExecutionMode.SCHEDULED_JOB, metadata)]
    assert repository.finalize_calls == [(RunId("run-1"), expected)]
    assert task.contexts[0].metadata is metadata
    assert task.contexts[0].started_at == datetime(2026, 7, 13, tzinfo=UTC)


def test_scheduled_success_without_self_schedule_becomes_faulted() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)

    result = RunCoordinator(repository).execute(
        TaskId("research"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _ReturningTask(TaskResult(Succeeded()), events),
    )

    assert isinstance(result.outcome, Faulted)
    assert isinstance(result.outcome.error, ScheduledTaskDidNotAdvanceError)
    assert repository.finalize_calls == [(RunId("run-1"), result)]


def test_scheduled_task_must_have_exactly_one_self_advancement() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    task_id = TaskId("research")
    due_at = datetime(2026, 7, 14, tzinfo=UTC)

    result = RunCoordinator(repository).execute(
        task_id,
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _ReturningTask(
            TaskResult(
                Succeeded(),
                effects=(RescheduleSelf(due_at), DisableTask(task_id)),
            ),
            events,
        ),
    )

    assert isinstance(result.outcome, Faulted)
    assert isinstance(result.outcome.error, ScheduledTaskDidNotAdvanceError)
    assert repository.finalize_calls == [(RunId("run-1"), result)]


@pytest.mark.parametrize(
    "effect",
    [
        RescheduleTask(TaskId("research"), datetime(2026, 7, 14, tzinfo=UTC)),
        WakeTask(TaskId("research"), datetime(2026, 7, 14, tzinfo=UTC), WakePolicy.FORCE_ENABLE),
    ],
)
def test_task_cannot_target_its_own_schedule_indirectly(effect: RescheduleTask | WakeTask) -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)

    result = RunCoordinator(repository).execute(
        TaskId("research"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _ReturningTask(TaskResult(Succeeded(), effects=(effect,)), events),
    )

    assert isinstance(result.outcome, Faulted)
    assert isinstance(result.outcome.error, ValueError)
    assert "must use RescheduleSelf" in str(result.outcome.error)


@pytest.mark.parametrize("mode", [ExecutionMode.ASSIST_SESSION, ExecutionMode.DIRECT_COMMAND])
def test_non_scheduled_modes_cannot_change_their_own_schedule(mode: ExecutionMode) -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)

    result = RunCoordinator(repository).execute(
        TaskId("event_story"),
        mode,
        _metadata(),
        _ReturningTask(
            TaskResult(Succeeded(), effects=(DisableTask(TaskId("event_story")),)),
            events,
        ),
    )

    assert isinstance(result.outcome, Faulted)
    assert isinstance(result.outcome.error, ValueError)
    assert "must not change its own schedule" in str(result.outcome.error)


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (AbortRequested("manual stop"), "manual stop"),
        (AbortRequested(), "abort requested"),
    ],
)
def test_abort_requested_becomes_a_finalized_cancelled_result(
    error: AbortRequested,
    expected_reason: str,
) -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)

    result = RunCoordinator(repository).execute(
        TaskId("main"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _RaisingTask(error, events),
    )

    assert result == TaskResult(outcome=Cancelled(expected_reason))
    assert repository.finalize_calls == [(RunId("run-1"), result)]


def test_abort_with_cleanup_failure_is_faulted_instead_of_cleanly_cancelled() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    abort_error = AbortRequested("manual stop")
    cleanup_error = OSError("runtime cleanup failed")
    error = ExceptionGroup("abort and cleanup both failed", (abort_error, cleanup_error))

    result = RunCoordinator(repository).execute(
        TaskId("main"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _RaisingTask(error, events),
    )

    assert isinstance(result.outcome, Faulted)
    assert result.outcome.error is error
    assert result.outcome.error.exceptions == (abort_error, cleanup_error)
    assert repository.finalize_calls == [(RunId("run-1"), result)]


def test_abort_requested_before_start_never_calls_the_task() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    task = _ReturningTask(TaskResult(Succeeded()), events)
    abort = AbortToken()
    abort.request("stop before start")

    result = RunCoordinator(repository).execute(
        TaskId("research"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        task,
        abort=abort,
    )

    assert result == TaskResult(Cancelled("stop before start"))
    assert task.contexts == []
    assert events == ["begin", "finalize"]


def test_preemption_before_scheduled_start_is_recorded_and_rescheduled_without_calling_task() -> None:
    events: list[str] = []
    started_at = datetime(2026, 7, 13, 3, tzinfo=UTC)
    repository = _RecordingRepository(events, run_start=RunStart(RunId("run-preempt"), started_at))
    task = _ReturningTask(TaskResult(Succeeded()), events)
    preemption = PreemptionRequest()
    preemption.request("higher priority task")

    result = RunCoordinator(repository).execute(
        TaskId("research"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        task,
        preemption=preemption,
    )

    assert result == TaskResult(
        Deferred("higher priority task"),
        effects=(RescheduleSelf(started_at),),
    )
    assert task.contexts == []
    assert events == ["begin", "finalize"]


@pytest.mark.parametrize("mode", [ExecutionMode.ASSIST_SESSION, ExecutionMode.DIRECT_COMMAND])
def test_preemption_before_non_scheduled_start_cancels_without_calling_task(mode: ExecutionMode) -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    task = _ReturningTask(TaskResult(Succeeded()), events)
    preemption = PreemptionRequest()
    preemption.request()

    result = RunCoordinator(repository).execute(
        TaskId("event_story"),
        mode,
        _metadata(),
        task,
        preemption=preemption,
    )

    assert result == TaskResult(Cancelled("preemption requested before task start"))
    assert task.contexts == []


def test_ordinary_exception_becomes_faulted_with_the_original_error() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    error = ValueError("invalid task state")

    result = RunCoordinator(repository).execute(
        TaskId("commission"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _RaisingTask(error, events),
    )

    assert isinstance(result.outcome, Faulted)
    assert result.outcome.error is error
    assert repository.finalize_calls == [(RunId("run-1"), result)]


def test_base_exception_propagates_without_finalizing() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    error = _StopRun("stop process")

    with pytest.raises(_StopRun) as raised:
        RunCoordinator(repository).execute(
            TaskId("daemon"),
            ExecutionMode.ASSIST_SESSION,
            _metadata(),
            _RaisingTask(error, events),
        )

    assert raised.value is error
    assert events == ["begin", "task"]
    assert repository.finalize_calls == []


def test_begin_failure_does_not_run_or_finalize() -> None:
    events: list[str] = []
    error = RuntimeError("begin failed")
    repository = _RecordingRepository(events, begin_error=error)
    task = _ReturningTask(TaskResult(outcome=Succeeded()), events)

    with pytest.raises(RuntimeError, match="begin failed") as raised:
        RunCoordinator(repository).execute(TaskId("reward"), ExecutionMode.SCHEDULED_JOB, _metadata(), task)

    assert raised.value is error
    assert task.contexts == []
    assert repository.finalize_calls == []


def test_invalid_run_start_stops_before_task_and_finalize() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events, run_start=cast("RunStart", RunId("run-1")))
    task = _ReturningTask(TaskResult(outcome=Succeeded()), events)

    with pytest.raises(TypeError, match=r"begin_run\(\) must return a RunStart"):
        RunCoordinator(repository).execute(TaskId("reward"), ExecutionMode.SCHEDULED_JOB, _metadata(), task)

    assert task.contexts == []
    assert repository.finalize_calls == []


def test_finalize_failure_propagates_after_one_attempt() -> None:
    events: list[str] = []
    error = OSError("finalize failed")
    repository = _RecordingRepository(events, finalize_error=error)
    task = _ReturningTask(TaskResult(outcome=Succeeded()), events)

    with pytest.raises(OSError, match="finalize failed") as raised:
        RunCoordinator(repository).execute(TaskId("daily"), ExecutionMode.SCHEDULED_JOB, _metadata(), task)

    assert raised.value is error
    assert events == ["begin", "task", "finalize"]
    assert len(repository.finalize_calls) == 1


def test_execute_injects_the_supplied_control_signals() -> None:
    events: list[str] = []
    repository = _RecordingRepository(
        events,
        run_start=RunStart(RunId("run-signals"), datetime(2026, 7, 13, tzinfo=UTC)),
    )
    task = _ReturningTask(TaskResult(outcome=Succeeded()), events)
    abort = AbortToken()
    preemption = PreemptionRequest()
    metadata = _metadata()

    RunCoordinator(repository).execute(
        TaskId("opsi_daemon"),
        ExecutionMode.ASSIST_SESSION,
        metadata,
        task,
        abort=abort,
        preemption=preemption,
    )

    context = task.contexts[0]
    assert context.task_id == TaskId("opsi_daemon")
    assert context.run_id == RunId("run-signals")
    assert context.mode is ExecutionMode.ASSIST_SESSION
    assert context.metadata is metadata
    assert context.abort is abort
    assert context.preemption is preemption


def test_invalid_task_result_becomes_a_finalized_fault() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)

    result = RunCoordinator(repository).execute(
        TaskId("benchmark"),
        ExecutionMode.DIRECT_COMMAND,
        _metadata(),
        _InvalidResultTask(),
    )

    assert isinstance(result.outcome, Faulted)
    assert isinstance(result.outcome.error, TypeError)
    assert str(result.outcome.error) == "Task.run() must return a TaskResult"
    assert repository.finalize_calls == [(RunId("run-1"), result)]


def test_task_cannot_mutate_another_task_state_namespace() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    task = _ReturningTask(
        TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(datetime(2026, 7, 14, tzinfo=UTC)),),
            state_effects=(UpsertTaskState("commission", "progress", 1, {"step": 2}),),
        ),
        events,
    )

    result = RunCoordinator(repository).execute(
        TaskId("research"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        task,
    )

    assert isinstance(result.outcome, Faulted)
    assert isinstance(result.outcome.error, ValueError)
    assert "another task's state namespace" in str(result.outcome.error)
    assert result.state_effects == ()
    assert repository.finalize_calls == [(RunId("run-1"), result)]


def test_invalid_execute_arguments_fail_before_begin() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    coordinator = RunCoordinator(repository)
    task = _ReturningTask(TaskResult(outcome=Succeeded()), events)

    with pytest.raises(TypeError, match="task_id must be a TaskId"):
        coordinator.execute(cast("TaskId", "reward"), ExecutionMode.SCHEDULED_JOB, _metadata(), task)
    with pytest.raises(TypeError, match="mode must be an ExecutionMode"):
        coordinator.execute(TaskId("reward"), cast("ExecutionMode", "scheduled_job"), _metadata(), task)
    with pytest.raises(TypeError, match="metadata must be a RunMetadata"):
        coordinator.execute(TaskId("reward"), ExecutionMode.SCHEDULED_JOB, cast("RunMetadata", object()), task)
    with pytest.raises(TypeError, match=r"task must implement Task\.run\(\)"):
        coordinator.execute(
            TaskId("reward"),
            ExecutionMode.SCHEDULED_JOB,
            _metadata(),
            cast("Task", _NoTaskRun()),
        )

    assert repository.begin_calls == []
