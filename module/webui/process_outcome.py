from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from datetime import datetime


class ProcessOutcomeStatus(StrEnum):
    FINISHED = "finished"
    FAILED = "failed"
    MANUAL_STOP = "manual_stop"
    KILLED = "killed"
    RESTART_REQUESTED = "restart_requested"


class ProcessOutcomeData(TypedDict):
    status: str
    config_name: str
    command: str
    exception_type: str | None
    message: str | None
    finished_at: str


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    status: ProcessOutcomeStatus
    config_name: str
    command: str
    exception_type: str | None
    message: str | None
    finished_at: datetime

    def to_dict(self) -> ProcessOutcomeData:
        return ProcessOutcomeData(
            status=self.status.value,
            config_name=self.config_name,
            command=self.command,
            exception_type=self.exception_type,
            message=self.message,
            finished_at=self.finished_at.isoformat(),
        )
