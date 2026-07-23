from datetime import UTC, datetime
from typing import override

from module.application import (
    AbortRequested,
    Cancelled,
    ExecutionMode,
    Faulted,
    RecoverableFault,
    RescheduleSelf,
    RunCoordinator,
    RunMetadata,
    RunRepository,
    ScheduledTaskDidNotAdvanceError,
    Succeeded,
    Task,
    TaskContext,
    TaskErrorRecovery,
    TaskId,
    TaskResult,
    WakePolicy,
    WakeTask,
)


def _metadata() -> RunMetadata:
    return RunMetadata(
        settings_revision=8,
        content_revision="content-20260713",
    )


class _RecordingRepository(RunRepository):
    def __init__(
        self,
        events: list[str],
        *,
        started_at: datetime | None = None,
        begin_error: Exception | None = None,
        finalize_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.started_at = datetime(2026, 7, 13, tzinfo=UTC) if started_at is None else started_at
        self.begin_error = begin_error
        self.finalize_error = finalize_error
        self.begin_calls: list[tuple[TaskId, ExecutionMode, RunMetadata]] = []
        self.finalize_calls: list[TaskResult] = []

    @override
    def begin_run(self, task_id: TaskId, mode: ExecutionMode, metadata: RunMetadata) -> datetime:
        self.events.append("begin")
        self.begin_calls.append((task_id, mode, metadata))
        if self.begin_error is not None:
            raise self.begin_error
        return self.started_at

    @override
    def finalize_run(self, result: TaskResult) -> None:
        self.events.append("finalize")
        self.finalize_calls.append(result)
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


class _RecoverDeviceFailure(TaskErrorRecovery):
    def __init__(self, expected: Exception, result: TaskResult) -> None:
        self.expected = expected
        self.result = result
        self.calls: list[tuple[TaskContext, Exception]] = []

    @override
    def recover(self, context: TaskContext, error: Exception) -> TaskResult | None:
        self.calls.append((context, error))
        if error is self.expected:
            return self.result
        return None


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
    assert repository.finalize_calls == [expected]
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
    assert repository.finalize_calls == [result]


def test_task_abort_is_finalized_as_cancelled() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)

    result = RunCoordinator(repository).execute(
        TaskId("main"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _RaisingTask(AbortRequested("manual stop"), events),
    )

    assert result == TaskResult(outcome=Cancelled("manual stop"))
    assert repository.finalize_calls == [result]


def test_recoverable_exception_is_translated_before_finalize() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    error = RuntimeError("temporary device failure")
    retry_at = datetime(2026, 7, 13, 0, 0, 10, tzinfo=UTC)
    expected = TaskResult(
        outcome=RecoverableFault(error),
        effects=(
            RescheduleSelf(retry_at),
            WakeTask(TaskId("restart"), retry_at, WakePolicy.FORCE_ENABLE),
        ),
    )
    recovery = _RecoverDeviceFailure(error, expected)

    result = RunCoordinator(repository, error_recovery=recovery).execute(
        TaskId("commission"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _RaisingTask(error, events),
    )

    assert result is expected
    assert repository.finalize_calls == [expected]
    assert recovery.calls[0][0].task_id == TaskId("commission")
    assert recovery.calls[0][1] is error


def test_error_recovery_can_decline_an_unknown_exception() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    expected_error = RuntimeError("temporary device failure")
    unknown_error = ValueError("invalid task state")
    retry_at = datetime(2026, 7, 13, 0, 0, 10, tzinfo=UTC)
    recovery = _RecoverDeviceFailure(
        expected_error,
        TaskResult(RecoverableFault(expected_error), effects=(RescheduleSelf(retry_at),)),
    )

    result = RunCoordinator(repository, error_recovery=recovery).execute(
        TaskId("commission"),
        ExecutionMode.SCHEDULED_JOB,
        _metadata(),
        _RaisingTask(unknown_error, events),
    )

    assert isinstance(result.outcome, Faulted)
    assert result.outcome.error is unknown_error
    assert repository.finalize_calls == [result]
