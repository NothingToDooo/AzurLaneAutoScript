from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence


def raise_cleanup_errors(errors: Sequence[BaseException], *, message: str) -> None:
    """清理链单错原样抛出，多错按发生顺序完整保留。"""

    if not errors:
        return
    if len(errors) == 1:
        raise errors[0]
    raise BaseExceptionGroup(message, tuple(errors))


def preserve_cleanup_failure(
    primary_error: BaseException,
    cleanup: Callable[[], None],
    *,
    message: str,
) -> None:
    """执行失败清理；清理也失败时同时保留 primary 与 cleanup 根因。"""

    try:
        cleanup()
    except BaseException as cleanup_error:  # ruff:ignore[blind-except] - 清理必须覆盖取消和进程退出类异常。
        raise BaseExceptionGroup(message, (primary_error, cleanup_error)) from None


@contextmanager
def cleanup_scope(
    cleanup: Callable[[], None],
    *,
    message: str,
) -> Iterator[None]:
    """离开作用域时清理；body 与 cleanup 双失败时保留两个根因。"""

    try:
        yield
    except BaseException as primary_error:
        preserve_cleanup_failure(primary_error, cleanup, message=message)
        raise
    else:
        cleanup()
