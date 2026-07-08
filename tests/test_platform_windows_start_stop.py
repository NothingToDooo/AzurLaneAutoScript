import pytest

from module.device.platform.emulator_windows import EmulatorInstance
from module.device.platform.platform_windows import EmulatorUnknown, PlatformWindows


class _Platform(PlatformWindows):
    def start_instance(self, instance: EmulatorInstance) -> None:
        self._emulator_start(instance)

    def stop_instance(self, instance: EmulatorInstance) -> None:
        self._emulator_stop(instance)


def _mumu12_instance(tmp_path):
    executable = tmp_path / "MuMuPlayer-12.0" / "shell" / "MuMuPlayer.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    return EmulatorInstance(
        serial="127.0.0.1:16416",
        name="MuMuPlayer-12.0-1",
        path=executable.as_posix(),
    )


def _legacy_instance(tmp_path):
    executable = tmp_path / "nemu" / "EmulatorShell" / "NemuPlayer.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    return EmulatorInstance(
        serial="127.0.0.1:7555",
        name="",
        path=executable.as_posix(),
    )


def test_emulator_start_uses_mumu12_manager_api(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(PlatformWindows, "execute", classmethod(lambda _cls, command: commands.append(command)))
    platform = object.__new__(_Platform)

    platform.start_instance(_mumu12_instance(tmp_path))

    assert commands == [
        [
            (tmp_path / "MuMuPlayer-12.0" / "shell" / "MuMuManager.exe").as_posix(),
            "api",
            "-v",
            "1",
            "launch_player",
        ]
    ]


def test_emulator_stop_uses_mumu12_manager_api(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(PlatformWindows, "execute", classmethod(lambda _cls, command: commands.append(command)))
    platform = object.__new__(_Platform)

    platform.stop_instance(_mumu12_instance(tmp_path))

    assert commands == [
        [
            (tmp_path / "MuMuPlayer-12.0" / "shell" / "MuMuManager.exe").as_posix(),
            "api",
            "-v",
            "1",
            "shutdown_player",
        ]
    ]


def test_legacy_emulator_instance_cannot_start_or_stop(tmp_path) -> None:
    platform = object.__new__(_Platform)
    instance = _legacy_instance(tmp_path)

    with pytest.raises(EmulatorUnknown):
        platform.start_instance(instance)
    with pytest.raises(EmulatorUnknown):
        platform.stop_instance(instance)
