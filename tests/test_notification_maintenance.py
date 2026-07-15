from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import module.bootstrap.notification_maintenance as notification_maintenance_module
from module.application import OperatorNotificationKind
from module.bootstrap import ProductionNotificationMaintenance
from module.notify import DisabledNotificationConfig, NotificationSpool, NotificationSpoolStore
from module.runtime import OutboxDispatcher, OutboxFailureFact, OutboxRetryPolicy
from module.state import (
    OutboxMessage,
    RunFinalization,
    RunMode,
    RunStartCommand,
    RunStatus,
    SQLiteStateStore,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_NOW = datetime(2026, 7, 14, 9, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.current = _NOW

    def now(self) -> datetime:
        return self.current


class _UnavailableSpool:
    @staticmethod
    def publish(*, topic: str, payload: object, key: str | None, idempotency_key: str) -> None:
        del topic, payload, key, idempotency_key
        message = "spool is temporarily unavailable"
        raise OSError(message)


def test_source_outbox_failure_log_includes_the_original_message(monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[str] = []
    monkeypatch.setattr(notification_maintenance_module.logger, "error", logs.append)
    failure = OutboxFailureFact(
        message_id="message-1",
        topic="operator.notification.requested",
        error_type="RuntimeError",
        error_message="SMTP server rejected local credentials",
        attempt_count=1,
        available_at=_NOW,
        discarded_at=None,
    )

    notification_maintenance_module._report_source_failure("alas", failure)  # noqa: SLF001

    assert len(logs) == 1
    assert "error_message='SMTP server rejected local credentials'" in logs[0]


def _seed_notification(store: SQLiteStateStore, message_id: str) -> None:
    settings = store.update_settings({}, expected_revision=0, updated_at=_NOW)
    store.start_run(
        RunStartCommand(
            run_id="run-maintenance",
            task_id="main",
            mode=RunMode.SCHEDULED_JOB,
            settings_revision=settings.revision,
            content_revision="content-1",
            client_ui_revision="ui-1",
            started_at=_NOW,
        )
    )
    store.finalize_run(
        "run-maintenance",
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
                        "run_id": "run-maintenance",
                        "task_id": "main",
                        "resource": "campaign_main/12-4",
                    },
                ),
            ),
        ),
    )


def test_periodic_maintenance_retries_source_outbox_without_another_business_run(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    state_path = state_root / "alas.sqlite3"
    message_id = "run-maintenance:operator.notification.requested:campaign_new_ship"
    clock = _Clock()

    with SQLiteStateStore(state_path) as source:
        _seed_notification(source, message_id)
        failed = OutboxDispatcher(
            store=source,
            publisher=_UnavailableSpool(),
            clock=clock,
            retry_policy=OutboxRetryPolicy(
                initial_delay=timedelta(minutes=1),
                maximum_delay=timedelta(minutes=1),
            ),
        ).dispatch_pending()
        assert failed.failure_count == 1
        assert source.list_outbox(pending_only=True)[0].available_at == _NOW + timedelta(minutes=1)

    maintenance = ProductionNotificationMaintenance(
        state_root=state_root,
        spool=NotificationSpool(
            store=NotificationSpoolStore(tmp_path / "notification-spool.sqlite3"),
            config_source=lambda _instance_name: DisabledNotificationConfig(),
            clock=clock,
        ),
        clock=clock,
    )
    try:
        maintenance.flush()
        with SQLiteStateStore(state_path) as source:
            assert len(source.list_outbox(pending_only=True)) == 1

        clock.current += timedelta(minutes=2)
        result = maintenance.flush()

        assert result.suppressed_intents == 1
        with SQLiteStateStore(state_path) as source:
            assert source.list_outbox(pending_only=True) == ()
    finally:
        maintenance.close()
