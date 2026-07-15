from dataclasses import dataclass
from enum import StrEnum


class OperatorNotificationKind(StrEnum):
    """需要操作者关注的稳定业务通知类型。"""

    CAMPAIGN_RUN_COUNT_LIMIT = "campaign_run_count_limit"
    CAMPAIGN_REACH_LEVEL_LIMIT = "campaign_reach_level_limit"
    CAMPAIGN_NEW_SHIP = "campaign_new_ship"


@dataclass(frozen=True, slots=True)
class OperatorNotificationRequest:
    """任务声明的通知意图；只携带稳定业务事实，不携带传输配置。"""

    kind: OperatorNotificationKind
    resource: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, OperatorNotificationKind):
            message = "kind must be an OperatorNotificationKind"
            raise TypeError(message)
        if not isinstance(self.resource, str):
            message = "resource must be a string"
            raise TypeError(message)
        if not self.resource.strip() or self.resource != self.resource.strip():
            message = "resource must be trimmed and non-empty"
            raise ValueError(message)
        if "\r" in self.resource or "\n" in self.resource:
            message = "resource must be a single line"
            raise ValueError(message)
