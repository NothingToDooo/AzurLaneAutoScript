import threading
from typing import TYPE_CHECKING, Protocol, Self, cast

from module.logger import logger

if TYPE_CHECKING:
    from types import TracebackType


class NotificationFlushSession(Protocol):
    def flush(
        self,
        *,
        instance_name: str | None = None,
        max_intents: int = 32,
        max_deliveries: int = 4,
    ) -> object: ...

    def close(self) -> None: ...


class NotificationFlushSessionFactory(Protocol):
    def __call__(self) -> NotificationFlushSession: ...


def _positive_number(value: float, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        message = f"{field_name} must be a positive number"
        raise ValueError(message)
    return float(value)


def _positive_integer(value: int, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        message = f"{field_name} must be a positive integer"
        raise ValueError(message)
    return value


def _optional_instance_name(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        message = "instance_name must be a string or None"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = "instance_name must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)
    return value


def _require_session(value: object) -> NotificationFlushSession:
    if isinstance(value, type) or not all(callable(getattr(value, method, None)) for method in ("flush", "close")):
        message = "session_factory must return a NotificationFlushSession"
        raise TypeError(message)
    return cast("NotificationFlushSession", value)


class NotificationSpoolPump:
    """长寿命宿主的通知维护 owner；每轮使用独立连接并隔离旁路失败。"""

    __slots__ = (
        "_instance_name",
        "_interval_seconds",
        "_lock",
        "_max_deliveries",
        "_max_intents",
        "_restart_requested",
        "_session_factory",
        "_shutdown_timeout_seconds",
        "_stop_event",
        "_thread",
    )

    def __init__(  # noqa: PLR0913 - 调度周期、批次预算与退出期限是彼此独立的策略参数。
        self,
        session_factory: NotificationFlushSessionFactory,
        *,
        instance_name: str | None = None,
        interval_seconds: float = 30.0,
        max_intents: int = 32,
        max_deliveries: int = 4,
        shutdown_timeout_seconds: float = 2.0,
    ) -> None:
        if not callable(session_factory):
            message = "session_factory must be callable"
            raise TypeError(message)
        self._session_factory = session_factory
        self._instance_name = _optional_instance_name(instance_name)
        self._interval_seconds = _positive_number(interval_seconds, field_name="interval_seconds")
        self._max_intents = _positive_integer(max_intents, field_name="max_intents")
        self._max_deliveries = _positive_integer(max_deliveries, field_name="max_deliveries")
        self._shutdown_timeout_seconds = _positive_number(
            shutdown_timeout_seconds,
            field_name="shutdown_timeout_seconds",
        )
        self._lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._restart_requested = False

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.stop()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop_event is not None and self._stop_event.is_set():
                    self._restart_requested = True
                return
            self._start_locked()

    def stop(self) -> None:
        with self._lock:
            self._restart_requested = False
            stop_event = self._stop_event
            thread = self._thread
        if stop_event is None or thread is None:
            return
        stop_event.set()
        thread.join(timeout=self._shutdown_timeout_seconds)
        if thread.is_alive():
            logger.warning("Notification spool pump did not stop before its bounded shutdown deadline")
            return
        with self._lock:
            if self._thread is thread:
                self._thread = None
                self._stop_event = None

    def run_once(self) -> None:
        session: NotificationFlushSession | None = None
        try:
            session = _require_session(self._session_factory())
            session.flush(
                instance_name=self._instance_name,
                max_intents=self._max_intents,
                max_deliveries=self._max_deliveries,
            )
        except Exception as error:  # noqa: BLE001 - 后台通知旁路不能终止宿主。
            logger.exception(error)
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception as close_error:  # noqa: BLE001 - 清理失败后下一轮使用新连接。
                    logger.exception(close_error)

    def _start_locked(self) -> None:
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run,
            args=(stop_event,),
            daemon=True,
            name="notification-spool-pump",
        )
        self._restart_requested = False
        self._stop_event = stop_event
        self._thread = thread
        thread.start()

    def _run(self, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                self.run_once()
                if stop_event.wait(self._interval_seconds):
                    return
        finally:
            current = threading.current_thread()
            with self._lock:
                if self._thread is current:
                    self._thread = None
                    self._stop_event = None
                    if self._restart_requested:
                        self._start_locked()
