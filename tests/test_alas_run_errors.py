import pytest

from alas import AzurLaneAutoScript
from module.config.config import TaskEnd
from module.exception import GameNotRunningError, GamePageUnknownError, GameStuckError


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


def _make_runner():
    runner = object.__new__(AzurLaneAutoScript)
    runner.config = _RunConfig()
    runner.device = _RunDevice()
    runner.error_log_calls = 0

    def save_error_log() -> None:
        runner.error_log_calls += 1

    runner.save_error_log = save_error_log
    return runner


def test_run_executes_command_method() -> None:
    runner = _make_runner()
    runner.command_calls = 0

    def sample_task() -> None:
        runner.command_calls += 1

    runner.sample_task = sample_task

    assert runner.run("sample_task")
    assert runner.device.screenshot_calls == 1
    assert runner.command_calls == 1


def test_run_treats_task_end_as_success() -> None:
    runner = _make_runner()

    def sample_task() -> None:
        raise TaskEnd

    runner.sample_task = sample_task

    assert runner.run("sample_task")


def test_run_schedules_restart_when_game_is_not_running() -> None:
    runner = _make_runner()

    def sample_task() -> None:
        raise GameNotRunningError("missing")

    runner.sample_task = sample_task

    assert not runner.run("sample_task")
    assert runner.config.task_calls == ["Restart"]


def test_run_saves_error_log_for_stuck_game() -> None:
    runner = _make_runner()

    def sample_task() -> None:
        raise GameStuckError("stuck")

    runner.sample_task = sample_task

    assert not runner.run("sample_task")
    assert runner.error_log_calls == 1
    assert runner.config.task_calls == ["Restart"]
    assert runner.device.sleep_calls == [10]


def test_run_exits_on_unknown_page() -> None:
    runner = _make_runner()

    def sample_task() -> None:
        raise GamePageUnknownError

    runner.sample_task = sample_task

    with pytest.raises(SystemExit) as error:
        runner.run("sample_task")

    assert error.value.code == 1
