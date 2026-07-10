from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

NAIVE_CLOCK_MESSAGE = "now must be a naive local datetime"

type ScheduleState = Literal["ready", "waiting", "error", "empty"]


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    enable: bool
    command: str
    next_run: object


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    state: ScheduleState
    entry: ScheduleEntry | None
    wake_at: datetime | None
    pending: tuple[ScheduleEntry, ...]
    waiting: tuple[ScheduleEntry, ...]
    errors: tuple[ScheduleEntry, ...]

    @property
    def command(self) -> str | None:
        return None if self.entry is None else self.entry.command


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _partition_entries(
    entries: Iterable[ScheduleEntry],
    *,
    now: datetime,
    priority: Mapping[str, int],
) -> tuple[list[ScheduleEntry], list[ScheduleEntry], list[ScheduleEntry]]:
    pending: list[ScheduleEntry] = []
    waiting: list[ScheduleEntry] = []
    errors: list[ScheduleEntry] = []
    for entry in entries:
        if not entry.enable or entry.command not in priority:
            continue
        if not isinstance(entry.next_run, datetime):
            errors.append(entry)
            continue
        if _is_aware(entry.next_run):
            message = f"next_run must be a naive local datetime: {entry.command}"
            raise ValueError(message)
        if entry.next_run < now:
            pending.append(entry)
        else:
            waiting.append(entry)
    return pending, waiting, errors


class SchedulePlanner:
    @staticmethod
    def select(
        entries: Iterable[ScheduleEntry],
        *,
        now: datetime,
        priority: Mapping[str, int],
    ) -> ScheduleDecision:
        if _is_aware(now):
            raise ValueError(NAIVE_CLOCK_MESSAGE)

        pending, waiting, errors = _partition_entries(entries, now=now, priority=priority)

        def priority_key(entry: ScheduleEntry) -> int:
            return priority[entry.command]

        errors.sort(key=priority_key)
        pending.sort(key=priority_key)
        waiting.sort(key=priority_key)
        waiting.sort(key=lambda entry: cast("datetime", entry.next_run))

        error_items = tuple(errors)
        pending_items = tuple(pending)
        waiting_items = tuple(waiting)
        if error_items:
            return ScheduleDecision(
                state="error",
                entry=error_items[0],
                wake_at=None,
                pending=pending_items,
                waiting=waiting_items,
                errors=error_items,
            )
        if pending_items:
            return ScheduleDecision(
                state="ready",
                entry=pending_items[0],
                wake_at=None,
                pending=pending_items,
                waiting=waiting_items,
                errors=(),
            )
        if waiting_items:
            entry = waiting_items[0]
            return ScheduleDecision(
                state="waiting",
                entry=entry,
                wake_at=cast("datetime", entry.next_run),
                pending=(),
                waiting=waiting_items,
                errors=(),
            )
        return ScheduleDecision(
            state="empty",
            entry=None,
            wake_at=None,
            pending=(),
            waiting=(),
            errors=(),
        )
