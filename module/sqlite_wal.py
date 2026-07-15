import sqlite3
import time
from typing import Final

_SETUP_BUSY_TIMEOUT_MS: Final = 250
_STEADY_BUSY_TIMEOUT_MS: Final = 5000
_WAL_ENABLE_ATTEMPTS: Final = 8
_WAL_RETRY_BASE_SECONDS: Final = 0.01
_WAL_RETRY_CAP_SECONDS: Final = 0.25
_SQLITE_BUSY_CODES: Final = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})


def _is_sqlite_busy(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return isinstance(code, int) and (code & 0xFF) in _SQLITE_BUSY_CODES


def _journal_mode(row: sqlite3.Row | tuple[object, ...] | None) -> str | None:
    if row is None or not row:
        return None
    value = row[0]
    return value.casefold() if isinstance(value, str) else None


def configure_sqlite_wal(connection: sqlite3.Connection) -> str | None:
    """并发安全地启用 WAL，返回 SQLite 最终报告的 journal mode。"""

    if not isinstance(connection, sqlite3.Connection):
        message = "connection must be a sqlite3.Connection"
        raise TypeError(message)

    # journal_mode 切换在部分 SQLite 构建中不会完整遵循 connect timeout；
    # 用短 busy window + 有界重试覆盖多个进程首次打开同一数据库的竞态。
    connection.execute(f"PRAGMA busy_timeout = {_SETUP_BUSY_TIMEOUT_MS}")
    try:
        for attempt in range(_WAL_ENABLE_ATTEMPTS):
            try:
                current = _journal_mode(connection.execute("PRAGMA journal_mode").fetchone())
                if current == "wal":
                    return current
                selected = _journal_mode(connection.execute("PRAGMA journal_mode = WAL").fetchone())
            except sqlite3.OperationalError as error:
                if not _is_sqlite_busy(error) or attempt + 1 == _WAL_ENABLE_ATTEMPTS:
                    raise
                delay = min(_WAL_RETRY_BASE_SECONDS * (2**attempt), _WAL_RETRY_CAP_SECONDS)
                time.sleep(delay)
            else:
                return selected
        message = "unreachable WAL retry state"
        raise AssertionError(message)
    finally:
        connection.execute(f"PRAGMA busy_timeout = {_STEADY_BUSY_TIMEOUT_MS}")
