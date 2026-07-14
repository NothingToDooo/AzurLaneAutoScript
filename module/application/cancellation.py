import threading
from typing import Protocol

from module.application._validation import validate_optional_reason


class ExternalRequestSignal(Protocol):
    def is_set(self) -> bool: ...


class CancellationSource(Protocol):
    def raise_if_requested(self) -> None: ...


def _validate_external_signal(signal: ExternalRequestSignal | None) -> None:
    if signal is not None and (isinstance(signal, type) or not callable(getattr(signal, "is_set", None))):
        message = "external_signal must implement is_set()"
        raise TypeError(message)


class _OneShotSignal:
    __slots__ = ("_event", "_external_reason", "_external_signal", "_lock", "_reason")

    def __init__(
        self,
        *,
        external_signal: ExternalRequestSignal | None = None,
        external_reason: str | None = None,
    ) -> None:
        _validate_external_signal(external_signal)
        validate_optional_reason(external_reason)
        self._event = threading.Event()
        self._external_signal = external_signal
        self._external_reason = external_reason
        self._lock = threading.Lock()
        self._reason: str | None = None

    @property
    def is_requested(self) -> bool:
        if self._event.is_set():
            return True
        external_signal = self._external_signal
        return external_signal is not None and external_signal.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            if self._event.is_set():
                return self._reason
        external_signal = self._external_signal
        if external_signal is not None and external_signal.is_set():
            return self._external_reason
        return None

    def request(self, reason: str | None = None) -> bool:
        validate_optional_reason(reason)
        with self._lock:
            if self._event.is_set() or (self._external_signal is not None and self._external_signal.is_set()):
                return False
            self._reason = reason
            self._event.set()
            return True


class AbortRequested(Exception):
    def __init__(self, reason: str | None = None) -> None:
        validate_optional_reason(reason)
        self.reason = reason
        super().__init__(reason or "abort requested")


class AbortToken:
    __slots__ = ("_signal",)

    def __init__(
        self,
        *,
        external_signal: ExternalRequestSignal | None = None,
        external_reason: str | None = "external abort requested",
    ) -> None:
        self._signal = _OneShotSignal(
            external_signal=external_signal,
            external_reason=external_reason,
        )

    @property
    def is_requested(self) -> bool:
        return self._signal.is_requested

    @property
    def reason(self) -> str | None:
        return self._signal.reason

    def request(self, reason: str | None = None) -> bool:
        return self._signal.request(reason)

    def raise_if_requested(self) -> None:
        if self.is_requested:
            raise AbortRequested(self.reason)


class SafeUnitCancellation:
    """安全单元开始前可取消；提交后把新请求延迟到单元闭合。"""

    __slots__ = ("_committed", "_lock", "_source")

    def __init__(self, source: CancellationSource) -> None:
        self._source = source
        self._lock = threading.Lock()
        self._committed = False

    @property
    def committed(self) -> bool:
        with self._lock:
            return self._committed

    def commit(self) -> bool:
        with self._lock:
            if self._committed:
                return False
            self._source.raise_if_requested()
            self._committed = True
            return True

    def raise_if_requested(self) -> None:
        with self._lock:
            if self._committed:
                return
            self._source.raise_if_requested()


class PreemptionRequest:
    __slots__ = ("_signal",)

    def __init__(
        self,
        *,
        external_signal: ExternalRequestSignal | None = None,
        external_reason: str | None = "external preemption requested",
    ) -> None:
        self._signal = _OneShotSignal(
            external_signal=external_signal,
            external_reason=external_reason,
        )

    @property
    def is_requested(self) -> bool:
        return self._signal.is_requested

    @property
    def reason(self) -> str | None:
        return self._signal.reason

    def request(self, reason: str | None = None) -> bool:
        return self._signal.request(reason)
