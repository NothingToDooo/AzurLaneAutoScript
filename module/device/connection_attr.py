import os
import sys
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from adbutils import AdbClient, AdbDevice

from module.base.decorator import del_cached_property
from module.config.config import AzurLaneConfig
from module.device.mumu import MUMU12_SERIAL_EXAMPLE, is_mumu12_serial, revise_mumu12_serial
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.webui.setting import State

if TYPE_CHECKING:
    from collections.abc import Iterator


@runtime_checkable
class _Releasable(Protocol):
    def release_resource(self) -> None: ...


class ConnectionAttr:
    config: AzurLaneConfig
    serial: str

    _serial_bound_cached_properties = (
        "port",
        "is_mumu12_family",
        "is_mumu_family",
        "adb",
    )

    adb_binary_list = (
        "./bin/adb/adb.exe",
        "./.venv/Lib/site-packages/adbutils/binaries/adb.exe",
    )

    def __init__(self, config: AzurLaneConfig | str) -> None:
        logger.hr("Device", level=1)
        if isinstance(config, str):
            self.config = AzurLaneConfig(config, task=None)
        else:
            self.config = config

        logger.attr("AdbBinary", self.adb_binary)
        # adbutils 的各子模块在导入时会绑定 adb_path 函数；官方环境变量是唯一能让
        # 这些调用统一使用当前项目 ADB binary 的入口。
        os.environ["ADBUTILS_ADB_PATH"] = self.adb_binary
        _ = self.adb_client

        self.serial = str(self.config.Emulator_Serial)
        self.serial_check()

    def _iter_serial_bound_cached_properties(self) -> Iterator[str]:
        """按 MRO 顺序收集各层声明的 serial 派生缓存。"""
        seen: set[str] = set()
        for owner in type(self).__mro__:
            names = owner.__dict__.get("_serial_bound_cached_properties", ())
            for name in names:
                if name in seen:
                    continue
                seen.add(name)
                yield name

    def bind_serial(self, serial: str, *, persist: bool = False) -> bool:
        """释放旧连接状态并发布新的 serial。"""
        if serial == self.serial:
            return False

        if isinstance(self, _Releasable):
            self.release_resource()

        for name in self._iter_serial_bound_cached_properties():
            del_cached_property(self, name)

        if persist:
            self.config.Emulator_Serial = serial
        self.serial = serial
        return True

    def serial_check(self) -> None:
        # 兼容常见手填错误。
        new = revise_mumu12_serial(self.serial)
        if new != self.serial:
            logger.warning(f'Serial "{self.config.Emulator_Serial}" is revised to "{new}"')
            self.bind_serial(new, persist=True)
        if is_mumu12_serial(self.serial):
            return
        logger.critical(f'当前个人分支只支持 MuMu12 TCP serial，例如 "{MUMU12_SERIAL_EXAMPLE}"，当前为 "{self.serial}"')
        raise RequestHumanTakeover

    @cached_property
    def port(self) -> int:
        _, sep, port = self.serial.partition(":")
        if not sep:
            return 0
        try:
            return int(port)
        except ValueError:
            return 0

    @cached_property
    def is_mumu12_family(self) -> bool:
        return is_mumu12_serial(self.serial)

    @cached_property
    def is_mumu_family(self) -> bool:
        return self.is_mumu12_family

    @cached_property
    def adb_binary(self) -> str:
        file = State.webui_config.AdbExecutable
        file = file.replace("\\", "/")
        if Path(file).exists():
            return str(Path(file).resolve())

        for file in self.adb_binary_list:
            if Path(file).exists():
                return str(Path(file).resolve())

        file = (Path(sys.executable) / "../Lib/site-packages/adbutils/binaries/adb.exe").resolve().as_posix()
        if Path(file).exists():
            return file

        return "adb"

    @cached_property
    def adb_server_port(self) -> int:
        port = 5037
        env = os.environ.get("ANDROID_ADB_SERVER_PORT", None)
        if env is not None:
            try:
                port = int(env)
            except ValueError:
                logger.warning(f"Invalid environ variable ANDROID_ADB_SERVER_PORT={port}, using default port")
        return port

    @cached_property
    def adb_client(self) -> AdbClient:
        host = "127.0.0.1"
        port = self.adb_server_port

        logger.attr("AdbClient", f"AdbClient({host}, {port})")
        return AdbClient(host, port)

    @cached_property
    def adb(self) -> AdbDevice:
        return AdbDevice(self.adb_client, self.serial)
