from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from typing import cast, override

import pytest

from module.application import (
    ScheduleItem,
    SchedulePlanner,
    Scheduler,
    SchedulerDecision,
    SchedulerSelection,
    ScheduleSource,
    TaskId,
    order_schedule_items,
)

_NOW = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)


def _set_attribute(instance: object, attribute: str, value: object) -> None:
    setattr(instance, attribute, value)


def _item(
    task_id: str,
    due_at: datetime | None,
    *,
    priority: int,
    enabled: bool = True,
) -> ScheduleItem:
    return ScheduleItem(task_id=TaskId(task_id), enabled=enabled, due_at=due_at, priority=priority)


class _StaticScheduleSource(ScheduleSource):
    def __init__(self, items: tuple[ScheduleItem, ...]) -> None:
        self.items = items
        self.calls = 0

    @override
    def list_items(self) -> tuple[ScheduleItem, ...]:
        self.calls += 1
        return self.items


def test_scheduler_decision_is_closed() -> None:
    assert tuple(decision.value for decision in SchedulerDecision) == ("ready", "waiting", "empty")


def test_schedule_item_is_immutable_and_validates_closed_fields() -> None:
    item = _item("daily", _NOW, priority=0)

    with pytest.raises(FrozenInstanceError):
        _set_attribute(item, "priority", 1)
    with pytest.raises(TypeError, match="task_id"):
        ScheduleItem(task_id=cast("TaskId", "daily"), enabled=True, due_at=_NOW, priority=0)
    with pytest.raises(TypeError, match="enabled"):
        ScheduleItem(task_id=TaskId("daily"), enabled=cast("bool", 1), due_at=_NOW, priority=0)
    with pytest.raises(ValueError, match="must have due_at"):
        _item("daily", None, priority=0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _item("daily", _NOW.replace(tzinfo=None), priority=0)
    with pytest.raises(TypeError, match="priority"):
        _item("daily", _NOW, priority=cast("int", 1.5))
    with pytest.raises(ValueError, match="priority"):
        _item("daily", _NOW, priority=-1)


def test_ready_includes_boundary_and_uses_priority_due_at_task_id_order() -> None:
    earliest = _NOW - timedelta(hours=2)
    selection = SchedulePlanner.select(
        iter(
            (
                _item("priority-two", _NOW - timedelta(hours=3), priority=2),
                _item("z-task", earliest, priority=1),
                _item("a-task", earliest, priority=1),
                _item("later", _NOW, priority=1),
            )
        ),
        now=_NOW,
        hoard_window=timedelta(minutes=5),
    )

    assert selection == SchedulerSelection(
        decision=SchedulerDecision.READY,
        item=_item("a-task", earliest, priority=1),
        wake_at=None,
    )


def test_order_schedule_items_exposes_the_same_ready_and_waiting_order() -> None:
    ready, waiting = order_schedule_items(
        (
            _item("waiting-later", _NOW + timedelta(minutes=2), priority=0),
            _item("ready-low", _NOW - timedelta(minutes=1), priority=2),
            _item("waiting-first", _NOW + timedelta(minutes=1), priority=5),
            _item("ready-high", _NOW, priority=1),
        ),
        now=_NOW,
    )

    assert [item.task_id.value for item in ready] == ["ready-high", "ready-low"]
    assert [item.task_id.value for item in waiting] == ["waiting-first", "waiting-later"]


def test_aware_datetimes_compare_by_instant_at_ready_boundary() -> None:
    hong_kong = timezone(timedelta(hours=8))
    due_at = _NOW.astimezone(hong_kong)

    selection = SchedulePlanner.select(
        (_item("cross-zone", due_at, priority=0),),
        now=_NOW,
        hoard_window=timedelta(0),
    )

    assert selection.decision is SchedulerDecision.READY
    assert selection.item is not None
    assert selection.item.task_id == TaskId("cross-zone")


def test_waiting_uses_due_at_priority_task_id_order_and_hoards() -> None:
    earliest = _NOW + timedelta(minutes=10)
    selection = SchedulePlanner.select(
        (
            _item("later-low-priority", _NOW + timedelta(minutes=20), priority=0),
            _item("earliest-high-priority", earliest, priority=5),
            _item("z-task", earliest, priority=1),
            _item("a-task", earliest, priority=1),
        ),
        now=_NOW,
        hoard_window=timedelta(minutes=3),
    )

    assert selection.decision is SchedulerDecision.WAITING
    assert selection.item == _item("a-task", earliest, priority=1)
    assert selection.wake_at == earliest + timedelta(minutes=3)


@pytest.mark.parametrize(
    "items",
    [
        (),
        (
            _item("disabled-unscheduled", None, priority=0, enabled=False),
            _item("disabled-scheduled", _NOW, priority=1, enabled=False),
        ),
    ],
)
def test_no_enabled_items_returns_empty(items: tuple[ScheduleItem, ...]) -> None:
    selection = SchedulePlanner.select(items, now=_NOW, hoard_window=timedelta(0))

    assert selection == SchedulerSelection(decision=SchedulerDecision.EMPTY, item=None, wake_at=None)


def test_planner_rejects_naive_now_and_negative_hoard_window() -> None:
    item = _item("daily", _NOW, priority=0)

    with pytest.raises(ValueError, match="now must be timezone-aware"):
        SchedulePlanner.select((item,), now=_NOW.replace(tzinfo=None), hoard_window=timedelta(0))
    with pytest.raises(TypeError, match="hoard_window must be a timedelta"):
        SchedulePlanner.select((item,), now=_NOW, hoard_window=cast("timedelta", 0))
    with pytest.raises(ValueError, match="hoard_window must not be negative"):
        SchedulePlanner.select((item,), now=_NOW, hoard_window=-timedelta(microseconds=1))


def test_scheduler_composes_source_with_stored_hoard_window() -> None:
    due_at = _NOW + timedelta(minutes=5)
    source = _StaticScheduleSource((_item("research", due_at, priority=10),))
    scheduler = Scheduler(source, hoard_window=timedelta(minutes=2))

    selection = scheduler.next(_NOW)

    assert selection.decision is SchedulerDecision.WAITING
    assert selection.item == _item("research", due_at, priority=10)
    assert selection.wake_at == due_at + timedelta(minutes=2)
    assert source.calls == 1


def test_scheduler_rejects_negative_hoard_window_at_construction() -> None:
    source = _StaticScheduleSource(())

    with pytest.raises(ValueError, match="hoard_window must not be negative"):
        Scheduler(source, hoard_window=-timedelta(seconds=1))
