from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.runtime import OutboxDispatcher
from module.state import OutboxRecord

if TYPE_CHECKING:
    from module.state import JsonValue

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)


def _record(message_id: str, *, offset: int = 0) -> OutboxRecord:
    return OutboxRecord(
        message_id=message_id,
        run_id=f"run-{message_id}",
        topic="app.restart.requested",
        payload={"reason": message_id},
        key="instance-a",
        created_at=_NOW + timedelta(seconds=offset),
        published_at=None,
    )


class _Store:
    def __init__(self, records: tuple[OutboxRecord, ...]) -> None:
        self.records = list(records)
        self.marks: list[tuple[str, datetime]] = []

    def list_outbox(self, *, pending_only: bool = False) -> tuple[OutboxRecord, ...]:
        records = tuple(self.records)
        return tuple(record for record in records if record.published_at is None) if pending_only else records

    def mark_outbox_published(self, message_id: str, published_at: datetime) -> OutboxRecord:
        self.marks.append((message_id, published_at))
        index = next(index for index, record in enumerate(self.records) if record.message_id == message_id)
        confirmed = replace(self.records[index], published_at=published_at)
        self.records[index] = confirmed
        return confirmed


class _Publisher:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[tuple[str, JsonValue, str | None, str]] = []

    def publish(
        self,
        *,
        topic: str,
        payload: JsonValue,
        key: str | None,
        idempotency_key: str,
    ) -> None:
        self.calls.append((topic, payload, key, idempotency_key))
        if idempotency_key == self.fail_on:
            message = "broker unavailable"
            raise RuntimeError(message)


class _Clock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return _NOW + timedelta(minutes=self.calls)


def test_dispatches_in_store_order_with_message_id_as_idempotency_key() -> None:
    store = _Store((_record("first"), _record("second", offset=1)))
    publisher = _Publisher()

    result = OutboxDispatcher(store=store, publisher=publisher, clock=_Clock()).dispatch_pending()

    assert result.message_ids == ("first", "second")
    assert result.published_count == 2
    assert [call[3] for call in publisher.calls] == ["first", "second"]
    assert [mark[0] for mark in store.marks] == ["first", "second"]
    assert store.list_outbox(pending_only=True) == ()


def test_publish_failure_stops_ordered_delivery_and_leaves_message_pending() -> None:
    store = _Store((_record("first"), _record("second", offset=1), _record("third", offset=2)))
    publisher = _Publisher(fail_on="second")

    with pytest.raises(RuntimeError, match="broker unavailable"):
        OutboxDispatcher(store=store, publisher=publisher, clock=_Clock()).dispatch_pending()

    assert [call[3] for call in publisher.calls] == ["first", "second"]
    assert [mark[0] for mark in store.marks] == ["first"]
    assert [record.message_id for record in store.list_outbox(pending_only=True)] == ["second", "third"]


def test_limit_bounds_one_dispatch_batch() -> None:
    store = _Store((_record("first"), _record("second", offset=1)))
    publisher = _Publisher()

    result = OutboxDispatcher(store=store, publisher=publisher, clock=_Clock()).dispatch_pending(max_messages=1)

    assert result.message_ids == ("first",)
    assert [record.message_id for record in store.list_outbox(pending_only=True)] == ["second"]


@pytest.mark.parametrize("max_messages", [0, -1, 1.5, True])
def test_rejects_invalid_batch_limits(max_messages: object) -> None:
    dispatcher = OutboxDispatcher(store=_Store(()), publisher=_Publisher(), clock=_Clock())

    with pytest.raises(ValueError, match="positive integer"):
        dispatcher.dispatch_pending(max_messages=cast("int | None", max_messages))
