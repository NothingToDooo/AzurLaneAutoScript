from typing import TYPE_CHECKING

from module.device.platform.emulator_windows import EmulatorManager

if TYPE_CHECKING:
    from pathlib import Path


class _EmulatorInfo:
    def __init__(self, path: Path) -> None:
        self.path = path.as_posix()


class _ConfiguredEmulatorManager(EmulatorManager):
    def __init__(self, path: Path) -> None:
        self.emulator_info = _EmulatorInfo(path)

    @staticmethod
    def iter_running_emulator():
        return ()


def test_emulator_manager_uses_configured_mumu_path(tmp_path: Path) -> None:
    executable = tmp_path / "MuMuPlayer-12.0" / "shell" / "MuMuPlayer.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    emulators = _ConfiguredEmulatorManager(executable).all_emulators

    assert len(emulators) == 1
    assert emulators[0].path == executable.as_posix()
