from enum import StrEnum
from typing import Protocol

from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeSessionContext,
    RuntimeSessionOutcome,
)
from module.base.failure import preserve_cleanup_failure, raise_cleanup_errors


class _RuntimeProfileSessionManager(Protocol):
    def begin_session(self, context: RuntimeSessionContext) -> None: ...

    def end_session(self, outcome: RuntimeSessionOutcome) -> None: ...

    def reset(self) -> None: ...


class RuntimeProfileLeaseState(StrEnum):
    READY = "ready"
    ACTIVE = "active"
    CLOSED = "closed"


class RuntimeProfileLease:
    """一次性持有 runtime profile，并把关闭失败与可复用性彻底分开。"""

    __slots__ = ("_manager", "_state")

    def __init__(self, manager: _RuntimeProfileSessionManager) -> None:
        if isinstance(manager, type) or any(
            not callable(getattr(manager, method, None)) for method in ("begin_session", "end_session", "reset")
        ):
            message = "runtime profile lease manager must implement the session lifecycle contract"
            raise TypeError(message)
        self._manager = manager
        self._state = RuntimeProfileLeaseState.READY

    @property
    def state(self) -> RuntimeProfileLeaseState:
        return self._state

    @property
    def active(self) -> bool:
        return self._state is RuntimeProfileLeaseState.ACTIVE

    def start(self, context: RuntimeSessionContext) -> None:
        if not isinstance(context, RuntimeSessionContext):
            message = "runtime profile lease context must be a RuntimeSessionContext"
            raise TypeError(message)
        if self._state is not RuntimeProfileLeaseState.READY:
            message = f"runtime profile lease cannot start from {self._state.value}"
            raise CampaignRuntimeProfileError(message)
        try:
            self._manager.begin_session(context)
        except BaseException as error:
            self._state = RuntimeProfileLeaseState.CLOSED
            preserve_cleanup_failure(
                error,
                self._manager.reset,
                message="runtime profile session start and reset both failed",
            )
            raise
        self._state = RuntimeProfileLeaseState.ACTIVE

    def close(self, outcome: RuntimeSessionOutcome) -> None:
        if not isinstance(outcome, RuntimeSessionOutcome):
            message = "runtime profile lease outcome must be a RuntimeSessionOutcome"
            raise TypeError(message)
        if self._state is not RuntimeProfileLeaseState.ACTIVE:
            message = f"runtime profile lease cannot close from {self._state.value}"
            raise CampaignRuntimeProfileError(message)
        self._state = RuntimeProfileLeaseState.CLOSED
        errors: list[BaseException] = []
        for cleanup in (
            lambda: self._manager.end_session(outcome),
            self._manager.reset,
        ):
            try:
                cleanup()
            except BaseException as error:  # ruff:ignore[blind-except] - end 与 reset 是独立且必须完整执行的关闭阶段。
                errors.append(error)
        raise_cleanup_errors(errors, message="runtime profile session cleanup failed")

    def discard(self) -> None:
        if self._state is RuntimeProfileLeaseState.ACTIVE:
            message = "active runtime profile lease must close before discard"
            raise CampaignRuntimeProfileError(message)
        if self._state is RuntimeProfileLeaseState.CLOSED:
            return
        self._state = RuntimeProfileLeaseState.CLOSED
        self._manager.reset()
