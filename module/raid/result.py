from dataclasses import dataclass

from module.content.activity_profile import RaidMode
from module.raid.profile import RaidAttemptSource


@dataclass(frozen=True, slots=True)
class RaidAttemptStatus:
    mode: RaidMode
    source: RaidAttemptSource
    remaining: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RaidMode):
            message = "mode must be a RaidMode"
            raise TypeError(message)
        if not isinstance(self.source, RaidAttemptSource):
            message = "source must be a RaidAttemptSource"
            raise TypeError(message)
        if self.source is RaidAttemptSource.UNMETERED:
            if self.remaining is not None:
                message = "unmetered raid status must not have remaining attempts"
                raise ValueError(message)
            return
        if type(self.remaining) is not int:
            message = "metered raid status must have an integer remaining count"
            raise TypeError(message)
        if self.remaining < 0:
            message = "remaining attempts must not be negative"
            raise ValueError(message)

    @property
    def exhausted(self) -> bool:
        return self.remaining == 0


@dataclass(frozen=True, slots=True)
class RaidExecutionResult:
    mode: RaidMode
    runs_completed: int

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RaidMode):
            message = "mode must be a RaidMode"
            raise TypeError(message)
        if self.runs_completed != 1:
            message = "an atomic raid execution must complete exactly one run"
            raise ValueError(message)
