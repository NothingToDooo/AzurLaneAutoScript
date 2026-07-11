from types import SimpleNamespace

import pytest
from adbutils.errors import AdbError

from module.device import minitouch_service as minitouch_module
from module.device.minitouch_service import MinitouchController, MinitouchNotInstalledError, MinitouchOccupiedError
from module.exception import RequestHumanTakeover


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.criticals: list[str] = []

    def error(self, error: BaseException) -> None:
        self.errors.append(str(error))

    def critical(self, message: str) -> None:
        self.criticals.append(str(message))


class _Session:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def adb_reconnect(self) -> None:
        self.calls.append("adb_reconnect")

    def adb_start_server(self) -> None:
        self.calls.append("adb_start_server")


class _Minitouch:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.run_count = 0
        self.session = _Session(self.calls)

    def _reset_minitouch_connection(self, *, remove_forward: bool = True) -> None:
        self.calls.append(f"reset:{remove_forward}")

    def _restart_minitouch_service(self) -> None:
        self.calls.append("restart_service")


def _patch_retry_runtime(monkeypatch: pytest.MonkeyPatch) -> _Logger:
    logger = _Logger()
    monkeypatch.setattr(minitouch_module, "logger", logger)
    monkeypatch.setattr(minitouch_module, "time", type("_Time", (), {"sleep": lambda _delay: None}))
    return logger


def _run_retry(
    monkeypatch: pytest.MonkeyPatch, error: Exception, *, retryable_adb: bool = True, unknown_host: bool = False
) -> tuple[str, _Minitouch, _Logger]:
    logger = _patch_retry_runtime(monkeypatch)
    device = _Minitouch()
    monkeypatch.setattr(minitouch_module, "handle_adb_error", lambda _error: retryable_adb)
    monkeypatch.setattr(minitouch_module, "handle_unknown_host_service", lambda _error: unknown_host)

    @minitouch_module.retry
    def flaky(target: _Minitouch) -> str:
        target.calls.append("run")
        target.run_count += 1
        if target.run_count == 1:
            raise error
        return "ok"

    return flaky(device), device, logger


def test_minitouch_retry_recovers_connection_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, ConnectionResetError("lost"))

    assert result == "ok"
    assert logger.errors == ["lost"]
    assert device.calls == ["run", "adb_reconnect", "reset:True", "run"]


def test_minitouch_retry_recovers_connection_aborted(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, ConnectionAbortedError("closed"))

    assert result == "ok"
    assert logger.errors == ["closed"]
    assert device.calls == ["run", "adb_reconnect", "reset:True", "run"]


def test_minitouch_retry_recovers_occupied_service(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, MinitouchOccupiedError("occupied"))

    assert result == "ok"
    assert logger.errors == ["occupied"]
    assert device.calls == ["run", "restart_service", "reset:True", "run"]


def test_minitouch_retry_recovers_retryable_adb_error(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, _ = _run_retry(monkeypatch, AdbError("closed"))

    assert result == "ok"
    assert device.calls == ["run", "adb_reconnect", "reset:True", "run"]


def test_minitouch_retry_recovers_unknown_host_service(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, _ = _run_retry(
        monkeypatch, AdbError("unknown host service"), retryable_adb=False, unknown_host=True
    )

    assert result == "ok"
    assert device.calls == ["run", "adb_start_server", "adb_reconnect", "reset:True", "run"]


def test_minitouch_retry_preserves_forward_on_broken_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, BrokenPipeError("pipe"))

    assert result == "ok"
    assert logger.errors == ["pipe"]
    assert device.calls == ["run", "reset:False", "run"]


def test_minitouch_retry_resets_connection_on_os_error(monkeypatch: pytest.MonkeyPatch) -> None:
    result, device, logger = _run_retry(monkeypatch, OSError("socket"))

    assert result == "ok"
    assert logger.errors == ["socket"]
    assert device.calls == ["run", "reset:True", "run"]


def test_minitouch_retry_stops_on_unhandled_adb_error(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _Minitouch()
    monkeypatch.setattr(minitouch_module, "handle_adb_error", lambda _error: False)
    monkeypatch.setattr(minitouch_module, "handle_unknown_host_service", lambda _error: False)

    @minitouch_module.retry
    def always_boom(target: _Minitouch) -> None:
        target.calls.append("run")
        message = "boom"
        raise AdbError(message)

    with pytest.raises(RequestHumanTakeover):
        always_boom(device)

    assert device.calls == ["run"]
    assert logger.criticals == ["Retry always_boom() failed"]


def test_minitouch_retry_hands_over_when_minitouch_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = _patch_retry_runtime(monkeypatch)
    device = _Minitouch()

    @minitouch_module.retry
    def always_missing(target: _Minitouch) -> None:
        target.calls.append("run")
        message = "missing"
        raise MinitouchNotInstalledError(message)

    with pytest.raises(RequestHumanTakeover):
        always_missing(device)

    assert device.calls == ["run"]
    assert logger.criticals == ["missing"]


def test_minitouch_release_resource_clears_cached_builder() -> None:
    device = MinitouchController(SimpleNamespace())
    device.__dict__["_minitouch_builder"] = object()

    device.release_resource()

    assert "_minitouch_builder" not in device.__dict__


def test_minitouch_rebind_excludes_old_pid_from_new_device_restart() -> None:
    old_serial = "127.0.0.1:16384"
    new_serial = "127.0.0.1:16385"
    session = SimpleNamespace(serial=old_serial, config=SimpleNamespace(Emulator_Serial=old_serial))
    device = MinitouchController(session)
    vars(device)["_minitouch_pid"] = "4312"
    adb_calls: list[tuple[str, object]] = []

    def adb_shell(command: str | list[str | int], **_kwargs: object) -> str:
        adb_calls.append((session.serial, command))
        if isinstance(command, str):
            return "u0_a123 9821 1 S minitouch"
        return ""

    session.adb_shell = adb_shell
    device.__dict__["_start_minitouch_service"] = lambda: None

    device.release()
    session.serial = new_serial
    restart_minitouch_service = vars(MinitouchController)["_restart_minitouch_service"]
    restart_minitouch_service(device)

    killed_pids = {command[1] for _, command in adb_calls if isinstance(command, list) and command[:1] == ["kill"]}
    assert killed_pids == {"9821"}
    assert {serial for serial, _ in adb_calls} == {new_serial}
