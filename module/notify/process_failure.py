from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from module.application import OperatorNotificationKind
from module.notify.spool_models import (
    NotificationIntent,
    NotificationIntentDraft,
    NotificationIntentSource,
    notification_intent_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _new_attempt_id() -> str:
    return uuid4().hex


def _identifier(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = f"{field_name} must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)
    return value


class ProcessFailureSpool(Protocol):
    def enqueue_intent(self, draft: NotificationIntentDraft) -> NotificationIntent: ...


class ProcessFailureNotifier:
    """run 尚未形成时只持久化安全意图；规划与触网由独立 flusher 负责。"""

    __slots__ = ("_attempt_id_factory", "_spool")

    def __init__(
        self,
        spool: ProcessFailureSpool,
        attempt_id_factory: Callable[[], str] = _new_attempt_id,
    ) -> None:
        if isinstance(spool, type) or not callable(getattr(spool, "enqueue_intent", None)):
            message = "spool must implement enqueue_intent()"
            raise TypeError(message)
        if not callable(attempt_id_factory):
            message = "attempt_id_factory must be callable"
            raise TypeError(message)
        self._spool = spool
        self._attempt_id_factory = attempt_id_factory

    def report(self, instance_name: str, command: str, error: Exception) -> None:
        instance = _identifier(instance_name, field_name="instance_name")
        process_command = _identifier(command, field_name="command")
        if not isinstance(error, Exception):
            message = "error must be an Exception"
            raise TypeError(message)
        attempt_id = _identifier(self._attempt_id_factory(), field_name="attempt_id")
        source = NotificationIntentSource.PROCESS_FAILURE
        source_id = f"process-failure:{attempt_id}"
        self._spool.enqueue_intent(
            NotificationIntentDraft(
                intent_id=notification_intent_id(
                    source=source,
                    instance_name=instance,
                    source_id=source_id,
                ),
                instance_name=instance,
                source=source,
                source_id=source_id,
                kind=OperatorNotificationKind.PROCESS_FAILED,
                subject=f"Alas <{instance}> crashed",
                body=f"<{instance}> {type(error).__name__} while executing `{process_command}`",
            )
        )
