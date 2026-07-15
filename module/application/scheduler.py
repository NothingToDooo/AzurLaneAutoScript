from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from module.application.identifiers import TaskId

if TYPE_CHECKING:
    from collections.abc import Iterable


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def _validate_hoard_window(value: timedelta) -> None:
    if not isinstance(value, timedelta):
        message = "hoard_window must be a timedelta"
        raise TypeError(message)
    if value < timedelta(0):
        message = "hoard_window must not be negative"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class ScheduleItem:
    task_id: TaskId
    enabled: bool
    due_at: datetime | None
    priority: int

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, TaskId):
            message = "task_id must be a TaskId"
            raise TypeError(message)
        if type(self.enabled) is not bool:
            message = "enabled must be a bool"
            raise TypeError(message)
        if self.due_at is None:
            if self.enabled:
                message = f"enabled schedule must have due_at: {self.task_id.value}"
                raise ValueError(message)
        else:
            _validate_aware_datetime(self.due_at, field_name="due_at")
        if type(self.priority) is not int:
            message = "priority must be an integer"
            raise TypeError(message)
        if self.priority < 0:
            message = "priority must not be negative"
            raise ValueError(message)


class SchedulerDecision(StrEnum):
    READY = "ready"
    WAITING = "waiting"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class SchedulerSelection:
    decision: SchedulerDecision
    item: ScheduleItem | None
    wake_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, SchedulerDecision):
            message = "decision must be a SchedulerDecision"
            raise TypeError(message)
        if self.decision is SchedulerDecision.EMPTY:
            if self.item is not None or self.wake_at is not None:
                message = "empty selection must not contain item or wake_at"
                raise ValueError(message)
            return
        if not isinstance(self.item, ScheduleItem) or not self.item.enabled:
            message = "ready or waiting selection requires an enabled ScheduleItem"
            raise ValueError(message)
        if self.decision is SchedulerDecision.READY:
            if self.wake_at is not None:
                message = "ready selection must not contain wake_at"
                raise ValueError(message)
            return
        if self.wake_at is None:
            message = "waiting selection requires wake_at"
            raise ValueError(message)
        _validate_aware_datetime(self.wake_at, field_name="wake_at")
        due_at = self.item.due_at
        if due_at is None or self.wake_at < due_at:
            message = "waiting wake_at must not precede item due_at"
            raise ValueError(message)


def order_schedule_items(
    items: Iterable[ScheduleItem],
    *,
    now: datetime,
) -> tuple[tuple[ScheduleItem, ...], tuple[ScheduleItem, ...]]:
    """按运行时 scheduler 的规则返回已到期和等待中的任务。"""
    _validate_aware_datetime(now, field_name="now")
    active: list[tuple[ScheduleItem, datetime]] = []
    for item in items:
        if not isinstance(item, ScheduleItem):
            message = "items must contain ScheduleItem instances"
            raise TypeError(message)
        if not item.enabled:
            continue
        due_at = item.due_at
        if due_at is None:
            message = f"enabled schedule must have due_at: {item.task_id.value}"
            raise ValueError(message)
        active.append((item, due_at))

    ready = tuple(
        item
        for item, due_at in sorted(
            (pair for pair in active if pair[1] <= now),
            key=lambda pair: (pair[0].priority, pair[1], pair[0].task_id.value),
        )
    )
    waiting = tuple(
        item
        for item, due_at in sorted(
            (pair for pair in active if pair[1] > now),
            key=lambda pair: (pair[1], pair[0].priority, pair[0].task_id.value),
        )
    )
    return ready, waiting


class SchedulePlanner:
    @staticmethod
    def select(
        items: Iterable[ScheduleItem],
        *,
        now: datetime,
        hoard_window: timedelta,
    ) -> SchedulerSelection:
        _validate_aware_datetime(now, field_name="now")
        _validate_hoard_window(hoard_window)
        ready, waiting = order_schedule_items(items, now=now)
        if ready:
            item = ready[0]
            return SchedulerSelection(decision=SchedulerDecision.READY, item=item, wake_at=None)
        if waiting:
            item = waiting[0]
            due_at = item.due_at
            if due_at is None:
                message = f"enabled schedule must have due_at: {item.task_id.value}"
                raise ValueError(message)
            return SchedulerSelection(
                decision=SchedulerDecision.WAITING,
                item=item,
                wake_at=due_at + hoard_window,
            )
        return SchedulerSelection(decision=SchedulerDecision.EMPTY, item=None, wake_at=None)


class ScheduleSource(Protocol):
    def list_items(self) -> tuple[ScheduleItem, ...]: ...


class Scheduler:
    __slots__ = ("_hoard_window", "_source")

    def __init__(self, source: ScheduleSource, *, hoard_window: timedelta) -> None:
        _validate_hoard_window(hoard_window)
        self._source = source
        self._hoard_window = hoard_window

    def next(self, now: datetime) -> SchedulerSelection:
        return SchedulePlanner.select(
            self._source.list_items(),
            now=now,
            hoard_window=self._hoard_window,
        )
