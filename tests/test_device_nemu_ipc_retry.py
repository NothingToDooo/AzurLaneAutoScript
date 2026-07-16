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


class _NemuIpc:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.run_count = 0
        self.timeouts: list[float] = []

    def reconnect(self) -> None:
        self.calls.append("reconnect")


def _patch_retry_runtime(monkeypatch: pytest.MonkeyPatch) -> _Logger:
    logger = _Logger()
    monkeypatch.setattr(nemu_ipc_module, "logger", logger)
    monkeypatch.setattr(nemu_ipc_module, "time", type("_Time", (), {"sleep": lambda _delay: None}))
    return logger


def _run_retry(monkeypatch: pytest.MonkeyPatch, error: Exception) -> tuple[str, _NemuIpc, _Logger]:
    logger = _patch_retry_runtime(monkeypatch)
    device = _NemuIpc()

    @nemu_ipc_module.retry
    def flaky(target: _NemuIpc) -> str:
        target.calls.append("run")
        target.run_count += 1
        if target.run_count == 1:
            raise error
        return "ok"

    return flaky(device), device, logger


def test_nemu_ipc_retry_recovers_ipc_error(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, NemuIpcError("lost"))

    assert result == "ok"
    assert logger.errors == ["lost"]
    assert device.calls == ["run", "reconnect", "run"]


def test_nemu_ipc_retry_stops_on_incompatible_version(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _NemuIpc()

    @nemu_ipc_module.retry
    def always_incompatible(target: _NemuIpc) -> None:
        target.calls.append("run")
        message = "old"
        raise NemuIpcIncompatible(message)

    with pytest.raises(RequestHumanTakeover):
        always_incompatible(device)

    assert device.calls == ["run"]
    assert logger.errors == ["old"]
    assert logger.criticals == ["Retry always_incompatible() failed"]


def test_nemu_ipc_timeout_stops_without_reusing_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = object.__new__(NemuIpcImpl)
    device._timed_out = False  # noqa: SLF001 - 构造不加载本机 DLL 的最小 NemuIpc 实例。
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
    device._timed_out = False  # noqa: SLF001 - 构造不加载本机 DLL 的最小 NemuIpc 实例。

    with pytest.raises(JobTimeout):
        device.run_func(lambda: 0)
    with pytest.raises(RequestHumanTakeover, match="can no longer be used"):
        device.run_func(lambda: 0, on_thread=False)

    assert pool.calls == 1


def test_poisoned_disconnect_drops_handle_without_native_call() -> None:
    device = object.__new__(NemuIpcImpl)
    device.connect_id = 7
    device._timed_out = True  # noqa: SLF001 - 构造不加载本机 DLL 的最小 NemuIpc 实例。
    device.lib = object()

    device.disconnect()

    assert device.connect_id == 0


def test_nemu_ipc_retry_retries_native_errors_without_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, OSError("native"))

    assert result == "ok"
    assert logger.errors == ["native"]
    assert device.calls == ["run", "run"]


def test_nemu_ipc_retry_retries_argument_errors_without_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, ctypes.ArgumentError("bad argument"))

    assert result == "ok"
    assert logger.errors == ["bad argument"]
    assert device.calls == ["run", "run"]
