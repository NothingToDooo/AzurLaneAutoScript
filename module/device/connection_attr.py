import os
import sys
from pathlib import Path

import adbutils
from adbutils import AdbClient, AdbDevice

from module.base.decorator import cached_property, del_cached_property
from module.config.config import AzurLaneConfig
from module.device.mumu import MUMU12_SERIAL_EXAMPLE, is_mumu12_serial, revise_mumu12_serial
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.webui.setting import State


class ConnectionAttr:
    config: AzurLaneConfig
    serial: str

    _serial_bound_cached_properties = (
        "port",
        "is_mumu12_family",
        "is_mumu_family",
        "adb",
        "emulator_instance",
        "nemud_app_keep_alive",
        "nemud_player_version",
        "is_mumu_over_version_400",
        "is_mumu_over_version_356",
        "nemu_ipc",
        "_minitouch_builder",
    )

    adb_binary_list = (
        "./bin/adb/adb.exe",
        "./.venv/Lib/site-packages/adbutils/binaries/adb.exe",
    )

    def __init__(self, config):
        """
        参数：
            config (AzurLaneConfig, str)：./config 下的用户配置名。
        """
        logger.hr("Device", level=1)
        if isinstance(config, str):
            self.config = AzurLaneConfig(config, task=None)
        else:
            self.config = config

        # 初始化 ADB 客户端。
        logger.attr("AdbBinary", self.adb_binary)

        # 让 adbutils 使用自定义 ADB。
        def adb_path() -> str:
            return self.adb_binary

        vars(adbutils)["adb_path"] = adb_path
        # 预热 adb_client 缓存。
        _ = self.adb_client

        # 解析自定义 serial。
        self.serial = str(self.config.Emulator_Serial)
        self.serial_check()

    def bind_serial(self, serial: str, *, persist: bool = False) -> bool:
        """释放旧连接状态并发布新的 serial。"""
        if serial == self.serial:
            return False

        release_resource = getattr(self, "release_resource", None)
        if callable(release_resource):
            release_resource()

        for name in self._serial_bound_cached_properties:
            del_cached_property(self, name)

        if persist:
            self.config.Emulator_Serial = serial
        self.serial = serial
        return True

    def serial_check(self):
        """
        检查并修正 serial。
        """
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
    def is_mumu12_family(self):
        return is_mumu12_serial(self.serial)

    @cached_property
    def is_mumu_family(self):
        return self.is_mumu12_family

    @cached_property
    def adb_binary(self):
        # 优先使用 WebUI 配置指定的 ADB。
        file = State.webui_config.AdbExecutable
        file = file.replace("\\", "/")
        if Path(file).exists():
            return str(Path(file).resolve())

        # 再尝试项目内已有的 adb.exe。
        for file in self.adb_binary_list:
            if Path(file).exists():
                return str(Path(file).resolve())

        # 再尝试 Python 环境里的 ADB。
        file = (Path(sys.executable) / "../Lib/site-packages/adbutils/binaries/adb.exe").resolve().as_posix()
        if Path(file).exists():
            return file

        # 最后使用系统 PATH 里的 ADB。
        return "adb"

    @cached_property
    def adb_client(self) -> AdbClient:
        host = "127.0.0.1"
        port = 5037

        # 允许通过环境变量覆盖 ADB server 端口。
        env = os.environ.get("ANDROID_ADB_SERVER_PORT", None)
        if env is not None:
            try:
                port = int(env)
            except ValueError:
                logger.warning(f"Invalid environ variable ANDROID_ADB_SERVER_PORT={port}, using default port")

        logger.attr("AdbClient", f"AdbClient({host}, {port})")
        return AdbClient(host, port)

    @cached_property
    def adb(self) -> AdbDevice:
        return AdbDevice(self.adb_client, self.serial)
