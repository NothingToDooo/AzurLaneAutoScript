from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from module.application import (
    AbortToken,
    ExecutionMode,
    RecoverableFault,
    RescheduleSelf,
    RunMetadata,
    TaskContext,
    TaskId,
    WakePolicy,
    WakeTask,
)
from module.exception import (
    GameBugError,
    GameNotRunningError,
    GamePageUnknownError,
    GameStuckError,
    GameTooManyClickError,
)
from module.runtime.recovery import GameErrorRecovery

NOW = datetime(2026, 7, 22, 4, tzinfo=UTC)


def _context() -> TaskContext:
    return TaskContext(
        task_id=TaskId("research"),
        started_at=NOW - timedelta(hours=1),
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=1, content_revision="content-test"),
        abort=AbortToken(),
    )


@pytest.mark.parametrize(
    ("error", "delay"),
    [
        (GameNotRunningError("game died"), timedelta(0)),
        (GameStuckError("stuck"), timedelta(seconds=10)),
        (GameTooManyClickError("click loop"), timedelta(seconds=10)),
        (GameBugError("client bug"), timedelta(seconds=10)),
    ],
)
def test_game_error_recovery_wakes_restart_and_advances_the_failed_task(
    error: Exception,
    delay: timedelta,
) -> None:
    recovery = GameErrorRecovery(lambda: True, lambda: NOW)

    result = recovery.recover(_context(), error)

    assert result is not None
    assert isinstance(result.outcome, RecoverableFault)
    assert result.outcome.error is error
    retry_at = NOW + delay
    assert result.effects == (
        RescheduleSelf(retry_at),
        WakeTask(TaskId("restart"), NOW, WakePolicy.FORCE_ENABLE),
    )


def test_game_error_recovery_respects_disabled_error_handling() -> None:
    recovery = GameErrorRecovery(lambda: False, lambda: NOW)

    assert recovery.recover(_context(), GameStuckError("stuck")) is None


def test_game_error_recovery_declines_unknown_exceptions() -> None:
    recovery = GameErrorRecovery(lambda: True, lambda: NOW)

    assert recovery.recover(_context(), ValueError("invalid task state")) is None


def test_game_page_unknown_stays_terminal_without_a_server_status_source() -> None:
    recovery = GameErrorRecovery(lambda: True, lambda: NOW)

    assert recovery.recover(_context(), GamePageUnknownError("unknown page")) is None


def test_restart_task_cannot_recursively_recover_itself() -> None:
    recovery = GameErrorRecovery(lambda: True, lambda: NOW)
    context = _context()
    restart_context = TaskContext(
        task_id=TaskId("restart"),
        started_at=context.started_at,
        mode=context.mode,
        metadata=context.metadata,
        abort=context.abort,
    )

    assert recovery.recover(restart_context, GameStuckError("restart stuck")) is None


def test_game_error_recovery_requires_a_boolean_live_setting() -> None:
    recovery = GameErrorRecovery(lambda: cast("bool", "yes"), lambda: NOW)

    with pytest.raises(TypeError, match="Error_HandleError must be a bool"):
        recovery.recover(_context(), GameStuckError("stuck"))
