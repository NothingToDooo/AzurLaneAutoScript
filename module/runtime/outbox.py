from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from module.state import OutboxRecord

if TYPE_CHECKING:
    from module.state import JsonValue


class OutboxStore(Protocol):
    def list_outbox(self, *, pending_only: bool = False) -> tuple[OutboxRecord, ...]: ...

    def mark_outbox_published(self, message_id: str, published_at: datetime) -> OutboxRecord: ...


class OutboxPublisher(Protocol):
    def publish(
        self,
        *,
        topic: str,
        payload: JsonValue,
        key: str | None,
        idempotency_key: str,
    ) -> None: ...


class OutboxClock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class OutboxDispatchResult:
    message_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.message_ids, tuple):
            message = "message_ids must be a tuple"
            raise TypeError(message)
        if any(not isinstance(message_id, str) or not message_id for message_id in self.message_ids):
            message = "message_ids must contain non-empty strings"
            raise TypeError(message)

    @property
    def published_count(self) -> int:
        return len(self.message_ids)


def _require_method(value: object, method: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method, None)):
        message = f"{field_name} must implement {method}()"
        raise TypeError(message)


def _aware_now(clock: OutboxClock) -> datetime:
    now = clock.now()
    if not isinstance(now, datetime):
        message = "OutboxClock.now() must return a datetime"
        raise TypeError(message)
    if now.utcoffset() is None:
        message = "OutboxClock.now() must return a timezone-aware datetime"
        raise ValueError(message)
    return now


class OutboxDispatcher:
    """按落库顺序投递 outbox；发布成功后才确认，失败时保留消息供重试。"""

    __slots__ = ("_clock", "_publisher", "_store")

    def __init__(self, *, store: OutboxStore, publisher: OutboxPublisher, clock: OutboxClock) -> None:
        _require_method(store, "list_outbox", field_name="store")
        _require_method(store, "mark_outbox_published", field_name="store")
        _require_method(publisher, "publish", field_name="publisher")
        _require_method(clock, "now", field_name="clock")
        self._store = store
        self._publisher = publisher
        self._clock = clock

    def dispatch_pending(self, *, max_messages: int | None = None) -> OutboxDispatchResult:
        if max_messages is not None and (type(max_messages) is not int or max_messages <= 0):
            message = "max_messages must be a positive integer or None"
            raise ValueError(message)

        pending = self._store.list_outbox(pending_only=True)
        if not isinstance(pending, tuple) or any(not isinstance(record, OutboxRecord) for record in pending):
            message = "OutboxStore.list_outbox() must return a tuple of OutboxRecord values"
            raise TypeError(message)
        selected = pending if max_messages is None else pending[:max_messages]

        published: list[str] = []
        for record in selected:
            if record.published_at is not None:
                message = "pending outbox query returned an already-published record"
                raise ValueError(message)
            self._publisher.publish(
                topic=record.topic,
                payload=record.payload,
                key=record.key,
                idempotency_key=record.message_id,
            )
            confirmed = self._store.mark_outbox_published(record.message_id, _aware_now(self._clock))
            if not isinstance(confirmed, OutboxRecord):
                message = "OutboxStore.mark_outbox_published() must return an OutboxRecord"
                raise TypeError(message)
            if confirmed.message_id != record.message_id or confirmed.published_at is None:
                message = "outbox publication confirmation does not match the dispatched message"
                raise ValueError(message)
            published.append(record.message_id)

        return OutboxDispatchResult(tuple(published))
