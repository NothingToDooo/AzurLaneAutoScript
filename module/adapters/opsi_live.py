from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol, override

from module.gameplay.opsi import (
    OperationSirenWorkflow,
    WorldOperation,
    WorldSchedule,
    WorldTaskReport,
    WorldTaskSpec,
    WorldTaskStatus,
)
from module.gameplay.opsi_progress import (
    WorldCheckpointMode,
    WorldProgress,
    WorldProgressCursor,
)

if TYPE_CHECKING:
    from module.application import PreemptionRequest, TaskId
    from module.interaction import CancellationSignal


def _validate_aware(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.tzinfo is None or value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class LiveOpsiStep:
    """一次真实客户端 step 已确认的事实，不包含调度时钟快照。"""

    operation: WorldOperation
    status: WorldTaskStatus
    completed_units: int = 0
    cursor: WorldProgressCursor | None = None
    retry_at: datetime | None = None
    retry_after: timedelta | None = None
    affected_task_ids: tuple[TaskId, ...] = ()
    has_surplus_yellow_coins: bool = False
    exploration_in_progress: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.operation, WorldOperation):
            message = "operation must be a WorldOperation"
            raise TypeError(message)
        if not isinstance(self.status, WorldTaskStatus):
            message = "status must be a WorldTaskStatus"
            raise TypeError(message)
        if type(self.completed_units) is not int:
            message = "completed_units must be an integer"
            raise TypeError(message)
        if not 0 <= self.completed_units <= 1:
            message = "a live OpSi step may complete at most one safe unit"
            raise ValueError(message)
        if self.status is WorldTaskStatus.IN_PROGRESS and self.completed_units != 1:
            message = "an in-progress live OpSi step must confirm exactly one safe unit"
            raise ValueError(message)
        self._validate_retry()

    def _validate_retry(self) -> None:
        if self.retry_at is not None:
            _validate_aware(self.retry_at, field_name="retry_at")
        if self.retry_after is not None:
            if not isinstance(self.retry_after, timedelta):
                message = "retry_after must be a timedelta"
                raise TypeError(message)
            if self.retry_after <= timedelta():
                message = "retry_after must be positive"
                raise ValueError(message)
        if self.retry_at is not None and self.retry_after is not None:
            message = "retry_at and retry_after are mutually exclusive"
            raise ValueError(message)


class OpsiLiveStepDriver(Protocol):
    def execute_step(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSignal,
    ) -> LiveOpsiStep: ...


class OpsiWorldScheduleSource(Protocol):
    def snapshot(self, observed_at: datetime) -> WorldSchedule:
        """返回 observed_at 之后的 WorldSchedule。"""


class OpsiLiveClock(Protocol):
    def now(self) -> datetime: ...


class SystemOpsiLiveClock(OpsiLiveClock):
    @override
    def now(self) -> datetime:
        return datetime.now().astimezone()


class LiveOperationSirenWorkflow(OperationSirenWorkflow):
    """把 live step evidence 翻译成纯领域 report。"""

    __slots__ = ("_clock", "_driver", "_schedule_source")

    def __init__(
        self,
        driver: OpsiLiveStepDriver,
        schedule_source: OpsiWorldScheduleSource,
        clock: OpsiLiveClock | None = None,
    ) -> None:
        for value, method_name, field_name in (
            (driver, "execute_step", "driver"),
            (schedule_source, "snapshot", "schedule_source"),
            (clock or SystemOpsiLiveClock(), "now", "clock"),
        ):
            if isinstance(value, type) or not callable(getattr(value, method_name, None)):
                message = f"{field_name} must implement {method_name}()"
                raise TypeError(message)
        self._driver = driver
        self._schedule_source = schedule_source
        self._clock = clock or SystemOpsiLiveClock()

    @override
    def execute(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSignal,
        preemption: PreemptionRequest,
    ) -> WorldTaskReport:
        cancellation.raise_if_requested()
        step = self._driver.execute_step(spec, progress, cancellation)
        cancellation.raise_if_requested()
        if not isinstance(step, LiveOpsiStep):
            message = "OpsiLiveStepDriver.execute_step() must return LiveOpsiStep"
            raise TypeError(message)
        if step.operation is not spec.operation:
            message = "live OpSi step operation must match WorldTaskSpec"
            raise ValueError(message)
        if spec.checkpoint_mode is WorldCheckpointMode.ONE_SHOT and step.status is WorldTaskStatus.IN_PROGRESS:
            message = f"one-shot operation cannot expose partial progress: {spec.operation.value}"
            raise ValueError(message)

        observed_at = self._clock.now()
        _validate_aware(observed_at, field_name="observed_at")
        retry_at = step.retry_at
        if step.retry_after is not None:
            retry_at = observed_at + step.retry_after
        status = step.status
        if (
            preemption.is_requested
            and spec.checkpoint_mode is WorldCheckpointMode.BOUNDED
            and status is WorldTaskStatus.IN_PROGRESS
        ):
            status = WorldTaskStatus.PREEMPTED
        schedule = self._schedule_source.snapshot(observed_at)
        return WorldTaskReport(
            observed_at=observed_at,
            status=status,
            schedule=schedule,
            completed_units=step.completed_units,
            retry_at=retry_at,
            affected_task_ids=step.affected_task_ids,
            has_surplus_yellow_coins=step.has_surplus_yellow_coins,
            exploration_in_progress=step.exploration_in_progress,
            cursor=step.cursor,
        )
