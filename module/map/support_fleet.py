from enum import StrEnum
from typing import Protocol, runtime_checkable


class SupportFleetStatus(StrEnum):
    UNOBSERVED = "unobserved"
    PRESENT = "present"
    EMPTY = "empty"


class SupportFleetStateError(RuntimeError):
    pass


class SupportFleetAttemptState:
    """保存一次进图尝试中的支援舰队观察结果。"""

    __slots__ = ("_sealed", "_status")

    def __init__(self) -> None:
        self._status = SupportFleetStatus.UNOBSERVED
        self._sealed = False

    @property
    def status(self) -> SupportFleetStatus:
        return self._status

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def available(self) -> bool:
        # profile 已声明本关存在支援舰队；只有准备页的 EMPTY 证据会关闭它。
        return self._status is not SupportFleetStatus.EMPTY

    def observe(self, status: SupportFleetStatus) -> None:
        if not isinstance(status, SupportFleetStatus):
            message = "support fleet observation must be a SupportFleetStatus"
            raise TypeError(message)
        if status is SupportFleetStatus.UNOBSERVED:
            message = "support fleet observation must be present or empty"
            raise ValueError(message)
        if self._sealed:
            message = "support fleet observation is sealed for the active session"
            raise SupportFleetStateError(message)
        self._status = status

    def seal(self) -> None:
        self._sealed = True

    def reset(self) -> None:
        self._status = SupportFleetStatus.UNOBSERVED
        self._sealed = False


@runtime_checkable
class SupportFleetStateSource(Protocol):
    @property
    def support_fleet_state(self) -> SupportFleetAttemptState: ...
