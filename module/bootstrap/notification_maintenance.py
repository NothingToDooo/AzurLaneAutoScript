from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from module.bootstrap.assembly_source import validate_instance_name
from module.logger import logger
from module.notify import LocalOutboxPublisher, NotificationFlushResult, NotificationSpool
from module.runtime import OutboxDispatcher, OutboxFailureFact
from module.state import SQLiteStateStore

if TYPE_CHECKING:
    from datetime import datetime


class NotificationMaintenanceClock(Protocol):
    def now(self) -> datetime: ...


def _report_source_failure(instance_name: str, failure: OutboxFailureFact) -> None:
    logger.error(
        "Notification source outbox routing failed "
        f"instance={instance_name!r} message_id={failure.message_id!r} "
        f"topic={failure.topic!r} error_type={failure.error_type!r} "
        f"attempt_count={failure.attempt_count} discarded={failure.is_discarded}"
    )


class ProductionNotificationMaintenance:
    """周期接管所有 instance outbox，再有界推进全局通知 spool。"""

    __slots__ = ("_clock", "_spool", "_state_root")

    def __init__(
        self,
        *,
        state_root: Path,
        spool: NotificationSpool,
        clock: NotificationMaintenanceClock,
    ) -> None:
        if not isinstance(state_root, Path):
            message = "state_root must be a Path"
            raise TypeError(message)
        if not isinstance(spool, NotificationSpool):
            message = "spool must be a NotificationSpool"
            raise TypeError(message)
        if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
            message = "clock must implement now()"
            raise TypeError(message)
        self._state_root = state_root
        self._spool = spool
        self._clock = clock

    def flush(
        self,
        *,
        instance_name: str | None = None,
        max_intents: int = 32,
        max_deliveries: int = 4,
    ) -> NotificationFlushResult:
        for name, state_path in self._state_paths(instance_name):
            self._route_instance(name, state_path)
        return self._spool.flush(
            instance_name=instance_name,
            max_intents=max_intents,
            max_deliveries=max_deliveries,
        )

    def close(self) -> None:
        self._spool.close()

    def _state_paths(self, instance_name: str | None) -> tuple[tuple[str, Path], ...]:
        if instance_name is not None:
            name = validate_instance_name(instance_name)
            path = self._state_root / f"{name}.sqlite3"
            return ((name, path),) if path.is_file() else ()
        if not self._state_root.is_dir():
            return ()
        paths: list[tuple[str, Path]] = []
        try:
            candidates = sorted(self._state_root.glob("*.sqlite3"))
        except OSError as error:
            logger.error(f"Notification state discovery failed ({type(error).__name__})")
            return ()
        for path in candidates:
            try:
                name = validate_instance_name(path.stem)
            except TypeError, ValueError:
                logger.error("Notification state discovery skipped an invalid instance filename")
                continue
            paths.append((name, path))
        return tuple(paths)

    def _route_instance(self, instance_name: str, state_path: Path) -> None:
        try:
            with SQLiteStateStore(state_path) as store:
                result = OutboxDispatcher(
                    store=store,
                    publisher=LocalOutboxPublisher(instance_name, self._spool),
                    clock=self._clock,
                ).dispatch_pending()
        except Exception as error:  # noqa: BLE001 - 单实例状态损坏不能阻断其他实例或全局 spool。
            logger.error(f"Notification source outbox maintenance failed ({type(error).__name__})")
            return
        for failure in result.failures:
            _report_source_failure(instance_name, failure)
