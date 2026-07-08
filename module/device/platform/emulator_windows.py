import re
import typing as t
from pathlib import Path

import psutil

# module/device/platform/emulator_base.py
# module/device/platform/emulator_windows.py
# 会被独立安装流程使用，因此这里不要导入 Alas 业务模块。
from module.device.platform.emulator_base import (
    EmulatorBase,
    EmulatorInstanceBase,
    EmulatorManagerBase,
    remove_duplicated_path,
)
from module.device.platform.utils import cached_property, iter_folder


class EmulatorInstance(EmulatorInstanceBase):
    @cached_property
    def emulator(self):
        """
        Returns:
            Emulator:
        """
        return Emulator(self.path)


class Emulator(EmulatorBase):
    @classmethod
    def path_to_type(cls, path: str) -> str:
        """
        Args:
            path: Path to .exe file, case insensitive

        Returns:
            str: Emulator type, such as Emulator.MuMuPlayer12
        """
        emulator_path = Path(path)
        exe = emulator_path.name.lower()
        dir2 = emulator_path.parent.parent.name.lower()
        if exe == "nemuplayer.exe":
            if dir2 == "nemu":
                return cls.MuMuPlayer
            if dir2 == "nemu9":
                return cls.MuMuPlayerX
            return cls.MuMuPlayer
        if exe in ["mumuplayer.exe", "mumunxmain.exe"]:
            return cls.MuMuPlayer12

        return ""

    @staticmethod
    def multi_to_single(exe: str):
        """
        Convert a string that might be a multi-instance manager to its single instance executable.

        Args:
            exe (str): Path to emulator executable

        Yields:
            str: Path to emulator executable
        """
        if "NemuMultiPlayer.exe" in exe:
            yield exe.replace("NemuMultiPlayer.exe", "NemuPlayer.exe")
        elif "MuMuMultiPlayer.exe" in exe:
            yield exe.replace("MuMuMultiPlayer.exe", "MuMuPlayer.exe")
        elif "MuMuManager.exe" in exe:
            yield exe.replace("MuMuManager.exe", "MuMuPlayer.exe")
        else:
            yield exe

    @staticmethod
    def single_to_console(exe: str):
        """
        Convert a string that might be a single instance executable to its console.

        Args:
            exe (str): Path to emulator executable

        Returns:
            str: Path to emulator console
        """
        if "MuMuPlayer.exe" in exe:
            return exe.replace("MuMuPlayer.exe", "MuMuManager.exe")
        # MuMuPlayer12 5.0
        if "MuMuNxMain.exe" in exe:
            return exe.replace("MuMuNxMain.exe", "MuMuManager.exe")
        return exe

    @staticmethod
    def vbox_file_to_serial(file: str) -> str:
        """
        Args:
            file: Path to vbox file

        Returns:
            str: serial such as `127.0.0.1:5555`
        """
        regex = re.compile('<*?hostport="(.*?)".*?guestport="5555"/>')
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

    def iter_instances(self):
        """
        Yields:
            EmulatorInstance: Emulator instances found in this emulator
        """
        if self == Emulator.MuMuPlayer:
            yield self._default_mumu_instance()
            return
        if self == Emulator.MuMuPlayerX:
            yield from self._iter_vbox_instances()
            return
        if self == Emulator.MuMuPlayer12:
            yield from self._iter_vbox_instances(allow_mumu12_default_serial=True)

    def _default_mumu_instance(self):
        # MuMu 单开版固定使用 7555。
        return EmulatorInstance(
            serial="127.0.0.1:7555",
            name="",
            path=self.path,
        )

    def _iter_vbox_instances(self, allow_mumu12_default_serial=False):
        for folder in self.list_folder("../vms", is_dir=True):
            yield from self._iter_vbox_folder_instances(folder, allow_mumu12_default_serial=allow_mumu12_default_serial)

    def _iter_vbox_folder_instances(self, folder, allow_mumu12_default_serial=False):
        name = Path(folder).name
        for file in iter_folder(folder, ext=".nemu"):
            serial = Emulator.vbox_file_to_serial(file)
            if serial:
                yield EmulatorInstance(
                    serial=serial,
                    name=name,
                    path=self.path,
                )
                continue

            instance = EmulatorInstance(
                serial=serial,
                name=name,
                path=self.path,
            )
            if allow_mumu12_default_serial and instance.MuMuPlayer12_id:
                instance.serial = self._mumu12_default_serial(instance)
                yield instance

    @staticmethod
    def _mumu12_default_serial(instance):
        # MuMu12 v4.0.4 默认实例的 vbox 配置可能没有转发记录。
        return f"127.0.0.1:{16384 + 32 * instance.MuMuPlayer12_id}"

    def iter_adb_binaries(self) -> t.Iterable[str]:
        """
        Yields:
            str: Filepath to adb binaries found in this emulator
        """
        if self != Emulator.MuMuPlayerFamily:
            return

        # MuMu9\emulator\nemu9\EmulatorShell -> MuMu9\emulator\nemu9\vmonitor\bin\adb_server.exe
        exe = self.abspath("../vmonitor/bin/adb_server.exe")
        if Path(exe).exists():
            yield exe

        # MuMu 目录内可能有 adb.exe。
        exe = self.abspath("./adb.exe")
        if Path(exe).exists():
            yield exe


class EmulatorManager(EmulatorManagerBase):
    def iter_configured_emulator(self):
        """
        Yields:
            str: 当前配置里明确填写的 MuMu 可执行文件路径。
        """
        emulator_info = getattr(self, "emulator_info", None)
        if emulator_info is None or not emulator_info.path:
            return
        for file in Emulator.multi_to_single(emulator_info.path.replace("\\", "/")):
            if Emulator.is_emulator(file) and Path(file).exists():
                yield file

    @staticmethod
    def iter_running_emulator():
        """
        Yields:
            str: Path to emulator executables, may contains duplicate values
        """
        for pid in psutil.pids():
            proc = psutil.Process(pid)
            try:
                exe = proc.cmdline()
                exe = exe[0].replace(r"\\", "/").replace("\\", "/")
            except psutil.AccessDenied, psutil.NoSuchProcess, IndexError, OSError:
                # psutil.AccessDenied
                # NoSuchProcess: process no longer exists (pid=xxx)
                # OSError: [WinError 87] 参数错误。: '(originated from ReadProcessMemory)'
                continue

            if Emulator.is_emulator(exe):
                yield exe

    @cached_property
    def all_emulators(self) -> list[Emulator]:
        """
        获取当前个人版会使用的 MuMu。
        """
        exe = set()

        for file in self.iter_configured_emulator():
            exe.add(file)
        for file in self.iter_running_emulator() or ():
            if Path(file).exists():
                exe.add(file)

        # 去重。
        emulator_paths = [Emulator(path).path for path in exe if Emulator.is_emulator(path)]
        return [Emulator(path) for path in remove_duplicated_path(emulator_paths)]

    @cached_property
    def all_emulator_instances(self) -> list[EmulatorInstance]:
        """
        Get all emulator instances installed on current computer.
        """
        instances = []
        for emulator in self.all_emulators:
            instances += list(emulator.iter_instances())

        instances: list[EmulatorInstance] = sorted(instances, key=str)
        return instances
