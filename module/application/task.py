from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from module.application.cancellation import AbortToken
from module.application.effects import (
    DelayTask,
    DisableTask,
    RequestAppRestart,
    RescheduleSelf,
    RescheduleTask,
    ScheduleEffect,
    WakeTask,
)
from module.application.identifiers import TaskId
from module.application.metadata import RunMetadata
from module.application.notifications import OperatorNotificationRequest
from module.application.outcomes import (
    Blocked,
    Cancelled,
    Deferred,
    Faulted,
    RecoverableFault,
    Retryable,
    RunOutcome,
    Succeeded,
)
from module.application.state_effects import DeleteTaskState, StateEffect, UpsertTaskState


class ExecutionMode(StrEnum):
    SCHEDULED_JOB = "scheduled_job"
    ASSIST_SESSION = "assist_session"
    DIRECT_COMMAND = "direct_command"


def _validate_distinct_effects(effects: tuple[ScheduleEffect, ...]) -> None:
    has_reschedule = False
    has_restart = False
    task_operations: set[TaskId] = set()

    for effect in effects:
        if isinstance(effect, RescheduleSelf):
            if has_reschedule:
                message = "effects must contain at most one RescheduleSelf"
                raise ValueError(message)
            has_reschedule = True
            continue

        if isinstance(effect, RequestAppRestart):
            if has_restart:
                message = "effects must contain at most one RequestAppRestart"
                raise ValueError(message)
            has_restart = True
            continue

        if isinstance(effect, RescheduleTask | DelayTask | WakeTask | DisableTask):
            if effect.task_id in task_operations:
                message = "effects must contain at most one target-task schedule operation per task_id"
                raise ValueError(message)
            task_operations.add(effect.task_id)


def _validate_distinct_state_effects(state_effects: tuple[StateEffect, ...]) -> None:
    operations: set[tuple[str, str]] = set()
    for effect in state_effects:
        address = (effect.namespace, effect.key)
        if address in operations:
            message = "state_effects must contain at most one operation per namespace/key"
            raise ValueError(message)
        operations.add(address)


@dataclass(frozen=True, slots=True)
class TaskContext:
    task_id: TaskId
    started_at: datetime
    mode: ExecutionMode
    metadata: RunMetadata
    abort: AbortToken

    def __post_init__(self) -> None:
        expected = (
            ("task_id", self.task_id, TaskId),
            ("started_at", self.started_at, datetime),
            ("mode", self.mode, ExecutionMode),
            ("metadata", self.metadata, RunMetadata),
            ("abort", self.abort, AbortToken),
        )
        for name, value, expected_type in expected:
            if not isinstance(value, expected_type):
                message = f"{name} must be a {expected_type.__name__}"
                raise TypeError(message)
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            message = "started_at must be timezone-aware"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class TaskResult:
    outcome: RunOutcome
    effects: tuple[ScheduleEffect, ...] = ()
    state_effects: tuple[StateEffect, ...] = ()
    notifications: tuple[OperatorNotificationRequest, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.outcome,
            Succeeded | Deferred | Retryable | Blocked | Cancelled | Faulted | RecoverableFault,
        ):
            message = "outcome must be a RunOutcome"
            raise TypeError(message)
        if not isinstance(self.effects, tuple):
            message = "effects must be a tuple"
            raise TypeError(message)
        if any(
            not isinstance(
                effect,
                RescheduleSelf | RescheduleTask | DelayTask | WakeTask | DisableTask | RequestAppRestart,
            )
            for effect in self.effects
        ):
            message = "effects must contain only ScheduleEffect values"
            raise TypeError(message)
        _validate_distinct_effects(self.effects)
        if not isinstance(self.state_effects, tuple):
            message = "state_effects must be a tuple"
            raise TypeError(message)
        if any(not isinstance(effect, UpsertTaskState | DeleteTaskState) for effect in self.state_effects):
            message = "state_effects must contain only StateEffect values"
            raise TypeError(message)
        _validate_distinct_state_effects(self.state_effects)
        if not isinstance(self.notifications, tuple):
            message = "notifications must be a tuple"
            raise TypeError(message)
        if any(not isinstance(request, OperatorNotificationRequest) for request in self.notifications):
            message = "notifications must contain only OperatorNotificationRequest values"
            raise TypeError(message)
        kinds = tuple(request.kind for request in self.notifications)
        if len(kinds) != len(set(kinds)):
            message = "notifications must contain at most one request per kind"
            raise ValueError(message)


class Task(Protocol):
    def run(self, context: TaskContext) -> TaskResult: ...
