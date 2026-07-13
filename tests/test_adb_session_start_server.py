import subprocess
from types import SimpleNamespace

import pytest

from module.device import adb_session as adb_session_module
from module.device.adb_session import AdbSession


class _Logger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.errors: list[str] = []

    def info(self, message: object) -> None:
        self.infos.append(str(message))

    def error(self, message: object) -> None:
        self.errors.append(str(message))


def test_adb_start_server_launches_configured_binary_on_isolated_port(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []
    run_options: list[dict[str, object]] = []
    events: list[str] = []
    adb_binary = "C:/Alas/bin/adb/adb.exe"
    monkeypatch.setenv("ANDROID_ADB_SERVER_PORT", "65037")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        run_options.append(kwargs)
        events.append("run")
        return subprocess.CompletedProcess(command, 0, stdout="daemon started\n", stderr="")

    def server_version() -> int:
        events.append("server_version")
        return 41

    monkeypatch.setattr(adb_session_module.subprocess, "run", run)
    session = object.__new__(AdbSession)
    vars(session).update(
        adb_binary=adb_binary,
        adb_client=SimpleNamespace(server_version=server_version),
    )

    version = session.adb_start_server()

    assert commands == [[adb_binary, "-P", "65037", "start-server"]]
    assert run_options == [
        {
            "capture_output": True,
            "check": True,
            "creationflags": subprocess.CREATE_NO_WINDOW,
            "text": True,
            "timeout": 10,
        }
    ]
    assert events == ["run", "server_version"]
    assert version == 41


def test_adb_start_server_translates_process_failure_and_logs_output(monkeypatch: pytest.MonkeyPatch) -> None:
    adb_binary = "C:/Alas/bin/adb/adb.exe"
    command = [adb_binary, "-P", "65037", "start-server"]
    process_error = subprocess.CalledProcessError(
        returncode=1,
        cmd=command,
        output="daemon stdout\n",
        stderr="cannot bind listener\n",
    )
    logger = _Logger()
    monkeypatch.setenv("ANDROID_ADB_SERVER_PORT", "65037")

    def fail_to_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise process_error

    monkeypatch.setattr(adb_session_module.subprocess, "run", fail_to_run)
    monkeypatch.setattr(adb_session_module, "logger", logger)
    session = object.__new__(AdbSession)
    vars(session).update(
        adb_binary=adb_binary,
        adb_client=SimpleNamespace(server_version=lambda: 0),
    )

    with pytest.raises(OSError, match=r"ADB start-server failed with exit code 1: cannot bind listener") as raised:
        session.adb_start_server()

    assert raised.value.__cause__ is process_error
    assert logger.errors == ["daemon stdout", "cannot bind listener"]


def test_adb_start_server_translates_timeout_and_logs_partial_output(monkeypatch: pytest.MonkeyPatch) -> None:
    adb_binary = "C:/Alas/bin/adb/adb.exe"
    command = [adb_binary, "-P", "65037", "start-server"]
    timeout_error = subprocess.TimeoutExpired(
        cmd=command,
        timeout=10,
        output="partial stdout\n",
        stderr="startup stalled\n",
    )
    logger = _Logger()
    server_version_called = False
    monkeypatch.setenv("ANDROID_ADB_SERVER_PORT", "65037")

    def fail_to_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise timeout_error

    def server_version() -> int:
        nonlocal server_version_called
        server_version_called = True
        return 0

    monkeypatch.setattr(adb_session_module.subprocess, "run", fail_to_run)
    monkeypatch.setattr(adb_session_module, "logger", logger)
    session = object.__new__(AdbSession)
    vars(session).update(
        adb_binary=adb_binary,
        adb_client=SimpleNamespace(server_version=server_version),
    )

    with pytest.raises(OSError, match=r"ADB start-server timed out after 10 seconds: startup stalled") as raised:
        session.adb_start_server()

    assert raised.value.__cause__ is timeout_error
    assert logger.errors == ["partial stdout", "startup stalled"]
    assert not server_version_called
