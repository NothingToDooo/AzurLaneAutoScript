from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from module.application._validation import validate_reason
from module.application.identifiers import TaskId


def _validate_due_at(due_at: datetime) -> None:
    if not isinstance(due_at, datetime):
        message = "due_at must be a datetime"
        raise TypeError(message)
    if due_at.tzinfo is None or due_at.utcoffset() is None:
        message = "due_at must be timezone-aware"
        raise ValueError(message)


def _validate_task_id(task_id: TaskId) -> None:
    if not isinstance(task_id, TaskId):
        message = "task_id must be a TaskId"
        raise TypeError(message)


class WakePolicy(StrEnum):
    FORCE_ENABLE = "force_enable"
    RESPECT_DISABLED = "respect_disabled"


@dataclass(frozen=True, slots=True)
class RescheduleSelf:
    due_at: datetime

    def __post_init__(self) -> None:
        _validate_due_at(self.due_at)


@dataclass(frozen=True, slots=True)
class RescheduleTask:
    """调整既有任务的 due time，同时保持其 enabled 状态。"""

    task_id: TaskId
    due_at: datetime

    def __post_init__(self) -> None:
        _validate_task_id(self.task_id)
        _validate_due_at(self.due_at)


@dataclass(frozen=True, slots=True)
class DelayTask:
    """仅把既有 due time 向后推，不提前任务，也不改变 enabled 状态。"""

    task_id: TaskId
    due_at: datetime

    def __post_init__(self) -> None:
        _validate_task_id(self.task_id)
        _validate_due_at(self.due_at)


@dataclass(frozen=True, slots=True)
class WakeTask:
    task_id: TaskId
    due_at: datetime
    enable_policy: WakePolicy

    def __post_init__(self) -> None:
        _validate_task_id(self.task_id)
        _validate_due_at(self.due_at)
        if not isinstance(self.enable_policy, WakePolicy):
            message = "enable_policy must be a WakePolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class DisableTask:
    task_id: TaskId

    def __post_init__(self) -> None:
        _validate_task_id(self.task_id)


@dataclass(frozen=True, slots=True)
class RequestAppRestart:
    reason: str

    def __post_init__(self) -> None:
        validate_reason(self.reason)


type ScheduleEffect = RescheduleSelf | RescheduleTask | DelayTask | WakeTask | DisableTask | RequestAppRestart
