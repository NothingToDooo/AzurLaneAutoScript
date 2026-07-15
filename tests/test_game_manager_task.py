import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    ExecutionMode,
    RunCoordinator,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.interaction import AppLifecycle, AppStatus, CancellationSignal
from module.maintenance import GameManagerSettings, GameManagerTask
from module.state.config_repository import ConfigStateRepository

if TYPE_CHECKING:
    from collections.abc import Callable


class _App(AppLifecycle):
    def __init__(self, calls: list[str], on_stop: Callable[[], None] | None = None) -> None:
        self.calls = calls
        self.on_stop = on_stop

    @override
    def status(self, cancellation: CancellationSignal) -> AppStatus:
        cancellation.raise_if_requested()
        return AppStatus.STOPPED

    @override
    def start(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self.calls.append("start")

    @override
    def stop(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self.calls.append("stop")
        if self.on_stop is not None:
            self.on_stop()


class _Login:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def ensure_logged_in(self, cancellation: CancellationSignal) -> None:
        cancellation.raise_if_requested()
        self.calls.append("login")


class _FixedClock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 7, 13, 12, tzinfo=UTC)


def _context(abort: AbortToken | None = None) -> TaskContext:
    return TaskContext(
        task_id=TaskId("game_manager"),
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        mode=ExecutionMode.DIRECT_COMMAND,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def test_game_manager_stops_without_restart_when_disabled() -> None:
    calls: list[str] = []
    task = GameManagerTask(_App(calls), _Login(calls), GameManagerSettings(auto_restart=False))

    result = task.run(_context())

    assert calls == ["stop"]
    assert result == TaskResult(outcome=Succeeded())


def test_game_manager_restarts_then_waits_for_login_when_enabled() -> None:
    calls: list[str] = []
    task = GameManagerTask(_App(calls), _Login(calls), GameManagerSettings(auto_restart=True))

    result = task.run(_context())

    assert calls == ["stop", "start", "login"]
    assert result == TaskResult(outcome=Succeeded())


def test_abort_before_run_prevents_the_first_app_side_effect() -> None:
    calls: list[str] = []
    abort = AbortToken()
    abort.request("manual stop")
    task = GameManagerTask(_App(calls), _Login(calls), GameManagerSettings(auto_restart=True))

    with pytest.raises(AbortRequested, match="manual stop"):
        task.run(_context(abort))

    assert calls == []


def test_abort_after_stop_prevents_restart_and_login() -> None:
    calls: list[str] = []
    abort = AbortToken()

    def request_abort() -> None:
        abort.request("stop requested")

    task = GameManagerTask(
        _App(calls, on_stop=request_abort),
        _Login(calls),
        GameManagerSettings(auto_restart=True),
    )

    with pytest.raises(AbortRequested, match="stop requested"):
        task.run(_context(abort))

    assert calls == ["stop"]


def test_game_manager_settings_reject_non_boolean_values() -> None:
    with pytest.raises(TypeError, match="auto_restart must be a bool"):
        GameManagerSettings(auto_restart=cast("bool", 1))


def test_game_manager_runs_through_coordinator_and_config_repository(tmp_path: Path) -> None:
    calls: list[str] = []
    task = GameManagerTask(_App(calls), _Login(calls), GameManagerSettings(auto_restart=True))
    metadata = RunMetadata(settings_revision=3, content_revision="content-3")
    config_path = tmp_path / "alas.json"
    document = json.loads(Path("config/template.json").read_text(encoding="utf-8"))
    config_path.write_text(json.dumps(document), encoding="utf-8")
    repository = ConfigStateRepository(
        _FixedClock(),
        config_path=config_path,
    )

    result = RunCoordinator(repository).execute(
        TaskId("game_manager"),
        ExecutionMode.DIRECT_COMMAND,
        metadata,
        task,
    )

    assert calls == ["stop", "start", "login"]
    assert result == TaskResult(outcome=Succeeded())
    assert json.loads(config_path.read_text(encoding="utf-8")) == document
