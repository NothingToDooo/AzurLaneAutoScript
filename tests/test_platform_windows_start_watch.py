from types import SimpleNamespace

import pytest

from module.device.platform import platform_windows
from module.device.platform.platform_windows import PlatformWindows
from module.map.map_grids import SelectedGrids


class _AdbClient:
    def __init__(self, messages: list[str] | None = None) -> None:
        self.messages = messages or ["connected"]
        self.connect_calls: list[str] = []
        self.disconnect_calls: list[str] = []

    def connect(self, serial: str) -> str:
        self.connect_calls.append(serial)
        if self.messages:
            return self.messages.pop(0)
        return "connected"

    def disconnect(self, serial: str) -> None:
        self.disconnect_calls.append(serial)


class _Timer:
    timeout_after = 10

    def __init__(self, limit: float) -> None:
        self.limit = limit
        self.reached_calls = 0

    def start(self):
        return self

    def wait(self) -> None:
        return None

    def reset(self) -> None:
        return None

    def reached(self) -> bool:
        if self.limit != 180:
            return False
        self.reached_calls += 1
        return self.reached_calls > self.timeout_after


def _device(serial: str, status: str):
    return SimpleNamespace(serial=serial, status=status)


def _make_platform(
    *,
    serial: str = "127.0.0.1:16384",
    device_batches: list[list[object]],
    shell_results: list[object] | None = None,
    package_results: list[list[str]] | None = None,
    connect_messages: list[str] | None = None,
):
    platform = object.__new__(PlatformWindows)
    platform.serial = serial
    platform.emulator_instance = SimpleNamespace(serial=serial)
    platform.adb_client = _AdbClient(connect_messages)
    platform.device_batches = list(device_batches)
    platform.last_devices: list[object] = []
    platform.shell_results = shell_results or ["pong"]
    platform.package_results = package_results or [["com.bilibili.azurlane"]]
    platform.shell_calls = 0
    platform.package_calls = 0

    def list_device():
        if platform.device_batches:
            platform.last_devices = platform.device_batches.pop(0)
        return SelectedGrids(platform.last_devices)

    def adb_shell(_command):
        platform.shell_calls += 1
        result = platform.shell_results.pop(0) if platform.shell_results else "pong"
        if isinstance(result, BaseException):
            raise result
        return result

    def list_known_packages(show_log=True):
        del show_log
        platform.package_calls += 1
        return platform.package_results.pop(0)

    platform.list_device = list_device
    platform.adb_shell = adb_shell
    platform.list_known_packages = list_known_packages
    return platform


@pytest.fixture(autouse=True)
def _patch_windows_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.timeout_after = 10
    monkeypatch.setattr(platform_windows, "Timer", _Timer)
    monkeypatch.setattr(platform_windows, "get_focused_window", lambda: 0)
    monkeypatch.setattr(platform_windows, "set_focus_window", lambda _hwnd: None)
    monkeypatch.setattr(platform_windows, "minimize_window", lambda _hwnd: None)
    monkeypatch.setattr(platform_windows, "flash_window", lambda _hwnd, *_args, **_kwargs: None)


def test_emulator_start_watch_succeeds_when_device_shell_and_package_are_ready() -> None:
    platform = _make_platform(device_batches=[[_device("127.0.0.1:16384", "device")]])

    assert platform.emulator_start_watch()
    assert platform.adb_client.connect_calls == []
    assert platform.shell_calls == 1
    assert platform.package_calls == 1


def test_emulator_start_watch_disconnects_offline_device_before_retrying() -> None:
    platform = _make_platform(
        device_batches=[
            [_device("127.0.0.1:16384", "offline")],
            [_device("127.0.0.1:16384", "device")],
        ]
    )

    assert platform.emulator_start_watch()
    assert platform.adb_client.disconnect_calls == ["127.0.0.1:16384"]
    assert platform.adb_client.connect_calls == ["127.0.0.1:16384"]


def test_emulator_start_watch_connects_when_device_is_missing() -> None:
    platform = _make_platform(
        device_batches=[
            [],
            [_device("127.0.0.1:16384", "device")],
        ]
    )

    assert platform.emulator_start_watch()
    assert platform.adb_client.connect_calls == ["127.0.0.1:16384"]


def test_emulator_start_watch_waits_until_shell_command_is_ready() -> None:
    platform = _make_platform(
        device_batches=[
            [_device("127.0.0.1:16384", "device")],
            [_device("127.0.0.1:16384", "device")],
        ],
        shell_results=[OSError("not ready"), "pong"],
    )

    assert platform.emulator_start_watch()
    assert platform.shell_calls == 2
    assert platform.package_calls == 1


def test_emulator_start_watch_waits_until_package_is_ready() -> None:
    platform = _make_platform(
        device_batches=[
            [_device("127.0.0.1:16384", "device")],
            [_device("127.0.0.1:16384", "device")],
        ],
        package_results=[[], ["com.bilibili.azurlane"]],
    )

    assert platform.emulator_start_watch()
    assert platform.package_calls == 2


def test_emulator_start_watch_returns_false_on_timeout() -> None:
    _Timer.timeout_after = 0
    platform = _make_platform(device_batches=[[_device("127.0.0.1:16384", "device")]])

    assert not platform.emulator_start_watch()
