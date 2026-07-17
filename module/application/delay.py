import random
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class DelayRange:
    """以整秒保存可在运行时采样的闭区间延迟。"""

    lower_seconds: int
    upper_seconds: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("lower_seconds", self.lower_seconds),
            ("upper_seconds", self.upper_seconds),
        ):
            if type(value) is not int:
                message = f"{field_name} must be an integer"
                raise TypeError(message)
            if value <= 0:
                message = f"{field_name} must be positive"
                raise ValueError(message)
        if self.lower_seconds > self.upper_seconds:
            message = "lower_seconds must not exceed upper_seconds"
            raise ValueError(message)


class DelaySampler:
    """按旧调度语义对闭区间做三次均匀整数采样并取均值。"""

    __slots__ = ("_randint",)

    def __init__(self, randint: Callable[[int, int], int] | None = None) -> None:
        default_randint = random.randint  # ruff:ignore[suspicious-non-cryptographic-random-usage] - 仅用于等待扰动。
        selected = default_randint if randint is None else randint
        if not callable(selected):
            message = "randint must be callable"
            raise TypeError(message)
        self._randint = selected

    def sample(self, delay: DelayRange) -> timedelta:
        if not isinstance(delay, DelayRange):
            message = "delay must be a DelayRange"
            raise TypeError(message)
        if delay.lower_seconds == delay.upper_seconds:
            return timedelta(seconds=delay.lower_seconds)
        total = sum(self._draw(delay) for _ in range(3))
        return timedelta(seconds=round(total / 3))

    def _draw(self, delay: DelayRange) -> int:
        value = self._randint(delay.lower_seconds, delay.upper_seconds)
        if type(value) is not int or not delay.lower_seconds <= value <= delay.upper_seconds:
            message = "randint must return an integer within the requested bounds"
            raise RuntimeError(message)
        return value


runtime_delay_sampler = DelaySampler()
