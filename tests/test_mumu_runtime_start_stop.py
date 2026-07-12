from typing import TYPE_CHECKING

import pytest

from module.device.platform.emulator_windows import EmulatorInstance
from module.device.runtime import EmulatorUnknown, MumuRuntime

if TYPE_CHECKING:
    from pathlib import Path


class _Runtime(MumuRuntime):
    def start_instance(self, instance: EmulatorInstance) -> None:
        self._emulator_start(instance)

    def stop_instance(self, instance: EmulatorInstance) -> None:
        self._emulator_stop(instance)


def _mumu12_instance(tmp_path: Path) -> EmulatorInstance:
    executable = tmp_path / "MuMuPlayer-12.0" / "shell" / "MuMuPlayer.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    return EmulatorInstance(
        serial="127.0.0.1:16416",
        name="MuMuPlayer-12.0-1",
        path=executable.as_posix(),
    )


def _legacy_instance(tmp_path: Path) -> EmulatorInstance:
    executable = tmp_path / "nemu" / "EmulatorShell" / "NemuPlayer.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    return EmulatorInstance(
        serial="127.0.0.1:7555",
        name="",
        path=executable.as_posix(),
    )


def test_emulator_start_uses_mumu12_manager_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(MumuRuntime, "execute", classmethod(lambda _cls, command: commands.append(command)))
    runtime = object.__new__(_Runtime)

    runtime.start_instance(_mumu12_instance(tmp_path))

    assert commands == [
        [
            (tmp_path / "MuMuPlayer-12.0" / "shell" / "MuMuManager.exe").as_posix(),
            "api",
            "-v",
            "1",
            "launch_player",
        ]
    ]


def test_emulator_stop_uses_mumu12_manager_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(MumuRuntime, "execute", classmethod(lambda _cls, command: commands.append(command)))
    runtime = object.__new__(_Runtime)

    runtime.stop_instance(_mumu12_instance(tmp_path))

    assert commands == [
        [
            (tmp_path / "MuMuPlayer-12.0" / "shell" / "MuMuManager.exe").as_posix(),
            "api",
            "-v",
            "1",
            "shutdown_player",
        ]
    ]


def test_legacy_emulator_instance_cannot_start_or_stop(tmp_path: Path) -> None:
    runtime = object.__new__(_Runtime)
    instance = _legacy_instance(tmp_path)

    with pytest.raises(EmulatorUnknown):
        runtime.start_instance(instance)
    with pytest.raises(EmulatorUnknown):
        runtime.stop_instance(instance)
