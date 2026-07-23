import random
import re
from contextlib import suppress
from functools import cached_property, wraps
from typing import TYPE_CHECKING, Protocol

from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable


class _HasInstanceDict(Protocol):
    __dict__: dict[str, object]


class _NamedCallable[R, **P](Protocol):
    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...


__all__ = (
    "cached_property",
    "del_cached_property",
    "function_drop",
    "has_cached_property",
    "run_once",
)


def del_cached_property(obj: _HasInstanceDict, name: str) -> None:
    with suppress(KeyError):
        del obj.__dict__[name]


def has_cached_property(obj: _HasInstanceDict, name: str) -> bool:
    return name in obj.__dict__


def function_drop[R, **P](
    rate: float = 0.5, default: R | None = None
) -> Callable[[_NamedCallable[R, P]], Callable[P, R | None]]:
    """按 0～1 的 rate 随机丢弃调用，用于模拟器卡顿测试；丢弃时返回 default。"""

    def decorate(func: _NamedCallable[R, P]) -> Callable[P, R | None]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
            if random.uniform(0, 1) > rate:  # ruff:ignore[suspicious-non-cryptographic-random-usage] - 仅用于模拟卡顿。
                return func(*args, **kwargs)
            cls = ""
            arguments = [str(arg) for arg in args]
            if arguments:
                matched = re.search(r"<(.*?) object at", arguments[0])
                if matched:
                    cls = matched.group(1) + "."
                    arguments.pop(0)
            arguments += [f"{k}={v}" for k, v in kwargs.items()]
            arguments = ", ".join(arguments)
            logger.info(f"Dropped: {cls}{func.__name__}({arguments})")
            return default

        return wrapper

    return decorate


def run_once[R, **P](f: Callable[P, R]) -> Callable[P, R | None]:
    """仅执行首次调用；后续调用返回 None。"""
    has_run = False

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        nonlocal has_run
        if not has_run:
            has_run = True
            return f(*args, **kwargs)
        return None

    return wrapper
