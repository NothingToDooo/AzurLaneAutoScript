from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from module.notify import (
    NotificationIntent,
    NotificationIntentDraft,
    NotificationIntentSource,
    NotificationIntentState,
    NotificationSpool,
    NotificationSpoolStore,
    ProcessFailureNotifier,
    SmtpNotificationConfig,
    SmtpTransport,
    notification_intent_id,
)

if TYPE_CHECKING:
    from pathlib import Path


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 14, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current


class _Sender:
    def __init__(self) -> None:
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


class _FailingSpool:
    def __init__(self) -> None:
        self.drafts: list[NotificationIntentDraft] = []

    def enqueue_intent(self, draft: NotificationIntentDraft) -> NotificationIntent:
        self.drafts.append(draft)
        message = "credential=secret"
        raise OSError(message)


def _smtp_config() -> SmtpNotificationConfig:
    return SmtpNotificationConfig(
        host="smtp.example.com",
        user="alas@example.com",
        password=f"credential-{id(_smtp_config)}",
        recipients=("operator@example.com",),
        port=465,
        transport=SmtpTransport.IMPLICIT_TLS,
    )


def _process_intent_id() -> str:
    return notification_intent_id(
        source=NotificationIntentSource.PROCESS_FAILURE,
        instance_name="alas",
        source_id="process-failure:attempt-1",
    )


def test_process_failure_notifier_persists_the_original_error_message(tmp_path: Path) -> None:
    clock = _Clock()
    sender = _Sender()
    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        spool = NotificationSpool(
            store=store,
            config_source=lambda _instance: _smtp_config(),
            clock=clock,
            sender_factory=lambda _config: sender,
        )
        notifier = ProcessFailureNotifier(spool, lambda: "attempt-1")

        notifier.report("alas", "alas", RuntimeError("credential=original-secret"))
        intent = store.get_intent(_process_intent_id())

        assert intent is not None
        assert intent.source is NotificationIntentSource.PROCESS_FAILURE
        assert intent.source_id == "process-failure:attempt-1"
        assert intent.kind.value == "process_failed"
        assert intent.subject == "Alas <alas> crashed"
        assert intent.body == "<alas> RuntimeError: credential=original-secret while executing `alas`"
        assert intent.state is NotificationIntentState.UNPLANNED
        assert sender.calls == []

        delivered = spool.flush(max_intents=1, max_deliveries=1)

    assert delivered.delivered == 1
    assert sender.calls[0][0] == "operator@example.com"
    assert sender.calls[0][2] == "<alas> RuntimeError: credential=original-secret while executing `alas`"


def test_process_failure_unplanned_intent_survives_config_failure_and_later_flushes(tmp_path: Path) -> None:
    clock = _Clock()
    sender = _Sender()
    config_available = False

    def load_config(_instance: str) -> SmtpNotificationConfig:
        if not config_available:
            message = "credential=config-secret"
            raise RuntimeError(message)
        return _smtp_config()

    with NotificationSpoolStore(tmp_path / "notification-spool.sqlite3") as store:
        spool = NotificationSpool(
            store=store,
            config_source=load_config,
            clock=clock,
            sender_factory=lambda _config: sender,
        )
        ProcessFailureNotifier(spool, lambda: "attempt-1").report(
            "alas",
            "alas",
            RuntimeError("original-secret"),
        )

        first_flush = spool.flush(max_intents=1, max_deliveries=1)
        deferred = store.get_intent(_process_intent_id())

        assert first_flush.deferred_intents == 1
        assert deferred is not None
        assert deferred.state is NotificationIntentState.UNPLANNED
        assert deferred.plan_attempt_count == 1

        config_available = True
        clock.current += timedelta(minutes=1)
        second_flush = spool.flush(max_intents=1, max_deliveries=1)
        completed = store.get_intent(_process_intent_id())

    assert second_flush.planned_intents == 1
    assert second_flush.delivered == 1
    assert completed is not None
    assert completed.state is NotificationIntentState.PLANNED


def test_process_failure_spool_failure_is_left_to_the_host_containment_boundary() -> None:
    spool = _FailingSpool()

    with pytest.raises(OSError, match="credential=secret"):
        ProcessFailureNotifier(spool, lambda: "attempt-1").report(
            "alas",
            "alas",
            RuntimeError("original"),
        )

    assert len(spool.drafts) == 1


def test_process_failure_message_with_line_breaks_is_preserved_in_body() -> None:
    spool = _FailingSpool()

    with pytest.raises(OSError, match="credential=secret"):
        ProcessFailureNotifier(spool, lambda: "attempt-1").report(
            "alas",
            "alas",
            RuntimeError("first line\nsecond line "),
        )

    assert spool.drafts[0].body == "<alas> RuntimeError: first line\nsecond line  while executing `alas`"
