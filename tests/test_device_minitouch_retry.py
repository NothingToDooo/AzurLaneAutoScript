from typing import TYPE_CHECKING, Literal, overload

import pytest
from adbutils.errors import AdbError

from module.device import minitouch_service as minitouch_module
from module.device.minitouch_service import MinitouchController, MinitouchNotInstalledError, MinitouchOccupiedError
from module.exception import RequestHumanTakeover

if TYPE_CHECKING:
    from collections.abc import Iterable

    from adbutils import AdbConnection

    from module.device.control_options import Duration


class _MinitouchConfigDouble:
    MINITOUCH_FILEPATH_REMOTE = "/data/local/tmp/minitouch"


class _MinitouchSessionDouble:
    def __init__(self, serial: str = "127.0.0.1:16384") -> None:
        self.serial = serial
        self.adb_calls: list[tuple[str, str | list[str | int]]] = []
        self.forward_requests: list[str] = []
        self.forward_removals: list[str] = []
        self._config = _MinitouchConfigDouble()
        self._orientation = 0
        self._adb_server_result = 0
        self._forward_port = 12345

    @property
    def config(self) -> _MinitouchConfigDouble:
        return self._config

    @property
    def orientation(self) -> int:
        return self._orientation

    @overload
    def adb_shell(
        self,
        cmd: str | Iterable[str | int],
        *,
        stream: Literal[False] = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str: ...

    @overload
    def adb_shell(
        self,
        cmd: str | Iterable[str | int],
        *,
        stream: Literal[True],
        recvall: Literal[True] = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> bytes: ...

    @overload
    def adb_shell(
        self,
        cmd: str | Iterable[str | int],
        *,
        stream: Literal[True],
        recvall: Literal[False],
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> AdbConnection: ...

    def adb_shell(
        self,
        cmd: str | Iterable[str | int],
        *,
        stream: bool = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str | bytes | AdbConnection:
        del recvall, timeout, rstrip
        command = cmd if isinstance(cmd, str) else list(cmd)
        self.adb_calls.append((self.serial, command))
        if stream:
            message = "streaming adb_shell is not used by this test double"
            raise AssertionError(message)
        if isinstance(command, str):
            return "u0_a123 9821 1 S minitouch"
        return ""

    def adb_reconnect(self) -> None:
        pass

    def adb_start_server(self) -> int:
        return self._adb_server_result

    def adb_forward(self, remote: str) -> int:
        self.forward_requests.append(remote)
        return self._forward_port

    def adb_forward_remove(self, local: str) -> None:
        self.forward_removals.append(local)

    def get_orientation(self) -> int:
        return self._orientation

    @staticmethod
    def sleep(second: Duration) -> None:
        del second


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

    def adb_start_server(self) -> int:
        self.calls.append("adb_start_server")
        return 0


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
    device = MinitouchController(_MinitouchSessionDouble())
    device.__dict__["_minitouch_builder"] = object()

    device.release_resource()

    assert "_minitouch_builder" not in device.__dict__


def test_minitouch_rebind_excludes_old_pid_from_new_device_restart() -> None:
    old_serial = "127.0.0.1:16384"
    new_serial = "127.0.0.1:16385"
    session = _MinitouchSessionDouble(old_serial)
    device = MinitouchController(session)
    vars(device)["_minitouch_pid"] = "4312"
    device.__dict__["_start_minitouch_service"] = lambda: None

    device.release()
    session.serial = new_serial
    restart_minitouch_service = vars(MinitouchController)["_restart_minitouch_service"]
    restart_minitouch_service(device)

    killed_pids = {
        command[1] for _, command in session.adb_calls if isinstance(command, list) and command[:1] == ["kill"]
    }
    assert killed_pids == {"9821"}
    assert {serial for serial, _ in session.adb_calls} == {new_serial}
