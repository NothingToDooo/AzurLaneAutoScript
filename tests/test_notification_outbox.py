from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

import module.notify.notify as smtp_module
from module.notify import (
    DisabledNotificationConfig,
    LocalOutboxPublisher,
    NotificationIntent,
    NotificationIntentDraft,
    NotificationIntentSource,
    NotificationIntentState,
    NotificationPayloadError,
    NotificationSpool,
    NotificationSpoolStore,
    SmtpNotificationConfig,
    SmtpNotificationSender,
    SmtpTransport,
    build_local_outbox_publisher,
    notification_intent_id,
)
from module.runtime import PermanentOutboxPublishError

if TYPE_CHECKING:
    from email.message import EmailMessage
    from pathlib import Path

    from module.state import JsonValue


class _Clock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 7, 14, tzinfo=UTC)


class _FailingSpool:
    @staticmethod
    def enqueue_intent(draft: NotificationIntentDraft) -> NotificationIntent:
        del draft
        message = "temporary spool I/O failure"
        raise OSError(message)


class _CapturingFailingSpool:
    def __init__(self) -> None:
        self.drafts: list[NotificationIntentDraft] = []

    def enqueue_intent(self, draft: NotificationIntentDraft) -> NotificationIntent:
        self.drafts.append(draft)
        message = "temporary spool I/O failure"
        raise OSError(message)


def _payload(kind: str, *, schema_version: int = 1, **extra: JsonValue) -> dict[str, JsonValue]:
    return {
        "schema_version": schema_version,
        "kind": kind,
        "run_id": "run-1",
        "task_id": "main",
        **extra,
    }


def _spool(store: NotificationSpoolStore) -> NotificationSpool:
    return NotificationSpool(
        store=store,
        config_source=lambda _instance: DisabledNotificationConfig(),
        clock=_Clock(),
    )


@pytest.mark.parametrize(
    ("kind", "extra", "subject", "body"),
    [
        (
            "campaign_run_count_limit",
            {"resource": "campaign_main/12-4"},
            "Alas <alas> campaign finished",
            "<alas> campaign_main/12-4 reached run count limit",
        ),
        (
            "run_faulted",
            {"error_type": "RequestHumanTakeover", "message": "human takeover requested"},
            "Alas <alas> crashed",
            "<alas> RequestHumanTakeover: human takeover requested",
        ),
        (
            "run_faulted",
            {"error_type": "LegacyRuntimeError"},
            "Alas <alas> crashed",
            "<alas> LegacyRuntimeError",
        ),
    ],
)
def test_local_publisher_persists_notification_intent(
    tmp_path: Path,
    kind: str,
    extra: dict[str, JsonValue],
    subject: str,
    body: str,
) -> None:
    path = tmp_path / "notification-spool.sqlite3"
    source_message_id = f"run-1:operator.notification.requested:{kind}"
    intent_id = notification_intent_id(
        source=NotificationIntentSource.INSTANCE_OUTBOX,
        instance_name="alas",
        source_id=source_message_id,
    )
    with NotificationSpoolStore(path) as store:
        publisher = LocalOutboxPublisher("alas", _spool(store))

        publisher.publish(
            topic="operator.notification.requested",
            payload=_payload(kind, schema_version=2 if "message" in extra else 1, **extra),
            key="main",
            idempotency_key=source_message_id,
        )
        intent = store.get_intent(intent_id)

    assert intent is not None
    assert intent.source is NotificationIntentSource.INSTANCE_OUTBOX
    assert intent.source_id == source_message_id
    assert intent.subject == subject
    assert intent.body == body
    assert intent.state is NotificationIntentState.UNPLANNED


def test_local_publisher_replay_is_idempotent_before_instance_outbox_ack(tmp_path: Path) -> None:
    source_message_id = "run-1:operator.notification.requested:campaign_new_ship"
    intent_id = notification_intent_id(
        source=NotificationIntentSource.INSTANCE_OUTBOX,
        instance_name="alas",
        source_id=source_message_id,
    )
    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        publisher = build_local_outbox_publisher("alas", _spool(store))
        request = {
            "topic": "operator.notification.requested",
            "payload": _payload("campaign_new_ship", resource="campaign_main/12-4"),
            "key": "main",
            "idempotency_key": source_message_id,
        }

        publisher.publish(**request)
        first = store.get_intent(intent_id)
        publisher.publish(**request)
        replay = store.get_intent(intent_id)

    assert replay == first


def test_local_publisher_explicitly_acknowledges_local_runtime_topics(tmp_path: Path) -> None:
    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        publisher = LocalOutboxPublisher("alas", _spool(store))

        publisher.publish(topic="run.finished", payload=None, key="main", idempotency_key="run-1:run.finished")
        publisher.publish(
            topic="app.restart.requested",
            payload=None,
            key="main",
            idempotency_key="run-1:app.restart.requested",
        )

        assert (
            store.get_intent(
                notification_intent_id(
                    source=NotificationIntentSource.INSTANCE_OUTBOX,
                    instance_name="alas",
                    source_id="run-1:run.finished",
                )
            )
            is None
        )
        assert (
            store.get_intent(
                notification_intent_id(
                    source=NotificationIntentSource.INSTANCE_OUTBOX,
                    instance_name="alas",
                    source_id="run-1:app.restart.requested",
                )
            )
            is None
        )


@pytest.mark.parametrize(
    ("topic", "payload", "key", "message"),
    [
        ("unknown.topic", None, "main", "unsupported local outbox topic"),
        (
            "operator.notification.requested",
            _payload("campaign_new_ship"),
            "main",
            "campaign notification payload requires resource",
        ),
        (
            "operator.notification.requested",
            _payload("run_faulted", schema_version=2, error_type="RuntimeError"),
            "main",
            "missing fields",
        ),
        (
            "operator.notification.requested",
            _payload("run_faulted", schema_version=2, error_type="RuntimeError", message="failed"),
            "another-task",
            "outbox key must match",
        ),
        (
            "operator.notification.requested",
            _payload("process_failed", error_type="RuntimeError"),
            "main",
            "cannot originate from an instance outbox",
        ),
    ],
)
def test_deterministic_local_publisher_errors_are_permanent(
    tmp_path: Path,
    topic: str,
    payload: JsonValue,
    key: str | None,
    message: str,
) -> None:
    with (
        NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store,
        pytest.raises(NotificationPayloadError, match=message) as raised,
    ):
        LocalOutboxPublisher("alas", _spool(store)).publish(
            topic=topic,
            payload=payload,
            key=key,
            idempotency_key="message-1",
        )

    assert isinstance(raised.value, PermanentOutboxPublishError)


def test_spool_io_failure_remains_retryable_for_instance_outbox() -> None:
    with pytest.raises(OSError, match="temporary spool I/O failure") as raised:
        LocalOutboxPublisher("alas", _FailingSpool()).publish(
            topic="operator.notification.requested",
            payload=_payload(
                "run_faulted",
                schema_version=2,
                error_type="RuntimeError",
                message="temporary failure",
            ),
            key="main",
            idempotency_key="message-1",
        )

    assert not isinstance(raised.value, PermanentOutboxPublishError)


def test_fault_message_with_line_breaks_is_preserved_in_body() -> None:
    spool = _CapturingFailingSpool()

    with pytest.raises(OSError, match="temporary spool I/O failure"):
        LocalOutboxPublisher("alas", spool).publish(
            topic="operator.notification.requested",
            payload=_payload(
                "run_faulted",
                schema_version=2,
                error_type="RuntimeError",
                message="first line\nsecond line ",
            ),
            key="main",
            idempotency_key="message-1",
        )

    assert spool.drafts[0].body == "<alas> RuntimeError: first line\nsecond line "


def test_unsupported_notification_kind_preserves_the_decoder_error() -> None:
    with pytest.raises(NotificationPayloadError) as raised:
        LocalOutboxPublisher("alas", _FailingSpool()).publish(
            topic="operator.notification.requested",
            payload=_payload("unsupported"),
            key="main",
            idempotency_key="message-1",
        )

    assert isinstance(raised.value.__cause__, ValueError)
    assert str(raised.value.__cause__) in str(raised.value)


def test_smtp_sender_uses_one_recipient_and_stable_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(smtp_module, "_send_email", lambda _config, message: sent.append(message))
    sender = SmtpNotificationSender(
        SmtpNotificationConfig(
            host="smtp.example.com",
            user="alas@example.com",
            password=f"credential-{id(sent)}",
            recipients=("first@example.com", "second@example.com"),
            port=465,
            transport=SmtpTransport.IMPLICIT_TLS,
        )
    )

    sender.send(
        recipient="second@example.com",
        title="first",
        content="body",
        idempotency_key="delivery-1",
    )
    sender.send(
        recipient="second@example.com",
        title="retry",
        content="body",
        idempotency_key="delivery-1",
    )
    sender.send(
        recipient="first@example.com",
        title="another",
        content="body",
        idempotency_key="delivery-2",
    )

    assert sent[0]["To"] == "second@example.com"
    assert sent[0]["Message-ID"] == sent[1]["Message-ID"]
    assert sent[0]["Message-ID"] != sent[2]["Message-ID"]
    assert sent[0]["Message-ID"].startswith("<alas-")
    assert sent[0]["Message-ID"].endswith("@alas.local>")
