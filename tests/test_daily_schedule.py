from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, time, timedelta, timezone
from typing import cast

import pytest

from module.application import DailySchedule


def test_next_after_selects_the_next_trigger_and_returns_utc() -> None:
    schedule = DailySchedule("UTC", (time(4), time(12, 30), time(20)))

    assert schedule.next_after(datetime(2026, 7, 13, 4, tzinfo=UTC)) == datetime(2026, 7, 13, 12, 30, tzinfo=UTC)
    assert schedule.next_after(datetime(2026, 7, 13, 13, tzinfo=UTC)) == datetime(2026, 7, 13, 20, tzinfo=UTC)


def test_next_after_crosses_the_local_day_and_accepts_other_input_timezones() -> None:
    schedule = DailySchedule("Asia/Hong_Kong", (time(1, 15), time(8)))
    input_timezone = timezone(timedelta(hours=-4))

    assert schedule.next_after(datetime(2026, 7, 13, 9, tzinfo=input_timezone)) == datetime(
        2026, 7, 13, 17, 15, tzinfo=UTC
    )
    assert schedule.next_after(datetime(2026, 7, 13, 17, 15, tzinfo=UTC)) == datetime(2026, 7, 14, 0, tzinfo=UTC)


def test_next_after_skips_a_nonexistent_dst_wall_time() -> None:
    schedule = DailySchedule("America/New_York", (time(2, 30),))

    assert schedule.next_after(datetime(2026, 3, 8, 6, tzinfo=UTC)) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)


def test_next_after_includes_both_instants_of_an_ambiguous_dst_wall_time() -> None:
    schedule = DailySchedule("America/New_York", (time(1, 30),))

    first = schedule.next_after(datetime(2026, 11, 1, 5, tzinfo=UTC))
    assert first == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert schedule.next_after(first) == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def test_next_after_orders_multiple_ambiguous_triggers_by_utc_instant() -> None:
    schedule = DailySchedule("America/New_York", (time(1, 15), time(1, 45)))

    assert schedule.next_after(datetime(2026, 11, 1, 5, 20, tzinfo=UTC)) == datetime(2026, 11, 1, 5, 45, tzinfo=UTC)


@pytest.mark.parametrize(
    ("timezone_name", "triggers", "error_type", "match"),
    [
        ("Removed/Timezone", (time(4),), ValueError, "IANA timezone"),
        (" UTC", (time(4),), ValueError, "trimmed and non-empty"),
        ("UTC", (), ValueError, "must not be empty"),
        ("UTC", [time(4)], TypeError, "must be a tuple"),
        ("UTC", (time(4, tzinfo=UTC),), ValueError, "naive"),
        ("UTC", (time(4), time(4)), ValueError, "unique and sorted"),
        ("UTC", (time(12), time(4)), ValueError, "unique and sorted"),
        ("UTC", ("04:00",), TypeError, "datetime.time"),
    ],
)
def test_daily_schedule_rejects_invalid_definition(
    timezone_name: str,
    triggers: object,
    error_type: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error_type, match=match):
        DailySchedule(timezone_name, cast("tuple[time, ...]", triggers))


def test_daily_schedule_is_immutable() -> None:
    schedule = DailySchedule("UTC", (time(4),))

    with pytest.raises(FrozenInstanceError):
        setattr(schedule, "timezone_name", "Asia/Hong_Kong")  # ruff:ignore[set-attr-with-constant]


def test_next_after_rejects_naive_datetime() -> None:
    schedule = DailySchedule("UTC", (time(4),))

    with pytest.raises(ValueError, match="timezone-aware"):
        schedule.next_after(datetime(2026, 7, 13, 3))
