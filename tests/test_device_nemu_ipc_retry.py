import ctypes
from typing import TYPE_CHECKING

import pytest

from module.device import nemu_ipc_service as nemu_ipc_module
from module.device.method.pool import JobTimeout
from module.device.nemu_ipc_service import NemuIpcError, NemuIpcImpl, NemuIpcIncompatible
from module.exception import RequestHumanTakeover

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.criticals: list[str] = []

    def error(self, error: BaseException) -> None:
        self.errors.append(str(error))

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def critical(self, message: str) -> None:
        self.criticals.append(message)


def _patch_retry_runtime(monkeypatch: pytest.MonkeyPatch) -> _Logger:
    logger = _Logger()
    monkeypatch.setattr(nemu_ipc_module, "logger", logger)
    monkeypatch.setattr(nemu_ipc_module, "time", type("_Time", (), {"sleep": lambda _delay: None}))
    return logger


def _connect_retry_device(monkeypatch: pytest.MonkeyPatch, error: Exception) -> tuple[NemuIpcImpl, list[str], _Logger]:
    logger = _patch_retry_runtime(monkeypatch)
    device = object.__new__(NemuIpcImpl)
    calls: list[str] = []
    attempts = 0

    def connect(*, on_thread: bool = True) -> None:
        nonlocal attempts
        calls.append(f"connect:{on_thread}")
        attempts += 1
        if attempts == 1:
            raise error

    def reconnect() -> None:
        calls.append("reconnect")

    monkeypatch.setattr(device, "connect", connect)
    monkeypatch.setattr(device, "reconnect", reconnect)
    return device, calls, logger


def test_nemu_ipc_retry_recovers_ipc_error(monkeypatch: pytest.MonkeyPatch) -> None:
    device, calls, logger = _connect_retry_device(monkeypatch, NemuIpcError("lost"))

    device.connect_with_retry(on_thread=False)

    assert logger.errors == ["lost"]
    assert calls == ["connect:False", "reconnect", "connect:False"]


def test_nemu_ipc_retry_stops_on_incompatible_version(monkeypatch: pytest.MonkeyPatch) -> None:
    device, calls, logger = _connect_retry_device(monkeypatch, NemuIpcIncompatible("old"))

    with pytest.raises(RequestHumanTakeover):
        device.connect_with_retry(on_thread=False)

    assert calls == ["connect:False"]
    assert logger.errors == ["old"]
    assert logger.criticals == ["Retry connect_with_retry() failed"]


def test_nemu_ipc_timeout_stops_without_reusing_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = object.__new__(NemuIpcImpl)
    device._timed_out = False  # ruff:ignore[private-member-access] - 构造不加载本机 DLL 的最小 NemuIpc 实例。
    timeouts: list[float] = []

    def screenshot_once(_device: NemuIpcImpl, timeout: float) -> ImageArray:
        timeouts.append(timeout)
        raise JobTimeout

    monkeypatch.setattr(NemuIpcImpl, "_screenshot_once", screenshot_once)

    with pytest.raises(RequestHumanTakeover):
        device.screenshot()

    assert timeouts == [0.5]
    assert logger.criticals == [
        "Func screenshot() call timeout; stop using this NemuIpc connection",
        "NemuIpc native call timed out; this connection can no longer be used",
    ]


def test_native_timeout_poison_prevents_later_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimedOutJob:
        @staticmethod
        def get_or_timeout(_timeout: float) -> None:
            raise JobTimeout

    class _Pool:
        def __init__(self) -> None:
            self.calls = 0

        def start_thread_soon(self, _func: object, *_args: object) -> _TimedOutJob:
            self.calls += 1
            return _TimedOutJob()

    pool = _Pool()
    monkeypatch.setattr(nemu_ipc_module, "WORKER_POOL", pool)
    device = object.__new__(NemuIpcImpl)
    device._timed_out = False  # ruff:ignore[private-member-access] - 构造不加载本机 DLL 的最小 NemuIpc 实例。

    with pytest.raises(JobTimeout):
        device.run_func(lambda: 0)
    with pytest.raises(RequestHumanTakeover, match="can no longer be used"):
        device.run_func(lambda: 0, on_thread=False)

    assert pool.calls == 1


def test_poisoned_disconnect_drops_handle_without_native_call() -> None:
    device = object.__new__(NemuIpcImpl)
    device.connect_id = 7
    device._timed_out = True  # ruff:ignore[private-member-access] - 构造不加载本机 DLL 的最小 NemuIpc 实例。
    device.lib = object()

    device.disconnect()

    assert device.connect_id == 0


def test_nemu_ipc_retry_retries_native_errors_without_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    device, calls, logger = _connect_retry_device(monkeypatch, OSError("native"))

    device.connect_with_retry(on_thread=False)

    assert logger.errors == ["native"]
    assert calls == ["connect:False", "connect:False"]


def test_nemu_ipc_retry_retries_argument_errors_without_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    device, calls, logger = _connect_retry_device(monkeypatch, ctypes.ArgumentError("bad argument"))

    device.connect_with_retry(on_thread=False)

    assert logger.errors == ["bad argument"]
    assert calls == ["connect:False", "connect:False"]
