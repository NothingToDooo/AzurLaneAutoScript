from __future__ import annotations

from typing import TYPE_CHECKING, override

import pytest

import alas as alas_module
from alas import AzurLaneAutoScript
from module.config.config import TaskEnd
from module.exception import (
    GameNotRunningError,
    GamePageUnknownError,
    GameStuckError,
    RequestHumanTakeover,
    ScriptError,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _RunConfig:
    Error_HandleError = True
    Error_OnePushConfig = "smtp-test-config"

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
        self.config_name = "alas"
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


@pytest.mark.parametrize(
    ("task_error", "reason"),
    [
        (GamePageUnknownError(), "GamePageUnknownError"),
        (ScriptError("invalid state"), "ScriptError"),
        (RequestHumanTakeover(), "RequestHumanTakeover"),
    ],
)
def test_fatal_run_errors_send_notification(
    monkeypatch: pytest.MonkeyPatch,
    task_error: Exception,
    reason: str,
) -> None:
    runner = _make_runner()
    notifications: list[tuple[str, str, str]] = []

    def record_notify(raw_config: str, *, title: str, content: str) -> bool:
        notifications.append((raw_config, title, content))
        return True

    def sample_task() -> None:
        raise task_error

    monkeypatch.setattr(alas_module, "handle_notify", record_notify)
    runner.task = sample_task

    with pytest.raises(SystemExit) as error:
        runner.run("sample_task")

    assert error.value.code == 1
    assert notifications == [
        ("smtp-test-config", "Alas <alas> crashed", f"<alas> {reason}"),
    ]


def test_unexpected_run_error_sends_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _make_runner()
    notifications: list[tuple[str, str, str]] = []

    def record_notify(raw_config: str, *, title: str, content: str) -> bool:
        notifications.append((raw_config, title, content))
        return True

    def sample_task() -> None:
        message = "unexpected"
        raise RuntimeError(message)

    monkeypatch.setattr(alas_module, "handle_notify", record_notify)
    runner.task = sample_task

    with pytest.raises(SystemExit) as error:
        runner.run("sample_task")

    assert error.value.code == 1
    assert notifications == [
        ("smtp-test-config", "Alas <alas> crashed", "<alas> Exception occurred"),
    ]


def test_notification_failure_does_not_replace_fatal_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _make_runner()

    def fail_notify(raw_config: str, *, title: str, content: str) -> bool:
        del raw_config, title, content
        message = "notification implementation failed"
        raise RuntimeError(message)

    def sample_task() -> None:
        raise RequestHumanTakeover

    monkeypatch.setattr(alas_module, "handle_notify", fail_notify)
    runner.task = sample_task

    with pytest.raises(SystemExit) as error:
        runner.run("sample_task")

    assert error.value.code == 1


def test_device_initialization_human_takeover_sends_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = AzurLaneAutoScript()
    vars(runner)["config"] = _RunConfig()
    notifications: list[tuple[str, str, str]] = []

    class _FailingDevice:
        def __init__(self, *, config: _RunConfig) -> None:
            del config
            raise RequestHumanTakeover

    def record_notify(raw_config: str, *, title: str, content: str) -> bool:
        notifications.append((raw_config, title, content))
        return True

    monkeypatch.setattr(alas_module, "_load_attr", lambda _module, _attr: _FailingDevice)
    monkeypatch.setattr(alas_module, "handle_notify", record_notify)

    with pytest.raises(SystemExit) as error:
        _ = runner.device

    assert error.value.code == 1
    assert notifications == [
        ("smtp-test-config", "Alas <alas> crashed", "<alas> RequestHumanTakeover"),
    ]


class _LoopDevice:
    config: _RunConfig

    @staticmethod
    def stuck_record_clear() -> None:
        pass

    @staticmethod
    def click_record_clear() -> None:
        pass


class _LoopRunner(AzurLaneAutoScript):
    config: _RunConfig
    device: _LoopDevice

    def __init__(self) -> None:
        self.config = _RunConfig()
        self.device = _LoopDevice()
        self.config_name = "alas"
        self.failure_record: dict[str, int] = {}
        self.is_first_task = False
        self.run_calls = 0

    @override
    def get_next_task(self) -> str:
        return "Main"

    @override
    def run(self, command: str, *, skip_first_screenshot: bool = False) -> bool:
        del command, skip_first_screenshot
        self.run_calls += 1
        return False


def test_three_consecutive_failures_send_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _LoopRunner()
    notifications: list[tuple[str, str, str]] = []

    def record_notify(raw_config: str, *, title: str, content: str) -> bool:
        notifications.append((raw_config, title, content))
        return True

    monkeypatch.setattr(alas_module, "handle_notify", record_notify)
    monkeypatch.setattr(alas_module, "del_cached_property", lambda *_args: None)
    monkeypatch.setattr(alas_module.logger, "set_file_logger", lambda _name: None)

    with pytest.raises(SystemExit) as error:
        runner.loop()

    assert error.value.code == 1
    assert runner.run_calls == 3
    assert notifications == [
        (
            "smtp-test-config",
            "Alas <alas> crashed",
            "<alas> RequestHumanTakeover\nTask `Main` failed 3 or more times.",
        ),
    ]
