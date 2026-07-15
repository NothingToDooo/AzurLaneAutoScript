from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    CancellationSource,
    DailySchedule,
    ExecutionMode,
    RescheduleSelf,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.maintenance import RestartSettings, RestartTask

if TYPE_CHECKING:
    from collections.abc import Callable


_SCHEDULE = DailySchedule("UTC", (time(4),))


class _App:
    def __init__(self, calls: list[str], *, on_stop: Callable[[], None] | None = None) -> None:
        self._calls = calls
        self._on_stop = on_stop

    def start(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self._calls.append("start")

    def stop(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self._calls.append("stop")
        if self._on_stop is not None:
            self._on_stop()


class _Login:
    def __init__(self, calls: list[str], *, error: RuntimeError | None = None) -> None:
        self._calls = calls
        self._error = error

    def ensure_logged_in(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self._calls.append("login")
        if self._error is not None:
            raise self._error


def _context(abort: AbortToken | None = None) -> TaskContext:
    return TaskContext(
        task_id=TaskId("restart"),
        started_at=datetime(2026, 7, 13, 4, tzinfo=UTC),
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def test_restart_runs_stop_start_login_and_reschedules_at_next_server_update() -> None:
    calls: list[str] = []
    due_at = datetime(2026, 7, 14, 4, tzinfo=UTC)
    task = RestartTask(_App(calls), _Login(calls), RestartSettings(_SCHEDULE))

    result = task.run(_context())

    assert calls == ["stop", "start", "login"]
    assert result == TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(due_at),))


def test_restart_abort_before_run_prevents_all_external_side_effects() -> None:
    calls: list[str] = []
    abort = AbortToken()
    abort.request("manual stop")
    task = RestartTask(
        _App(calls),
        _Login(calls),
        RestartSettings(_SCHEDULE),
    )

    with pytest.raises(AbortRequested, match="manual stop"):
        task.run(_context(abort))

    assert calls == []


def test_restart_abort_after_stop_prevents_start_login_and_reschedule() -> None:
    calls: list[str] = []
    abort = AbortToken()

    def request_abort() -> None:
        abort.request("stop requested")

    task = RestartTask(
        _App(calls, on_stop=request_abort),
        _Login(calls),
        RestartSettings(_SCHEDULE),
    )

    with pytest.raises(AbortRequested, match="stop requested"):
        task.run(_context(abort))

    assert calls == ["stop"]


def test_restart_failure_stops_the_workflow_without_returning_schedule_effects() -> None:
    calls: list[str] = []
    error = RuntimeError("login failed")
    task = RestartTask(
        _App(calls),
        _Login(calls, error=error),
        RestartSettings(_SCHEDULE),
    )

    with pytest.raises(RuntimeError, match="login failed"):
        task.run(_context())

    assert calls == ["stop", "start", "login"]


def test_restart_settings_require_a_daily_schedule() -> None:
    with pytest.raises(TypeError, match="DailySchedule"):
        RestartSettings(cast("DailySchedule", "tomorrow"))
