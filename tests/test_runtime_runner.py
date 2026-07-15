from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from module.application import (
    AbortToken,
    Cancelled,
    DisableTask,
    ExecutionMode,
    Faulted,
    RequestAppRestart,
    RescheduleSelf,
    RunMetadata,
    ScheduleItem,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.runtime.factories import TaskBuildContext, TaskFactoryRegistry
from module.runtime.runner import CommandStatus, ResultObserver, RuntimeRunner
from module.runtime.settings import TaskSettingsDocument
from module.runtime.task_state import TaskStateDocument
from module.task_registry import TaskDefinition

NOW = datetime(2026, 7, 15, 6, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.current = now
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float, cancellation: AbortToken) -> None:
        cancellation.raise_if_requested()
        self.sleeps.append(seconds)
        self.current += timedelta(seconds=seconds)


class _Task:
    def __init__(self, result: TaskResult) -> None:
        self.result = result
        self.contexts: list[TaskContext] = []

    def run(self, context: TaskContext) -> TaskResult:
        self.contexts.append(context)
        return self.result


@dataclass(slots=True)
class _Factory:
    task: _Task

    def build(self, context: TaskBuildContext) -> _Task:
        del context
        return self.task


class _Repository:
    def __init__(self, items: tuple[ScheduleItem, ...] = ()) -> None:
        self.items = {item.task_id: item for item in items}
        self.active_task: TaskId | None = None
        self.results: list[tuple[TaskId, TaskResult]] = []

    def begin_run(self, task_id: TaskId, mode: ExecutionMode, metadata: RunMetadata) -> datetime:
        del mode, metadata
        self.active_task = task_id
        return NOW

    def finalize_run(self, result: TaskResult) -> None:
        task_id = self.active_task
        if task_id is None:
            message = "no active task"
            raise RuntimeError(message)
        self.active_task = None
        self.results.append((task_id, result))
        current = self.items.get(task_id)
        for effect in result.effects:
            if isinstance(effect, RescheduleSelf) and current is not None:
                self.items[task_id] = ScheduleItem(
                    task_id=task_id,
                    enabled=current.enabled,
                    due_at=effect.due_at,
                    priority=current.priority,
                )
            elif isinstance(effect, DisableTask) and current is not None:
                self.items[task_id] = ScheduleItem(
                    task_id=task_id,
                    enabled=False,
                    due_at=current.due_at,
                    priority=current.priority,
                )

    def list_items(self) -> tuple[ScheduleItem, ...]:
        return tuple(self.items.values())

    @staticmethod
    def task_state(task_id: TaskId) -> TaskStateDocument:
        return TaskStateDocument.empty(task_id.value)


def _definition(command: str, mode: ExecutionMode, priority: int | None) -> TaskDefinition:
    return TaskDefinition(
        command=command,
        config_scopes=(),
        priority=priority,
        execution_mode=mode,
    )


def _runner(
    definitions: tuple[TaskDefinition, ...],
    tasks: tuple[_Task, ...],
    repository: _Repository,
    clock: _Clock,
    *,
    observer: ResultObserver | None = None,
) -> RuntimeRunner:
    catalog = {definition.command: definition for definition in definitions}
    registry = TaskFactoryRegistry(
        catalog=catalog,
        factories={definition.command: _Factory(task) for definition, task in zip(definitions, tasks, strict=True)},
        content_revision="content-test",
    )
    settings = TaskSettingsDocument.from_payload(
        {"schema_version": 1, "tasks": {definition.command: {} for definition in definitions}},
        revision=1,
        updated_at=NOW,
        task_ids=catalog,
    )
    return RuntimeRunner(
        factories=registry,
        settings=settings,
        repository=repository,
        clock=clock,
        observer=observer,
    )


def test_direct_command_runs_once() -> None:
    task = _Task(TaskResult(Succeeded()))
    runner = _runner(
        (_definition("benchmark", ExecutionMode.DIRECT_COMMAND, None),),
        (task,),
        _Repository(),
        _Clock(),
    )

    outcome = runner.run("benchmark")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.runs_completed == 1
    assert len(task.contexts) == 1
    assert task.contexts[0].mode is ExecutionMode.DIRECT_COMMAND


def test_scheduler_waits_runs_due_task_and_finishes_when_disabled() -> None:
    due_at = NOW + timedelta(minutes=5)
    task = _Task(TaskResult(Succeeded(), effects=(DisableTask(TaskId("reward")),)))
    repository = _Repository(
        (
            ScheduleItem(
                task_id=TaskId("reward"),
                enabled=True,
                due_at=due_at,
                priority=0,
            ),
        )
    )
    clock = _Clock()
    runner = _runner(
        (_definition("reward", ExecutionMode.SCHEDULED_JOB, 0),),
        (task,),
        repository,
        clock,
    )

    outcome = runner.run("alas")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.runs_completed == 1
    assert clock.sleeps == [330.0]


@pytest.mark.parametrize(
    ("result", "status"),
    [
        (TaskResult(Cancelled("operator stopped")), CommandStatus.STOPPED),
        (TaskResult(Succeeded(), effects=(RequestAppRestart("game restart"),)), CommandStatus.RESTART_REQUESTED),
        (TaskResult(Faulted(RuntimeError("boom"))), CommandStatus.FAILED),
    ],
)
def test_direct_command_maps_terminal_result(result: TaskResult, status: CommandStatus) -> None:
    runner = _runner(
        (_definition("benchmark", ExecutionMode.DIRECT_COMMAND, None),),
        (_Task(result),),
        _Repository(),
        _Clock(),
    )

    outcome = runner.run("benchmark")

    assert outcome.status is status
    if status is CommandStatus.FAILED:
        assert (outcome.exception_type, outcome.message) == ("RuntimeError", "boom")


def test_result_observer_can_attach_error_bundle() -> None:
    error = RuntimeError("boom")
    observed: list[tuple[TaskId, TaskResult]] = []

    def observe(task_id: TaskId, result: TaskResult) -> str:
        observed.append((task_id, result))
        return "log/error/bundle"

    runner = _runner(
        (_definition("benchmark", ExecutionMode.DIRECT_COMMAND, None),),
        (_Task(TaskResult(Faulted(error))),),
        _Repository(),
        _Clock(),
        observer=observe,
    )

    outcome = runner.run("benchmark")

    assert observed[0][0] == TaskId("benchmark")
    assert outcome.error_bundle == "log/error/bundle"


def test_abort_before_scheduler_tick_returns_stopped() -> None:
    abort = AbortToken()
    abort.request("stop")
    runner = _runner((), (), _Repository(), _Clock())

    outcome = runner.run("alas", abort=abort)

    assert outcome.status is CommandStatus.STOPPED
    assert outcome.runs_completed == 0


def test_scheduled_task_can_be_launched_once_for_debugging() -> None:
    task = _Task(TaskResult(Succeeded(), effects=(RescheduleSelf(NOW + timedelta(hours=1)),)))
    runner = _runner(
        (_definition("reward", ExecutionMode.SCHEDULED_JOB, 0),),
        (task,),
        _Repository(),
        _Clock(),
    )

    outcome = runner.run("reward")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.runs_completed == 1
    assert len(task.contexts) == 1
    assert task.contexts[0].mode is ExecutionMode.SCHEDULED_JOB
