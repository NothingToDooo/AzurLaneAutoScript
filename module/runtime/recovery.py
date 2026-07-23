from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from module.application import (
    ExecutionMode,
    RecoverableFault,
    RescheduleSelf,
    TaskContext,
    TaskId,
    TaskResult,
    WakePolicy,
    WakeTask,
)
from module.exception import (
    GameBugError,
    GameNotRunningError,
    GameStuckError,
    GameTooManyClickError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_RESTART_TASK = TaskId("restart")
_RECOVERABLE_GAME_ERRORS = (
    GameNotRunningError,
    GameStuckError,
    GameTooManyClickError,
    GameBugError,
)
_DELAYED_GAME_ERRORS = (
    GameStuckError,
    GameTooManyClickError,
    GameBugError,
)
_RESTART_BACKOFF = timedelta(seconds=10)


class GameErrorRecovery:
    """把 legacy 游戏瞬态异常转换为可持久化的 scheduler 恢复结果。"""

    __slots__ = ("_is_enabled", "_now")

    def __init__(self, is_enabled: Callable[[], bool], now: Callable[[], datetime]) -> None:
        if not callable(is_enabled):
            message = "is_enabled must be callable"
            raise TypeError(message)
        if not callable(now):
            message = "now must be callable"
            raise TypeError(message)
        self._is_enabled = is_enabled
        self._now = now

    def recover(self, context: TaskContext, error: Exception) -> TaskResult | None:
        if (
            context.mode is not ExecutionMode.SCHEDULED_JOB
            or context.task_id == _RESTART_TASK
            or not isinstance(error, _RECOVERABLE_GAME_ERRORS)
        ):
            return None
        is_enabled = self._is_enabled()
        if type(is_enabled) is not bool:
            message = "Error_HandleError must be a bool"
            raise TypeError(message)
        if not is_enabled:
            return None

        delay = _RESTART_BACKOFF if isinstance(error, _DELAYED_GAME_ERRORS) else timedelta(0)
        now = self._now()
        if not isinstance(now, datetime):
            message = "recovery clock now() must return a datetime"
            raise TypeError(message)
        if now.utcoffset() is None:
            message = "recovery clock now() must return a timezone-aware datetime"
            raise ValueError(message)
        retry_at = now + delay
        return TaskResult(
            outcome=RecoverableFault(error),
            effects=(
                RescheduleSelf(retry_at),
                WakeTask(_RESTART_TASK, now, WakePolicy.FORCE_ENABLE),
            ),
        )
