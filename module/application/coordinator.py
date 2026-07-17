from datetime import datetime
from typing import Final, Protocol

from module.application.cancellation import AbortRequested, AbortToken
from module.application.effects import DelayTask, DisableTask, RescheduleSelf, RescheduleTask, WakeTask
from module.application.identifiers import TaskId
from module.application.metadata import RunMetadata
from module.application.outcomes import Cancelled, Faulted
from module.application.state_effects import DeleteTaskState, UpsertTaskState
from module.application.task import ExecutionMode, Task, TaskContext, TaskResult

_DEFAULT_ABORT_REASON: Final = "abort requested"


class ScheduledTaskDidNotAdvanceError(RuntimeError):
    """scheduled task 正常返回但没有推进或禁用自己的 schedule。"""


class RunRepository(Protocol):
    def begin_run(self, task_id: TaskId, mode: ExecutionMode, metadata: RunMetadata) -> datetime: ...

    def finalize_run(self, result: TaskResult) -> None: ...


def _validate_execute_arguments(
    task_id: TaskId,
    mode: ExecutionMode,
    metadata: RunMetadata,
    task: Task,
) -> None:
    if not isinstance(task_id, TaskId):
        message = "task_id must be a TaskId"
        raise TypeError(message)
    if not isinstance(mode, ExecutionMode):
        message = "mode must be an ExecutionMode"
        raise TypeError(message)
    if not isinstance(metadata, RunMetadata):
        message = "metadata must be a RunMetadata"
        raise TypeError(message)
    if isinstance(task, type) or not callable(getattr(task, "run", None)):
        message = "task must implement Task.run()"
        raise TypeError(message)


def _validate_abort(abort: AbortToken | None) -> None:
    if abort is not None and not isinstance(abort, AbortToken):
        message = "abort must be an AbortToken or None"
        raise TypeError(message)


def _require_task_result(result: object) -> TaskResult:
    if not isinstance(result, TaskResult):
        message = "Task.run() must return a TaskResult"
        raise TypeError(message)
    return result


def _validate_scheduled_result(task_id: TaskId, mode: ExecutionMode, result: TaskResult) -> None:
    indirect_self_effects = tuple(
        effect
        for effect in result.effects
        if isinstance(effect, RescheduleTask | DelayTask | WakeTask) and effect.task_id == task_id
    )
    if indirect_self_effects:
        message = f"task {task_id.value!r} must use RescheduleSelf or DisableTask for its own schedule"
        raise ValueError(message)

    advancements = tuple(
        effect
        for effect in result.effects
        if isinstance(effect, RescheduleSelf) or (isinstance(effect, DisableTask) and effect.task_id == task_id)
    )
    if mode is not ExecutionMode.SCHEDULED_JOB:
        if advancements:
            message = f"{mode.value} task {task_id.value!r} must not change its own schedule"
            raise ValueError(message)
        return
    if isinstance(result.outcome, Cancelled | Faulted):
        return
    if len(advancements) != 1:
        message = f"scheduled task {task_id.value!r} must reschedule or disable itself"
        raise ScheduledTaskDidNotAdvanceError(message)


def _validate_state_effects(task_id: TaskId, result: TaskResult) -> None:
    foreign = tuple(
        effect
        for effect in result.state_effects
        if isinstance(effect, UpsertTaskState | DeleteTaskState) and effect.namespace != task_id.value
    )
    if foreign:
        message = f"task {task_id.value!r} must not mutate another task's state namespace"
        raise ValueError(message)


class RunCoordinator:
    __slots__ = ("repository",)

    def __init__(self, repository: RunRepository) -> None:
        self.repository = repository

    def execute(
        self,
        task_id: TaskId,
        mode: ExecutionMode,
        metadata: RunMetadata,
        task: Task,
        *,
        abort: AbortToken | None = None,
    ) -> TaskResult:
        _validate_execute_arguments(task_id, mode, metadata, task)
        _validate_abort(abort)

        started_at = self.repository.begin_run(task_id, mode, metadata)
        if not isinstance(started_at, datetime):
            message = "begin_run() must return a datetime"
            raise TypeError(message)
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            message = "begin_run() must return a timezone-aware datetime"
            raise ValueError(message)

        context = TaskContext(
            task_id=task_id,
            started_at=started_at,
            mode=mode,
            metadata=metadata,
            abort=AbortToken() if abort is None else abort,
        )
        try:
            context.abort.raise_if_requested()
            result = _require_task_result(task.run(context))
            _validate_scheduled_result(task_id, mode, result)
            _validate_state_effects(task_id, result)
        except AbortRequested as error:
            result = TaskResult(outcome=Cancelled(error.reason or _DEFAULT_ABORT_REASON))
        except Exception as error:  # ruff:ignore[blind-except]
            result = TaskResult(outcome=Faulted(error))

        self.repository.finalize_run(result)
        return result
