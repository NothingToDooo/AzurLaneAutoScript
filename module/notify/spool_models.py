from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from module.application import OperatorNotificationKind

if TYPE_CHECKING:
    from datetime import datetime


class NotificationIntentSource(StrEnum):
    INSTANCE_OUTBOX = "instance_outbox"
    PROCESS_FAILURE = "process_failure"


class NotificationIntentState(StrEnum):
    UNPLANNED = "unplanned"
    PLANNED = "planned"
    SUPPRESSED = "suppressed"


class NotificationDeliveryState(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"
    SUPPRESSED = "suppressed"


class NotificationFailureKind(StrEnum):
    CONFIGURATION = "configuration"
    NETWORK = "network"
    SMTP_TRANSIENT = "smtp_transient"
    SMTP_PERMANENT = "smtp_permanent"
    UNKNOWN = "unknown"


def _identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = f"{field_name} must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)


def _single_line(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or "\r" in value or "\n" in value:
        message = f"{field_name} must be trimmed, non-empty, single-line text"
        raise ValueError(message)


def notification_intent_id(
    *,
    source: NotificationIntentSource,
    instance_name: str,
    source_id: str,
) -> str:
    if not isinstance(source, NotificationIntentSource):
        message = "source must be a NotificationIntentSource"
        raise TypeError(message)
    _identifier(instance_name, field_name="instance_name")
    _identifier(source_id, field_name="source_id")
    digest = sha256(f"notification-intent-v1\0{source.value}\0{instance_name}\0{source_id}".encode()).hexdigest()
    return f"notification-intent:{digest}"


@dataclass(frozen=True, slots=True)
class NotificationIntentDraft:
    intent_id: str
    instance_name: str
    source: NotificationIntentSource
    source_id: str
    kind: OperatorNotificationKind
    subject: str
    body: str

    def __post_init__(self) -> None:
        _identifier(self.intent_id, field_name="intent_id")
        _identifier(self.instance_name, field_name="instance_name")
        _identifier(self.source_id, field_name="source_id")
        if not isinstance(self.source, NotificationIntentSource):
            message = "source must be a NotificationIntentSource"
            raise TypeError(message)
        if not isinstance(self.kind, OperatorNotificationKind):
            message = "kind must be an OperatorNotificationKind"
            raise TypeError(message)
        _single_line(self.subject, field_name="subject")
        _single_line(self.body, field_name="body")
        expected_intent_id = notification_intent_id(
            source=self.source,
            instance_name=self.instance_name,
            source_id=self.source_id,
        )
        if self.intent_id != expected_intent_id:
            message = "intent_id must match the versioned source identity"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class NotificationIntent:
    sequence: int
    intent_id: str
    instance_name: str
    source: NotificationIntentSource
    source_id: str
    kind: OperatorNotificationKind
    subject: str
    body: str
    state: NotificationIntentState
    plan_attempt_count: int
    next_plan_attempt_at: datetime | None
    last_plan_failure_kind: NotificationFailureKind | None
    plan_claim_token: str | None
    plan_claim_until: datetime | None
    created_at: datetime
    planned_at: datetime | None
    suppressed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationDelivery:
    delivery_id: str
    intent_id: str
    recipient: str
    state: NotificationDeliveryState
    attempt_count: int
    next_attempt_at: datetime | None
    last_failure_kind: NotificationFailureKind | None
    smtp_status_code: int | None
    claim_token: str | None
    claim_until: datetime | None
    created_at: datetime
    last_attempt_at: datetime | None
    delivered_at: datetime | None
    dead_lettered_at: datetime | None
    suppressed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationDeliveryWork:
    delivery: NotificationDelivery
    instance_name: str
    subject: str
    body: str


@dataclass(frozen=True, slots=True)
class NotificationDeliveryRetry:
    attempted_at: datetime
    next_attempt_at: datetime
    failure_kind: NotificationFailureKind
    smtp_status_code: int | None


@dataclass(frozen=True, slots=True)
class NotificationFlushResult:
    planned_intents: int = 0
    suppressed_intents: int = 0
    deferred_intents: int = 0
    delivered: int = 0
    retried: int = 0
    dead_lettered: int = 0
    suppressed_deliveries: int = 0
