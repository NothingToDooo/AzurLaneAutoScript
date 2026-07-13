from types import SimpleNamespace
from typing import TYPE_CHECKING

from module.device.platform.emulator_base import EmulatorManagerBase
from module.device.platform.emulator_windows import Emulator, EmulatorInstance

if TYPE_CHECKING:
    from pathlib import Path


def _touch_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    return path


def _write_nemu(folder: Path, hostport: str | None = None, *, filename: str = "instance.nemu") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if hostport is None:
        text = "<Machine></Machine>"
    else:
        text = f'<Forwarding name="port2" proto="1" hostip="127.0.0.1" hostport="{hostport}" guestport="5555"/>'
    (folder / filename).write_text(text, encoding="utf-8")


def test_legacy_nemu_player_is_not_supported(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nemu" / "EmulatorShell" / "NemuPlayer.exe")
    emulator = Emulator(exe.as_posix())

    assert emulator.type == ""
    assert list(emulator.iter_instances()) == []


def test_legacy_mumux_player_is_not_supported(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nemu9" / "EmulatorShell" / "NemuPlayer.exe")
    _write_nemu(tmp_path / "nemu9" / "vms" / "nemu-12.0-x64-default", hostport="62026")
    emulator = Emulator(exe.as_posix())

    assert emulator.type == ""
    assert list(emulator.iter_instances()) == []


def test_iter_instances_falls_back_to_mumu12_default_serial(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nx_main" / "MuMuNxMain.exe")
    _write_nemu(tmp_path / "vms" / "MuMuPlayer-12.0-2")
    emulator = Emulator(exe.as_posix())

    instances = list(emulator.iter_instances())

    assert len(instances) == 1
    assert instances[0].serial == "127.0.0.1:16448"
    assert instances[0].name == "MuMuPlayer-12.0-2"
    assert instances[0].path == emulator.path


def test_all_emulator_serials_keeps_only_mumu_tcp_serials() -> None:
    manager = object.__new__(EmulatorManagerBase)
    manager.all_emulator_instances = [
        SimpleNamespace(serial="127.0.0.1:5555"),
        SimpleNamespace(serial="emulator-5554"),
        SimpleNamespace(serial="127.0.0.1:16384"),
    ]

    assert manager.all_emulator_serials == ["127.0.0.1:16384"]


def test_iter_instances_normalizes_legacy_hostport_to_mumu12_default_serial(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nx_main" / "MuMuNxMain.exe")
    _write_nemu(tmp_path / "vms" / "MuMuPlayer-12.0-1", hostport="7555")
    emulator = Emulator(exe.as_posix())

    instances = list(emulator.iter_instances())

    assert len(instances) == 1
    assert instances[0].serial == "127.0.0.1:16416"
    assert instances[0].name == "MuMuPlayer-12.0-1"


def test_iter_instances_deduplicates_identical_nemu_files(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nx_main" / "MuMuNxMain.exe")
    folder = tmp_path / "vms" / "MuMuPlayer-12.0-1"
    _write_nemu(folder, hostport="16416", filename="instance.nemu")
    _write_nemu(folder, hostport="16416", filename="instance-copy.nemu")
    emulator = Emulator(exe.as_posix())

    instances = list(emulator.iter_instances())

    assert [(instance.serial, instance.name, instance.path) for instance in instances] == [
        ("127.0.0.1:16416", "MuMuPlayer-12.0-1", emulator.path)
    ]


def test_iter_instances_keeps_distinct_names_with_same_serial(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nx_main" / "MuMuNxMain.exe")
    _write_nemu(tmp_path / "vms" / "MuMuPlayer-12.0-0", hostport="16384")
    _write_nemu(tmp_path / "vms" / "MuMuPlayer-12.0-1", hostport="16384")
    emulator = Emulator(exe.as_posix())

    instances = list(emulator.iter_instances())

    assert [(instance.serial, instance.name) for instance in instances] == [
        ("127.0.0.1:16384", "MuMuPlayer-12.0-0"),
        ("127.0.0.1:16384", "MuMuPlayer-12.0-1"),
    ]


def test_mumu_global_name_is_not_supported(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nx_main" / "MuMuNxMain.exe")
    instance = EmulatorInstance(
        serial="",
        name="MuMuPlayerGlobal-12.0-0",
        path=exe.as_posix(),
    )

    assert instance.mumu_player_12_id is None


def test_iter_instances_ignores_mumu_global_folder(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nx_main" / "MuMuNxMain.exe")
    _write_nemu(tmp_path / "vms" / "MuMuPlayerGlobal-12.0-0", hostport="16384")
    _write_nemu(tmp_path / "vms" / "MuMuPlayer-12.0-1", hostport="16416")
    emulator = Emulator(exe.as_posix())

    instances = list(emulator.iter_instances())

    assert len(instances) == 1
    assert instances[0].serial == "127.0.0.1:16416"
    assert instances[0].name == "MuMuPlayer-12.0-1"
