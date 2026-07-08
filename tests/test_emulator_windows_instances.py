from typing import TYPE_CHECKING

from module.device.platform.emulator_windows import Emulator

if TYPE_CHECKING:
    from pathlib import Path


def _touch_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    return path


def _write_nemu(folder: Path, hostport: str | None = None) -> None:
    folder.mkdir(parents=True)
    if hostport is None:
        text = "<Machine></Machine>"
    else:
        text = f'<Forwarding name="port2" proto="1" hostip="127.0.0.1" hostport="{hostport}" guestport="5555"/>'
    (folder / "instance.nemu").write_text(text, encoding="utf-8")


def test_iter_instances_returns_legacy_mumu_default_serial(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nemu" / "EmulatorShell" / "NemuPlayer.exe")
    emulator = Emulator(exe.as_posix())

    instances = list(emulator.iter_instances())

    assert len(instances) == 1
    assert instances[0].serial == "127.0.0.1:7555"
    assert instances[0].name == ""
    assert instances[0].path == emulator.path


def test_iter_instances_reads_vbox_serial_for_mumux(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "nemu9" / "EmulatorShell" / "NemuPlayer.exe")
    _write_nemu(tmp_path / "nemu9" / "vms" / "nemu-12.0-x64-default", hostport="62026")
    emulator = Emulator(exe.as_posix())

    instances = list(emulator.iter_instances())

    assert len(instances) == 1
    assert instances[0].serial == "127.0.0.1:62026"
    assert instances[0].name == "nemu-12.0-x64-default"
    assert instances[0].path == emulator.path


def test_iter_instances_falls_back_to_mumu12_default_serial(tmp_path: Path) -> None:
    exe = _touch_exe(tmp_path / "shell" / "MuMuPlayer.exe")
    _write_nemu(tmp_path / "vms" / "MuMuPlayer-12.0-2")
    emulator = Emulator(exe.as_posix())

    instances = list(emulator.iter_instances())

    assert len(instances) == 1
    assert instances[0].serial == "127.0.0.1:16448"
    assert instances[0].name == "MuMuPlayer-12.0-2"
    assert instances[0].path == emulator.path
