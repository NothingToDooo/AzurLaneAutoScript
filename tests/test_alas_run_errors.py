from __future__ import annotations

from typing import TYPE_CHECKING, override

import pytest

from alas import AzurLaneAutoScript
from module.config.config import TaskEnd
from module.exception import GameNotRunningError, GamePageUnknownError, GameStuckError, ScriptError

if TYPE_CHECKING:
    from collections.abc import Callable


class _RunConfig:
    def __init__(self) -> None:
        self.task_calls: list[str] = []

    def task_call(self, task: str) -> None:
        self.task_calls.append(task)


class _RunDevice:
    package = "test.package"

    def __init__(self) -> None:
        self.screenshot_calls = 0
        self.sleep_calls: list[int] = []

    def screenshot(self) -> None:
        self.screenshot_calls += 1

    def sleep(self, seconds: int) -> None:
        self.sleep_calls.append(seconds)


class _RunRunner(AzurLaneAutoScript):
    config: _RunConfig
    device: _RunDevice

    def __init__(self) -> None:
        self.config = _RunConfig()
        self.device = _RunDevice()
        self.error_log_calls = 0
        self.command_calls = 0
        self.task: Callable[[], None] = lambda: None

    def sample_task(self) -> None:
        self.task()

    @override
    def save_error_log(self) -> None:
        self.error_log_calls += 1


class _FailingErrorLogRunner(_RunRunner):
    @override
    def save_error_log(self) -> None:
        message = "disk full"
        raise OSError(message)


def _make_runner() -> _RunRunner:
    return _RunRunner()


def test_run_executes_command_method() -> None:
    runner = _make_runner()

    def sample_task() -> None:
        runner.command_calls += 1

    runner.task = sample_task

    assert runner.run("sample_task")
    assert runner.device.screenshot_calls == 1
    assert runner.command_calls == 1


def test_run_treats_task_end_as_success() -> None:
    runner = _make_runner()

    def sample_task() -> None:
        raise TaskEnd

    runner.task = sample_task

    assert runner.run("sample_task")


def test_run_schedules_restart_when_game_is_not_running() -> None:
    runner = _make_runner()
    message = "missing"

    def sample_task() -> None:
        raise GameNotRunningError(message)

    runner.task = sample_task

    assert not runner.run("sample_task")
    assert runner.error_log_calls == 1
    assert runner.config.task_calls == ["Restart"]


def test_run_saves_error_log_for_stuck_game() -> None:
    runner = _make_runner()
    message = "stuck"

    def sample_task() -> None:
        raise GameStuckError(message)

    runner.task = sample_task

    assert not runner.run("sample_task")
    assert runner.error_log_calls == 1
    assert runner.config.task_calls == ["Restart"]
    assert runner.device.sleep_calls == [10]


def test_run_exits_on_unknown_page() -> None:
    runner = _make_runner()

    def sample_task() -> None:
        raise GamePageUnknownError

    runner.task = sample_task

    with pytest.raises(SystemExit) as error:
        runner.run("sample_task")

    assert error.value.code == 1
    assert runner.error_log_calls == 1


def test_run_saves_error_log_for_script_error() -> None:
    runner = _make_runner()
    message = "invalid state"

    def sample_task() -> None:
        raise ScriptError(message)

    runner.task = sample_task

    with pytest.raises(SystemExit) as error:
        runner.run("sample_task")

    assert error.value.code == 1
    assert runner.error_log_calls == 1


def test_error_log_failure_does_not_replace_recoverable_error() -> None:
    runner = _FailingErrorLogRunner()
    task_message = "stuck"

    def sample_task() -> None:
        raise GameStuckError(task_message)

    runner.task = sample_task

    assert not runner.run("sample_task")
    assert runner.config.task_calls == ["Restart"]
    assert runner.device.sleep_calls == [10]
