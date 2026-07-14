from dataclasses import dataclass
from datetime import datetime

from module.application.identifiers import RunId


@dataclass(frozen=True, slots=True)
class RunStart:
    """仓储确认持久化后的 run 身份与唯一 started_at 事实。"""

    run_id: RunId
    started_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, RunId):
            message = "run_id must be a RunId"
            raise TypeError(message)
        if not isinstance(self.started_at, datetime):
            message = "started_at must be a datetime"
            raise TypeError(message)
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            message = "started_at must be timezone-aware"
            raise ValueError(message)
