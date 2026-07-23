from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    Blocked,
    Cancelled,
    Deferred,
    DisableTask,
    ExecutionMode,
    Faulted,
    RecoverableFault,
    RequestAppRestart,
    RescheduleSelf,
    RunMetadata,
    ScheduleItem,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
    WakePolicy,
    WakeTask,
)
from module.exception import GameStuckError
from module.runtime.errors import RecoveryLimitExceededError
from module.runtime.factories import TaskBuildContext, bind_tasks
from module.runtime.recovery import GameErrorRecovery
from module.runtime.runner import CommandStatus, ResultObserver, RuntimeRunner, SchedulerResourceLifecycle
from module.runtime.settings import compile_task_settings
from module.runtime.task_state import TaskStateDocument
from module.task_registry import ContentRevisionPolicy, TaskDomain, TaskSpec

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


class _FailOnceTask(_Task):
    def __init__(self, error: Exception, result: TaskResult) -> None:
        super().__init__(result)
        self.error = error

    def run(self, context: TaskContext) -> TaskResult:
        self.contexts.append(context)
        if len(self.contexts) == 1:
            raise self.error
        return self.result


class _AlwaysFailTask(_Task):
    def __init__(self, error: Exception) -> None:
        super().__init__(TaskResult(Succeeded()))
        self.error = error

    def run(self, context: TaskContext) -> TaskResult:
        self.contexts.append(context)
        raise self.error


class _Lifecycle(SchedulerResourceLifecycle):
    def __init__(self) -> None:
        self.calls: list[tuple[str, TaskId | None]] = []

    def before_task(self, next_task: TaskId) -> None:
        self.calls.append(("task", next_task))

    def before_wait(self) -> None:
        self.calls.append(("wait", None))


@dataclass(slots=True)
class _Factory:
    task: _Task

    def build(self, context: TaskBuildContext) -> _Task:
        del context
        return self.task


@dataclass(frozen=True, slots=True)
class _Settings:
    command: str


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
            elif isinstance(effect, WakeTask):
                target = self.items[effect.task_id]
                self.items[effect.task_id] = ScheduleItem(
                    task_id=effect.task_id,
                    enabled=effect.enable_policy is WakePolicy.FORCE_ENABLE or target.enabled,
                    due_at=effect.due_at,
                    priority=target.priority,
                )

    def list_items(self) -> tuple[ScheduleItem, ...]:
        return tuple(self.items.values())

    @staticmethod
    def task_state(task_id: TaskId) -> TaskStateDocument:
        return TaskStateDocument.empty(task_id.value)


def _spec(command: str, mode: ExecutionMode, priority: int | None) -> TaskSpec:
    return TaskSpec(
        command=command,
        config_scopes=(),
        priority=priority,
        execution_mode=mode,
        domain=TaskDomain.MAINTENANCE,
        content_revision_policy=ContentRevisionPolicy.BUILTIN,
    )


def _runner(  # ruff:ignore[too-many-arguments] - 测试装配器显式暴露 runner 的独立边界依赖。
    specs: tuple[TaskSpec, ...],
    tasks: tuple[_Task, ...],
    repository: _Repository,
    clock: _Clock,
    *,
    observer: ResultObserver | None = None,
    error_recovery: GameErrorRecovery | None = None,
    lifecycle: SchedulerResourceLifecycle | None = None,
) -> RuntimeRunner:
    spec_map = {spec.command: spec for spec in specs}
    settings = compile_task_settings(
        {spec.command: _Settings(spec.command) for spec in specs},
        task_ids=spec_map,
    )
    bindings = bind_tasks(
        specs=spec_map,
        factories={spec.command: _Factory(task) for spec, task in zip(specs, tasks, strict=True)},
        settings=settings,
        content_revisions={spec.command: f"content-{spec.command}" for spec in specs},
    )
    return RuntimeRunner(
        bindings=bindings,
        repository=repository,
        clock=clock,
        observer=observer,
        error_recovery=error_recovery,
        lifecycle=lifecycle,
    )


def test_direct_command_runs_once() -> None:
    task = _Task(TaskResult(Succeeded()))
    runner = _runner(
        (_spec("benchmark", ExecutionMode.DIRECT_COMMAND, None),),
        (task,),
        _Repository(),
        _Clock(),
    )

    outcome = runner.run("benchmark")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.runs_completed == 1
    assert len(task.contexts) == 1
    assert task.contexts[0].mode is ExecutionMode.DIRECT_COMMAND
    assert task.contexts[0].metadata.settings_revision > 0
    assert task.contexts[0].metadata.content_revision == "content-benchmark"


def test_scheduler_runs_all_due_tasks_then_finishes_when_empty() -> None:
    due_at = NOW + timedelta(minutes=5)
    reward_task = _Task(TaskResult(Succeeded(), effects=(DisableTask(TaskId("reward")),)))
    tactical_task = _Task(TaskResult(Succeeded(), effects=(DisableTask(TaskId("tactical")),)))
    repository = _Repository(
        (
            ScheduleItem(
                task_id=TaskId("reward"),
                enabled=True,
                due_at=due_at,
                priority=1,
            ),
            ScheduleItem(
                task_id=TaskId("tactical"),
                enabled=True,
                due_at=due_at,
                priority=0,
            ),
        )
    )
    clock = _Clock()
    lifecycle = _Lifecycle()
    runner = _runner(
        (
            _spec("reward", ExecutionMode.SCHEDULED_JOB, 1),
            _spec("tactical", ExecutionMode.SCHEDULED_JOB, 0),
        ),
        (reward_task, tactical_task),
        repository,
        clock,
        lifecycle=lifecycle,
    )

    outcome = runner.run("alas")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.runs_completed == 2
    assert outcome.last_task == "reward"
    assert [task_id for task_id, _result in repository.results] == [
        TaskId("tactical"),
        TaskId("reward"),
    ]
    assert clock.sleeps == [330.0]
    assert lifecycle.calls == [
        ("wait", None),
        ("task", TaskId("tactical")),
        ("task", TaskId("reward")),
    ]


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
        (_spec("benchmark", ExecutionMode.DIRECT_COMMAND, None),),
        (_Task(result),),
        _Repository(),
        _Clock(),
    )

    outcome = runner.run("benchmark")

    assert outcome.status is status
    if status is CommandStatus.FAILED:
        assert (outcome.exception_type, outcome.message) == ("RuntimeError", "boom")


def test_direct_command_rejects_incomplete_result() -> None:
    result = TaskResult(Blocked("not available"))
    runner = _runner(
        (_spec("benchmark", ExecutionMode.DIRECT_COMMAND, None),),
        (_Task(result),),
        _Repository(),
        _Clock(),
    )

    outcome = runner.run("benchmark")

    assert outcome.status is CommandStatus.FAILED
    assert outcome.message == "not available"


def test_scheduled_task_launched_once_accepts_routine_incomplete_result() -> None:
    result = TaskResult(Deferred("try later"), effects=(RescheduleSelf(NOW + timedelta(hours=1)),))
    runner = _runner(
        (_spec("research", ExecutionMode.SCHEDULED_JOB, 0),),
        (_Task(result),),
        _Repository(),
        _Clock(),
    )

    outcome = runner.run("research")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.message == "try later"


def test_scheduler_recovers_a_known_game_error_then_runs_restart_and_retries() -> None:
    research_id = TaskId("research")
    restart_id = TaskId("restart")
    repository = _Repository(
        (
            ScheduleItem(research_id, enabled=True, due_at=NOW, priority=1),
            ScheduleItem(restart_id, enabled=False, due_at=None, priority=0),
        )
    )
    research = _FailOnceTask(
        GameStuckError("stuck"),
        TaskResult(Succeeded(), effects=(DisableTask(research_id),)),
    )
    restart = _Task(
        TaskResult(Succeeded(), effects=(DisableTask(restart_id),)),
    )
    lifecycle = _Lifecycle()
    runner = _runner(
        (
            _spec("research", ExecutionMode.SCHEDULED_JOB, 1),
            _spec("restart", ExecutionMode.SCHEDULED_JOB, 0),
        ),
        (research, restart),
        repository,
        _Clock(),
        error_recovery=GameErrorRecovery(lambda: True, lambda: NOW),
        lifecycle=lifecycle,
    )

    outcome = runner.run("alas")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.runs_completed == 3
    first_result = repository.results[0][1]
    assert isinstance(first_result.outcome, RecoverableFault)
    assert isinstance(first_result.outcome.error, GameStuckError)
    assert [task_id for task_id, _result in repository.results] == [research_id, restart_id, research_id]
    assert lifecycle.calls[:3] == [
        ("task", research_id),
        ("wait", None),
        ("task", restart_id),
    ]


def test_scheduler_stops_after_three_consecutive_recoverable_failures() -> None:
    research_id = TaskId("research")
    restart_id = TaskId("restart")
    repository = _Repository(
        (
            ScheduleItem(research_id, enabled=True, due_at=NOW, priority=1),
            ScheduleItem(restart_id, enabled=False, due_at=None, priority=0),
        )
    )
    error = GameStuckError("still stuck")
    research = _AlwaysFailTask(error)
    restart = _Task(TaskResult(Succeeded(), effects=(DisableTask(restart_id),)))
    observed: list[tuple[TaskId, TaskResult]] = []

    def observer(task_id: TaskId, result: TaskResult) -> str | None:
        observed.append((task_id, result))
        return "terminal-bundle" if isinstance(result.outcome, Faulted) else None

    clock = _Clock()
    runner = _runner(
        (
            _spec("research", ExecutionMode.SCHEDULED_JOB, 1),
            _spec("restart", ExecutionMode.SCHEDULED_JOB, 0),
        ),
        (research, restart),
        repository,
        clock,
        observer=observer,
        error_recovery=GameErrorRecovery(lambda: True, clock.now),
    )

    outcome = runner.run("alas")

    assert outcome.status is CommandStatus.FAILED
    assert outcome.exception_type == "RecoveryLimitExceededError"
    assert outcome.message == "Task 'research' failed 3 consecutive times; recovery limit exhausted"
    assert outcome.error_bundle == "terminal-bundle"
    assert outcome.runs_completed == 5
    assert [task_id for task_id, _result in repository.results] == [
        research_id,
        restart_id,
        research_id,
        restart_id,
        research_id,
    ]
    assert isinstance(observed[-1][1].outcome, Faulted)
    limit_error = observed[-1][1].outcome.error
    assert isinstance(limit_error, RecoveryLimitExceededError)
    assert limit_error.task_id == "research"
    assert limit_error.attempts == 3
    assert limit_error.last_error is error
    assert limit_error.__cause__ is error


def test_scheduler_keeps_known_game_error_terminal_when_recovery_is_disabled() -> None:
    task_id = TaskId("research")
    repository = _Repository((ScheduleItem(task_id, enabled=True, due_at=NOW, priority=0),))
    initial_schedule = repository.list_items()
    runner = _runner(
        (_spec(task_id.value, ExecutionMode.SCHEDULED_JOB, 0),),
        (_FailOnceTask(GameStuckError("stuck"), TaskResult(Succeeded(), effects=(DisableTask(task_id),))),),
        repository,
        _Clock(),
        error_recovery=GameErrorRecovery(lambda: False, lambda: NOW),
    )

    outcome = runner.run("alas")

    assert outcome.status is CommandStatus.FAILED
    assert outcome.exception_type == "GameStuckError"
    assert outcome.runs_completed == 1
    assert repository.list_items() == initial_schedule


def test_persistence_failure_keeps_task_context_for_diagnostics() -> None:
    class _FailingRepository(_Repository):
        def finalize_run(self, result: TaskResult) -> None:
            del result
            self.active_task = None
            message = "disk full"
            raise OSError(message)

    observed: list[tuple[TaskId, TaskResult]] = []

    def observe(task_id: TaskId, result: TaskResult) -> str:
        observed.append((task_id, result))
        return "log/error/benchmark"

    task = _Task(TaskResult(Succeeded()))
    runner = _runner(
        (_spec("benchmark", ExecutionMode.DIRECT_COMMAND, None),),
        (task,),
        _FailingRepository(),
        _Clock(),
        observer=observe,
    )

    outcome = runner.run("benchmark")

    assert len(task.contexts) == 1
    assert observed[0][0] == TaskId("benchmark")
    assert isinstance(observed[0][1].outcome, Faulted)
    assert outcome.status is CommandStatus.FAILED
    assert outcome.last_task == "benchmark"
    assert outcome.runs_completed == 1
    assert outcome.exception_type == "OSError"
    assert outcome.message == "disk full"
    assert outcome.error_bundle == "log/error/benchmark"


def test_abort_before_scheduler_tick_returns_stopped() -> None:
    abort = AbortToken()
    abort.request("stop")
    runner = _runner((), (), _Repository(), _Clock())

    outcome = runner.run("alas", abort=abort)

    assert outcome.status is CommandStatus.STOPPED
    assert outcome.runs_completed == 0


def test_abort_during_scheduler_sleep_returns_stopped() -> None:
    class _AbortingClock(_Clock):
        def sleep(self, seconds: float, cancellation: AbortToken) -> None:
            del cancellation
            self.sleeps.append(seconds)
            raise AbortRequested

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
    clock = _AbortingClock()
    runner = _runner(
        (_spec("reward", ExecutionMode.SCHEDULED_JOB, 0),),
        (task,),
        repository,
        clock,
    )

    outcome = runner.run("alas")

    assert outcome.status is CommandStatus.STOPPED
    assert outcome.runs_completed == 0
    assert outcome.last_task is None
    assert clock.sleeps == [330.0]
    assert task.contexts == []


def test_scheduled_task_can_be_launched_once_for_debugging() -> None:
    task = _Task(TaskResult(Succeeded(), effects=(RescheduleSelf(NOW + timedelta(hours=1)),)))
    runner = _runner(
        (_spec("reward", ExecutionMode.SCHEDULED_JOB, 0),),
        (task,),
        _Repository(),
        _Clock(),
    )

    outcome = runner.run("reward")

    assert outcome.status is CommandStatus.FINISHED
    assert outcome.runs_completed == 1
    assert len(task.contexts) == 1
    assert task.contexts[0].mode is ExecutionMode.SCHEDULED_JOB
