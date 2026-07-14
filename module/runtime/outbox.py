from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol, cast
from uuid import uuid4

from module.logger import logger
from module.state import OutboxClaimRequest, OutboxFailureUpdate, OutboxRecord

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.state import JsonValue


class OutboxStore(Protocol):
    def claim_ready_outbox(self, request: OutboxClaimRequest) -> tuple[OutboxRecord, ...]: ...

    def mark_outbox_published(
        self,
        message_id: str,
        published_at: datetime,
        *,
        claim_token: str,
        expected_attempt_count: int,
    ) -> OutboxRecord: ...

    def record_outbox_failure(self, update: OutboxFailureUpdate) -> OutboxRecord: ...


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


class OutboxDeliveryError(RuntimeError):
    """outbox 状态边界异常，保留底层错误供调用方诊断。"""


class OutboxLoadError(OutboxDeliveryError):
    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__(f"failed to load ready outbox messages: {type(error).__name__}: {error}")


class OutboxDispatchError(OutboxDeliveryError):
    """publish 结果无法可靠写回状态库时抛出，并保留底层错误。"""

    def __init__(self, message_id: str, topic: str, operation: str, error: Exception) -> None:
        for field_name, value in (("message_id", message_id), ("topic", topic), ("operation", operation)):
            if not isinstance(value, str) or not value:
                message = f"{field_name} must be a non-empty string"
                raise ValueError(message)
        self.message_id = message_id
        self.topic = topic
        self.operation = operation
        self.error = error
        super().__init__(
            f"failed to confirm outbox {operation} for message {message_id!r} and topic {topic!r}: "
            f"{type(error).__name__}: {error}"
        )


class PermanentOutboxPublishError(RuntimeError):
    """publisher 用此 marker 表示重试不会改变结果，应立即 dead-letter。"""


@dataclass(frozen=True, slots=True)
class OutboxRetryPolicy:
    batch_size: int = 32
    startup_max_batches: int = 8
    max_attempts: int = 8
    initial_delay: timedelta = timedelta(minutes=1)
    maximum_delay: timedelta = timedelta(hours=1)
    claim_ttl: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("batch_size", self.batch_size),
            ("startup_max_batches", self.startup_max_batches),
            ("max_attempts", self.max_attempts),
        ):
            if type(value) is not int or value <= 0:
                message = f"{field_name} must be a positive integer"
                raise ValueError(message)
        for field_name, value in (
            ("initial_delay", self.initial_delay),
            ("maximum_delay", self.maximum_delay),
            ("claim_ttl", self.claim_ttl),
        ):
            if not isinstance(value, timedelta) or value <= timedelta(0):
                message = f"{field_name} must be a positive timedelta"
                raise ValueError(message)
        if self.maximum_delay < self.initial_delay:
            message = "maximum_delay must not be shorter than initial_delay"
            raise ValueError(message)

    def next_available_at(self, *, failed_at: datetime, attempt_count: int) -> datetime | None:
        _validate_aware_datetime(failed_at, field_name="failed_at")
        if type(attempt_count) is not int or attempt_count <= 0:
            message = "attempt_count must be a positive integer"
            raise ValueError(message)
        if attempt_count >= self.max_attempts:
            return None

        delay = self.initial_delay
        for _ in range(1, attempt_count):
            delay = min(delay * 2, self.maximum_delay)
            if delay == self.maximum_delay:
                break
        return failed_at + delay


DEFAULT_OUTBOX_RETRY_POLICY = OutboxRetryPolicy()


@dataclass(frozen=True, slots=True)
class OutboxFailureFact:
    message_id: str
    topic: str
    error_type: str
    error_message: str
    attempt_count: int
    available_at: datetime
    discarded_at: datetime | None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("message_id", self.message_id),
            ("topic", self.topic),
            ("error_type", self.error_type),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                message = f"{field_name} must be trimmed and non-empty"
                raise ValueError(message)
        if not isinstance(self.error_message, str):
            message = "error_message must be a string"
            raise TypeError(message)
        if type(self.attempt_count) is not int or self.attempt_count <= 0:
            message = "attempt_count must be a positive integer"
            raise ValueError(message)
        _validate_aware_datetime(self.available_at, field_name="available_at")
        if self.discarded_at is not None:
            _validate_aware_datetime(self.discarded_at, field_name="discarded_at")

    @property
    def is_discarded(self) -> bool:
        return self.discarded_at is not None


@dataclass(frozen=True, slots=True)
class OutboxDelivery:
    """把 publisher、有限重试策略和逐条失败报告器交给 instance runtime。"""

    publisher: OutboxPublisher
    failure_reporter: Callable[[OutboxFailureFact], object] | None = None
    retry_policy: OutboxRetryPolicy = DEFAULT_OUTBOX_RETRY_POLICY

    def __post_init__(self) -> None:
        if isinstance(self.publisher, type) or not callable(getattr(self.publisher, "publish", None)):
            message = "publisher must implement publish()"
            raise TypeError(message)
        if self.failure_reporter is not None and not callable(self.failure_reporter):
            message = "failure_reporter must be callable or None"
            raise TypeError(message)
        if not isinstance(self.retry_policy, OutboxRetryPolicy):
            message = "retry_policy must be an OutboxRetryPolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class OutboxDispatchResult:
    published_message_ids: tuple[str, ...]
    failures: tuple[OutboxFailureFact, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.published_message_ids, tuple) or any(
            not isinstance(message_id, str) or not message_id for message_id in self.published_message_ids
        ):
            message = "published_message_ids must be a tuple of non-empty strings"
            raise TypeError(message)
        if not isinstance(self.failures, tuple) or any(
            not isinstance(failure, OutboxFailureFact) for failure in self.failures
        ):
            message = "failures must be a tuple of OutboxFailureFact values"
            raise TypeError(message)

    @property
    def published_count(self) -> int:
        return len(self.published_message_ids)

    @property
    def failure_count(self) -> int:
        return len(self.failures)


def _require_method(value: object, method: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method, None)):
        message = f"{field_name} must implement {method}()"
        raise TypeError(message)


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def _aware_now(clock: OutboxClock) -> datetime:
    now = clock.now()
    _validate_aware_datetime(now, field_name="OutboxClock.now()")
    return now


def _validate_ready_records(
    records: object,
    *,
    request: OutboxClaimRequest,
) -> tuple[OutboxRecord, ...]:
    if not isinstance(records, tuple) or any(not isinstance(record, OutboxRecord) for record in records):
        message = "OutboxStore.claim_ready_outbox() must return a tuple of OutboxRecord values"
        raise TypeError(message)
    typed_records = cast("tuple[OutboxRecord, ...]", records)
    if len(typed_records) > request.limit:
        message = "ready outbox query exceeded its batch limit"
        raise ValueError(message)
    sequences = tuple(record.sequence for record in typed_records)
    if sequences != tuple(sorted(sequences)) or len(sequences) != len(set(sequences)):
        message = "ready outbox records must have unique ascending sequences"
        raise ValueError(message)
    if any(
        record.published_at is not None
        or record.discarded_at is not None
        or record.available_at > request.claimed_at
        or record.claim_token != request.claim_token
        or record.claim_until != request.claim_until
        for record in typed_records
    ):
        message = "ready outbox query returned an unavailable or terminal record"
        raise ValueError(message)
    return typed_records


def _validate_published_confirmation(expected: OutboxRecord, confirmed: object, attempted_at: datetime) -> None:
    if not isinstance(confirmed, OutboxRecord):
        message = "OutboxStore.mark_outbox_published() must return an OutboxRecord"
        raise TypeError(message)
    confirmed_fields = (
        confirmed.message_id,
        confirmed.attempt_count,
        confirmed.last_attempt_at,
        confirmed.last_error_type,
        confirmed.last_error_message,
        confirmed.published_at,
        confirmed.discarded_at,
        confirmed.claim_token,
        confirmed.claim_until,
    )
    expected_fields = (
        expected.message_id,
        expected.attempt_count + 1,
        attempted_at,
        expected.last_error_type,
        expected.last_error_message,
        attempted_at,
        None,
        None,
        None,
    )
    if confirmed_fields != expected_fields:
        message = "outbox publication confirmation does not match the dispatched message"
        raise ValueError(message)


def _validate_failure_confirmation(
    expected: OutboxRecord,
    confirmed: object,
    update: OutboxFailureUpdate,
) -> OutboxRecord:
    if not isinstance(confirmed, OutboxRecord):
        message = "OutboxStore.record_outbox_failure() must return an OutboxRecord"
        raise TypeError(message)
    is_discarded = update.available_at is None
    expected_available_at = update.failed_at if is_discarded else update.available_at
    confirmed_fields = (
        confirmed.message_id,
        confirmed.attempt_count,
        confirmed.last_attempt_at,
        confirmed.last_error_type,
        confirmed.last_error_message,
        confirmed.available_at,
        confirmed.published_at,
        confirmed.claim_token,
        confirmed.claim_until,
    )
    expected_fields = (
        expected.message_id,
        expected.attempt_count + 1,
        update.failed_at,
        update.error_type,
        update.error_message,
        expected_available_at,
        None,
        None,
        None,
    )
    if confirmed_fields != expected_fields or (confirmed.discarded_at is not None) is not is_discarded:
        message = "outbox failure confirmation does not match the failed message"
        raise ValueError(message)
    return confirmed


class OutboxDispatcher:
    """有限批量投递 ready 消息；单条失败持久退避并隔离，不阻塞后续消息。"""

    __slots__ = ("_clock", "_publisher", "_retry_policy", "_store")

    def __init__(
        self,
        *,
        store: OutboxStore,
        publisher: OutboxPublisher,
        clock: OutboxClock,
        retry_policy: OutboxRetryPolicy = DEFAULT_OUTBOX_RETRY_POLICY,
    ) -> None:
        _require_method(store, "claim_ready_outbox", field_name="store")
        _require_method(store, "mark_outbox_published", field_name="store")
        _require_method(store, "record_outbox_failure", field_name="store")
        _require_method(publisher, "publish", field_name="publisher")
        _require_method(clock, "now", field_name="clock")
        if not isinstance(retry_policy, OutboxRetryPolicy):
            message = "retry_policy must be an OutboxRetryPolicy"
            raise TypeError(message)
        self._store = store
        self._publisher = publisher
        self._clock = clock
        self._retry_policy = retry_policy

    def dispatch_pending(self) -> OutboxDispatchResult:
        claimed_at = _aware_now(self._clock)
        request = OutboxClaimRequest(
            claim_token=uuid4().hex,
            claimed_at=claimed_at,
            claim_until=claimed_at + self._retry_policy.claim_ttl,
            limit=self._retry_policy.batch_size,
        )
        try:
            selected = _validate_ready_records(self._store.claim_ready_outbox(request), request=request)
        except Exception as error:
            raise OutboxLoadError(error) from error

        published: list[str] = []
        failures: list[OutboxFailureFact] = []
        for record in selected:
            try:
                self._publisher.publish(
                    topic=record.topic,
                    payload=record.payload,
                    key=record.key,
                    idempotency_key=record.message_id,
                )
            except Exception as error:  # noqa: BLE001 - publisher 是外部边界，失败必须持久化并隔离。
                logger.exception(
                    "Outbox publisher failed for message %s on topic %s",
                    record.message_id,
                    record.topic,
                )
                failures.append(
                    self._record_failure(
                        record,
                        error_type=type(error).__name__,
                        error_message=str(error),
                        is_permanent=isinstance(error, PermanentOutboxPublishError),
                    )
                )
                continue
            self._confirm_published(record)
            published.append(record.message_id)

        return OutboxDispatchResult(tuple(published), tuple(failures))

    def _confirm_published(self, record: OutboxRecord) -> None:
        attempted_at = _aware_now(self._clock)
        try:
            confirmed = self._store.mark_outbox_published(
                record.message_id,
                attempted_at,
                claim_token=cast("str", record.claim_token),
                expected_attempt_count=record.attempt_count,
            )
            _validate_published_confirmation(record, confirmed, attempted_at)
        except Exception as error:
            raise OutboxDispatchError(record.message_id, record.topic, "publication", error) from error

    def _record_failure(
        self,
        record: OutboxRecord,
        *,
        error_type: str,
        error_message: str,
        is_permanent: bool,
    ) -> OutboxFailureFact:
        failed_at = _aware_now(self._clock)
        attempt_count = record.attempt_count + 1
        update = OutboxFailureUpdate(
            message_id=record.message_id,
            claim_token=cast("str", record.claim_token),
            expected_attempt_count=record.attempt_count,
            failed_at=failed_at,
            error_type=error_type,
            error_message=error_message,
            available_at=(
                None
                if is_permanent
                else self._retry_policy.next_available_at(
                    failed_at=failed_at,
                    attempt_count=attempt_count,
                )
            ),
        )
        try:
            confirmed = _validate_failure_confirmation(
                record,
                self._store.record_outbox_failure(update),
                update,
            )
        except Exception as error:
            raise OutboxDispatchError(record.message_id, record.topic, "failure", error) from error
        return OutboxFailureFact(
            message_id=record.message_id,
            topic=record.topic,
            error_type=error_type,
            error_message=error_message,
            attempt_count=confirmed.attempt_count,
            available_at=confirmed.available_at,
            discarded_at=confirmed.discarded_at,
        )
