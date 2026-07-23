from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, cast

from module.application import (
    AbortRequested,
    AbortToken,
    Blocked,
    Cancelled,
    Deferred,
    ExecutionMode,
    Faulted,
    RecoverableFault,
    RequestAppRestart,
    RescheduleSelf,
    Retryable,
    RunCoordinator,
    RunMetadata,
    RunRepository,
    Scheduler,
    SchedulerDecision,
    ScheduleSource,
    TaskErrorRecovery,
    TaskId,
    TaskResult,
)
from module.runtime.errors import RecoveryLimitExceededError, UnknownTaskError
from module.runtime.factories import TaskBinding
from module.runtime.task_state import TaskStateDocument


class CommandStatus(StrEnum):
    FINISHED = "finished"
    STOPPED = "stopped"
    RESTART_REQUESTED = "restart_requested"
    FAILED = "failed"
    KILLED = "killed"


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    command: str
    status: CommandStatus
    finished_at: datetime
    runs_completed: int = 0
    last_task: str | None = None
    exception_type: str | None = None
    message: str | None = None
    error_bundle: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.command, str) or not self.command or self.command != self.command.strip():
            message = "command must be trimmed and non-empty"
            raise ValueError(message)
        if not isinstance(self.status, CommandStatus):
            message = "status must be a CommandStatus"
            raise TypeError(message)
        if not isinstance(self.finished_at, datetime):
            message = "finished_at must be a datetime"
            raise TypeError(message)
        if self.finished_at.utcoffset() is None:
            message = "finished_at must be timezone-aware"
            raise ValueError(message)
        if type(self.runs_completed) is not int or self.runs_completed < 0:
            message = "runs_completed must be a non-negative integer"
            raise ValueError(message)
        for field_name, value in (
            ("last_task", self.last_task),
            ("exception_type", self.exception_type),
            ("message", self.message),
            ("error_bundle", self.error_bundle),
        ):
            if value is not None and not isinstance(value, str):
                message = f"{field_name} must be a string or None"
                raise TypeError(message)


class RunnerClock(Protocol):
    def now(self) -> datetime: ...

    def sleep(self, seconds: float, cancellation: AbortToken) -> None: ...


class RuntimeRepository(RunRepository, ScheduleSource, Protocol):
    def task_state(self, task_id: TaskId) -> TaskStateDocument: ...


class SchedulerResourceLifecycle(Protocol):
    def before_task(self, next_task: TaskId) -> None: ...

    def before_wait(self) -> None: ...


type ResultObserver = Callable[[TaskId, TaskResult], str | None]

_MAX_RECOVERABLE_FAILURES = 3


def _require_clock(clock: object) -> RunnerClock:
    if isinstance(clock, type) or not all(callable(getattr(clock, method, None)) for method in ("now", "sleep")):
        message = "clock must implement now() and sleep()"
        raise TypeError(message)
    return cast("RunnerClock", clock)


def _require_lifecycle(lifecycle: object) -> SchedulerResourceLifecycle:
    if isinstance(lifecycle, type) or not all(
        callable(getattr(lifecycle, method, None)) for method in ("before_task", "before_wait")
    ):
        message = "lifecycle must implement before_task() and before_wait()"
        raise TypeError(message)
    return cast("SchedulerResourceLifecycle", lifecycle)


def _require_task_state(value: object) -> TaskStateDocument:
    if not isinstance(value, TaskStateDocument):
        message = "RuntimeRepository.task_state() must return a TaskStateDocument"
        raise TypeError(message)
    return value


def _result_status(result: TaskResult) -> CommandStatus | None:
    if any(isinstance(effect, RequestAppRestart) for effect in result.effects):
        return CommandStatus.RESTART_REQUESTED
    if isinstance(result.outcome, Cancelled):
        return CommandStatus.STOPPED
    if isinstance(result.outcome, Faulted):
        return CommandStatus.FAILED
    if isinstance(result.outcome, RecoverableFault):
        return None
    return None


class RuntimeRunner:
    """串行执行一个固定配置的调度任务或调试命令。"""

    __slots__ = (
        "_bindings",
        "_clock",
        "_coordinator",
        "_lifecycle",
        "_observer",
        "_repository",
        "_scheduler",
        "_scheduler_coordinator",
    )

    def __init__(  # ruff:ignore[too-many-arguments] - 运行入口显式接收存储、时钟和三个可选边界 hook。
        self,
        *,
        bindings: Mapping[TaskId, TaskBinding],
        repository: RuntimeRepository,
        clock: RunnerClock,
        hoard_window: timedelta = timedelta(seconds=30),
        observer: ResultObserver | None = None,
        error_recovery: TaskErrorRecovery | None = None,
        lifecycle: SchedulerResourceLifecycle | None = None,
    ) -> None:
        if not isinstance(bindings, Mapping):
            message = "bindings must be a mapping"
            raise TypeError(message)
        binding_copy = dict(bindings)
        if any(
            not isinstance(task_id, TaskId)
            or not isinstance(binding, TaskBinding)
            or binding.spec.command != task_id.value
            for task_id, binding in binding_copy.items()
        ):
            message = "bindings must map task ids to coherent TaskBinding values"
            raise TypeError(message)
        if isinstance(repository, type) or not all(
            callable(getattr(repository, method, None))
            for method in ("begin_run", "finalize_run", "list_items", "task_state")
        ):
            message = "repository must implement run, schedule, and task-state operations"
            raise TypeError(message)
        if not isinstance(hoard_window, timedelta) or hoard_window < timedelta(0):
            message = "hoard_window must be a non-negative timedelta"
            raise ValueError(message)
        if observer is not None and not callable(observer):
            message = "observer must be callable or None"
            raise TypeError(message)
        if error_recovery is not None and (
            isinstance(error_recovery, type) or not callable(getattr(error_recovery, "recover", None))
        ):
            message = "error_recovery must implement recover() or be None"
            raise TypeError(message)
        self._bindings = MappingProxyType(binding_copy)
        self._repository = repository
        self._clock = _require_clock(clock)
        self._observer = observer
        self._lifecycle = None if lifecycle is None else _require_lifecycle(lifecycle)
        self._coordinator = RunCoordinator(repository)
        self._scheduler_coordinator = RunCoordinator(repository, error_recovery=error_recovery)
        self._scheduler = Scheduler(repository, hoard_window=hoard_window)

    def run(self, command: str, *, abort: AbortToken | None = None) -> CommandOutcome:
        if not isinstance(command, str) or not command or command != command.strip():
            message = "command must be trimmed and non-empty"
            raise ValueError(message)
        active_abort = AbortToken() if abort is None else abort
        if not isinstance(active_abort, AbortToken):
            message = "abort must be an AbortToken or None"
            raise TypeError(message)
        if command == "alas":
            return self._run_scheduler(active_abort)
        return self._run_direct(command, active_abort)

    def _run_direct(self, command: str, abort: AbortToken) -> CommandOutcome:
        task_id = TaskId(command)
        binding = self._binding(task_id)
        mode = binding.spec.execution_mode
        result = self._execute(task_id, mode, abort)
        bundle = self._observe(task_id, result)
        return self._outcome(
            command,
            result,
            runs_completed=1,
            last_task=command,
            error_bundle=bundle,
            execution_mode=mode,
        )

    def _run_scheduler(  # ruff:ignore[complex-structure] - 主循环直接呈现 empty、waiting、ready 与取消状态。
        self,
        abort: AbortToken,
    ) -> CommandOutcome:
        runs_completed = 0
        last_task: str | None = None
        recoverable_failures: dict[TaskId, int] = {}
        while True:
            try:
                abort.raise_if_requested()
            except AbortRequested:
                return self._stopped("alas", runs_completed=runs_completed, last_task=last_task)

            selection = self._scheduler.next(self._clock.now())
            if selection.decision is SchedulerDecision.EMPTY:
                return CommandOutcome(
                    command="alas",
                    status=CommandStatus.FINISHED,
                    finished_at=self._finished_at(),
                    runs_completed=runs_completed,
                    last_task=last_task,
                )
            item = selection.item
            if item is None:
                message = f"{selection.decision.value} selection must contain an item"
                raise RuntimeError(message)
            if selection.decision is SchedulerDecision.WAITING:
                wake_at = selection.wake_at
                if wake_at is None:
                    message = "waiting selection must contain wake_at"
                    raise RuntimeError(message)
                seconds = max(0.0, (wake_at - self._clock.now()).total_seconds())
                if not self._wait(seconds, abort):
                    return self._stopped("alas", runs_completed=runs_completed, last_task=last_task)
                continue

            last_task = item.task_id.value
            if self._lifecycle is not None:
                self._lifecycle.before_task(item.task_id)
            result = self._execute(
                item.task_id,
                ExecutionMode.SCHEDULED_JOB,
                abort,
                recover_errors=True,
            )
            runs_completed += 1
            if isinstance(result.outcome, RecoverableFault):
                failures = recoverable_failures.get(item.task_id, 0) + 1
                recoverable_failures[item.task_id] = failures
                if failures >= _MAX_RECOVERABLE_FAILURES:
                    terminal_error = RecoveryLimitExceededError(
                        item.task_id.value,
                        failures,
                        result.outcome.error,
                    )
                    terminal = TaskResult(Faulted(terminal_error))
                    bundle = self._observe(item.task_id, terminal)
                    return self._outcome(
                        "alas",
                        terminal,
                        runs_completed=runs_completed,
                        last_task=last_task,
                        error_bundle=bundle,
                        execution_mode=ExecutionMode.SCHEDULED_JOB,
                    )
                self._observe(item.task_id, result)
                if not self._wait_for_recovery(result, abort):
                    return self._stopped("alas", runs_completed=runs_completed, last_task=last_task)
                continue
            recoverable_failures.pop(item.task_id, None)
            bundle = self._observe(item.task_id, result)
            status = _result_status(result)
            if status is None:
                continue
            return self._outcome(
                "alas",
                result,
                runs_completed=runs_completed,
                last_task=last_task,
                error_bundle=bundle,
                execution_mode=ExecutionMode.SCHEDULED_JOB,
            )

    def _wait_for_recovery(self, result: TaskResult, abort: AbortToken) -> bool:
        retry_at = next(
            (effect.due_at for effect in result.effects if isinstance(effect, RescheduleSelf)),
            None,
        )
        if retry_at is None:
            return True
        seconds = max(0.0, (retry_at - self._clock.now()).total_seconds())
        return seconds <= 0 or self._wait(seconds, abort)

    def _wait(self, seconds: float, abort: AbortToken) -> bool:
        if self._lifecycle is not None:
            self._lifecycle.before_wait()
        try:
            self._clock.sleep(seconds, abort)
        except AbortRequested:
            return False
        return True

    def _execute(
        self,
        task_id: TaskId,
        mode: ExecutionMode,
        abort: AbortToken,
        *,
        recover_errors: bool = False,
    ) -> TaskResult:
        try:
            task_state = _require_task_state(self._repository.task_state(task_id))
            binding = self._binding(task_id)
            task = binding.build(task_state)
            coordinator = self._scheduler_coordinator if recover_errors else self._coordinator
            result = coordinator.execute(
                task_id,
                mode,
                RunMetadata(
                    settings_revision=binding.settings_revision,
                    content_revision=binding.content_revision,
                ),
                task,
                abort=abort,
            )
        except Exception as error:  # ruff:ignore[blind-except] - task 边界必须保留 task id 并生成诊断。
            result = TaskResult(Faulted(error))
        return result

    def _observe(self, task_id: TaskId, result: TaskResult) -> str | None:
        bundle = None if self._observer is None else self._observer(task_id, result)
        if bundle is not None and not isinstance(bundle, str):
            message = "result observer must return a string or None"
            raise TypeError(message)
        return bundle

    def _binding(self, task_id: TaskId) -> TaskBinding:
        try:
            return self._bindings[task_id]
        except KeyError:
            message = f"unknown task: {task_id.value}"
            raise UnknownTaskError(message) from None

    def _outcome(  # ruff:ignore[too-many-arguments] - CommandOutcome 的执行上下文在此一次性序列化。
        self,
        command: str,
        result: TaskResult,
        *,
        runs_completed: int,
        last_task: str,
        error_bundle: str | None,
        execution_mode: ExecutionMode,
    ) -> CommandOutcome:
        status = _result_status(result) or CommandStatus.FINISHED
        exception_type: str | None = None
        message: str | None = None
        if isinstance(result.outcome, Faulted | RecoverableFault):
            exception_type = type(result.outcome.error).__name__
            message = str(result.outcome.error)
            if isinstance(result.outcome, RecoverableFault):
                status = CommandStatus.FAILED
        elif isinstance(result.outcome, Cancelled):
            message = result.outcome.reason
        elif isinstance(result.outcome, Blocked | Deferred | Retryable):
            if execution_mode is ExecutionMode.DIRECT_COMMAND:
                status = CommandStatus.FAILED
            message = result.outcome.reason
        return CommandOutcome(
            command=command,
            status=status,
            finished_at=self._finished_at(),
            runs_completed=runs_completed,
            last_task=last_task,
            exception_type=exception_type,
            message=message,
            error_bundle=error_bundle,
        )

    def _stopped(self, command: str, *, runs_completed: int, last_task: str | None) -> CommandOutcome:
        return CommandOutcome(
            command=command,
            status=CommandStatus.STOPPED,
            finished_at=self._finished_at(),
            runs_completed=runs_completed,
            last_task=last_task,
        )

    def _finished_at(self) -> datetime:
        value = self._clock.now()
        if not isinstance(value, datetime) or value.utcoffset() is None:
            return datetime.now(UTC)
        return value
