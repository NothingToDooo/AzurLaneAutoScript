import ctypes

import pytest

from module.device.method import nemu_ipc as nemu_ipc_module
from module.device.method.nemu_ipc import NemuIpcError, NemuIpcIncompatible
from module.device.method.pool import JobTimeout
from module.exception import RequestHumanTakeover


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.criticals: list[str] = []

    def error(self, error) -> None:
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


def _patch_retry_runtime(monkeypatch):
    logger = _Logger()
    monkeypatch.setattr(nemu_ipc_module, "logger", logger)
    monkeypatch.setattr(nemu_ipc_module, "time", type("_Time", (), {"sleep": lambda _delay: None}))
    return logger


def _run_retry(monkeypatch, error: Exception):
    logger = _patch_retry_runtime(monkeypatch)
    device = _NemuIpc()

    @nemu_ipc_module.retry
    def flaky(target):
        target.calls.append("run")
        target.run_count += 1
        if target.run_count == 1:
            raise error
        return "ok"

    return flaky(device), device, logger


def test_nemu_ipc_retry_recovers_ipc_error(monkeypatch) -> None:
    result, device, logger = _run_retry(monkeypatch, NemuIpcError("lost"))

    assert result == "ok"
    assert logger.errors == ["lost"]
    assert device.calls == ["run", "reconnect", "run"]


def test_nemu_ipc_retry_stops_on_incompatible_version(monkeypatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _NemuIpc()

    @nemu_ipc_module.retry
    def always_incompatible(target):
        target.calls.append("run")
        raise NemuIpcIncompatible("old")

    with pytest.raises(RequestHumanTakeover):
        always_incompatible(device)

    assert device.calls == ["run"]
    assert logger.errors == ["old"]
    assert logger.criticals == ["Retry always_incompatible() failed"]


def test_nemu_ipc_retry_extends_screenshot_timeout(monkeypatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _NemuIpc()

    @nemu_ipc_module.retry
    def screenshot(target, timeout=0.5):
        target.calls.append("run")
        target.timeouts.append(timeout)
        target.run_count += 1
        if target.run_count <= 2:
            raise JobTimeout
        return timeout

    assert screenshot(device) == 1
    assert device.calls == ["run", "run", "run"]
    assert device.timeouts == [0.5, 0.5, 1]
    assert logger.warnings == [
        "Func screenshot() call timeout, retrying: 0",
        "Func screenshot() call timeout, retrying: 1",
    ]


def test_nemu_ipc_retry_retries_native_errors_without_reconnect(monkeypatch) -> None:
    result, device, logger = _run_retry(monkeypatch, OSError("native"))

    assert result == "ok"
    assert logger.errors == ["native"]
    assert device.calls == ["run", "run"]


def test_nemu_ipc_retry_retries_argument_errors_without_reconnect(monkeypatch) -> None:
    result, device, logger = _run_retry(monkeypatch, ctypes.ArgumentError("bad argument"))

    assert result == "ok"
    assert logger.errors == ["bad argument"]
    assert device.calls == ["run", "run"]
