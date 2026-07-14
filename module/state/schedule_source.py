from typing import override

from module.application.identifiers import TaskId
from module.application.scheduler import ScheduleItem, ScheduleSource
from module.state.store import SQLiteStateStore


class SQLiteScheduleSource(ScheduleSource):
    """把 SQLite schedule snapshot 严格投影为 application 调度输入。"""

    __slots__ = ("_store",)

    def __init__(self, store: SQLiteStateStore) -> None:
        if not isinstance(store, SQLiteStateStore):
            message = "store must be a SQLiteStateStore"
            raise TypeError(message)
        self._store = store

    @override
    def list_items(self) -> tuple[ScheduleItem, ...]:
        return tuple(
            ScheduleItem(
                task_id=TaskId(record.task_id),
                enabled=record.enabled,
                due_at=record.due_at,
                priority=record.priority,
            )
            for record in self._store.list_schedules()
        )
