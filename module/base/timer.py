from datetime import datetime, timedelta
from functools import wraps
from time import sleep, time
from typing import TYPE_CHECKING, Protocol, Self

from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable


class _NamedCallable[R, **P](Protocol):
    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...


def timer[R, **P](function: _NamedCallable[R, P]) -> Callable[P, R]:
    """记录函数执行耗时，仅用于调试和生成流程。"""

    @wraps(function)
    def function_timer(*args: P.args, **kwargs: P.kwargs) -> R:
        start = time()
        result = function(*args, **kwargs)
        cost = time() - start
        logger.info(f"{function.__name__}: {cost:.10f} s")
        return result

    return function_timer


def future_time(string: str) -> datetime:
    hour, minute = [int(x) for x in string.split(":")]
    now = datetime.now()
    future = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if future < now:
        return future + timedelta(days=1)
    return future


class Timer:
    def __init__(self, limit: float, count: int = 0) -> None:
        """同时按秒数 limit 和访问次数 count 判定，避免慢设备仅凭截图耗时提前触发。"""
        self.limit = limit
        self.count = count
        self._start = 0.0
        self._access = 0

    @classmethod
    def from_seconds(cls, limit: float, speed: float = 0.5) -> Self:
        """按估计的单次截图耗时 speed 换算访问次数。"""
        count = int(limit / speed)
        return cls(limit, count=count)

    def start(self) -> Self:
        if self._start <= 0:
            self._start = time()
            self._access = 0

        return self

    def started(self) -> bool:
        return self._start > 0

    def current_time(self) -> float:
        if self._start > 0:
            diff = time() - self._start
            if diff < 0:
                diff = 0.0
            return diff
        return 0.0

    def current_count(self) -> int:
        return self._access

    def reached(self) -> bool:
        """每次调用计一次访问；未启动时返回 True，以允许首次立即执行。"""
        self._access += 1
        if self._start > 0:
            return self._access > self.count and time() - self._start > self.limit
        return True

    def reset(self) -> Self:
        self._start = time()
        self._access = 0
        return self

    def clear(self) -> Self:
        self._start = 0.0
        self._access = self.count
        return self

    def reached_and_reset(self) -> bool:
        if self.reached():
            self.reset()
            return True
        return False

    def wait(self) -> None:
        diff = self._start + self.limit - time()
        if diff > 0:
            sleep(diff)

    def show(self) -> None:
        logger.info(str(self))

    def __str__(self) -> str:
        return f"Timer(limit={round(self.current_time(), 3)}/{self.limit}, count={self._access}/{self.count})"

    __repr__ = __str__
