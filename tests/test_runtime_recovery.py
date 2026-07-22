from datetime import UTC, datetime, timedelta

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
from module.exception import GameNotRunningError, GameStuckError
from module.runtime.recovery import GameErrorRecovery

NOW = datetime(2026, 7, 22, 4, tzinfo=UTC)


def _context(
    task_id: str = "research",
    mode: ExecutionMode = ExecutionMode.SCHEDULED_JOB,
) -> TaskContext:
    return TaskContext(
        task_id=TaskId(task_id),
        started_at=NOW - timedelta(hours=1),
        mode=mode,
        metadata=RunMetadata(settings_revision=1, content_revision="content-test"),
        abort=AbortToken(),
    )


@pytest.mark.parametrize(
    ("error", "delay"),
    [
        (GameNotRunningError("game died"), timedelta(0)),
        (GameStuckError("stuck"), timedelta(seconds=10)),
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


@pytest.mark.parametrize(
    ("enabled", "error", "task_id", "mode"),
    [
        (True, ValueError("invalid task state"), "research", ExecutionMode.SCHEDULED_JOB),
        (True, GameStuckError("restart stuck"), "restart", ExecutionMode.SCHEDULED_JOB),
        (True, GameStuckError("direct command"), "research", ExecutionMode.DIRECT_COMMAND),
    ],
)
def test_game_error_recovery_declines_ineligible_faults(
    *,
    enabled: bool,
    error: Exception,
    task_id: str,
    mode: ExecutionMode,
) -> None:
    recovery = GameErrorRecovery(lambda: enabled, lambda: NOW)

    assert recovery.recover(_context(task_id, mode), error) is None
