import ctypes
from typing import TYPE_CHECKING

import numpy as np
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


def test_nemu_ipc_retry_extends_screenshot_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = object.__new__(NemuIpcImpl)
    timeouts: list[float] = []
    run_count = 0

    def screenshot_once(_device: NemuIpcImpl, timeout: float) -> ImageArray:
        nonlocal run_count
        timeouts.append(timeout)
        run_count += 1
        if run_count <= 2:
            raise JobTimeout
        return np.full((1, 1, 4), round(timeout * 10), dtype=np.uint8)

    monkeypatch.setattr(NemuIpcImpl, "_screenshot_once", screenshot_once)

    assert device.screenshot()[0, 0, 0] == 10
    assert timeouts == [0.5, 0.5, 1]
    assert logger.warnings == [
        "Func screenshot() call timeout, retrying: 0",
        "Func screenshot() call timeout, retrying: 1",
    ]


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
