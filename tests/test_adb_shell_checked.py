from types import SimpleNamespace

import pytest

from module.device.adb_session import AdbSession


class _Adb:
    def __init__(self, *, returncode: int, output: str, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.output = output
        self.stderr = stderr
        self.stdout = stdout
        self.last_timeout: float | None = None

    def shell2(
        self,
        command: list[str],
        *,
        timeout: float | None,
        rstrip: bool,
    ) -> SimpleNamespace:
        self.last_timeout = timeout
        return SimpleNamespace(
            command=" ".join(command),
            returncode=self.returncode,
            output=self.output.rstrip() if rstrip else self.output,
            stderr=self.stderr.rstrip() if rstrip else self.stderr,
            stdout=self.stdout.rstrip() if rstrip else self.stdout,
        )


def _session(adb: _Adb) -> AdbSession:
    session = object.__new__(AdbSession)
    session.__dict__["adb"] = adb
    return session


def test_adb_shell_checked_returns_success_output() -> None:
    session = _session(_Adb(returncode=0, output="selected\n"))

    assert session.adb_shell_checked(["ime", "set", "example/.Ime"]) == "selected"


def test_adb_shell_checked_raises_with_command_failure_reason() -> None:
    session = _session(_Adb(returncode=1, output="", stderr="Unknown id: example/.Ime\n"))

    with pytest.raises(OSError, match=r"exit code 1.*Unknown id"):
        session.adb_shell_checked(["ime", "set", "example/.Ime"])
