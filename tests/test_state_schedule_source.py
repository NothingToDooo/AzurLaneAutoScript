import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from module.application import Scheduler, SchedulerDecision, TaskId
from module.state import (
    CorruptStateError,
    ScheduleMutation,
    SQLiteScheduleSource,
    SQLiteStateStore,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)


def _seed_schedule(
    store: SQLiteStateStore,
    task_id: str,
    *,
    enabled: bool,
    due_at: datetime | None,
    priority: int,
) -> None:
    store.upsert_schedule(
        ScheduleMutation(task_id=task_id, enabled=enabled, due_at=due_at, priority=priority),
        updated_at=_NOW,
    )


def test_source_strictly_maps_records_in_store_order(tmp_path: Path) -> None:
    hong_kong = timezone(timedelta(hours=8))
    source_due_at = (_NOW + timedelta(hours=1)).astimezone(hong_kong)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        _seed_schedule(store, "z-task", enabled=True, due_at=source_due_at, priority=30)
        _seed_schedule(store, "a-task", enabled=False, due_at=None, priority=10)
        _seed_schedule(store, "middle-task", enabled=True, due_at=_NOW, priority=20)

        records = store.list_schedules()
        items = SQLiteScheduleSource(store).list_items()

        assert tuple(item.task_id for item in items) == (
            TaskId("a-task"),
            TaskId("middle-task"),
            TaskId("z-task"),
        )
        assert tuple((item.task_id.value, item.enabled, item.due_at, item.priority) for item in items) == tuple(
            (record.task_id, record.enabled, record.due_at, record.priority) for record in records
        )
        assert items[-1].due_at == records[-1].due_at
        assert items[-1].due_at is not None
        assert items[-1].due_at.tzinfo is UTC


def test_sqlite_scheduler_integration_selects_ready_and_ignores_disabled(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        _seed_schedule(store, "disabled-none", enabled=False, due_at=None, priority=0)
        _seed_schedule(store, "disabled-due", enabled=False, due_at=_NOW - timedelta(days=1), priority=0)
        _seed_schedule(store, "ready-lower", enabled=True, due_at=_NOW - timedelta(hours=1), priority=20)
        _seed_schedule(store, "ready-first", enabled=True, due_at=_NOW, priority=10)
        _seed_schedule(store, "future", enabled=True, due_at=_NOW + timedelta(hours=1), priority=0)
        scheduler = Scheduler(SQLiteScheduleSource(store), hoard_window=timedelta(minutes=5))

        selection = scheduler.next(_NOW)

        assert selection.decision is SchedulerDecision.READY
        assert selection.item is not None
        assert selection.item.task_id == TaskId("ready-first")
        assert selection.wake_at is None


def test_sqlite_scheduler_integration_selects_waiting_with_hoard_window(tmp_path: Path) -> None:
    earliest = _NOW + timedelta(minutes=10)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        _seed_schedule(store, "disabled-none", enabled=False, due_at=None, priority=0)
        _seed_schedule(store, "disabled-due", enabled=False, due_at=_NOW, priority=0)
        _seed_schedule(store, "later-low-priority", enabled=True, due_at=_NOW + timedelta(minutes=20), priority=0)
        _seed_schedule(store, "earliest", enabled=True, due_at=earliest, priority=50)
        scheduler = Scheduler(SQLiteScheduleSource(store), hoard_window=timedelta(minutes=3))

        selection = scheduler.next(_NOW)

        assert selection.decision is SchedulerDecision.WAITING
        assert selection.item is not None
        assert selection.item.task_id == TaskId("earliest")
        assert selection.wake_at == earliest + timedelta(minutes=3)


def test_sqlite_scheduler_integration_returns_empty_for_disabled_records(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        _seed_schedule(store, "disabled-none", enabled=False, due_at=None, priority=0)
        _seed_schedule(store, "disabled-due", enabled=False, due_at=_NOW, priority=1)
        scheduler = Scheduler(SQLiteScheduleSource(store), hoard_window=timedelta(0))

        selection = scheduler.next(_NOW)

        assert selection.decision is SchedulerDecision.EMPTY
        assert selection.item is None
        assert selection.wake_at is None


def test_source_does_not_fill_due_at_for_enabled_record(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        _seed_schedule(store, "invalid-enabled", enabled=True, due_at=None, priority=0)

        with pytest.raises(ValueError, match="enabled schedule must have due_at"):
            SQLiteScheduleSource(store).list_items()


def test_store_corruption_fails_before_source_mapping(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"
    with SQLiteStateStore(database_path) as store:
        _seed_schedule(store, "corrupt", enabled=True, due_at=_NOW, priority=0)
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute(
                "UPDATE schedule SET due_at = ? WHERE task_id = ?",
                ("2026-07-13T08:00:00", "corrupt"),
            )
            connection.commit()

        with pytest.raises(CorruptStateError, match=r"naive datetime in schedule\.due_at"):
            SQLiteScheduleSource(store).list_items()
