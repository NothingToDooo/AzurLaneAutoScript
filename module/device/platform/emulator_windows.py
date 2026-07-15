import re
import winreg
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

# module/device/platform/emulator_base.py
# module/device/platform/emulator_windows.py
# 会被独立安装流程使用，因此这里不要导入 Alas 业务模块。
from module.device.mumu import is_mumu12_serial
from module.device.platform.emulator_base import (
    EmulatorBase,
    EmulatorInstanceBase,
    EmulatorManagerBase,
    remove_duplicated_path,
)
from module.device.platform.utils import cached_property, iter_folder

if TYPE_CHECKING:
    from collections.abc import Iterator


class EmulatorInstance(EmulatorInstanceBase):
    @cached_property
    def emulator(self) -> Emulator:
        return Emulator(self.path)


class Emulator(EmulatorBase):
    @classmethod
    def path_to_type(cls, path: str) -> str:
        emulator_path = Path(path)
        if emulator_path.name.casefold() == "mumunxmain.exe":
            return cls.MuMuPlayer12

        return ""

    @staticmethod
    def single_to_console(exe: str) -> str:
        return Path(exe).with_name("MuMuManager.exe").as_posix()

    @staticmethod
    def vbox_file_to_serial(file: str) -> str:
        """返回 vbox 中转发的 `127.0.0.1:<port>`，文件不存在时返回空字符串。"""
        regex = re.compile(r'<*?hostport="(.*?)".*?guestport="5555"/>')
        serial = ""
        try:
            with Path(file).open(encoding="utf-8", errors="ignore") as f:
                for line in f:
                    # <Forwarding name="port2" proto="1" hostip="127.0.0.1" hostport="62026" guestport="5555"/>
                    res = regex.search(line)
                    if res:
                        serial = f"127.0.0.1:{res.group(1)}"
                        break
        except FileNotFoundError:
            return ""
        else:
            return serial

    def iter_instances(self) -> Iterator[EmulatorInstance]:
        if self.type == Emulator.MuMuPlayer12:
            yield from self._iter_vbox_instances()

    def _iter_vbox_instances(self) -> Iterator[EmulatorInstance]:
        for folder in self.list_folder("../vms", is_dir=True):
            yield from self._iter_vbox_folder_instances(folder)

    def _iter_vbox_folder_instances(self, folder: str) -> Iterator[EmulatorInstance]:
        name = Path(folder).name
        if "MuMuPlayerGlobal" in name:
            return

        seen: set[tuple[str, str, str]] = set()
        for file in iter_folder(folder, ext=".nemu"):
            serial = Emulator.vbox_file_to_serial(file)
            instance = EmulatorInstance(
                serial=serial,
                name=name,
                path=self.path,
            )
            if not is_mumu12_serial(serial):
                instance_id = instance.mumu_player_12_id
                if instance_id is None:
                    continue
                instance.serial = self._mumu12_default_serial(instance_id)

            key = (instance.serial, instance.name, instance.path)
            if key in seen:
                continue
            seen.add(key)
            yield instance

    @staticmethod
    def _mumu12_default_serial(instance_id: int) -> str:
        # MuMu12 v4.0.4 默认实例的 vbox 配置可能没有转发记录。
        return f"127.0.0.1:{16384 + 32 * instance_id}"

    def iter_adb_binaries(self) -> Iterator[str]:
        if self.type != Emulator.MuMuPlayer12:
            return

        # MuMu 目录内可能带有 ADB。
        exe = self.abspath("../vmonitor/bin/adb_server.exe")
        if Path(exe).exists():
            yield exe

        exe = self.abspath("./adb.exe")
        if Path(exe).exists():
            yield exe


class EmulatorManager(EmulatorManagerBase):
    def __init__(self, configured_emulator_path: str = "") -> None:
        self.configured_emulator_path = configured_emulator_path

    def iter_configured_emulator(self) -> Iterator[str]:
        """产生配置中存在的 MuMu12 可执行文件路径。"""
        path = self.configured_emulator_path
        if not path:
            return
        file = path.replace("\\", "/")
        if Emulator.is_emulator(file) and Path(file).is_file():
            yield file

    @staticmethod
    def iter_running_emulator() -> Iterator[str]:
        """产生正在运行的模拟器路径，可能重复。"""
        for pid in psutil.pids():
            proc = psutil.Process(pid)
            try:
                exe = proc.cmdline()
                exe = exe[0].replace(r"\\", "/").replace("\\", "/")
            except psutil.AccessDenied, psutil.NoSuchProcess, IndexError, OSError:
                # NoSuchProcess: process no longer exists (pid=xxx)
                # OSError: [WinError 87] 参数错误。: '(originated from ReadProcessMemory)'
                continue

            if Emulator.is_emulator(exe):
                yield exe

    @staticmethod
    def iter_installed_emulator() -> Iterator[str]:
        """从 Windows 卸载信息定位已安装的 MuMu12 nx_main。"""
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MuMuPlayer"
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, key_path) as key:
                    install_location, _ = winreg.QueryValueEx(key, "InstallLocation")
            except OSError:
                continue

            executable = Path(install_location, "nx_main", "MuMuNxMain.exe")
            if executable.is_file():
                yield executable.as_posix()

    @cached_property
    def all_emulators(self) -> list[Emulator]:
        exe = set(self.iter_configured_emulator())
        if not exe:
            exe.update(self.iter_installed_emulator())
        for file in self.iter_running_emulator() or ():
            if Path(file).exists():
                exe.add(file)

        emulator_paths = [Emulator(path).path for path in exe if Emulator.is_emulator(path)]
        return [Emulator(path) for path in remove_duplicated_path(emulator_paths)]

    @cached_property
    def all_emulator_instances(self) -> list[EmulatorInstance]:
        instances = []
        for emulator in self.all_emulators:
            instances += list(emulator.iter_instances())

        instances: list[EmulatorInstance] = sorted(instances, key=str)
        return instances
