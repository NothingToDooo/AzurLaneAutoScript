import math
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from module.interaction.ports import CancellationSignal


class SystemClock:
    __slots__ = ("_sleep_quantum",)

    def __init__(self, *, sleep_quantum: float = 0.1) -> None:
        if not math.isfinite(sleep_quantum) or sleep_quantum <= 0:
            message = "sleep quantum must be a finite positive number"
            raise ValueError(message)
        self._sleep_quantum = sleep_quantum

    @staticmethod
    def monotonic() -> float:
        return time.monotonic()

    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)

    def sleep(self, seconds: float, cancellation: CancellationSignal) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            message = "sleep duration must be a finite non-negative number"
            raise ValueError(message)

        deadline = self.monotonic() + seconds
        while True:
            cancellation.raise_if_requested()
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, self._sleep_quantum))
