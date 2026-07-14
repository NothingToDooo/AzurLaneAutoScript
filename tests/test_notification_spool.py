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
from module.notify.spool_models import NotificationIntentRetry

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


def _create_v1_spool(path: Path, *, now: datetime) -> tuple[str, str]:
    planned_source_id = "source-message-2"
    planned_intent_id = notification_intent_id(
        source=NotificationIntentSource.INSTANCE_OUTBOX,
        instance_name="alas",
        source_id=planned_source_id,
    )
    delivery_id = notification_delivery_id(planned_intent_id, "operator@example.com")
    encoded_now = now.isoformat(timespec="microseconds")
    encoded_next = (now + timedelta(minutes=1)).isoformat(timespec="microseconds")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE notification_intents (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                intent_id TEXT NOT NULL UNIQUE,
                instance_name TEXT NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                state TEXT NOT NULL,
                plan_attempt_count INTEGER NOT NULL DEFAULT 0,
                next_plan_attempt_at TEXT,
                last_plan_failure_kind TEXT,
                plan_claim_token TEXT,
                plan_claim_until TEXT,
                created_at TEXT NOT NULL,
                planned_at TEXT,
                suppressed_at TEXT
            ) STRICT;
            CREATE TABLE notification_deliveries (
                delivery_id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL REFERENCES notification_intents(intent_id),
                recipient TEXT NOT NULL,
                state TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_failure_kind TEXT,
                smtp_status_code INTEGER,
                claim_token TEXT,
                claim_until TEXT,
                created_at TEXT NOT NULL,
                last_attempt_at TEXT,
                delivered_at TEXT,
                dead_lettered_at TEXT,
                suppressed_at TEXT,
                UNIQUE(intent_id, recipient)
            ) STRICT;
            CREATE INDEX notification_intents_due_idx
            ON notification_intents(state, next_plan_attempt_at, plan_claim_until, sequence);
            CREATE INDEX notification_deliveries_due_idx
            ON notification_deliveries(state, next_attempt_at, claim_until, intent_id);
            PRAGMA user_version = 1;
            """
        )
        connection.execute(
            """
            INSERT INTO notification_intents(
                intent_id, instance_name, source, source_id, kind, subject, body, state,
                plan_attempt_count, next_plan_attempt_at, last_plan_failure_kind, created_at
            ) VALUES (?, 'alas', 'instance_outbox', ?, 'run_faulted', ?, ?, 'unplanned', 1, ?, 'configuration', ?)
            """,
            (_INTENT_ID, _SOURCE_ID, "Alas <alas> crashed", "<alas> RuntimeError", encoded_next, encoded_now),
        )
        connection.execute(
            """
            INSERT INTO notification_intents(
                intent_id, instance_name, source, source_id, kind, subject, body, state,
                plan_attempt_count, next_plan_attempt_at, created_at, planned_at
            ) VALUES (?, 'alas', 'instance_outbox', ?, 'run_faulted', ?, ?, 'planned', 0, NULL, ?, ?)
            """,
            (
                planned_intent_id,
                planned_source_id,
                "Alas <alas> crashed",
                "<alas> OSError",
                encoded_now,
                encoded_now,
            ),
        )
        connection.execute(
            """
            INSERT INTO notification_deliveries(
                delivery_id, intent_id, recipient, state, attempt_count, next_attempt_at,
                last_failure_kind, smtp_status_code, created_at, last_attempt_at, dead_lettered_at
            ) VALUES (?, ?, 'operator@example.com', 'dead_letter', 2, NULL, 'network', NULL, ?, ?, ?)
            """,
            (delivery_id, planned_intent_id, encoded_now, encoded_now, encoded_now),
        )
    return planned_intent_id, delivery_id


def _schema_sql(path: Path) -> tuple[tuple[str, str, str], ...]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
    return tuple(cast("tuple[str, str, str]", row) for row in rows)


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


def test_intent_body_preserves_multiline_text_without_normalization() -> None:
    body = "first line\n  second line  \n"
    draft = NotificationIntentDraft(
        intent_id=_INTENT_ID,
        instance_name="alas",
        source=NotificationIntentSource.INSTANCE_OUTBOX,
        source_id=_SOURCE_ID,
        kind=OperatorNotificationKind.RUN_FAULTED,
        subject="Alas <alas> crashed",
        body=body,
    )

    assert draft.body == body
    with pytest.raises(ValueError, match="body must contain non-whitespace text"):
        NotificationIntentDraft(
            intent_id=_INTENT_ID,
            instance_name="alas",
            source=NotificationIntentSource.INSTANCE_OUTBOX,
            source_id=_SOURCE_ID,
            kind=OperatorNotificationKind.RUN_FAULTED,
            subject="Alas <alas> crashed",
            body=" \n ",
        )


def test_spool_persists_idempotent_intent_and_stable_per_recipient_deliveries(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    path = tmp_path / "notification-spool.sqlite3"
    with NotificationSpoolStore(path) as store:
        first = store.enqueue_intent(_draft(), created_at=now)
        replay = store.enqueue_intent(_draft(), created_at=now + timedelta(hours=1))

        assert replay == first
        assert store.schema_version == 2
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

    assert _open_spool_concurrently(path) == (2,) * 8
    assert _open_spool_concurrently(path) == (2,) * 8


def test_v1_spool_migrates_failure_audit_into_the_exact_v2_schema(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    migrated_path = tmp_path / "migrated.sqlite3"
    fresh_path = tmp_path / "fresh.sqlite3"
    _planned_intent_id, delivery_id = _create_v1_spool(migrated_path, now=now)

    with NotificationSpoolStore(migrated_path) as migrated:
        intent = migrated.get_intent(_INTENT_ID)
        deliveries = migrated.list_deliveries()

        assert migrated.schema_version == 2
        assert intent is not None
        assert intent.last_plan_failure_kind is NotificationFailureKind.CONFIGURATION
        assert intent.last_plan_error_type == "LegacyNotificationError"
        assert intent.last_plan_error_message == "(error message unavailable in schema v1)"
        assert len(deliveries) == 1
        assert deliveries[0].delivery_id == delivery_id
        assert deliveries[0].last_failure_kind is NotificationFailureKind.NETWORK
        assert deliveries[0].last_error_type == "LegacyNotificationError"
        assert deliveries[0].last_error_message == "(error message unavailable in schema v1)"

        requeued = migrated.retry_delivery(delivery_id, now=now + timedelta(minutes=1))
        assert requeued.state is NotificationDeliveryState.PENDING
        assert requeued.last_failure_kind is NotificationFailureKind.NETWORK
        assert requeued.last_error_type == "LegacyNotificationError"
        assert requeued.last_error_message == "(error message unavailable in schema v1)"

    with NotificationSpoolStore(fresh_path) as fresh:
        assert fresh.schema_version == 2

    assert _schema_sql(migrated_path) == _schema_sql(fresh_path)


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
                retry=NotificationIntentRetry(
                    attempted_at=now + timedelta(minutes=5),
                    next_attempt_at=now + timedelta(minutes=6),
                    failure_kind=NotificationFailureKind.CONFIGURATION,
                    error_type="RuntimeError",
                    error_message="first claim error",
                ),
            )
        deferred = second_store.defer_intent(
            _INTENT_ID,
            claim_token=_claim("second-plan"),
            retry=NotificationIntentRetry(
                attempted_at=now + timedelta(minutes=5),
                next_attempt_at=now + timedelta(minutes=6),
                failure_kind=NotificationFailureKind.CONFIGURATION,
                error_type="RuntimeError",
                error_message="second claim error",
            ),
        )

    assert deferred.plan_attempt_count == 1
    assert deferred.plan_claim_token is None
    assert deferred.last_plan_error_type == "RuntimeError"
    assert deferred.last_plan_error_message == "second claim error"


def test_planning_failure_persists_raw_error_and_success_clears_current_error(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    clock = _Clock(now)
    config_error = RuntimeError("configuration password=secret\nsecond line")
    current: list[RuntimeError | SmtpNotificationConfig] = [config_error]

    def config_source(_instance: str) -> SmtpNotificationConfig:
        value = current[0]
        if isinstance(value, RuntimeError):
            raise value
        return value

    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        spool = NotificationSpool(
            store=store,
            config_source=config_source,
            clock=clock,
            sender_factory=lambda _config: _Sender(),
        )
        spool.enqueue_intent(_draft())

        failed = spool.flush(max_intents=1, max_deliveries=1)
        deferred = store.get_intent(_INTENT_ID)

        assert failed.deferred_intents == 1
        assert deferred is not None
        assert deferred.last_plan_failure_kind is NotificationFailureKind.CONFIGURATION
        assert deferred.last_plan_error_type == "RuntimeError"
        assert deferred.last_plan_error_message == str(config_error)

        current[0] = _smtp_config("operator@example.com")
        clock.advance(timedelta(minutes=1))
        completed = spool.flush(max_intents=1, max_deliveries=1)
        planned = store.get_intent(_INTENT_ID)

    assert completed.planned_intents == 1
    assert completed.delivered == 1
    assert planned is not None
    assert planned.state is NotificationIntentState.PLANNED
    assert planned.last_plan_failure_kind is None
    assert planned.last_plan_error_type is None
    assert planned.last_plan_error_message is None


def test_wrong_config_type_is_persisted_as_an_explicit_type_error(tmp_path: Path) -> None:
    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        spool = NotificationSpool(
            store=store,
            config_source=lambda _instance: cast("SmtpNotificationConfig", object()),
            clock=_Clock(datetime(2026, 7, 14, tzinfo=UTC)),
        )
        spool.enqueue_intent(_draft())

        result = spool.flush(max_intents=1, max_deliveries=1)
        intent = store.get_intent(_INTENT_ID)

    assert result.deferred_intents == 1
    assert intent is not None
    assert intent.last_plan_error_type == "TypeError"
    assert intent.last_plan_error_message == (
        "config_source must return DisabledNotificationConfig or SmtpNotificationConfig, got object"
    )


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


def test_partial_recipients_persist_raw_failures_and_clear_them_after_success(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    clock = _Clock(now)
    path = tmp_path / "notification-spool.sqlite3"
    transient_server_text = b"temporary server detail password=transient"
    permanent_server_text = b"permanent server detail password=permanent\nsecond line"
    transient_error = smtplib.SMTPRecipientsRefused({"second@example.com": (451, transient_server_text)})
    permanent_error = smtplib.SMTPRecipientsRefused({"third@example.com": (550, permanent_server_text)})
    sender = _Sender(
        {
            "second@example.com": [
                transient_error,
                None,
            ],
            "third@example.com": [permanent_error],
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
        assert deliveries["first@example.com"].last_error_type is None
        assert deliveries["first@example.com"].last_error_message is None
        assert deliveries["second@example.com"].state is NotificationDeliveryState.PENDING
        assert deliveries["second@example.com"].last_failure_kind is NotificationFailureKind.SMTP_TRANSIENT
        assert deliveries["second@example.com"].smtp_status_code == 451
        assert deliveries["second@example.com"].last_error_type == "SMTPRecipientsRefused"
        assert deliveries["second@example.com"].last_error_message == str(transient_error)
        assert deliveries["second@example.com"].next_attempt_at == now + timedelta(minutes=1)
        assert deliveries["third@example.com"].state is NotificationDeliveryState.DEAD_LETTER
        assert deliveries["third@example.com"].last_failure_kind is NotificationFailureKind.SMTP_PERMANENT
        assert deliveries["third@example.com"].smtp_status_code == 550
        assert deliveries["third@example.com"].last_error_type == "SMTPRecipientsRefused"
        assert deliveries["third@example.com"].last_error_message == str(permanent_error)

        clock.advance(timedelta(minutes=1))
        retry_result = spool.flush(max_intents=1, max_deliveries=1)
        retried = store.list_deliveries(intent_id=_INTENT_ID)[1]

    assert retry_result.delivered == 1
    assert retried.state is NotificationDeliveryState.DELIVERED
    assert retried.attempt_count == 2
    assert retried.last_failure_kind is None
    assert retried.smtp_status_code is None
    assert retried.last_error_type is None
    assert retried.last_error_message is None
    assert [call[0] for call in sender.calls].count("first@example.com") == 1
    persisted = path.read_bytes()
    assert permanent_server_text.splitlines()[0] in persisted
    assert b"Traceback (most recent call last)" not in persisted


def test_transient_failure_is_bounded_then_manual_retry_uses_injected_clock(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    clock = _Clock(now)
    sender = _Sender(
        {
            "operator@example.com": [
                OSError(),
                OSError("network response\nsecond line"),
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
        first_failure = store.list_deliveries(intent_id=_INTENT_ID)[0]
        clock.advance(timedelta(minutes=1))
        second = spool.flush(max_intents=1, max_deliveries=1)
        dead_letters = spool.list_dead_letters()

        assert first.retried == 1
        assert first_failure.last_error_type == "OSError"
        assert first_failure.last_error_message == ""
        assert second.dead_lettered == 1
        assert len(dead_letters) == 1
        assert dead_letters[0].delivery.attempt_count == 2
        assert dead_letters[0].delivery.last_failure_kind is NotificationFailureKind.NETWORK
        assert dead_letters[0].delivery.last_error_type == "OSError"
        assert dead_letters[0].delivery.last_error_message == "network response\nsecond line"

        spool.retry_delivery(dead_letters[0].delivery.delivery_id)
        requeued = store.list_deliveries(intent_id=_INTENT_ID)[0]
        assert requeued.state is NotificationDeliveryState.PENDING
        assert requeued.attempt_count == 2
        assert requeued.next_attempt_at == clock.current
        assert requeued.last_failure_kind is NotificationFailureKind.NETWORK
        assert requeued.last_error_type == "OSError"
        assert requeued.last_error_message == "network response\nsecond line"

        third = spool.flush(max_intents=1, max_deliveries=1)
        completed = store.list_deliveries(intent_id=_INTENT_ID)[0]

    assert third.delivered == 1
    assert completed.state is NotificationDeliveryState.DELIVERED
    assert completed.attempt_count == 3
    assert completed.last_failure_kind is None
    assert completed.last_error_type is None
    assert completed.last_error_message is None


def test_disabling_after_planning_suppresses_frozen_recipient_cohort(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    clock = _Clock(now)
    sender = _Sender({"operator@example.com": [OSError("temporary failure")]})
    current_config: list[DisabledNotificationConfig | SmtpNotificationConfig] = [_smtp_config("operator@example.com")]
    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        store.enqueue_intent(_draft(), created_at=now)
        _plan(store, now=now, recipients=("operator@example.com",))
        spool = NotificationSpool(
            store=store,
            config_source=lambda _instance: current_config[0],
            clock=clock,
            sender_factory=lambda _config: sender,
        )

        failed = spool.flush(max_intents=1, max_deliveries=1)
        failed_delivery = store.list_deliveries(intent_id=_INTENT_ID)[0]
        assert failed.retried == 1
        assert failed_delivery.last_error_message == "temporary failure"

        current_config[0] = DisabledNotificationConfig()
        clock.advance(timedelta(minutes=1))
        suppressed = spool.flush(max_intents=1, max_deliveries=1)
        delivery = store.list_deliveries(intent_id=_INTENT_ID)[0]

        assert suppressed.suppressed_deliveries == 1
        assert delivery.state is NotificationDeliveryState.SUPPRESSED
        assert delivery.attempt_count == 1
        assert delivery.suppressed_at == clock.current
        assert delivery.last_failure_kind is None
        assert delivery.smtp_status_code is None
        assert delivery.last_error_type is None
        assert delivery.last_error_message is None

        current_config[0] = _smtp_config("operator@example.com")
        retried = spool.flush(max_intents=1, max_deliveries=1)

    assert retried.delivered == 0
    assert len(sender.calls) == 1


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
