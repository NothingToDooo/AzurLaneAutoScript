from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from module.application import OperatorNotificationKind, RunId, TaskId
from module.notify.spool_models import (
    NotificationIntent,
    NotificationIntentDraft,
    NotificationIntentSource,
    notification_intent_id,
)
from module.notify.spool_store import NotificationIntentConflictError
from module.runtime.outbox import PermanentOutboxPublishError

if TYPE_CHECKING:
    from module.state import JsonValue

_NOTIFICATION_TOPIC = "operator.notification.requested"
_ACKNOWLEDGED_LOCAL_TOPICS = frozenset({"run.finished", "app.restart.requested"})


class NotificationPayloadError(PermanentOutboxPublishError):
    pass


class NotificationIntentSink(Protocol):
    def enqueue_intent(self, draft: NotificationIntentDraft) -> NotificationIntent: ...


@dataclass(frozen=True, slots=True)
class _NotificationEnvelope:
    kind: OperatorNotificationKind
    run_id: RunId
    task_id: TaskId
    resource: str | None = None
    error_type: str | None = None
    error_message: str | None = None


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value != value.strip() or "\n" in value or "\r" in value:
        message = f"notification payload field {key} must be trimmed, non-empty, single-line text"
        raise NotificationPayloadError(message)
    return value


def _notification_kind(raw: Mapping[str, object]) -> OperatorNotificationKind:
    try:
        kind = OperatorNotificationKind(_required_text(raw, "kind"))
    except ValueError as error:
        message = f"notification payload kind is unsupported: {error}"
        raise NotificationPayloadError(message) from error
    if kind is OperatorNotificationKind.PROCESS_FAILED:
        message = "process failure notification cannot originate from an instance outbox"
        raise NotificationPayloadError(message)
    return kind


def _schema_version(raw: Mapping[str, object]) -> int:
    value = raw.get("schema_version")
    if type(value) is not int or value not in (1, 2):
        message = "notification payload schema_version must be 1 or 2"
        raise NotificationPayloadError(message)
    return value


def _expected_fields(kind: OperatorNotificationKind, schema_version: int) -> set[str]:
    common_fields = {"schema_version", "kind", "run_id", "task_id"}
    if kind is not OperatorNotificationKind.RUN_FAULTED:
        if schema_version == 2:
            message = "notification payload schema_version 2 is only supported for run_faulted"
            raise NotificationPayloadError(message)
        return common_fields | {"resource"}
    fields = common_fields | {"error_type"}
    if schema_version == 2:
        fields.add("message")
    return fields


def _error_message(raw: Mapping[str, object], schema_version: int) -> str:
    if schema_version == 1:
        return ""
    value = raw["message"]
    if not isinstance(value, str):
        message = "notification payload field message must be text"
        raise NotificationPayloadError(message)
    return value


def _decode_notification(payload: JsonValue) -> _NotificationEnvelope:
    if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
        message = "notification payload must be an object with string fields"
        raise NotificationPayloadError(message)
    raw = cast("Mapping[str, object]", payload)
    schema_version = _schema_version(raw)
    kind = _notification_kind(raw)
    try:
        run_id = RunId(_required_text(raw, "run_id"))
        task_id = TaskId(_required_text(raw, "task_id"))
    except (TypeError, ValueError) as error:
        raise NotificationPayloadError(str(error)) from error

    expected_fields = _expected_fields(kind, schema_version)
    unexpected = set(raw) - expected_fields
    if unexpected:
        message = f"notification payload contains unexpected fields: {sorted(unexpected)}"
        raise NotificationPayloadError(message)
    missing = expected_fields - set(raw)
    if missing:
        if "resource" in missing:
            message = "campaign notification payload requires resource"
        else:
            message = f"notification payload is missing fields: {sorted(missing)}"
        raise NotificationPayloadError(message)
    if kind is OperatorNotificationKind.RUN_FAULTED:
        error_type = _required_text(raw, "error_type")
        error_message = _error_message(raw, schema_version)
        resource = None
    else:
        resource = _required_text(raw, "resource")
        error_type = None
        error_message = None
    return _NotificationEnvelope(
        kind=kind,
        run_id=run_id,
        task_id=task_id,
        resource=resource,
        error_type=error_type,
        error_message=error_message,
    )


def _validate_instance_name(value: str) -> str:
    if not isinstance(value, str):
        message = "instance_name must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = "instance_name must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)
    return value


class LocalOutboxPublisher:
    """进程内 outbox sink：通知意图独立落盘成功后，instance outbox 才能确认。"""

    __slots__ = ("_instance_name", "_spool")

    def __init__(self, instance_name: str, spool: NotificationIntentSink) -> None:
        if isinstance(spool, type) or not callable(getattr(spool, "enqueue_intent", None)):
            message = "spool must implement enqueue_intent()"
            raise TypeError(message)
        self._instance_name = _validate_instance_name(instance_name)
        self._spool = spool

    def publish(
        self,
        *,
        topic: str,
        payload: JsonValue,
        key: str | None,
        idempotency_key: str,
    ) -> None:
        if topic in _ACKNOWLEDGED_LOCAL_TOPICS:
            return
        if topic != _NOTIFICATION_TOPIC:
            message = f"unsupported local outbox topic: {topic!r}"
            raise NotificationPayloadError(message)
        envelope = _decode_notification(payload)
        if key != envelope.task_id.value:
            message = "notification outbox key must match payload task_id"
            raise NotificationPayloadError(message)

        if envelope.kind is OperatorNotificationKind.RUN_FAULTED:
            subject = f"Alas <{self._instance_name}> crashed"
            error_summary = envelope.error_type
            if envelope.error_message:
                error_summary = f"{error_summary}: {envelope.error_message}"
            body = f"<{self._instance_name}> {error_summary}"
        else:
            reason = {
                OperatorNotificationKind.CAMPAIGN_RUN_COUNT_LIMIT: "reached run count limit",
                OperatorNotificationKind.CAMPAIGN_REACH_LEVEL_LIMIT: "reached level limit",
                OperatorNotificationKind.CAMPAIGN_NEW_SHIP: "got new ship",
            }[envelope.kind]
            subject = f"Alas <{self._instance_name}> campaign finished"
            body = f"<{self._instance_name}> {envelope.resource} {reason}"
        try:
            source = NotificationIntentSource.INSTANCE_OUTBOX
            draft = NotificationIntentDraft(
                intent_id=notification_intent_id(
                    source=source,
                    instance_name=self._instance_name,
                    source_id=idempotency_key,
                ),
                instance_name=self._instance_name,
                source=source,
                source_id=idempotency_key,
                kind=envelope.kind,
                subject=subject,
                body=body,
            )
        except (TypeError, ValueError) as error:
            message = f"notification outbox identity is invalid: {error}"
            raise NotificationPayloadError(message) from error
        try:
            self._spool.enqueue_intent(draft)
        except NotificationIntentConflictError as error:
            message = f"notification outbox id conflicts with persisted intent: {error}"
            raise NotificationPayloadError(message) from error


def build_local_outbox_publisher(instance_name: str, spool: NotificationIntentSink) -> LocalOutboxPublisher:
    return LocalOutboxPublisher(instance_name, spool)
