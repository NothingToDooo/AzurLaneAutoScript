import re
import typing as t
from dataclasses import dataclass
from pathlib import Path

from module.device.mumu import is_mumu12_serial
from module.device.platform.utils import cached_property, iter_folder


def abspath(path):
    return Path(path).resolve().as_posix()


def remove_duplicated_path(paths):
    """
    Args:
        paths (list[str]):

    Returns:
        list[str]:
    """
    paths = sorted(set(paths))
    dic = {}
    for path in paths:
        dic.setdefault(path.lower(), path)
    return list(dic.values())


@dataclass
class EmulatorInstanceBase:
    # ADB 连接使用的 Serial
    serial: str
    # 启停模拟器时使用的实例名称
    name: str
    # 模拟器可执行文件路径
    path: str

    def __str__(self):
        return f'{self.type}(serial="{self.serial}", name="{self.name}", path="{self.path}")'

    @cached_property
    def type(self) -> str:
        """
        Returns:
            str: Emulator type, such as Emulator.MuMuPlayer12
        """
        return self.emulator.type

    @cached_property
    def emulator(self):
        """
        Returns:
            Emulator:
        """
        return EmulatorBase(self.path)

    def __eq__(self, other):
        if isinstance(other, str) and self.type == other:
            return True
        if isinstance(other, (list, tuple)) and self.type in other:
            return True
        if isinstance(other, EmulatorInstanceBase):
            return super().__eq__(other) and self.type == other.type
        return super().__eq__(other)

    def __hash__(self):
        return hash(str(self))

    def __bool__(self):
        return True

    @cached_property
    def MuMuPlayer12_id(self):
        """
        将当前个人版支持的 MuMu 实例名称转换为实例编号。

        示例名称：
            MuMuPlayer-12.0-3
            MuMuPlayer-15.0-0
            YXArkNights-12.0-1

        Returns:
            int: 实例编号；不是当前个人版支持的 MuMu 实例时返回 None
        """
        res = re.search(r"MuMuPlayer-12.0-(\d+)", self.name)
        if res:
            return int(res.group(1))
        res = re.search(r"MuMuPlayer-15.0-(\d+)", self.name)
        if res:
            return int(res.group(1))
        res = re.search(r"YXArkNights-12.0-(\d+)", self.name)
        if res:
            return int(res.group(1))

        return None

    def mumu_vms_config(self, file):
        """
        Args:
            file (str): Such as customer_config.json

        Returns:
            str: Absolute filepath to the file
        """
        return self.emulator.abspath(f"../vms/{self.name}/configs/{file}")


class EmulatorBase:
    MuMuPlayer12 = "MuMuPlayer12"

    @classmethod
    def path_to_type(cls, path: str) -> str:
        """
        Args:
            path: Path to .exe file

        Returns:
            str: Emulator type, such as Emulator.MuMuPlayer12,
                or '' if this is not a emulator.
        """
        # 基类只定义接口，具体识别由平台子类实现。
        del path
        return ""

    def iter_instances(self) -> t.Iterable[EmulatorInstanceBase]:
        """
        Yields:
            EmulatorInstance: Emulator instances found in this emulator
        """
        return []

    def iter_adb_binaries(self) -> t.Iterable[str]:
        """
        Yields:
            str: Filepath to adb binaries found in this emulator
        """
        return []

    def __init__(self, path):
        # Path to .exe file
        self.path = path.replace("\\", "/")
        # Path to emulator folder
        parent = Path(path).parent
        self.dir = "" if parent == Path() else str(parent).replace("\\", "/")
        # str: Emulator type, or '' if this is not a emulator.
        self.type = self.__class__.path_to_type(path)

    def __eq__(self, other):
        if isinstance(other, str) and self.type == other:
            return True
        if isinstance(other, (list, tuple)) and self.type in other:
            return True
        return super().__eq__(other)

    def __str__(self):
        return f'{self.type}(path="{self.path}")'

    __repr__ = __str__

    def __hash__(self):
        return hash(self.path)

    def __bool__(self):
        return True

    def abspath(self, path, folder=None):
        if folder is None:
            folder = self.dir
        return abspath(Path(folder) / path)

    @classmethod
    def is_emulator(cls, path: str) -> bool:
        """
        Args:
            path: Path to .exe file.

        Returns:
            bool: If this is a emulator.
        """
        return bool(cls.path_to_type(path))

    def list_folder(self, folder, is_dir=False, ext=None):
        """
        Safely list files in a folder

        Args:
            folder:
            is_dir:
            ext:

        Returns:
            list[str]:
        """
        folder = self.abspath(folder)
        return list(iter_folder(folder, is_dir=is_dir, ext=ext))


class EmulatorManagerBase:
    @staticmethod
    def iter_running_emulator():
        """
        Yields:
            str: Path to emulator executables, may contains duplicate values
        """
        return

    @cached_property
    def all_emulators(self) -> list[EmulatorBase]:
        """
        Get all emulators installed on current computer.
        """
        return []

    @cached_property
    def all_emulator_instances(self) -> list[EmulatorInstanceBase]:
        """
        Get all emulator instances installed on current computer.
        """
        return []

    @cached_property
    def all_emulator_serials(self) -> list[str]:
        """
        返回当前个人版可尝试连接的 MuMu TCP serial。
        """
        return [emulator.serial for emulator in self.all_emulator_instances if is_mumu12_serial(emulator.serial)]

    @cached_property
    def all_adb_binaries(self) -> list[str]:
        """
        Returns:
            list[str]: All adb binaries of emulators on current computer.
        """
        out = []
        for emulator in self.all_emulators:
            out.extend(emulator.iter_adb_binaries())
        return out
