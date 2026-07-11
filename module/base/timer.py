from datetime import datetime, timedelta
from functools import wraps
from time import sleep, time
from typing import Self

from module.logger import logger


def timer(function):
    """记录函数执行耗时，仅用于调试和生成流程。"""

    @wraps(function)
    def function_timer(*args, **kwargs):
        start = time()
        result = function(*args, **kwargs)
        cost = time() - start
        logger.info(f"{function.__name__}: {cost:.10f} s")
        return result

    return function_timer


def future_time(string):
    hour, minute = [int(x) for x in string.split(":")]
    now = datetime.now()
    future = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if future < now:
        return future + timedelta(days=1)
    return future


def past_time(string):
    hour, minute = [int(x) for x in string.split(":")]
    now = datetime.now()
    past = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if past > now:
        return past - timedelta(days=1)
    return past


def future_time_range(string):
    """把 `23:30-06:30` 转为未来起止时间；跨午夜时起点落在前一天。"""
    start, end = [future_time(s) for s in string.split("-")]
    if start > end:
        start -= timedelta(days=1)
    return start, end


def time_range_active(time_range):
    return time_range[0] < datetime.now() < time_range[1]


class Timer:
    def __init__(self, limit, count=0):
        """同时按秒数 limit 和访问次数 count 判定，避免慢设备仅凭截图耗时提前触发。"""
        self.limit = limit
        self.count = count
        self._start = 0.0
        self._access = 0

    @classmethod
    def from_seconds(cls, limit, speed=0.5) -> Self:
        """按估计的单次截图耗时 speed 换算访问次数。"""
        count = int(limit / speed)
        return cls(limit, count=count)

    def start(self):
        if self._start <= 0:
            self._start = time()
            self._access = 0

        return self

    def started(self):
        return self._start > 0

    def current_time(self):
        if self._start > 0:
            diff = time() - self._start
            if diff < 0:
                diff = 0.0
            return diff
        return 0.0

    def current_count(self):
        return self._access

    def add_count(self):
        self._access += 1
        return self

    def reached(self):
        """每次调用计一次访问；未启动时返回 True，以允许首次立即执行。"""
        self._access += 1
        if self._start > 0:
            return self._access > self.count and time() - self._start > self.limit
        return True

    def reset(self):
        self._start = time()
        self._access = 0
        return self

    def clear(self):
        self._start = 0.0
        self._access = self.count
        return self

    def reached_and_reset(self):
        if self.reached():
            self.reset()
            return True
        return False

    def wait(self):
        diff = self._start + self.limit - time()
        if diff > 0:
            sleep(diff)

    def show(self):
        logger.info(str(self))

    def __str__(self):
        return f"Timer(limit={round(self.current_time(), 3)}/{self.limit}, count={self._access}/{self.count})"

    __repr__ = __str__
