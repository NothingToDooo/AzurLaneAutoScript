import pytest
from adbutils.errors import AdbError

from module.device import adb_session as adb_session_module
from module.device.method.utils import PackageNotInstalled
from module.exception import RequestHumanTakeover


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.criticals: list[str] = []

    def error(self, error: BaseException) -> None:
        self.errors.append(str(error))

    def critical(self, message: str) -> None:
        self.criticals.append(message)


class _Connection:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.run_count = 0

    def adb_reconnect(self) -> None:
        self.calls.append("adb_reconnect")

    def adb_start_server(self) -> int:
        self.calls.append("adb_start_server")
        return 0

    def detect_package(self) -> None:
        self.calls.append("detect_package")


class _FailingStartConnection(_Connection):
    def adb_start_server(self) -> int:
        self.calls.append("adb_start_server")
        message = "ADB start-server failed with exit code 1: cannot bind listener"
        raise OSError(message)


def _patch_retry_runtime(monkeypatch: pytest.MonkeyPatch) -> _Logger:
    logger = _Logger()
    monkeypatch.setattr(adb_session_module, "logger", logger)
    monkeypatch.setattr(adb_session_module, "time", type("_Time", (), {"sleep": lambda _delay: None}))
    return logger


def _run_retry(
    monkeypatch: pytest.MonkeyPatch, error: Exception, *, retryable_adb: bool = True, unknown_host: bool = False
) -> tuple[str, _Connection, _Logger]:
    logger = _patch_retry_runtime(monkeypatch)
    device = _Connection()
    monkeypatch.setattr(adb_session_module, "handle_adb_error", lambda _error: retryable_adb)
    monkeypatch.setattr(adb_session_module, "handle_unknown_host_service", lambda _error: unknown_host)

    @adb_session_module.retry
    def flaky(target: _Connection) -> str:
        target.calls.append("run")
        target.run_count += 1
        if target.run_count == 1:
            raise error
        return "ok"

    return flaky(device), device, logger


def test_connection_retry_recovers_connection_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, ConnectionResetError("lost"))

    assert result == "ok"
    assert logger.errors == ["lost"]
    assert device.calls == ["run", "adb_reconnect", "run"]


def test_connection_retry_recovers_retryable_adb_error(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, _ = _run_retry(monkeypatch, AdbError("closed"))

    assert result == "ok"
    assert device.calls == ["run", "adb_reconnect", "run"]


def test_connection_retry_recovers_unknown_host_service(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, _ = _run_retry(
        monkeypatch, AdbError("unknown host service"), retryable_adb=False, unknown_host=True
    )

    assert result == "ok"
    assert device.calls == ["run", "adb_start_server", "adb_reconnect", "run"]


def test_connection_retry_stops_on_unhandled_adb_error(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _Connection()
    monkeypatch.setattr(adb_session_module, "handle_adb_error", lambda _error: False)
    monkeypatch.setattr(adb_session_module, "handle_unknown_host_service", lambda _error: False)

    @adb_session_module.retry
    def always_boom(target: _Connection) -> None:
        target.calls.append("run")
        message = "boom"
        raise AdbError(message)

    with pytest.raises(RequestHumanTakeover):
        always_boom(device)

    assert device.calls == ["run"]
    assert logger.criticals == ["Retry always_boom() failed"]


def test_connection_retry_recovers_missing_package(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, PackageNotInstalled("pkg"))

    assert result == "ok"
    assert logger.errors == ["pkg"]
    assert device.calls == ["run", "detect_package", "run"]


def test_connection_retry_starts_adb_server_when_connection_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, device, logger = _run_retry(monkeypatch, ConnectionRefusedError("adb server is stopped"))

    assert result == "ok"
    assert logger.errors == ["adb server is stopped"]
    assert device.calls == ["run", "adb_start_server", "run"]


def test_connection_retry_keeps_os_error_as_plain_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, OSError("pipe"))

    assert result == "ok"
    assert logger.errors == ["pipe"]
    assert device.calls == ["run", "run"]


def test_connection_retry_converges_when_adb_server_start_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _FailingStartConnection()

    @adb_session_module.retry
    def always_refused(target: _Connection) -> None:
        target.calls.append("run")
        message = "adb server is stopped"
        raise ConnectionRefusedError(message)

    with pytest.raises(RequestHumanTakeover):
        always_refused(device)

    assert "adb_start_server" in device.calls
    assert logger.errors == [
        "adb server is stopped",
        "ADB start-server failed with exit code 1: cannot bind listener",
        "adb server is stopped",
        "ADB start-server failed with exit code 1: cannot bind listener",
        "adb server is stopped",
    ]
    assert logger.criticals == ["Retry always_refused() failed"]
