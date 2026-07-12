from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, overload, override

import pytest
from adbutils import AdbClient

from module.device import runtime as runtime_module
from module.device.platform.emulator_base import EmulatorInstanceBase
from module.device.runtime import MumuRuntime
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from adbutils import AdbConnection

    from module.device.contracts import AdbCommand


class _AdbClient(AdbClient):
    def __init__(self, messages: list[str] | None = None) -> None:
        self.messages = messages or ["connected"]
        self.connect_calls: list[str] = []
        self.disconnect_calls: list[str] = []

    @override
    def connect(self, addr: str, timeout: float | None = None) -> str:
        del timeout
        self.connect_calls.append(addr)
        if self.messages:
            return self.messages.pop(0)
        return "connected"

    @override
    def disconnect(self, addr: str, raise_error: bool = False) -> str:
        del raise_error
        self.disconnect_calls.append(addr)
        return "disconnected"


class _Timer:
    timeout_after = 10

    def __init__(self, limit: float) -> None:
        self.limit = limit
        self.reached_calls = 0
        self.wait_calls = 0
        self.reset_calls = 0

    def start(self) -> Self:
        return self

    def wait(self) -> None:
        self.wait_calls += 1

    def reset(self) -> Self:
        self.reset_calls += 1
        return self

    def reached(self) -> bool:
        if self.limit != 180:
            return False
        self.reached_calls += 1
        return self.reached_calls > self.timeout_after


@dataclass(frozen=True, slots=True)
class _Device:
    serial: str
    status: str


type _ShellResult = str | BaseException


class _Session:
    def __init__(
        self,
        *,
        serial: str,
        device_batches: list[list[_Device]],
        shell_results: list[_ShellResult],
        package_results: list[list[str]],
        connect_messages: list[str] | None,
    ) -> None:
        self.serial = serial
        self.is_mumu_family = True
        self.is_mumu12_family = True
        self.package = "com.bilibili.azurlane"
        self.adb_client = _AdbClient(connect_messages)
        self.device_batches = list(device_batches)
        self.last_devices: list[_Device] = []
        self.shell_results = shell_results
        self.package_results = package_results
        self.shell_calls = 0
        self.package_calls = 0
        self.recovery_calls = 0
        self.prop_calls: list[str] = []

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[False] = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str: ...

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[True],
        recvall: Literal[True] = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> bytes: ...

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[True],
        recvall: Literal[False],
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> AdbConnection: ...

    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: bool = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str | bytes | AdbConnection:
        del cmd, recvall, timeout, rstrip
        if stream:
            raise AssertionError
        self.shell_calls += 1
        result = self.shell_results.pop(0) if self.shell_results else "pong"
        if isinstance(result, BaseException):
            raise result
        return result

    def adb_start_server(self) -> int:
        self.recovery_calls += 1
        return 0

    def adb_reconnect(self) -> None:
        self.recovery_calls += 1

    def detect_package(self) -> None:
        self.recovery_calls += 1

    def adb_getprop(self, name: str) -> str:
        self.prop_calls.append(name)
        return ""

    def list_device(self) -> SelectedGrids[_Device]:
        if self.device_batches:
            self.last_devices = self.device_batches.pop(0)
        return SelectedGrids(self.last_devices)

    def list_known_packages(self, *, show_log: bool = True) -> list[str]:
        del show_log
        self.package_calls += 1
        return self.package_results.pop(0)


def _device(serial: str, status: str) -> _Device:
    return _Device(serial=serial, status=status)


class _Runtime(MumuRuntime):
    session: _Session

    def __init__(self, session: _Session) -> None:
        super().__init__(session)


def _make_runtime(
    *,
    serial: str = "127.0.0.1:16384",
    device_batches: list[list[_Device]],
    shell_results: list[_ShellResult] | None = None,
    package_results: list[list[str]] | None = None,
    connect_messages: list[str] | None = None,
) -> _Runtime:
    session = _Session(
        serial=serial,
        device_batches=device_batches,
        shell_results=shell_results or ["pong"],
        package_results=package_results or [["com.bilibili.azurlane"]],
        connect_messages=connect_messages,
    )
    runtime = _Runtime(session)
    runtime.__dict__["emulator_instance"] = EmulatorInstanceBase(serial=serial, name="test", path="test")
    return runtime


@pytest.fixture(autouse=True)
def _patch_windows_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.timeout_after = 10
    monkeypatch.setattr(runtime_module, "Timer", _Timer)
    monkeypatch.setattr(runtime_module, "get_focused_window", lambda: 0)
    monkeypatch.setattr(runtime_module, "set_focus_window", lambda _hwnd: None)
    monkeypatch.setattr(runtime_module, "minimize_window", lambda _hwnd: None)
    monkeypatch.setattr(runtime_module, "flash_window", lambda _hwnd, *_args, **_kwargs: None)


def test_emulator_start_watch_succeeds_when_device_shell_and_package_are_ready() -> None:
    runtime = _make_runtime(device_batches=[[_device("127.0.0.1:16384", "device")]])

    assert runtime.emulator_start_watch()
    assert runtime.session.adb_client.connect_calls == []
    assert runtime.session.shell_calls == 1
    assert runtime.session.package_calls == 1


def test_emulator_start_watch_disconnects_offline_device_before_retrying() -> None:
    runtime = _make_runtime(
        device_batches=[
            [_device("127.0.0.1:16384", "offline")],
            [_device("127.0.0.1:16384", "device")],
        ]
    )

    assert runtime.emulator_start_watch()
    assert runtime.session.adb_client.disconnect_calls == ["127.0.0.1:16384"]
    assert runtime.session.adb_client.connect_calls == ["127.0.0.1:16384"]


def test_emulator_start_watch_connects_when_device_is_missing() -> None:
    runtime = _make_runtime(
        device_batches=[
            [],
            [_device("127.0.0.1:16384", "device")],
        ]
    )

    assert runtime.emulator_start_watch()
    assert runtime.session.adb_client.connect_calls == ["127.0.0.1:16384"]


def test_emulator_start_watch_waits_until_shell_command_is_ready() -> None:
    runtime = _make_runtime(
        device_batches=[
            [_device("127.0.0.1:16384", "device")],
            [_device("127.0.0.1:16384", "device")],
        ],
        shell_results=[OSError("not ready"), "pong"],
    )

    assert runtime.emulator_start_watch()
    assert runtime.session.shell_calls == 2
    assert runtime.session.package_calls == 1


def test_emulator_start_watch_waits_until_package_is_ready() -> None:
    runtime = _make_runtime(
        device_batches=[
            [_device("127.0.0.1:16384", "device")],
            [_device("127.0.0.1:16384", "device")],
        ],
        package_results=[[], ["com.bilibili.azurlane"]],
    )

    assert runtime.emulator_start_watch()
    assert runtime.session.package_calls == 2


def test_emulator_start_watch_returns_false_on_timeout() -> None:
    _Timer.timeout_after = 0
    runtime = _make_runtime(device_batches=[[_device("127.0.0.1:16384", "device")]])

    assert not runtime.emulator_start_watch()
