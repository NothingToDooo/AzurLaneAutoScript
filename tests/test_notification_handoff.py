import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from module.application import OperatorNotificationKind
from module.notify import (
    DisabledNotificationConfig,
    LocalOutboxPublisher,
    NotificationIntentSource,
    NotificationSpool,
    NotificationSpoolStore,
    notification_intent_id,
)
from module.runtime import OutboxDispatcher, OutboxDispatchError, OutboxRetryPolicy
from module.state import (
    OutboxClaimRequest,
    OutboxFailureUpdate,
    OutboxMessage,
    OutboxRecord,
    RunFinalization,
    RunMode,
    RunStartCommand,
    RunStatus,
    SQLiteStateStore,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 7, 14, 9, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.current = _NOW

    def now(self) -> datetime:
        return self.current


class _FailingPublicationConfirmation:
    """模拟 spool commit 后、source ack 前数据库连接失效。"""

    def __init__(self, store: SQLiteStateStore) -> None:
        self._store = store
        self._failed = False

    def claim_ready_outbox(self, request: OutboxClaimRequest) -> tuple[OutboxRecord, ...]:
        return self._store.claim_ready_outbox(request)

    def mark_outbox_published(
        self,
        message_id: str,
        published_at: datetime,
        *,
        claim_token: str,
        expected_attempt_count: int,
    ) -> OutboxRecord:
        if not self._failed:
            self._failed = True
            message = "source database connection was lost"
            raise RuntimeError(message)
        return self._store.mark_outbox_published(
            message_id,
            published_at,
            claim_token=claim_token,
            expected_attempt_count=expected_attempt_count,
        )

    def record_outbox_failure(self, update: OutboxFailureUpdate) -> OutboxRecord:
        return self._store.record_outbox_failure(update)


def _seed_notification(store: SQLiteStateStore, message_id: str) -> None:
    settings = store.update_settings({}, expected_revision=0, updated_at=_NOW)
    store.start_run(
        RunStartCommand(
            run_id="run-1",
            task_id="main",
            mode=RunMode.SCHEDULED_JOB,
            settings_revision=settings.revision,
            content_revision="content-1",
            client_ui_revision="ui-1",
            started_at=_NOW,
        )
    )
    store.finalize_run(
        "run-1",
        RunFinalization(
            status=RunStatus.SUCCEEDED,
            finished_at=_NOW,
            outbox_messages=(
                OutboxMessage(
                    message_id=message_id,
                    topic="operator.notification.requested",
                    key="main",
                    payload={
                        "schema_version": 1,
                        "kind": OperatorNotificationKind.CAMPAIGN_NEW_SHIP.value,
                        "run_id": "run-1",
                        "task_id": "main",
                        "resource": "campaign_main/12-4",
                    },
                ),
            ),
        ),
    )


def test_spool_commit_then_source_ack_failure_replays_to_exactly_one_intent(tmp_path: Path) -> None:
    source_path = tmp_path / "instance.sqlite3"
    spool_path = tmp_path / "notification-spool.sqlite3"
    message_id = "run-1:operator.notification.requested:campaign_new_ship"
    clock = _Clock()
    policy = OutboxRetryPolicy(batch_size=1, claim_ttl=timedelta(minutes=1))

    with (
        SQLiteStateStore(source_path) as source,
        NotificationSpool(
            store=NotificationSpoolStore(spool_path),
            config_source=lambda _instance_name: DisabledNotificationConfig(),
            clock=clock,
        ) as spool,
    ):
        _seed_notification(source, message_id)
        publisher = LocalOutboxPublisher("alas", spool)

        with pytest.raises(OutboxDispatchError, match="publication"):
            OutboxDispatcher(
                store=_FailingPublicationConfirmation(source),
                publisher=publisher,
                clock=clock,
                retry_policy=policy,
            ).dispatch_pending()

        intent_id = notification_intent_id(
            source=NotificationIntentSource.INSTANCE_OUTBOX,
            instance_name="alas",
            source_id=message_id,
        )
        first_intent = spool.store.get_intent(intent_id)
        assert first_intent is not None
        assert source.list_outbox(pending_only=True)[0].claim_token is not None

        clock.current += timedelta(minutes=2)
        replay = OutboxDispatcher(
            store=source,
            publisher=publisher,
            clock=clock,
            retry_policy=policy,
        ).dispatch_pending()

        assert replay.published_message_ids == (message_id,)
        assert spool.store.get_intent(intent_id) == first_intent
        assert source.list_outbox(pending_only=True) == ()

    with sqlite3.connect(spool_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM notification_intents").fetchone()
    assert count == (1,)
