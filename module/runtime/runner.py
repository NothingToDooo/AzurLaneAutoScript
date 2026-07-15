from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, cast

from module.application import (
    AbortRequested,
    AbortToken,
    Blocked,
    Cancelled,
    Deferred,
    ExecutionMode,
    Faulted,
    RequestAppRestart,
    Retryable,
    RunCoordinator,
    RunMetadata,
    RunRepository,
    Scheduler,
    SchedulerDecision,
    ScheduleSource,
    TaskId,
    TaskResult,
)
from module.runtime.factories import TaskFactoryRegistry
from module.runtime.settings import TaskSettingsDocument
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


type ResultObserver = Callable[[TaskId, TaskResult], str | None]


def _require_clock(clock: object) -> RunnerClock:
    if isinstance(clock, type) or not all(callable(getattr(clock, method, None)) for method in ("now", "sleep")):
        message = "clock must implement now() and sleep()"
        raise TypeError(message)
    return cast("RunnerClock", clock)


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
    return None


class RuntimeRunner:
    """串行执行一个固定配置的调度任务或调试命令。"""

    __slots__ = (
        "_clock",
        "_coordinator",
        "_factories",
        "_observer",
        "_repository",
        "_scheduler",
        "_settings",
    )

    def __init__(  # noqa: PLR0913 - runner 的五个依赖在唯一 composition root 显式组装。
        self,
        *,
        factories: TaskFactoryRegistry,
        settings: TaskSettingsDocument,
        repository: RuntimeRepository,
        clock: RunnerClock,
        hoard_window: timedelta = timedelta(seconds=30),
        observer: ResultObserver | None = None,
    ) -> None:
        if not isinstance(factories, TaskFactoryRegistry):
            message = "factories must be a TaskFactoryRegistry"
            raise TypeError(message)
        if not isinstance(settings, TaskSettingsDocument):
            message = "settings must be a TaskSettingsDocument"
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
        factories.validate_settings(settings)
        self._factories = factories
        self._settings = settings
        self._repository = repository
        self._clock = _require_clock(clock)
        self._observer = observer
        self._coordinator = RunCoordinator(repository)
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
        definition = self._factories.definition(command)
        result, bundle = self._execute(TaskId(command), definition.execution_mode, abort)
        return self._outcome(
            command,
            result,
            runs_completed=1,
            last_task=command,
            error_bundle=bundle,
        )

    def _run_scheduler(self, abort: AbortToken) -> CommandOutcome:
        runs_completed = 0
        last_task: str | None = None
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
                try:
                    self._clock.sleep(seconds, abort)
                except AbortRequested:
                    return self._stopped("alas", runs_completed=runs_completed, last_task=last_task)
                continue

            last_task = item.task_id.value
            result, bundle = self._execute(item.task_id, ExecutionMode.SCHEDULED_JOB, abort)
            runs_completed += 1
            status = _result_status(result)
            if status is None:
                continue
            return self._outcome(
                "alas",
                result,
                runs_completed=runs_completed,
                last_task=last_task,
                error_bundle=bundle,
            )

    def _execute(
        self,
        task_id: TaskId,
        mode: ExecutionMode,
        abort: AbortToken,
    ) -> tuple[TaskResult, str | None]:
        try:
            task_state = _require_task_state(self._repository.task_state(task_id))
            task = self._factories.build(task_id.value, self._settings, task_state)
            result = self._coordinator.execute(
                task_id,
                mode,
                RunMetadata(
                    settings_revision=self._settings.revision_for(task_id.value),
                    content_revision=self._factories.content_revision_for(task_id.value),
                ),
                task,
                abort=abort,
            )
        except Exception as error:  # noqa: BLE001 - task 边界必须保留 task id 并生成诊断。
            result = TaskResult(Faulted(error))
        bundle = None if self._observer is None else self._observer(task_id, result)
        if bundle is not None and not isinstance(bundle, str):
            message = "result observer must return a string or None"
            raise TypeError(message)
        return result, bundle

    def _outcome(
        self,
        command: str,
        result: TaskResult,
        *,
        runs_completed: int,
        last_task: str,
        error_bundle: str | None,
    ) -> CommandOutcome:
        status = _result_status(result) or CommandStatus.FINISHED
        exception_type: str | None = None
        message: str | None = None
        if isinstance(result.outcome, Faulted):
            exception_type = type(result.outcome.error).__name__
            message = str(result.outcome.error)
        elif isinstance(result.outcome, Cancelled):
            message = result.outcome.reason
        elif isinstance(result.outcome, Blocked | Deferred | Retryable):
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
