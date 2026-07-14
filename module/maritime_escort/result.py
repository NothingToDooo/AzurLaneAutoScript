from dataclasses import dataclass
from enum import StrEnum


class MaritimeEscortExecutionStatus(StrEnum):
    WITHDRAWAL_COMPLETED = "withdrawal_completed"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


@dataclass(frozen=True, slots=True)
class MaritimeEscortExecutionResult:
    status: MaritimeEscortExecutionStatus

    def __post_init__(self) -> None:
        if not isinstance(self.status, MaritimeEscortExecutionStatus):
            message = "status must be a MaritimeEscortExecutionStatus"
            raise TypeError(message)
