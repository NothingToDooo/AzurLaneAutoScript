from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, override

import pytest

from module.runtime import (
    OutboxDispatcher,
    OutboxDispatchError,
    OutboxLoadError,
    OutboxRetryPolicy,
    PermanentOutboxPublishError,
)
from module.state import OutboxClaimRequest, OutboxFailureUpdate, OutboxRecord

if TYPE_CHECKING:
    from module.state import JsonValue

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)


def _record(message_id: str, *, sequence: int, offset: int = 0) -> OutboxRecord:
    created_at = _NOW + timedelta(seconds=offset)
    return OutboxRecord(
        sequence=sequence,
        message_id=message_id,
        run_id=f"run-{message_id}",
        topic="app.restart.requested",
        payload={"reason": message_id},
        key="instance-a",
        created_at=created_at,
        available_at=_NOW,
        attempt_count=0,
        last_attempt_at=None,
        last_error_type=None,
        claim_token=None,
        claim_until=None,
        published_at=None,
        discarded_at=None,
    )


class _Store:
    def __init__(self, records: tuple[OutboxRecord, ...]) -> None:
        self.records = list(records)
        self.claim_limits: list[int] = []

    def claim_ready_outbox(self, request: OutboxClaimRequest) -> tuple[OutboxRecord, ...]:
        self.claim_limits.append(request.limit)
        selected: list[OutboxRecord] = []
        for index, record in enumerate(self.records):
            if len(selected) >= request.limit:
                break
            is_claimable = record.claim_until is None or record.claim_until <= request.claimed_at
            if (
                record.published_at is not None
                or record.discarded_at is not None
                or record.available_at > request.claimed_at
                or not is_claimable
            ):
                continue
            claimed = replace(record, claim_token=request.claim_token, claim_until=request.claim_until)
            self.records[index] = claimed
            selected.append(claimed)
        return tuple(selected)

    def mark_outbox_published(
        self,
        message_id: str,
        published_at: datetime,
        *,
        claim_token: str,
        expected_attempt_count: int,
    ) -> OutboxRecord:
        index = self._claimed_index(message_id, claim_token, expected_attempt_count)
        confirmed = replace(
            self.records[index],
            attempt_count=expected_attempt_count + 1,
            last_attempt_at=published_at,
            claim_token=None,
            claim_until=None,
            published_at=published_at,
        )
        self.records[index] = confirmed
        return confirmed

    def record_outbox_failure(self, update: OutboxFailureUpdate) -> OutboxRecord:
        index = self._claimed_index(update.message_id, update.claim_token, update.expected_attempt_count)
        is_discarded = update.available_at is None
        confirmed = replace(
            self.records[index],
            attempt_count=update.expected_attempt_count + 1,
            available_at=update.failed_at if is_discarded else update.available_at,
            last_attempt_at=update.failed_at,
            last_error_type=update.error_type,
            claim_token=None,
            claim_until=None,
            discarded_at=update.failed_at if is_discarded else None,
        )
        self.records[index] = confirmed
        return confirmed

    def pending(self) -> tuple[OutboxRecord, ...]:
        return tuple(record for record in self.records if record.published_at is None and record.discarded_at is None)

    def _claimed_index(self, message_id: str, claim_token: str, attempt_count: int) -> int:
        return next(
            index
            for index, record in enumerate(self.records)
            if record.message_id == message_id
            and record.claim_token == claim_token
            and record.attempt_count == attempt_count
        )


class _Publisher:
    def __init__(self, failures: dict[str, Exception] | None = None) -> None:
        self.failures = {} if failures is None else failures
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
        failure = self.failures.get(idempotency_key)
        if failure is not None:
            raise failure


class _Clock:
    def __init__(self, now: datetime = _NOW) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


def test_dispatches_in_sequence_order_with_message_id_as_idempotency_key() -> None:
    store = _Store((_record("first", sequence=1), _record("second", sequence=2, offset=1)))
    publisher = _Publisher()

    result = OutboxDispatcher(store=store, publisher=publisher, clock=_Clock()).dispatch_pending()

    assert result.published_message_ids == ("first", "second")
    assert result.failures == ()
    assert result.published_count == 2
    assert [call[3] for call in publisher.calls] == ["first", "second"]
    assert store.pending() == ()


def test_publish_failure_is_persisted_and_does_not_block_later_messages() -> None:
    store = _Store(
        (
            _record("first", sequence=1),
            _record("poison", sequence=2, offset=1),
            _record("third", sequence=3, offset=2),
        )
    )
    publisher = _Publisher({"poison": RuntimeError("broker password=secret")})

    result = OutboxDispatcher(store=store, publisher=publisher, clock=_Clock()).dispatch_pending()

    assert result.published_message_ids == ("first", "third")
    assert result.failure_count == 1
    assert result.failures[0].message_id == "poison"
    assert result.failures[0].error_type == "RuntimeError"
    assert result.failures[0].available_at == _NOW + timedelta(minutes=1)
    assert not result.failures[0].is_discarded
    assert [call[3] for call in publisher.calls] == ["first", "poison", "third"]
    assert tuple(record.message_id for record in store.pending()) == ("poison",)
    assert "secret" not in repr(result.failures[0])


def test_exponential_backoff_becomes_dead_letter_at_max_attempts() -> None:
    store = _Store((_record("retry", sequence=1),))
    publisher = _Publisher({"retry": RuntimeError("offline")})
    clock = _Clock()
    policy = OutboxRetryPolicy(
        batch_size=1,
        max_attempts=3,
        initial_delay=timedelta(minutes=1),
        maximum_delay=timedelta(minutes=10),
    )
    dispatcher = OutboxDispatcher(store=store, publisher=publisher, clock=clock, retry_policy=policy)

    first = dispatcher.dispatch_pending().failures[0]
    assert first.available_at == _NOW + timedelta(minutes=1)

    assert dispatcher.dispatch_pending().failure_count == 0
    clock.current = first.available_at
    second = dispatcher.dispatch_pending().failures[0]
    assert second.available_at == _NOW + timedelta(minutes=3)

    clock.current = second.available_at
    third = dispatcher.dispatch_pending().failures[0]
    assert third.attempt_count == 3
    assert third.is_discarded
    assert store.pending() == ()


def test_permanent_publish_error_is_dead_lettered_on_first_attempt() -> None:
    store = _Store((_record("invalid", sequence=1),))
    publisher = _Publisher({"invalid": PermanentOutboxPublishError("invalid payload with secret")})

    failure = OutboxDispatcher(store=store, publisher=publisher, clock=_Clock()).dispatch_pending().failures[0]

    assert failure.attempt_count == 1
    assert failure.error_type == "PermanentOutboxPublishError"
    assert failure.is_discarded
    assert store.pending() == ()


def test_ready_query_failure_is_translated_without_exposing_store_error() -> None:
    class _FailingStore(_Store):
        @override
        def claim_ready_outbox(self, request: OutboxClaimRequest) -> tuple[OutboxRecord, ...]:
            del request
            message = "database-password=secret"
            raise RuntimeError(message)

    with pytest.raises(OutboxLoadError, match="failed to load ready outbox messages") as raised:
        OutboxDispatcher(store=_FailingStore(()), publisher=_Publisher(), clock=_Clock()).dispatch_pending()

    assert raised.value.__cause__ is None
    assert "secret" not in str(raised.value)


def test_clock_contract_error_is_not_misreported_as_a_store_load_failure() -> None:
    class _NaiveClock(_Clock):
        @override
        def now(self) -> datetime:
            return _NOW.replace(tzinfo=None)

    with pytest.raises(ValueError, match=r"OutboxClock\.now\(\) must be timezone-aware"):
        OutboxDispatcher(store=_Store(()), publisher=_Publisher(), clock=_NaiveClock()).dispatch_pending()


def test_state_confirmation_failure_raises_safe_error_without_cause_text() -> None:
    class _FailingStore(_Store):
        @override
        def mark_outbox_published(
            self,
            message_id: str,
            published_at: datetime,
            *,
            claim_token: str,
            expected_attempt_count: int,
        ) -> OutboxRecord:
            del message_id, published_at, claim_token, expected_attempt_count
            message = "database-password=secret"
            raise RuntimeError(message)

    with pytest.raises(
        OutboxDispatchError,
        match=r"message 'first'.*topic 'app\.restart\.requested'",
    ) as raised:
        OutboxDispatcher(
            store=_FailingStore((_record("first", sequence=1),)),
            publisher=_Publisher(),
            clock=_Clock(),
        ).dispatch_pending()

    assert raised.value.__cause__ is None
    assert raised.value.message_id == "first"
    assert "secret" not in str(raised.value)


def test_retry_policy_bounds_each_claimed_batch() -> None:
    store = _Store((_record("first", sequence=1), _record("second", sequence=2)))
    policy = OutboxRetryPolicy(batch_size=1)

    result = OutboxDispatcher(
        store=store,
        publisher=_Publisher(),
        clock=_Clock(),
        retry_policy=policy,
    ).dispatch_pending()

    assert result.published_message_ids == ("first",)
    assert store.claim_limits == [1]
    assert tuple(record.message_id for record in store.pending()) == ("second",)
