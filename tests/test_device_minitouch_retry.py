import pytest
from adbutils.errors import AdbError

from module.device.method import minitouch as minitouch_module
from module.device.method.minitouch import Minitouch, MinitouchNotInstalledError, MinitouchOccupiedError
from module.exception import RequestHumanTakeover


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.criticals: list[str] = []

    def error(self, error) -> None:
        self.errors.append(str(error))

    def critical(self, message) -> None:
        self.criticals.append(str(message))


class _Minitouch:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.run_count = 0

    def adb_reconnect(self) -> None:
        self.calls.append("adb_reconnect")

    def adb_start_server(self) -> None:
        self.calls.append("adb_start_server")

    def _reset_minitouch_connection(self, remove_forward=True) -> None:
        self.calls.append(f"reset:{remove_forward}")

    def _restart_minitouch_service(self) -> None:
        self.calls.append("restart_service")


def _patch_retry_runtime(monkeypatch):
    logger = _Logger()
    monkeypatch.setattr(minitouch_module, "logger", logger)
    monkeypatch.setattr(minitouch_module, "time", type("_Time", (), {"sleep": lambda _delay: None}))
    return logger


def _run_retry(monkeypatch, error: Exception, *, retryable_adb=True, unknown_host=False):
    logger = _patch_retry_runtime(monkeypatch)
    device = _Minitouch()
    monkeypatch.setattr(minitouch_module, "handle_adb_error", lambda _error: retryable_adb)
    monkeypatch.setattr(minitouch_module, "handle_unknown_host_service", lambda _error: unknown_host)

    @minitouch_module.retry
    def flaky(target):
        target.calls.append("run")
        target.run_count += 1
        if target.run_count == 1:
            raise error
        return "ok"

    return flaky(device), device, logger


def test_minitouch_retry_recovers_connection_reset(monkeypatch) -> None:
    result, device, logger = _run_retry(monkeypatch, ConnectionResetError("lost"))

    assert result == "ok"
    assert logger.errors == ["lost"]
    assert device.calls == ["run", "adb_reconnect", "reset:True", "run"]


def test_minitouch_retry_recovers_connection_aborted(monkeypatch) -> None:
    result, device, logger = _run_retry(monkeypatch, ConnectionAbortedError("closed"))

    assert result == "ok"
    assert logger.errors == ["closed"]
    assert device.calls == ["run", "adb_reconnect", "reset:True", "run"]


def test_minitouch_retry_recovers_occupied_service(monkeypatch) -> None:
    result, device, logger = _run_retry(monkeypatch, MinitouchOccupiedError("occupied"))

    assert result == "ok"
    assert logger.errors == ["occupied"]
    assert device.calls == ["run", "restart_service", "reset:True", "run"]


def test_minitouch_retry_recovers_retryable_adb_error(monkeypatch) -> None:
    result, device, _ = _run_retry(monkeypatch, AdbError("closed"))

    assert result == "ok"
    assert device.calls == ["run", "adb_reconnect", "reset:True", "run"]


def test_minitouch_retry_recovers_unknown_host_service(monkeypatch) -> None:
    result, device, _ = _run_retry(
        monkeypatch, AdbError("unknown host service"), retryable_adb=False, unknown_host=True
    )

    assert result == "ok"
    assert device.calls == ["run", "adb_start_server", "adb_reconnect", "reset:True", "run"]


def test_minitouch_retry_preserves_forward_on_broken_pipe(monkeypatch) -> None:
    result, device, logger = _run_retry(monkeypatch, BrokenPipeError("pipe"))

    assert result == "ok"
    assert logger.errors == ["pipe"]
    assert device.calls == ["run", "reset:False", "run"]


def test_minitouch_retry_resets_connection_on_os_error(monkeypatch) -> None:
    result, device, logger = _run_retry(monkeypatch, OSError("socket"))

    assert result == "ok"
    assert logger.errors == ["socket"]
    assert device.calls == ["run", "reset:True", "run"]


def test_minitouch_retry_stops_on_unhandled_adb_error(monkeypatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _Minitouch()
    monkeypatch.setattr(minitouch_module, "handle_adb_error", lambda _error: False)
    monkeypatch.setattr(minitouch_module, "handle_unknown_host_service", lambda _error: False)

    @minitouch_module.retry
    def always_boom(target):
        target.calls.append("run")
        message = "boom"
        raise AdbError(message)

    with pytest.raises(RequestHumanTakeover):
        always_boom(device)

    assert device.calls == ["run"]
    assert logger.criticals == ["Retry always_boom() failed"]


def test_minitouch_retry_hands_over_when_minitouch_missing(monkeypatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _Minitouch()

    @minitouch_module.retry
    def always_missing(target):
        target.calls.append("run")
        message = "missing"
        raise MinitouchNotInstalledError(message)

    with pytest.raises(RequestHumanTakeover):
        always_missing(device)

    assert device.calls == ["run"]
    assert logger.criticals == ["missing"]


def test_minitouch_release_resource_clears_cached_builder() -> None:
    device = object.__new__(Minitouch)
    device.__dict__["_minitouch_builder"] = object()

    device.release_resource()

    assert "_minitouch_builder" not in device.__dict__
