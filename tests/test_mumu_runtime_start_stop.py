from typing import TYPE_CHECKING

from module.device.mumu_instance import MuMuInstance
from module.device.runtime import MumuRuntime

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class _Runtime(MumuRuntime):
    def start_instance(self, instance: MuMuInstance) -> None:
        self._emulator_start(instance)

    def stop_instance(self, instance: MuMuInstance) -> None:
        self._emulator_stop(instance)


def _mumu12_instance(tmp_path: Path) -> MuMuInstance:
    executable = tmp_path / "MuMu Player 12" / "nx_main" / "MuMuNxMain.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    return MuMuInstance(
        executable=executable,
        instance_id=1,
        name="MuMuPlayer-15.0-1",
        config_dir=tmp_path / "MuMu Player 12" / "vms" / "MuMuPlayer-15.0-1" / "configs",
    )


def test_emulator_start_uses_mumu12_manager_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(MumuRuntime, "execute", classmethod(lambda _cls, command: commands.append(command)))
    runtime = object.__new__(_Runtime)

    runtime.start_instance(_mumu12_instance(tmp_path))

    assert commands == [
        [
            (tmp_path / "MuMu Player 12" / "nx_main" / "MuMuManager.exe").as_posix(),
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
            (tmp_path / "MuMu Player 12" / "nx_main" / "MuMuManager.exe").as_posix(),
            "api",
            "-v",
            "1",
            "shutdown_player",
        ]
    ]
