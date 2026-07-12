import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING

from module.device import adb_session as adb_session_module
from module.device.adb_session import AdbSession

if TYPE_CHECKING:
    import pytest


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
