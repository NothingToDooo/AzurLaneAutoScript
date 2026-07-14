from __future__ import annotations

import smtplib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, cast

import pytest

from module.application import OperatorNotificationKind
from module.notify import (
    DisabledNotificationConfig,
    NotificationDeliveryState,
    NotificationFailureKind,
    NotificationIntentConflictError,
    NotificationIntentDraft,
    NotificationIntentSource,
    NotificationIntentState,
    NotificationSpool,
    NotificationSpoolPolicy,
    NotificationSpoolStore,
    NotificationStateTransitionError,
    SmtpNotificationConfig,
    SmtpTransport,
    notification_delivery_id,
    notification_intent_id,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True)
class _Clock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


class _Sender:
    def __init__(self, outcomes: dict[str, list[Exception | None]] | None = None) -> None:
        self.outcomes = {} if outcomes is None else outcomes
        self.calls: list[tuple[str, str, str, str]] = []

    def send(
        self,
        *,
        recipient: str,
        title: str,
        content: str,
        idempotency_key: str,
    ) -> None:
        self.calls.append((recipient, title, content, idempotency_key))
        outcomes = self.outcomes.get(recipient, [])
        if outcomes:
            outcome = outcomes.pop(0)
            if outcome is not None:
                raise outcome


def _smtp_config(*recipients: str) -> SmtpNotificationConfig:
    return SmtpNotificationConfig(
        host="smtp.example.com",
        user="alas@example.com",
        password=f"credential-{id(recipients)}",
        recipients=tuple(recipients),
        port=465,
        transport=SmtpTransport.IMPLICIT_TLS,
    )


_SOURCE_ID = "source-message-1"
_INTENT_ID = notification_intent_id(
    source=NotificationIntentSource.INSTANCE_OUTBOX,
    instance_name="alas",
    source_id=_SOURCE_ID,
)


def _draft() -> NotificationIntentDraft:
    return NotificationIntentDraft(
        intent_id=_INTENT_ID,
        instance_name="alas",
        source=NotificationIntentSource.INSTANCE_OUTBOX,
        source_id=_SOURCE_ID,
        kind=OperatorNotificationKind.RUN_FAULTED,
        subject="Alas <alas> crashed",
        body="<alas> RuntimeError",
    )


def _claim(label: str) -> str:
    return f"claim-{sha256(label.encode()).hexdigest()}"


def _open_spool_concurrently(path: Path, *, workers: int = 8) -> tuple[int, ...]:
    barrier = threading.Barrier(workers)

    def open_store() -> int:
        barrier.wait()
        with NotificationSpoolStore(path) as store:
            return store.schema_version

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return tuple(pool.map(lambda _index: open_store(), range(workers)))


def _plan(
    store: NotificationSpoolStore,
    *,
    now: datetime,
    recipients: tuple[str, ...],
) -> None:
    claimed = store.claim_due_intents(
        due_at=now,
        limit=1,
        claim_token=_claim("plan"),
        claim_until=now + timedelta(minutes=5),
    )
    assert len(claimed) == 1
    store.plan_intent(
        claimed[0].intent_id,
        recipients,
        claim_token=_claim("plan"),
        planned_at=now,
    )


def test_spool_persists_idempotent_intent_and_stable_per_recipient_deliveries(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    path = tmp_path / "notification-spool.sqlite3"
    with NotificationSpoolStore(path) as store:
        first = store.enqueue_intent(_draft(), created_at=now)
        replay = store.enqueue_intent(_draft(), created_at=now + timedelta(hours=1))

        assert replay == first
        assert store.schema_version == 1
        assert store.journal_mode == "wal"
        with pytest.raises(NotificationIntentConflictError, match="different content"):
            store.enqueue_intent(
                NotificationIntentDraft(
                    intent_id=_INTENT_ID,
                    instance_name="alas",
                    source=NotificationIntentSource.INSTANCE_OUTBOX,
                    source_id=_SOURCE_ID,
                    kind=OperatorNotificationKind.RUN_FAULTED,
                    subject="Alas <alas> crashed",
                    body="<alas> DifferentError",
                ),
                created_at=now,
            )

        _plan(store, now=now, recipients=("first@example.com", "second@example.com"))
        deliveries = store.list_deliveries(intent_id=_INTENT_ID)

    assert tuple(delivery.delivery_id for delivery in deliveries) == (
        notification_delivery_id(_INTENT_ID, "first@example.com"),
        notification_delivery_id(_INTENT_ID, "second@example.com"),
    )
    assert all(delivery.state is NotificationDeliveryState.PENDING for delivery in deliveries)


def test_concurrent_openers_initialize_and_reopen_one_notification_spool(tmp_path: Path) -> None:
    path = tmp_path / "concurrent-notification-spool.sqlite3"

    assert _open_spool_concurrently(path) == (1,) * 8
    assert _open_spool_concurrently(path) == (1,) * 8


def test_planning_claim_is_exclusive_and_expired_claim_can_be_recovered(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    path = tmp_path / "notification-spool.sqlite3"
    with NotificationSpoolStore(path) as first_store, NotificationSpoolStore(path) as second_store:
        first_store.enqueue_intent(_draft(), created_at=now)
        first_claim = first_store.claim_due_intents(
            due_at=now,
            limit=1,
            claim_token=_claim("first-plan"),
            claim_until=now + timedelta(minutes=5),
        )

        assert len(first_claim) == 1
        assert (
            second_store.claim_due_intents(
                due_at=now + timedelta(minutes=1),
                limit=1,
                claim_token=_claim("second-plan"),
                claim_until=now + timedelta(minutes=6),
            )
            == ()
        )
        recovered = second_store.claim_due_intents(
            due_at=now + timedelta(minutes=5),
            limit=1,
            claim_token=_claim("second-plan"),
            claim_until=now + timedelta(minutes=10),
        )

        assert len(recovered) == 1
        assert recovered[0].plan_claim_token == _claim("second-plan")
        with pytest.raises(NotificationStateTransitionError, match="planning claim"):
            first_store.defer_intent(
                _INTENT_ID,
                claim_token=_claim("first-plan"),
                attempted_at=now + timedelta(minutes=5),
                next_attempt_at=now + timedelta(minutes=6),
                failure_kind=NotificationFailureKind.CONFIGURATION,
            )
        deferred = second_store.defer_intent(
            _INTENT_ID,
            claim_token=_claim("second-plan"),
            attempted_at=now + timedelta(minutes=5),
            next_attempt_at=now + timedelta(minutes=6),
            failure_kind=NotificationFailureKind.CONFIGURATION,
        )

    assert deferred.plan_attempt_count == 1
    assert deferred.plan_claim_token is None


def test_delivery_claim_is_exclusive_and_expired_claim_can_be_recovered(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    path = tmp_path / "notification-spool.sqlite3"
    with NotificationSpoolStore(path) as first_store, NotificationSpoolStore(path) as second_store:
        first_store.enqueue_intent(_draft(), created_at=now)
        _plan(first_store, now=now, recipients=("operator@example.com",))
        first_claim = first_store.claim_due_deliveries(
            due_at=now,
            limit=1,
            claim_token=_claim("first-delivery"),
            claim_until=now + timedelta(minutes=5),
        )

        assert len(first_claim) == 1
        assert (
            second_store.claim_due_deliveries(
                due_at=now + timedelta(minutes=1),
                limit=1,
                claim_token=_claim("second-delivery"),
                claim_until=now + timedelta(minutes=6),
            )
            == ()
        )
        recovered = second_store.claim_due_deliveries(
            due_at=now + timedelta(minutes=5),
            limit=1,
            claim_token=_claim("second-delivery"),
            claim_until=now + timedelta(minutes=10),
        )

        assert len(recovered) == 1
        with pytest.raises(NotificationStateTransitionError, match="another claim"):
            first_store.mark_delivered(
                recovered[0].delivery.delivery_id,
                claim_token=_claim("first-delivery"),
                delivered_at=now + timedelta(minutes=5),
            )
        delivered = second_store.mark_delivered(
            recovered[0].delivery.delivery_id,
            claim_token=_claim("second-delivery"),
            delivered_at=now + timedelta(minutes=5),
        )

    assert delivered.state is NotificationDeliveryState.DELIVERED
    assert delivered.attempt_count == 1


def test_partial_recipients_retry_and_dead_letter_independently_without_secret_persistence(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    clock = _Clock(now)
    path = tmp_path / "notification-spool.sqlite3"
    transient_server_text = b"temporary server detail must not persist"
    permanent_server_text = b"permanent server detail must not persist"
    sender = _Sender(
        {
            "second@example.com": [
                smtplib.SMTPRecipientsRefused({"second@example.com": (451, transient_server_text)}),
                None,
            ],
            "third@example.com": [smtplib.SMTPRecipientsRefused({"third@example.com": (550, permanent_server_text)})],
        }
    )
    with NotificationSpoolStore(path) as store:
        spool = NotificationSpool(
            store=store,
            config_source=lambda _instance: _smtp_config(
                "first@example.com",
                "second@example.com",
                "third@example.com",
            ),
            clock=clock,
            sender_factory=lambda _config: sender,
        )
        spool.enqueue_intent(_draft())

        result = spool.flush(max_intents=1, max_deliveries=3)
        deliveries = {delivery.recipient: delivery for delivery in store.list_deliveries(intent_id=_INTENT_ID)}

        assert result.planned_intents == 1
        assert result.delivered == 1
        assert result.retried == 1
        assert result.dead_lettered == 1
        assert deliveries["first@example.com"].state is NotificationDeliveryState.DELIVERED
        assert deliveries["second@example.com"].state is NotificationDeliveryState.PENDING
        assert deliveries["second@example.com"].last_failure_kind is NotificationFailureKind.SMTP_TRANSIENT
        assert deliveries["second@example.com"].smtp_status_code == 451
        assert deliveries["second@example.com"].next_attempt_at == now + timedelta(minutes=1)
        assert deliveries["third@example.com"].state is NotificationDeliveryState.DEAD_LETTER
        assert deliveries["third@example.com"].last_failure_kind is NotificationFailureKind.SMTP_PERMANENT
        assert deliveries["third@example.com"].smtp_status_code == 550

        clock.advance(timedelta(minutes=1))
        retry_result = spool.flush(max_intents=1, max_deliveries=1)
        retried = store.list_deliveries(intent_id=_INTENT_ID)[1]

    assert retry_result.delivered == 1
    assert retried.state is NotificationDeliveryState.DELIVERED
    assert retried.attempt_count == 2
    assert [call[0] for call in sender.calls].count("first@example.com") == 1
    persisted = path.read_bytes()
    for secret in (
        b"credential-",
        transient_server_text,
        permanent_server_text,
    ):
        assert secret not in persisted


def test_transient_failure_is_bounded_then_manual_retry_uses_injected_clock(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    clock = _Clock(now)
    sender = _Sender(
        {
            "operator@example.com": [
                OSError("network response must not persist"),
                OSError("network response must not persist"),
                None,
            ]
        }
    )
    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        spool = NotificationSpool(
            store=store,
            config_source=lambda _instance: _smtp_config("operator@example.com"),
            clock=clock,
            sender_factory=lambda _config: sender,
            policy=NotificationSpoolPolicy(max_attempts=2),
        )
        spool.enqueue_intent(_draft())

        first = spool.flush(max_intents=1, max_deliveries=1)
        clock.advance(timedelta(minutes=1))
        second = spool.flush(max_intents=1, max_deliveries=1)
        dead_letters = spool.list_dead_letters()

        assert first.retried == 1
        assert second.dead_lettered == 1
        assert len(dead_letters) == 1
        assert dead_letters[0].delivery.attempt_count == 2
        assert dead_letters[0].delivery.last_failure_kind is NotificationFailureKind.NETWORK

        spool.retry_delivery(dead_letters[0].delivery.delivery_id)
        requeued = store.list_deliveries(intent_id=_INTENT_ID)[0]
        assert requeued.state is NotificationDeliveryState.PENDING
        assert requeued.attempt_count == 2
        assert requeued.next_attempt_at == clock.current

        third = spool.flush(max_intents=1, max_deliveries=1)
        completed = store.list_deliveries(intent_id=_INTENT_ID)[0]

    assert third.delivered == 1
    assert completed.state is NotificationDeliveryState.DELIVERED
    assert completed.attempt_count == 3


def test_disabling_after_planning_suppresses_frozen_recipient_cohort(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    clock = _Clock(now)
    sender = _Sender()
    current_config: list[DisabledNotificationConfig | SmtpNotificationConfig] = [DisabledNotificationConfig()]
    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        store.enqueue_intent(_draft(), created_at=now)
        _plan(store, now=now, recipients=("operator@example.com",))
        spool = NotificationSpool(
            store=store,
            config_source=lambda _instance: current_config[0],
            clock=clock,
            sender_factory=lambda _config: sender,
        )

        suppressed = spool.flush(max_intents=1, max_deliveries=1)
        delivery = store.list_deliveries(intent_id=_INTENT_ID)[0]

        assert suppressed.suppressed_deliveries == 1
        assert delivery.state is NotificationDeliveryState.SUPPRESSED
        assert delivery.attempt_count == 0
        assert delivery.suppressed_at == now

        current_config[0] = _smtp_config("operator@example.com")
        retried = spool.flush(max_intents=1, max_deliveries=1)

    assert retried.delivered == 0
    assert sender.calls == []


def test_spool_context_closes_its_owned_store_idempotently(tmp_path: Path) -> None:
    store = NotificationSpoolStore(tmp_path / "notification-spool.sqlite3")
    with NotificationSpool(
        store=store,
        config_source=lambda _instance: DisabledNotificationConfig(),
        clock=_Clock(datetime(2026, 7, 14, tzinfo=UTC)),
    ) as spool:
        spool.enqueue_intent(_draft())

    spool.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        store.get_intent(_INTENT_ID)


def test_explicitly_disabled_unplanned_intent_is_terminally_suppressed(tmp_path: Path) -> None:
    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        spool = NotificationSpool(
            store=store,
            config_source=lambda _instance: DisabledNotificationConfig(),
            clock=_Clock(datetime(2026, 7, 14, tzinfo=UTC)),
        )
        spool.enqueue_intent(_draft())

        result = spool.flush(max_intents=1, max_deliveries=1)
        intent = store.get_intent(_INTENT_ID)
        deliveries = store.list_deliveries(intent_id=_INTENT_ID)

    assert result.suppressed_intents == 1
    assert intent is not None
    assert intent.state is NotificationIntentState.SUPPRESSED
    assert deliveries == ()


def test_spool_policy_rejects_wrong_runtime_types() -> None:
    invalid_attempts: object = True
    with pytest.raises(ValueError, match="retry_base must be a positive timedelta"):
        NotificationSpoolPolicy(retry_base=cast("timedelta", 60))
    with pytest.raises(ValueError, match="max_attempts must be a positive integer"):
        NotificationSpoolPolicy(max_attempts=cast("int", invalid_attempts))
