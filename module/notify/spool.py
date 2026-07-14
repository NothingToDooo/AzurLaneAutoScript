from __future__ import annotations

import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol, cast
from uuid import uuid4

from module.notify.configuration import DisabledNotificationConfig, SmtpNotificationConfig
from module.notify.notify import SmtpNotificationSender
from module.notify.spool_models import (
    NotificationDelivery,
    NotificationDeliveryRetry,
    NotificationDeliveryWork,
    NotificationFailureKind,
    NotificationFlushResult,
    NotificationIntent,
    NotificationIntentDraft,
)
from module.notify.spool_store import NotificationSpoolStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType
    from typing import Self

    from module.notify.configuration import NotificationConfig

_DEFAULT_MAX_INTENTS = 32
_DEFAULT_MAX_DELIVERIES = 32


class NotificationClock(Protocol):
    def now(self) -> datetime: ...


class RecipientNotificationSender(Protocol):
    def send(
        self,
        *,
        recipient: str,
        title: str,
        content: str,
        idempotency_key: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class NotificationSpoolPolicy:
    retry_base: timedelta = timedelta(minutes=1)
    retry_cap: timedelta = timedelta(hours=6)
    claim_lease: timedelta = timedelta(minutes=5)
    max_attempts: int = 8

    def __post_init__(self) -> None:
        for field_name, value in (
            ("retry_base", self.retry_base),
            ("retry_cap", self.retry_cap),
            ("claim_lease", self.claim_lease),
        ):
            if not isinstance(value, timedelta) or value <= timedelta(0):
                message = f"{field_name} must be a positive timedelta"
                raise ValueError(message)
        if self.retry_cap < self.retry_base:
            message = "retry_cap must be at least retry_base"
            raise ValueError(message)
        if type(self.max_attempts) is not int or self.max_attempts <= 0:
            message = "max_attempts must be a positive integer"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class _DeliveryFailure:
    kind: NotificationFailureKind
    smtp_status_code: int | None
    permanent: bool


@dataclass(frozen=True, slots=True)
class _PlanningCounts:
    planned: int = 0
    suppressed: int = 0
    deferred: int = 0


@dataclass(frozen=True, slots=True)
class _DeliveryCounts:
    delivered: int = 0
    retried: int = 0
    dead_lettered: int = 0
    suppressed: int = 0


def _aware_now(clock: NotificationClock) -> datetime:
    now = clock.now()
    if not isinstance(now, datetime):
        message = "NotificationClock.now() must return a datetime"
        raise TypeError(message)
    if now.utcoffset() is None:
        message = "NotificationClock.now() must return a timezone-aware datetime"
        raise ValueError(message)
    return now


def _require_positive(value: int, *, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        message = f"{field_name} must be a positive integer"
        raise ValueError(message)


def _smtp_status_code(error: BaseException, recipient: str) -> int | None:
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        refused: object = error.recipients.get(recipient)
        if refused is None and error.recipients:
            refused = next(iter(error.recipients.values()))
        if isinstance(refused, tuple) and refused and type(refused[0]) is int:
            return refused[0]
    if isinstance(error, smtplib.SMTPResponseException) and type(error.smtp_code) is int:
        return error.smtp_code
    return None


def _classify_delivery_failure(error: BaseException, recipient: str) -> _DeliveryFailure:
    status_code = _smtp_status_code(error, recipient)
    if status_code is not None:
        if 500 <= status_code <= 599:
            return _DeliveryFailure(NotificationFailureKind.SMTP_PERMANENT, status_code, permanent=True)
        if 400 <= status_code <= 499:
            return _DeliveryFailure(NotificationFailureKind.SMTP_TRANSIENT, status_code, permanent=False)
    if isinstance(error, (OSError, TimeoutError, smtplib.SMTPServerDisconnected)):
        return _DeliveryFailure(NotificationFailureKind.NETWORK, None, permanent=False)
    return _DeliveryFailure(NotificationFailureKind.UNKNOWN, status_code, permanent=False)


def _require_sender(value: object) -> RecipientNotificationSender:
    if isinstance(value, type) or not callable(getattr(value, "send", None)):
        message = "sender_factory must return a RecipientNotificationSender"
        raise TypeError(message)
    return cast("RecipientNotificationSender", value)


class NotificationSpool:
    """持久化通知意图，规划每个收件人的 delivery，并执行有租约的有界投递。"""

    __slots__ = ("_clock", "_config_source", "_policy", "_sender_factory", "_store")

    def __init__(
        self,
        *,
        store: NotificationSpoolStore,
        config_source: Callable[[str], NotificationConfig],
        clock: NotificationClock,
        sender_factory: Callable[[SmtpNotificationConfig], RecipientNotificationSender] = SmtpNotificationSender,
        policy: NotificationSpoolPolicy | None = None,
    ) -> None:
        if not isinstance(store, NotificationSpoolStore):
            message = "store must be a NotificationSpoolStore"
            raise TypeError(message)
        if not callable(config_source):
            message = "config_source must be callable"
            raise TypeError(message)
        if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
            message = "clock must implement now()"
            raise TypeError(message)
        if not callable(sender_factory):
            message = "sender_factory must be callable"
            raise TypeError(message)
        if policy is None:
            policy = NotificationSpoolPolicy()
        if not isinstance(policy, NotificationSpoolPolicy):
            message = "policy must be a NotificationSpoolPolicy"
            raise TypeError(message)
        self._store = store
        self._config_source = config_source
        self._clock = clock
        self._sender_factory = sender_factory
        self._policy = policy

    @property
    def store(self) -> NotificationSpoolStore:
        return self._store

    def close(self) -> None:
        self._store.close()

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

    def enqueue_intent(self, draft: NotificationIntentDraft) -> NotificationIntent:
        return self._store.enqueue_intent(draft, created_at=_aware_now(self._clock))

    def flush(
        self,
        *,
        instance_name: str | None = None,
        max_intents: int = _DEFAULT_MAX_INTENTS,
        max_deliveries: int = _DEFAULT_MAX_DELIVERIES,
    ) -> NotificationFlushResult:
        _require_positive(max_intents, field_name="max_intents")
        _require_positive(max_deliveries, field_name="max_deliveries")
        planning = self._plan_due(
            instance_name=instance_name,
            max_intents=max_intents,
        )
        delivery = self._deliver_due(
            instance_name=instance_name,
            max_deliveries=max_deliveries,
        )
        return NotificationFlushResult(
            planned_intents=planning.planned,
            suppressed_intents=planning.suppressed,
            deferred_intents=planning.deferred,
            delivered=delivery.delivered,
            retried=delivery.retried,
            dead_lettered=delivery.dead_lettered,
            suppressed_deliveries=delivery.suppressed,
        )

    def list_dead_letters(
        self,
        *,
        limit: int = 100,
        instance_name: str | None = None,
    ) -> tuple[NotificationDeliveryWork, ...]:
        return self._store.list_dead_letters(limit=limit, instance_name=instance_name)

    def retry_delivery(self, delivery_id: str) -> NotificationDelivery:
        return self._store.retry_delivery(delivery_id, now=_aware_now(self._clock))

    def _plan_due(
        self,
        *,
        instance_name: str | None,
        max_intents: int,
    ) -> _PlanningCounts:
        planned = suppressed = deferred = 0
        for _ in range(max_intents):
            now = _aware_now(self._clock)
            claim_token = f"notification-plan-claim:{uuid4().hex}"
            intents = self._store.claim_due_intents(
                due_at=now,
                limit=1,
                claim_token=claim_token,
                claim_until=now + self._policy.claim_lease,
                instance_name=instance_name,
            )
            if not intents:
                break
            intent = intents[0]
            try:
                config = self._config_source(intent.instance_name)
            except Exception:  # noqa: BLE001 - 配置适配器边界必须归一化任意第三方错误。
                self._defer_intent(
                    intent,
                    claim_token=claim_token,
                    now=now,
                    failure_kind=NotificationFailureKind.CONFIGURATION,
                )
                deferred += 1
                continue
            if isinstance(config, DisabledNotificationConfig):
                self._store.suppress_intent(intent.intent_id, claim_token=claim_token, suppressed_at=now)
                suppressed += 1
                continue
            if not isinstance(config, SmtpNotificationConfig):
                self._defer_intent(
                    intent,
                    claim_token=claim_token,
                    now=now,
                    failure_kind=NotificationFailureKind.CONFIGURATION,
                )
                deferred += 1
                continue
            recipients = tuple(dict.fromkeys(config.recipients))
            self._store.plan_intent(
                intent.intent_id,
                recipients,
                claim_token=claim_token,
                planned_at=now,
            )
            planned += 1
        return _PlanningCounts(planned=planned, suppressed=suppressed, deferred=deferred)

    def _deliver_due(
        self,
        *,
        instance_name: str | None,
        max_deliveries: int,
    ) -> _DeliveryCounts:
        delivered = retried = dead_lettered = suppressed = 0
        for _ in range(max_deliveries):
            now = _aware_now(self._clock)
            claim_token = f"notification-claim:{uuid4().hex}"
            claimed = self._store.claim_due_deliveries(
                due_at=now,
                limit=1,
                claim_token=claim_token,
                claim_until=now + self._policy.claim_lease,
                instance_name=instance_name,
            )
            if not claimed:
                break
            disposition = self._deliver_one(claimed[0], claim_token=claim_token, attempted_at=now)
            if disposition == "delivered":
                delivered += 1
            elif disposition == "retried":
                retried += 1
            elif disposition == "dead_lettered":
                dead_lettered += 1
            else:
                suppressed += 1
        return _DeliveryCounts(
            delivered=delivered,
            retried=retried,
            dead_lettered=dead_lettered,
            suppressed=suppressed,
        )

    def _deliver_one(
        self,
        work: NotificationDeliveryWork,
        *,
        claim_token: str,
        attempted_at: datetime,
    ) -> str:
        try:
            config = self._config_source(work.instance_name)
        except Exception:  # noqa: BLE001 - 配置错误正文可能包含凭据，只记录安全分类。
            failure = _DeliveryFailure(NotificationFailureKind.CONFIGURATION, None, permanent=False)
        else:
            if isinstance(config, DisabledNotificationConfig):
                self._store.mark_suppressed(
                    work.delivery.delivery_id,
                    claim_token=claim_token,
                    suppressed_at=attempted_at,
                )
                return "suppressed"
            if not isinstance(config, SmtpNotificationConfig):
                failure = _DeliveryFailure(NotificationFailureKind.CONFIGURATION, None, permanent=False)
            else:
                try:
                    sender = _require_sender(self._sender_factory(config))
                    sender.send(
                        recipient=work.delivery.recipient,
                        title=work.subject,
                        content=work.body,
                        idempotency_key=work.delivery.delivery_id,
                    )
                except Exception as error:  # noqa: BLE001 - SMTP 适配器边界必须归一化任意第三方错误。
                    failure = _classify_delivery_failure(error, work.delivery.recipient)
                else:
                    self._store.mark_delivered(
                        work.delivery.delivery_id,
                        claim_token=claim_token,
                        delivered_at=attempted_at,
                    )
                    return "delivered"
        completed_attempts = work.delivery.attempt_count + 1
        if failure.permanent or completed_attempts >= self._policy.max_attempts:
            self._store.mark_dead_letter(
                work.delivery.delivery_id,
                claim_token=claim_token,
                dead_lettered_at=attempted_at,
                failure_kind=failure.kind,
                smtp_status_code=failure.smtp_status_code,
            )
            return "dead_lettered"
        next_attempt_at = self._next_attempt_at(attempted_at, completed_attempts=completed_attempts)
        self._store.mark_retry(
            work.delivery.delivery_id,
            claim_token=claim_token,
            retry=NotificationDeliveryRetry(
                attempted_at=attempted_at,
                next_attempt_at=next_attempt_at,
                failure_kind=failure.kind,
                smtp_status_code=failure.smtp_status_code,
            ),
        )
        return "retried"

    def _defer_intent(
        self,
        intent: NotificationIntent,
        *,
        claim_token: str,
        now: datetime,
        failure_kind: NotificationFailureKind,
    ) -> None:
        next_attempt_at = self._next_attempt_at(now, completed_attempts=intent.plan_attempt_count + 1)
        self._store.defer_intent(
            intent.intent_id,
            claim_token=claim_token,
            attempted_at=now,
            next_attempt_at=next_attempt_at,
            failure_kind=failure_kind,
        )

    def _next_attempt_at(self, now: datetime, *, completed_attempts: int) -> datetime:
        exponent = min(max(completed_attempts - 1, 0), 30)
        delay = min(self._policy.retry_base * (2**exponent), self._policy.retry_cap)
        return now + delay
