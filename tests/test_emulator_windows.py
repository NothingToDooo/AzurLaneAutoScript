from contextlib import nullcontext
from types import SimpleNamespace
from typing import TYPE_CHECKING

from module.device.platform import emulator_windows as emulator_windows_module
from module.device.platform.emulator_windows import EmulatorManager
from module.device.runtime import MumuRuntime

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import pytest


class _ConfiguredEmulatorManager(EmulatorManager):
    def __init__(self, path: Path) -> None:
        super().__init__(path.as_posix())

    @staticmethod
    def iter_running_emulator() -> Iterator[str]:
        return iter(())


def test_emulator_manager_uses_configured_mumu_path(tmp_path: Path) -> None:
    executable = tmp_path / "MuMuPlayer-12.0" / "shell" / "MuMuPlayer.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    emulators = _ConfiguredEmulatorManager(executable).all_emulators

    assert len(emulators) == 1
    assert emulators[0].path == executable.as_posix()


def test_emulator_manager_discovers_stopped_mumu_from_windows_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_location = tmp_path / "MuMu Player 12"
    executable = install_location / "nx_main" / "MuMuNxMain.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    def open_key(root: object, key_path: str) -> nullcontext[object]:
        assert key_path == r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MuMuPlayer"
        if root == "current_user":
            raise FileNotFoundError
        return nullcontext(object())

    def query_value_ex(_key: object, value_name: str) -> tuple[str, int]:
        assert value_name == "InstallLocation"
        return install_location.as_posix(), 1

    registry = SimpleNamespace(
        HKEY_CURRENT_USER="current_user",
        HKEY_LOCAL_MACHINE="local_machine",
        OpenKey=open_key,
        QueryValueEx=query_value_ex,
    )
    monkeypatch.setattr(emulator_windows_module, "winreg", registry)
    monkeypatch.setattr(EmulatorManager, "iter_running_emulator", staticmethod(lambda: iter(())))

    emulators = EmulatorManager().all_emulators

    assert [emulator.path for emulator in emulators] == [executable.as_posix()]


def test_mumu_runtime_uses_configured_path_to_discover_stopped_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "MuMu Player 12" / "nx_main" / "MuMuNxMain.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    instance_folder = tmp_path / "MuMu Player 12" / "vms" / "MuMuPlayer-15.0-1"
    instance_folder.mkdir(parents=True)
    (instance_folder / "instance.nemu").write_text(
        '<Forwarding hostport="16416" guestport="5555"/>',
        encoding="utf-8",
    )
    monkeypatch.setattr(EmulatorManager, "iter_running_emulator", staticmethod(lambda: iter(())))
    runtime = object.__new__(MumuRuntime)
    runtime.session = SimpleNamespace(config=SimpleNamespace(Emulator_MuMuPath=executable.as_posix()))

    instances = runtime.emulator_manager.all_emulator_instances

    assert [(instance.serial, instance.name, instance.path) for instance in instances] == [
        ("127.0.0.1:16416", "MuMuPlayer-15.0-1", executable.as_posix())
    ]


def test_mumu_runtime_caches_emulator_manager() -> None:
    runtime = object.__new__(MumuRuntime)
    runtime.session = SimpleNamespace(config=SimpleNamespace(Emulator_MuMuPath="C:/MuMu/MuMuNxMain.exe"))

    manager = runtime.emulator_manager

    assert isinstance(manager, EmulatorManager)
    assert manager.configured_emulator_path == "C:/MuMu/MuMuNxMain.exe"
    assert runtime.emulator_manager is manager
