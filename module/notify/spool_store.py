from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Final

from module.application import OperatorNotificationKind
from module.notify.spool_models import (
    NotificationDelivery,
    NotificationDeliveryFailure,
    NotificationDeliveryRetry,
    NotificationDeliveryState,
    NotificationDeliveryWork,
    NotificationFailureKind,
    NotificationIntent,
    NotificationIntentDraft,
    NotificationIntentRetry,
    NotificationIntentSource,
    NotificationIntentState,
)
from module.sqlite_wal import configure_sqlite_wal

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType
    from typing import Self

SPOOL_SCHEMA_VERSION: Final = 2
_EXPECTED_TABLES: Final = frozenset({"notification_intents", "notification_deliveries"})
_V1_EXPECTED_COLUMNS: Final = {
    "notification_intents": (
        "sequence",
        "intent_id",
        "instance_name",
        "source",
        "source_id",
        "kind",
        "subject",
        "body",
        "state",
        "plan_attempt_count",
        "next_plan_attempt_at",
        "last_plan_failure_kind",
        "plan_claim_token",
        "plan_claim_until",
        "created_at",
        "planned_at",
        "suppressed_at",
    ),
    "notification_deliveries": (
        "delivery_id",
        "intent_id",
        "recipient",
        "state",
        "attempt_count",
        "next_attempt_at",
        "last_failure_kind",
        "smtp_status_code",
        "claim_token",
        "claim_until",
        "created_at",
        "last_attempt_at",
        "delivered_at",
        "dead_lettered_at",
        "suppressed_at",
    ),
}
_EXPECTED_COLUMNS: Final = {
    "notification_intents": (
        "sequence",
        "intent_id",
        "instance_name",
        "source",
        "source_id",
        "kind",
        "subject",
        "body",
        "state",
        "plan_attempt_count",
        "next_plan_attempt_at",
        "last_plan_failure_kind",
        "last_plan_error_type",
        "last_plan_error_message",
        "plan_claim_token",
        "plan_claim_until",
        "created_at",
        "planned_at",
        "suppressed_at",
    ),
    "notification_deliveries": (
        "delivery_id",
        "intent_id",
        "recipient",
        "state",
        "attempt_count",
        "next_attempt_at",
        "last_failure_kind",
        "smtp_status_code",
        "last_error_type",
        "last_error_message",
        "claim_token",
        "claim_until",
        "created_at",
        "last_attempt_at",
        "delivered_at",
        "dead_lettered_at",
        "suppressed_at",
    ),
}
_LEGACY_ERROR_TYPE: Final = "LegacyNotificationError"
_LEGACY_ERROR_MESSAGE: Final = "(error message unavailable in schema v1)"
_SCHEMA_STATEMENTS: Final = (
    """
    CREATE TABLE notification_intents (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        intent_id TEXT NOT NULL UNIQUE,
        instance_name TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('instance_outbox', 'process_failure')),
        source_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (
            kind IN (
                'run_faulted', 'process_failed',
                'campaign_run_count_limit', 'campaign_reach_level_limit', 'campaign_new_ship'
            )
        ),
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('unplanned', 'planned', 'suppressed')),
        plan_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (plan_attempt_count >= 0),
        next_plan_attempt_at TEXT,
        last_plan_failure_kind TEXT CHECK (
            last_plan_failure_kind IS NULL OR last_plan_failure_kind IN (
                'configuration', 'network', 'smtp_transient', 'smtp_permanent', 'unknown'
            )
        ),
        last_plan_error_type TEXT CHECK (
            last_plan_error_type IS NULL
            OR (length(last_plan_error_type) > 0 AND last_plan_error_type = trim(last_plan_error_type))
        ),
        last_plan_error_message TEXT,
        plan_claim_token TEXT,
        plan_claim_until TEXT,
        created_at TEXT NOT NULL,
        planned_at TEXT,
        suppressed_at TEXT,
        CHECK ((plan_claim_token IS NULL) = (plan_claim_until IS NULL)),
        CHECK (state = 'unplanned' OR plan_claim_token IS NULL),
        CHECK ((last_plan_failure_kind IS NULL) = (last_plan_error_type IS NULL)),
        CHECK ((last_plan_error_type IS NULL) = (last_plan_error_message IS NULL)),
        CHECK (
            (
                state = 'unplanned'
                AND (
                    (plan_attempt_count = 0 AND last_plan_failure_kind IS NULL)
                    OR (plan_attempt_count > 0 AND last_plan_failure_kind IS NOT NULL)
                )
            )
            OR (state IN ('planned', 'suppressed') AND last_plan_failure_kind IS NULL)
        ),
        CHECK (
            (state = 'unplanned' AND next_plan_attempt_at IS NOT NULL AND planned_at IS NULL AND suppressed_at IS NULL)
            OR (state = 'planned' AND next_plan_attempt_at IS NULL AND planned_at IS NOT NULL AND suppressed_at IS NULL)
            OR (
                state = 'suppressed'
                AND next_plan_attempt_at IS NULL
                AND planned_at IS NULL
                AND suppressed_at IS NOT NULL
            )
        )
    ) STRICT
    """,
    """
    CREATE TABLE notification_deliveries (
        delivery_id TEXT PRIMARY KEY,
        intent_id TEXT NOT NULL REFERENCES notification_intents(intent_id),
        recipient TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('pending', 'delivered', 'dead_letter', 'suppressed')),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        next_attempt_at TEXT,
        last_failure_kind TEXT CHECK (
            last_failure_kind IS NULL OR last_failure_kind IN (
                'configuration', 'network', 'smtp_transient', 'smtp_permanent', 'unknown'
            )
        ),
        smtp_status_code INTEGER CHECK (
            smtp_status_code IS NULL OR smtp_status_code BETWEEN 100 AND 599
        ),
        last_error_type TEXT CHECK (
            last_error_type IS NULL
            OR (length(last_error_type) > 0 AND last_error_type = trim(last_error_type))
        ),
        last_error_message TEXT,
        claim_token TEXT,
        claim_until TEXT,
        created_at TEXT NOT NULL,
        last_attempt_at TEXT,
        delivered_at TEXT,
        dead_lettered_at TEXT,
        suppressed_at TEXT,
        UNIQUE(intent_id, recipient),
        CHECK ((claim_token IS NULL) = (claim_until IS NULL)),
        CHECK ((last_failure_kind IS NULL) = (last_error_type IS NULL)),
        CHECK ((last_error_type IS NULL) = (last_error_message IS NULL)),
        CHECK (last_failure_kind IS NOT NULL OR smtp_status_code IS NULL),
        CHECK (
            (
                state = 'pending'
                AND (
                    (attempt_count = 0 AND last_failure_kind IS NULL)
                    OR (attempt_count > 0 AND last_failure_kind IS NOT NULL)
                )
            )
            OR (state = 'dead_letter' AND last_failure_kind IS NOT NULL)
            OR (
                state IN ('delivered', 'suppressed')
                AND last_failure_kind IS NULL
                AND smtp_status_code IS NULL
            )
        ),
        CHECK (
            (
                state = 'pending'
                AND next_attempt_at IS NOT NULL
                AND delivered_at IS NULL
                AND dead_lettered_at IS NULL
                AND suppressed_at IS NULL
            )
            OR (
                state = 'delivered'
                AND next_attempt_at IS NULL
                AND delivered_at IS NOT NULL
                AND dead_lettered_at IS NULL
                AND suppressed_at IS NULL
            )
            OR (
                state = 'dead_letter'
                AND next_attempt_at IS NULL
                AND delivered_at IS NULL
                AND dead_lettered_at IS NOT NULL
                AND suppressed_at IS NULL
            )
            OR (
                state = 'suppressed'
                AND next_attempt_at IS NULL
                AND delivered_at IS NULL
                AND dead_lettered_at IS NULL
                AND suppressed_at IS NOT NULL
            )
        ),
        CHECK (state = 'pending' OR claim_token IS NULL)
    ) STRICT
    """,
    """
    CREATE INDEX notification_intents_due_idx
    ON notification_intents(state, next_plan_attempt_at, plan_claim_until, sequence)
    """,
    """
    CREATE INDEX notification_deliveries_due_idx
    ON notification_deliveries(state, next_attempt_at, claim_until, intent_id)
    """,
)


class NotificationSpoolError(RuntimeError):
    pass


class NotificationSpoolSchemaError(NotificationSpoolError):
    pass


class NotificationSpoolCorruptionError(NotificationSpoolError):
    pass


class NotificationIntentConflictError(NotificationSpoolError):
    pass


class NotificationStateTransitionError(NotificationSpoolError):
    pass


@dataclass(frozen=True, slots=True)
class _DeliveryCompletion:
    state: NotificationDeliveryState
    completed_at: str
    failure_kind: NotificationFailureKind | None
    smtp_status_code: int | None
    error_type: str | None
    error_message: str | None


def _require_identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = f"{field_name} must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)


def _require_limit(value: int) -> None:
    if type(value) is not int or value <= 0:
        message = "limit must be a positive integer"
        raise ValueError(message)


def _encode_datetime(value: datetime, *, field_name: str) -> str:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _required_text(row: sqlite3.Row, column: str) -> str:
    value: object = row[column]
    if not isinstance(value, str) or not value:
        message = f"column {column} must contain non-empty text"
        raise NotificationSpoolCorruptionError(message)
    return value


def _optional_text(row: sqlite3.Row, column: str) -> str | None:
    value: object = row[column]
    if value is not None and (not isinstance(value, str) or not value):
        message = f"column {column} must contain non-empty text or NULL"
        raise NotificationSpoolCorruptionError(message)
    return value


def _optional_raw_text(row: sqlite3.Row, column: str) -> str | None:
    value: object = row[column]
    if value is not None and not isinstance(value, str):
        message = f"column {column} must contain text or NULL"
        raise NotificationSpoolCorruptionError(message)
    return value


def _required_integer(row: sqlite3.Row, column: str) -> int:
    value: object = row[column]
    if type(value) is not int:
        message = f"column {column} must contain an integer"
        raise NotificationSpoolCorruptionError(message)
    return value


def _optional_integer(row: sqlite3.Row, column: str) -> int | None:
    value: object = row[column]
    if value is not None and type(value) is not int:
        message = f"column {column} must contain an integer or NULL"
        raise NotificationSpoolCorruptionError(message)
    return value


def _decode_datetime(row: sqlite3.Row, column: str) -> datetime:
    value = _required_text(row, column)
    try:
        decoded = datetime.fromisoformat(value)
    except ValueError:
        message = f"column {column} must contain an ISO datetime"
        raise NotificationSpoolCorruptionError(message) from None
    if decoded.utcoffset() is None:
        message = f"column {column} must contain a timezone-aware datetime"
        raise NotificationSpoolCorruptionError(message)
    return decoded


def _decode_optional_datetime(row: sqlite3.Row, column: str) -> datetime | None:
    return None if row[column] is None else _decode_datetime(row, column)


def _decode_optional_failure_kind(row: sqlite3.Row, column: str) -> NotificationFailureKind | None:
    value = _optional_text(row, column)
    if value is None:
        return None
    try:
        return NotificationFailureKind(value)
    except ValueError:
        message = f"column {column} contains an unsupported failure kind"
        raise NotificationSpoolCorruptionError(message) from None


def notification_delivery_id(intent_id: str, recipient: str) -> str:
    _require_identifier(intent_id, field_name="intent_id")
    if (
        not isinstance(recipient, str)
        or not recipient
        or recipient != recipient.strip()
        or "\r" in recipient
        or "\n" in recipient
    ):
        message = "recipient must be trimmed, non-empty, single-line text"
        raise ValueError(message)
    digest = sha256(f"notification-delivery-v1\0{intent_id}\0{recipient}".encode()).hexdigest()
    return f"notification-delivery:{digest}"


class NotificationSpoolStore:
    """独立于 instance state 的持久通知队列。"""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        if str(self._path) == ":memory:":
            message = "NotificationSpoolStore requires a file path so WAL is durable"
            raise ValueError(message)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path, isolation_level=None, timeout=5.0)
        self._connection.row_factory = sqlite3.Row
        self._closed = False
        try:
            self._configure_connection()
            self._initialize_schema()
        except BaseException:
            self._connection.close()
            self._closed = True
            raise

    @property
    def path(self) -> Path:
        return self._path

    @property
    def schema_version(self) -> int:
        row = self._connection.execute("PRAGMA user_version").fetchone()
        if row is None:
            message = "PRAGMA user_version returned no row"
            raise NotificationSpoolCorruptionError(message)
        return _required_integer(row, "user_version")

    @property
    def journal_mode(self) -> str:
        row = self._connection.execute("PRAGMA journal_mode").fetchone()
        if row is None:
            message = "PRAGMA journal_mode returned no row"
            raise NotificationSpoolCorruptionError(message)
        return _required_text(row, "journal_mode").lower()

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def table_names(self) -> frozenset[str]:
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return frozenset(_required_text(row, "name") for row in rows)

    def enqueue_intent(self, draft: NotificationIntentDraft, *, created_at: datetime) -> NotificationIntent:
        if not isinstance(draft, NotificationIntentDraft):
            message = "draft must be a NotificationIntentDraft"
            raise TypeError(message)
        encoded_created_at = _encode_datetime(created_at, field_name="created_at")
        with self._transaction():
            existing = self._get_intent(draft.intent_id)
            if existing is not None:
                self._validate_idempotent_intent(existing, draft)
                return existing
            self._connection.execute(
                """
                INSERT INTO notification_intents(
                    intent_id, instance_name, source, source_id, kind, subject, body, state,
                    plan_attempt_count, next_plan_attempt_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unplanned', 0, ?, ?)
                """,
                (
                    draft.intent_id,
                    draft.instance_name,
                    draft.source.value,
                    draft.source_id,
                    draft.kind.value,
                    draft.subject,
                    draft.body,
                    encoded_created_at,
                    encoded_created_at,
                ),
            )
            inserted = self._get_intent(draft.intent_id)
            if inserted is None:
                message = "intent insert did not produce a row"
                raise NotificationSpoolCorruptionError(message)
            return inserted

    def get_intent(self, intent_id: str) -> NotificationIntent | None:
        _require_identifier(intent_id, field_name="intent_id")
        return self._get_intent(intent_id)

    def claim_due_intents(
        self,
        *,
        due_at: datetime,
        limit: int,
        claim_token: str,
        claim_until: datetime,
        instance_name: str | None = None,
    ) -> tuple[NotificationIntent, ...]:
        _require_limit(limit)
        _require_identifier(claim_token, field_name="claim_token")
        encoded_due_at = _encode_datetime(due_at, field_name="due_at")
        encoded_claim_until = _encode_datetime(claim_until, field_name="claim_until")
        if encoded_claim_until <= encoded_due_at:
            message = "claim_until must be later than due_at"
            raise ValueError(message)
        with self._transaction():
            if instance_name is None:
                rows = self._connection.execute(
                    """
                    SELECT intent_id
                    FROM notification_intents
                    WHERE state = 'unplanned'
                        AND next_plan_attempt_at <= ?
                        AND (plan_claim_until IS NULL OR plan_claim_until <= ?)
                    ORDER BY next_plan_attempt_at, sequence
                    LIMIT ?
                    """,
                    (encoded_due_at, encoded_due_at, limit),
                ).fetchall()
            else:
                _require_identifier(instance_name, field_name="instance_name")
                rows = self._connection.execute(
                    """
                    SELECT intent_id
                    FROM notification_intents
                    WHERE state = 'unplanned'
                        AND next_plan_attempt_at <= ?
                        AND (plan_claim_until IS NULL OR plan_claim_until <= ?)
                        AND instance_name = ?
                    ORDER BY next_plan_attempt_at, sequence
                    LIMIT ?
                    """,
                    (encoded_due_at, encoded_due_at, instance_name, limit),
                ).fetchall()
            intent_ids = tuple(_required_text(row, "intent_id") for row in rows)
            for intent_id in intent_ids:
                updated = self._connection.execute(
                    """
                    UPDATE notification_intents
                    SET plan_claim_token = ?, plan_claim_until = ?
                    WHERE intent_id = ? AND state = 'unplanned'
                        AND (plan_claim_until IS NULL OR plan_claim_until <= ?)
                    """,
                    (claim_token, encoded_claim_until, intent_id, encoded_due_at),
                )
                if updated.rowcount != 1:
                    message = f"notification intent {intent_id!r} could not be claimed atomically"
                    raise NotificationStateTransitionError(message)
            return tuple(self._require_intent(intent_id) for intent_id in intent_ids)

    def plan_intent(
        self,
        intent_id: str,
        recipients: tuple[str, ...],
        *,
        claim_token: str,
        planned_at: datetime,
    ) -> tuple[NotificationDelivery, ...]:
        _require_identifier(intent_id, field_name="intent_id")
        _require_identifier(claim_token, field_name="claim_token")
        if not isinstance(recipients, tuple) or not recipients:
            message = "recipients must be a non-empty tuple"
            raise ValueError(message)
        if len(set(recipients)) != len(recipients):
            message = "recipients must not contain duplicates"
            raise ValueError(message)
        delivery_ids = tuple(notification_delivery_id(intent_id, recipient) for recipient in recipients)
        encoded_planned_at = _encode_datetime(planned_at, field_name="planned_at")
        with self._transaction():
            intent = self._require_intent(intent_id)
            if intent.state is not NotificationIntentState.UNPLANNED or intent.plan_claim_token != claim_token:
                message = f"notification intent {intent_id!r} is not owned by the planning claim"
                raise NotificationStateTransitionError(message)
            for delivery_id, recipient in zip(delivery_ids, recipients, strict=True):
                self._connection.execute(
                    """
                    INSERT INTO notification_deliveries(
                        delivery_id, intent_id, recipient, state, attempt_count, next_attempt_at, created_at
                    ) VALUES (?, ?, ?, 'pending', 0, ?, ?)
                    """,
                    (delivery_id, intent_id, recipient, encoded_planned_at, encoded_planned_at),
                )
            updated = self._connection.execute(
                """
                UPDATE notification_intents
                SET state = 'planned', next_plan_attempt_at = NULL,
                    last_plan_failure_kind = NULL,
                    last_plan_error_type = NULL, last_plan_error_message = NULL,
                    plan_claim_token = NULL, plan_claim_until = NULL, planned_at = ?
                WHERE intent_id = ? AND state = 'unplanned' AND plan_claim_token = ?
                """,
                (encoded_planned_at, intent_id, claim_token),
            )
            if updated.rowcount != 1:
                message = f"notification intent {intent_id!r} was not unplanned while planning"
                raise NotificationStateTransitionError(message)
            return self.list_deliveries(intent_id=intent_id)

    def suppress_intent(
        self,
        intent_id: str,
        *,
        claim_token: str,
        suppressed_at: datetime,
    ) -> NotificationIntent:
        _require_identifier(intent_id, field_name="intent_id")
        _require_identifier(claim_token, field_name="claim_token")
        encoded_suppressed_at = _encode_datetime(suppressed_at, field_name="suppressed_at")
        with self._transaction():
            intent = self._require_intent(intent_id)
            if intent.state is not NotificationIntentState.UNPLANNED or intent.plan_claim_token != claim_token:
                message = f"notification intent {intent_id!r} is not owned by the planning claim"
                raise NotificationStateTransitionError(message)
            updated = self._connection.execute(
                """
                UPDATE notification_intents
                SET state = 'suppressed', next_plan_attempt_at = NULL,
                    last_plan_failure_kind = NULL,
                    last_plan_error_type = NULL, last_plan_error_message = NULL,
                    plan_claim_token = NULL, plan_claim_until = NULL, suppressed_at = ?
                WHERE intent_id = ? AND state = 'unplanned' AND plan_claim_token = ?
                """,
                (encoded_suppressed_at, intent_id, claim_token),
            )
            if updated.rowcount != 1:
                message = f"notification intent {intent_id!r} was not unplanned while suppressing"
                raise NotificationStateTransitionError(message)
            return self._require_intent(intent_id)

    def defer_intent(
        self,
        intent_id: str,
        *,
        claim_token: str,
        retry: NotificationIntentRetry,
    ) -> NotificationIntent:
        _require_identifier(intent_id, field_name="intent_id")
        _require_identifier(claim_token, field_name="claim_token")
        if not isinstance(retry, NotificationIntentRetry):
            message = "retry must be a NotificationIntentRetry"
            raise TypeError(message)
        if not isinstance(retry.failure_kind, NotificationFailureKind):
            message = "failure_kind must be a NotificationFailureKind"
            raise TypeError(message)
        self._validate_failure_error(retry.error_type, retry.error_message)
        encoded_attempted_at = _encode_datetime(retry.attempted_at, field_name="attempted_at")
        encoded_next_attempt_at = _encode_datetime(retry.next_attempt_at, field_name="next_attempt_at")
        if encoded_next_attempt_at <= encoded_attempted_at:
            message = "next_attempt_at must be later than attempted_at"
            raise ValueError(message)
        with self._transaction():
            intent = self._require_intent(intent_id)
            if intent.state is not NotificationIntentState.UNPLANNED or intent.plan_claim_token != claim_token:
                message = f"notification intent {intent_id!r} is not owned by the planning claim"
                raise NotificationStateTransitionError(message)
            updated = self._connection.execute(
                """
                UPDATE notification_intents
                SET plan_attempt_count = plan_attempt_count + 1,
                    next_plan_attempt_at = ?, last_plan_failure_kind = ?,
                    last_plan_error_type = ?, last_plan_error_message = ?,
                    plan_claim_token = NULL, plan_claim_until = NULL
                WHERE intent_id = ? AND state = 'unplanned' AND plan_claim_token = ?
                """,
                (
                    encoded_next_attempt_at,
                    retry.failure_kind.value,
                    retry.error_type,
                    retry.error_message,
                    intent_id,
                    claim_token,
                ),
            )
            if updated.rowcount != 1:
                message = f"notification intent {intent_id!r} was not unplanned while deferring"
                raise NotificationStateTransitionError(message)
            return self._require_intent(intent_id)

    def claim_due_deliveries(
        self,
        *,
        due_at: datetime,
        limit: int,
        claim_token: str,
        claim_until: datetime,
        instance_name: str | None = None,
    ) -> tuple[NotificationDeliveryWork, ...]:
        _require_limit(limit)
        _require_identifier(claim_token, field_name="claim_token")
        encoded_due_at = _encode_datetime(due_at, field_name="due_at")
        encoded_claim_until = _encode_datetime(claim_until, field_name="claim_until")
        if encoded_claim_until <= encoded_due_at:
            message = "claim_until must be later than due_at"
            raise ValueError(message)
        with self._transaction():
            if instance_name is None:
                rows = self._connection.execute(
                    """
                    SELECT d.delivery_id
                    FROM notification_deliveries AS d
                    JOIN notification_intents AS i ON i.intent_id = d.intent_id
                    WHERE d.state = 'pending'
                        AND d.next_attempt_at <= ?
                        AND (d.claim_until IS NULL OR d.claim_until <= ?)
                    ORDER BY d.next_attempt_at, i.sequence, d.recipient
                    LIMIT ?
                    """,
                    (encoded_due_at, encoded_due_at, limit),
                ).fetchall()
            else:
                _require_identifier(instance_name, field_name="instance_name")
                rows = self._connection.execute(
                    """
                    SELECT d.delivery_id
                    FROM notification_deliveries AS d
                    JOIN notification_intents AS i ON i.intent_id = d.intent_id
                    WHERE d.state = 'pending'
                        AND d.next_attempt_at <= ?
                        AND (d.claim_until IS NULL OR d.claim_until <= ?)
                        AND i.instance_name = ?
                    ORDER BY d.next_attempt_at, i.sequence, d.recipient
                    LIMIT ?
                    """,
                    (encoded_due_at, encoded_due_at, instance_name, limit),
                ).fetchall()
            delivery_ids = tuple(_required_text(row, "delivery_id") for row in rows)
            for delivery_id in delivery_ids:
                updated = self._connection.execute(
                    """
                    UPDATE notification_deliveries
                    SET claim_token = ?, claim_until = ?
                    WHERE delivery_id = ? AND state = 'pending'
                        AND (claim_until IS NULL OR claim_until <= ?)
                    """,
                    (claim_token, encoded_claim_until, delivery_id, encoded_due_at),
                )
                if updated.rowcount != 1:
                    message = f"delivery {delivery_id!r} could not be claimed atomically"
                    raise NotificationStateTransitionError(message)
            return tuple(self._delivery_work(delivery_id) for delivery_id in delivery_ids)

    def list_deliveries(self, *, intent_id: str | None = None) -> tuple[NotificationDelivery, ...]:
        if intent_id is None:
            rows = self._connection.execute(
                """
                SELECT
                    delivery_id, intent_id, recipient, state, attempt_count, next_attempt_at,
                    last_failure_kind, smtp_status_code, last_error_type, last_error_message,
                    claim_token, claim_until,
                    created_at, last_attempt_at, delivered_at, dead_lettered_at, suppressed_at
                FROM notification_deliveries
                ORDER BY intent_id, recipient
                """
            ).fetchall()
        else:
            _require_identifier(intent_id, field_name="intent_id")
            rows = self._connection.execute(
                """
                SELECT
                    delivery_id, intent_id, recipient, state, attempt_count, next_attempt_at,
                    last_failure_kind, smtp_status_code, last_error_type, last_error_message,
                    claim_token, claim_until,
                    created_at, last_attempt_at, delivered_at, dead_lettered_at, suppressed_at
                FROM notification_deliveries
                WHERE intent_id = ?
                ORDER BY recipient
                """,
                (intent_id,),
            ).fetchall()
        return tuple(self._delivery_from_row(row) for row in rows)

    def list_dead_letters(
        self,
        *,
        limit: int = 100,
        instance_name: str | None = None,
    ) -> tuple[NotificationDeliveryWork, ...]:
        _require_limit(limit)
        if instance_name is None:
            rows = self._connection.execute(
                """
                SELECT d.delivery_id
                FROM notification_deliveries AS d
                JOIN notification_intents AS i ON i.intent_id = d.intent_id
                WHERE d.state = 'dead_letter'
                ORDER BY d.dead_lettered_at, i.sequence, d.recipient
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            _require_identifier(instance_name, field_name="instance_name")
            rows = self._connection.execute(
                """
                SELECT d.delivery_id
                FROM notification_deliveries AS d
                JOIN notification_intents AS i ON i.intent_id = d.intent_id
                WHERE d.state = 'dead_letter' AND i.instance_name = ?
                ORDER BY d.dead_lettered_at, i.sequence, d.recipient
                LIMIT ?
                """,
                (instance_name, limit),
            ).fetchall()
        return tuple(self._delivery_work(_required_text(row, "delivery_id")) for row in rows)

    def retry_delivery(self, delivery_id: str, *, now: datetime) -> NotificationDelivery:
        """把 dead-letter 重新排队；attempt_count 保留为累计已完成投递尝试次数。"""
        _require_identifier(delivery_id, field_name="delivery_id")
        encoded_now = _encode_datetime(now, field_name="now")
        with self._transaction():
            updated = self._connection.execute(
                """
                UPDATE notification_deliveries
                SET state = 'pending', next_attempt_at = ?,
                    claim_token = NULL, claim_until = NULL, dead_lettered_at = NULL
                WHERE delivery_id = ? AND state = 'dead_letter'
                """,
                (encoded_now, delivery_id),
            )
            if updated.rowcount != 1:
                message = f"delivery {delivery_id!r} is not a dead letter"
                raise NotificationStateTransitionError(message)
            return self._require_delivery(delivery_id)

    def mark_delivered(
        self,
        delivery_id: str,
        *,
        claim_token: str,
        delivered_at: datetime,
    ) -> NotificationDelivery:
        encoded_delivered_at = _encode_datetime(delivered_at, field_name="delivered_at")
        return self._complete_delivery(
            delivery_id,
            claim_token=claim_token,
            completion=_DeliveryCompletion(
                state=NotificationDeliveryState.DELIVERED,
                completed_at=encoded_delivered_at,
                failure_kind=None,
                smtp_status_code=None,
                error_type=None,
                error_message=None,
            ),
        )

    def mark_suppressed(
        self,
        delivery_id: str,
        *,
        claim_token: str,
        suppressed_at: datetime,
    ) -> NotificationDelivery:
        """显式禁用通知时终止已规划 delivery；这不算一次 SMTP 投递尝试。"""
        _require_identifier(delivery_id, field_name="delivery_id")
        _require_identifier(claim_token, field_name="claim_token")
        encoded_suppressed_at = _encode_datetime(suppressed_at, field_name="suppressed_at")
        with self._transaction():
            updated = self._connection.execute(
                """
                UPDATE notification_deliveries
                SET state = 'suppressed', next_attempt_at = NULL,
                    last_failure_kind = NULL, smtp_status_code = NULL,
                    last_error_type = NULL, last_error_message = NULL,
                    claim_token = NULL, claim_until = NULL, suppressed_at = ?
                WHERE delivery_id = ? AND state = 'pending' AND claim_token = ?
                """,
                (encoded_suppressed_at, delivery_id, claim_token),
            )
            self._require_transition(updated, delivery_id)
            return self._require_delivery(delivery_id)

    def mark_retry(
        self,
        delivery_id: str,
        *,
        claim_token: str,
        retry: NotificationDeliveryRetry,
    ) -> NotificationDelivery:
        if not isinstance(retry, NotificationDeliveryRetry):
            message = "retry must be a NotificationDeliveryRetry"
            raise TypeError(message)
        self._validate_delivery_failure(
            retry.failure_kind,
            retry.smtp_status_code,
            retry.error_type,
            retry.error_message,
        )
        encoded_attempted_at = _encode_datetime(retry.attempted_at, field_name="attempted_at")
        encoded_next_attempt_at = _encode_datetime(retry.next_attempt_at, field_name="next_attempt_at")
        if encoded_next_attempt_at <= encoded_attempted_at:
            message = "next_attempt_at must be later than attempted_at"
            raise ValueError(message)
        _require_identifier(delivery_id, field_name="delivery_id")
        _require_identifier(claim_token, field_name="claim_token")
        with self._transaction():
            updated = self._connection.execute(
                """
                UPDATE notification_deliveries
                SET attempt_count = attempt_count + 1, next_attempt_at = ?,
                    last_failure_kind = ?, smtp_status_code = ?,
                    last_error_type = ?, last_error_message = ?,
                    claim_token = NULL, claim_until = NULL, last_attempt_at = ?
                WHERE delivery_id = ? AND state = 'pending' AND claim_token = ?
                """,
                (
                    encoded_next_attempt_at,
                    retry.failure_kind.value,
                    retry.smtp_status_code,
                    retry.error_type,
                    retry.error_message,
                    encoded_attempted_at,
                    delivery_id,
                    claim_token,
                ),
            )
            self._require_transition(updated, delivery_id)
            return self._require_delivery(delivery_id)

    def mark_dead_letter(
        self,
        delivery_id: str,
        *,
        claim_token: str,
        failure: NotificationDeliveryFailure,
    ) -> NotificationDelivery:
        if not isinstance(failure, NotificationDeliveryFailure):
            message = "failure must be a NotificationDeliveryFailure"
            raise TypeError(message)
        self._validate_delivery_failure(
            failure.failure_kind,
            failure.smtp_status_code,
            failure.error_type,
            failure.error_message,
        )
        encoded_dead_lettered_at = _encode_datetime(failure.attempted_at, field_name="attempted_at")
        return self._complete_delivery(
            delivery_id,
            claim_token=claim_token,
            completion=_DeliveryCompletion(
                state=NotificationDeliveryState.DEAD_LETTER,
                completed_at=encoded_dead_lettered_at,
                failure_kind=failure.failure_kind,
                smtp_status_code=failure.smtp_status_code,
                error_type=failure.error_type,
                error_message=failure.error_message,
            ),
        )

    def _complete_delivery(
        self,
        delivery_id: str,
        *,
        claim_token: str,
        completion: _DeliveryCompletion,
    ) -> NotificationDelivery:
        _require_identifier(delivery_id, field_name="delivery_id")
        _require_identifier(claim_token, field_name="claim_token")
        if completion.state is NotificationDeliveryState.DELIVERED:
            statement = """
                UPDATE notification_deliveries
                SET state = ?, attempt_count = attempt_count + 1, next_attempt_at = NULL,
                    last_failure_kind = ?, smtp_status_code = ?,
                    last_error_type = ?, last_error_message = ?,
                    claim_token = NULL, claim_until = NULL,
                    last_attempt_at = ?, delivered_at = ?
                WHERE delivery_id = ? AND state = 'pending' AND claim_token = ?
            """
        elif completion.state is NotificationDeliveryState.DEAD_LETTER:
            statement = """
                UPDATE notification_deliveries
                SET state = ?, attempt_count = attempt_count + 1, next_attempt_at = NULL,
                    last_failure_kind = ?, smtp_status_code = ?,
                    last_error_type = ?, last_error_message = ?,
                    claim_token = NULL, claim_until = NULL,
                    last_attempt_at = ?, dead_lettered_at = ?
                WHERE delivery_id = ? AND state = 'pending' AND claim_token = ?
            """
        else:
            message = "state must be DELIVERED or DEAD_LETTER"
            raise ValueError(message)
        with self._transaction():
            updated = self._connection.execute(
                statement,
                (
                    completion.state.value,
                    None if completion.failure_kind is None else completion.failure_kind.value,
                    completion.smtp_status_code,
                    completion.error_type,
                    completion.error_message,
                    completion.completed_at,
                    completion.completed_at,
                    delivery_id,
                    claim_token,
                ),
            )
            self._require_transition(updated, delivery_id)
            return self._require_delivery(delivery_id)

    @staticmethod
    def _validate_delivery_failure(
        failure_kind: NotificationFailureKind,
        smtp_status_code: int | None,
        error_type: str,
        error_message: str,
    ) -> None:
        if not isinstance(failure_kind, NotificationFailureKind):
            message = "failure_kind must be a NotificationFailureKind"
            raise TypeError(message)
        if smtp_status_code is not None and (type(smtp_status_code) is not int or not 100 <= smtp_status_code <= 599):
            message = "smtp_status_code must be from 100 to 599 or None"
            raise ValueError(message)
        NotificationSpoolStore._validate_failure_error(error_type, error_message)

    @staticmethod
    def _validate_failure_error(error_type: str, error_message: str) -> None:
        _require_identifier(error_type, field_name="error_type")
        if not isinstance(error_message, str):
            message = "error_message must be a string"
            raise TypeError(message)

    @staticmethod
    def _require_transition(cursor: sqlite3.Cursor, delivery_id: str) -> None:
        if cursor.rowcount != 1:
            message = f"delivery {delivery_id!r} is not pending or is owned by another claim"
            raise NotificationStateTransitionError(message)

    def _configure_connection(self) -> None:
        self._connection.execute("PRAGMA foreign_keys = ON")
        if configure_sqlite_wal(self._connection) != "wal":
            message = "notification spool requires SQLite WAL mode"
            raise NotificationSpoolSchemaError(message)
        self._connection.execute("PRAGMA synchronous = FULL")

    def _initialize_schema(self) -> None:
        if self.schema_version == SPOOL_SCHEMA_VERSION:
            self._validate_current_schema()
            return

        # 多进程首次打开时必须在拿到写锁后重读；后取得锁者会看到 owner
        # 已提交的 schema，只做验证而不会重复执行裸 CREATE TABLE。
        with self._transaction():
            version = self.schema_version
            tables = self.table_names()
            if version == SPOOL_SCHEMA_VERSION:
                self._validate_current_schema(tables)
                return
            if version == 0 and not tables:
                self._create_schema()
            elif version == 1:
                self._validate_schema_tables(tables)
                self._validate_schema_columns(_V1_EXPECTED_COLUMNS)
                self._migrate_v1_to_v2()
            else:
                message = f"unsupported notification spool schema version: {version}"
                raise NotificationSpoolSchemaError(message)
            self._validate_current_schema()
            self._connection.execute(f"PRAGMA user_version = {SPOOL_SCHEMA_VERSION}")

    def _create_schema(self) -> None:
        for statement in _SCHEMA_STATEMENTS:
            self._connection.execute(statement)

    def _migrate_v1_to_v2(self) -> None:
        """重建 v1 表；历史版本没有原始异常详情，只能写入显式占位审计。"""
        self._connection.execute("DROP INDEX IF EXISTS notification_intents_due_idx")
        self._connection.execute("DROP INDEX IF EXISTS notification_deliveries_due_idx")
        self._connection.execute("ALTER TABLE notification_deliveries RENAME TO notification_deliveries_v1")
        self._connection.execute("ALTER TABLE notification_intents RENAME TO notification_intents_v1")
        self._create_schema()
        self._connection.execute(
            """
            INSERT INTO notification_intents(
                sequence, intent_id, instance_name, source, source_id, kind, subject, body, state,
                plan_attempt_count, next_plan_attempt_at, last_plan_failure_kind,
                last_plan_error_type, last_plan_error_message,
                plan_claim_token, plan_claim_until, created_at, planned_at, suppressed_at
            )
            SELECT
                sequence, intent_id, instance_name, source, source_id, kind, subject, body, state,
                plan_attempt_count, next_plan_attempt_at,
                CASE
                    WHEN state = 'unplanned' AND plan_attempt_count > 0
                    THEN COALESCE(last_plan_failure_kind, 'unknown')
                    ELSE NULL
                END,
                CASE
                    WHEN state = 'unplanned' AND plan_attempt_count > 0 THEN ?
                    ELSE NULL
                END,
                CASE
                    WHEN state = 'unplanned' AND plan_attempt_count > 0 THEN ?
                    ELSE NULL
                END,
                plan_claim_token, plan_claim_until, created_at, planned_at, suppressed_at
            FROM notification_intents_v1
            """,
            (_LEGACY_ERROR_TYPE, _LEGACY_ERROR_MESSAGE),
        )
        self._connection.execute(
            """
            INSERT INTO notification_deliveries(
                delivery_id, intent_id, recipient, state, attempt_count, next_attempt_at,
                last_failure_kind, smtp_status_code, last_error_type, last_error_message,
                claim_token, claim_until, created_at, last_attempt_at,
                delivered_at, dead_lettered_at, suppressed_at
            )
            SELECT
                delivery_id, intent_id, recipient, state, attempt_count, next_attempt_at,
                CASE
                    WHEN state = 'dead_letter' OR (state = 'pending' AND attempt_count > 0)
                    THEN COALESCE(last_failure_kind, 'unknown')
                    ELSE NULL
                END,
                CASE
                    WHEN state = 'dead_letter' OR (state = 'pending' AND attempt_count > 0)
                    THEN smtp_status_code
                    ELSE NULL
                END,
                CASE
                    WHEN state = 'dead_letter' OR (state = 'pending' AND attempt_count > 0) THEN ?
                    ELSE NULL
                END,
                CASE
                    WHEN state = 'dead_letter' OR (state = 'pending' AND attempt_count > 0) THEN ?
                    ELSE NULL
                END,
                claim_token, claim_until, created_at, last_attempt_at,
                delivered_at, dead_lettered_at, suppressed_at
            FROM notification_deliveries_v1
            """,
            (_LEGACY_ERROR_TYPE, _LEGACY_ERROR_MESSAGE),
        )
        self._connection.execute("DROP TABLE notification_deliveries_v1")
        self._connection.execute("DROP TABLE notification_intents_v1")

    def _validate_current_schema(self, tables: frozenset[str] | None = None) -> None:
        self._validate_schema_tables(tables)
        self._validate_schema_columns(_EXPECTED_COLUMNS)

    def _validate_schema_tables(self, tables: frozenset[str] | None = None) -> None:
        actual = self.table_names() if tables is None else tables
        if actual != _EXPECTED_TABLES:
            message = "notification spool schema tables do not match the supported version"
            raise NotificationSpoolSchemaError(message)

    def _validate_schema_columns(self, expected_columns: dict[str, tuple[str, ...]]) -> None:
        for table_name, expected in expected_columns.items():
            rows = self._connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            actual = tuple(_required_text(row, "name") for row in rows)
            if actual != expected:
                message = f"notification spool table {table_name!r} columns do not match its schema version"
                raise NotificationSpoolSchemaError(message)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _get_intent(self, intent_id: str) -> NotificationIntent | None:
        row = self._connection.execute(
            """
            SELECT
                sequence, intent_id, instance_name, source, source_id, kind, subject, body, state,
                plan_attempt_count, next_plan_attempt_at, last_plan_failure_kind,
                last_plan_error_type, last_plan_error_message,
                plan_claim_token, plan_claim_until,
                created_at, planned_at, suppressed_at
            FROM notification_intents
            WHERE intent_id = ?
            """,
            (intent_id,),
        ).fetchone()
        return None if row is None else self._intent_from_row(row)

    def _require_intent(self, intent_id: str) -> NotificationIntent:
        intent = self._get_intent(intent_id)
        if intent is None:
            message = f"notification intent does not exist: {intent_id!r}"
            raise NotificationStateTransitionError(message)
        return intent

    def _require_delivery(self, delivery_id: str) -> NotificationDelivery:
        row = self._connection.execute(
            """
            SELECT
                delivery_id, intent_id, recipient, state, attempt_count, next_attempt_at,
                last_failure_kind, smtp_status_code, last_error_type, last_error_message,
                claim_token, claim_until,
                created_at, last_attempt_at, delivered_at, dead_lettered_at, suppressed_at
            FROM notification_deliveries
            WHERE delivery_id = ?
            """,
            (delivery_id,),
        ).fetchone()
        if row is None:
            message = f"notification delivery does not exist: {delivery_id!r}"
            raise NotificationStateTransitionError(message)
        return self._delivery_from_row(row)

    def _delivery_work(self, delivery_id: str) -> NotificationDeliveryWork:
        row = self._connection.execute(
            """
            SELECT
                d.delivery_id, d.intent_id, d.recipient, d.state, d.attempt_count, d.next_attempt_at,
                d.last_failure_kind, d.smtp_status_code, d.last_error_type, d.last_error_message,
                d.claim_token, d.claim_until,
                d.created_at, d.last_attempt_at, d.delivered_at, d.dead_lettered_at, d.suppressed_at,
                i.instance_name AS work_instance_name,
                i.subject AS work_subject,
                i.body AS work_body
            FROM notification_deliveries AS d
            JOIN notification_intents AS i ON i.intent_id = d.intent_id
            WHERE d.delivery_id = ?
            """,
            (delivery_id,),
        ).fetchone()
        if row is None:
            message = f"notification delivery does not exist: {delivery_id!r}"
            raise NotificationStateTransitionError(message)
        return NotificationDeliveryWork(
            delivery=self._delivery_from_row(row),
            instance_name=_required_text(row, "work_instance_name"),
            subject=_required_text(row, "work_subject"),
            body=_required_text(row, "work_body"),
        )

    @staticmethod
    def _validate_idempotent_intent(existing: NotificationIntent, draft: NotificationIntentDraft) -> None:
        persisted = (
            existing.instance_name,
            existing.source,
            existing.source_id,
            existing.kind,
            existing.subject,
            existing.body,
        )
        requested = (
            draft.instance_name,
            draft.source,
            draft.source_id,
            draft.kind,
            draft.subject,
            draft.body,
        )
        if persisted != requested:
            message = f"notification intent id conflicts with different content: {draft.intent_id!r}"
            raise NotificationIntentConflictError(message)

    @staticmethod
    def _intent_from_row(row: sqlite3.Row) -> NotificationIntent:
        try:
            source = NotificationIntentSource(_required_text(row, "source"))
            kind = OperatorNotificationKind(_required_text(row, "kind"))
            state = NotificationIntentState(_required_text(row, "state"))
        except ValueError:
            message = "notification intent contains an unsupported enum value"
            raise NotificationSpoolCorruptionError(message) from None
        return NotificationIntent(
            sequence=_required_integer(row, "sequence"),
            intent_id=_required_text(row, "intent_id"),
            instance_name=_required_text(row, "instance_name"),
            source=source,
            source_id=_required_text(row, "source_id"),
            kind=kind,
            subject=_required_text(row, "subject"),
            body=_required_text(row, "body"),
            state=state,
            plan_attempt_count=_required_integer(row, "plan_attempt_count"),
            next_plan_attempt_at=_decode_optional_datetime(row, "next_plan_attempt_at"),
            last_plan_failure_kind=_decode_optional_failure_kind(row, "last_plan_failure_kind"),
            last_plan_error_type=_optional_text(row, "last_plan_error_type"),
            last_plan_error_message=_optional_raw_text(row, "last_plan_error_message"),
            plan_claim_token=_optional_text(row, "plan_claim_token"),
            plan_claim_until=_decode_optional_datetime(row, "plan_claim_until"),
            created_at=_decode_datetime(row, "created_at"),
            planned_at=_decode_optional_datetime(row, "planned_at"),
            suppressed_at=_decode_optional_datetime(row, "suppressed_at"),
        )

    @staticmethod
    def _delivery_from_row(row: sqlite3.Row) -> NotificationDelivery:
        try:
            state = NotificationDeliveryState(_required_text(row, "state"))
        except ValueError:
            message = "notification delivery contains an unsupported state"
            raise NotificationSpoolCorruptionError(message) from None
        return NotificationDelivery(
            delivery_id=_required_text(row, "delivery_id"),
            intent_id=_required_text(row, "intent_id"),
            recipient=_required_text(row, "recipient"),
            state=state,
            attempt_count=_required_integer(row, "attempt_count"),
            next_attempt_at=_decode_optional_datetime(row, "next_attempt_at"),
            last_failure_kind=_decode_optional_failure_kind(row, "last_failure_kind"),
            smtp_status_code=_optional_integer(row, "smtp_status_code"),
            last_error_type=_optional_text(row, "last_error_type"),
            last_error_message=_optional_raw_text(row, "last_error_message"),
            claim_token=_optional_text(row, "claim_token"),
            claim_until=_decode_optional_datetime(row, "claim_until"),
            created_at=_decode_datetime(row, "created_at"),
            last_attempt_at=_decode_optional_datetime(row, "last_attempt_at"),
            delivered_at=_decode_optional_datetime(row, "delivered_at"),
            dead_lettered_at=_decode_optional_datetime(row, "dead_lettered_at"),
            suppressed_at=_decode_optional_datetime(row, "suppressed_at"),
        )
