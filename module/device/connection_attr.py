import os
import re
import sys
from pathlib import Path

import adbutils
from adbutils import AdbClient, AdbDevice

from module.base.decorator import cached_property
from module.config.config import AzurLaneConfig
from module.logger import logger
from module.webui.setting import State


class ConnectionAttr:
    config: AzurLaneConfig
    serial: str

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
        adbutils.adb_path = lambda: self.adb_binary
        # 预热 adb_client 缓存。
        _ = self.adb_client

        # 解析自定义 serial。
        self.serial = str(self.config.Emulator_Serial)
        self.serial_check()

    @staticmethod
    def revise_serial(serial: str):
        """
        修正常见手填 serial 错误。

        用法：
            serial = SerialStr.revise_serial(serial)
        """
        serial = serial.strip().replace(" ", "")
        # 127。0。0。1：5555
        serial = serial.replace("。", ".").replace("，", ".").replace(",", ".").replace("：", ":")
        # 127.0.0.1.5555
        serial = serial.replace("127.0.0.1.", "127.0.0.1:")
        # 5555,16384。逗号已被替换为点，实际形态是 5555.16384。
        if "." in serial:
            left, _, right = serial.partition(".")
            try:
                left = int(left)
                right = int(right)
                if 5500 < left < 6000 and 16300 < right < 20000:
                    serial = str(right)
            except ValueError:
                pass
        # 16384
        if serial.isdigit():
            try:
                port = int(serial)
                if 1000 < port < 65536:
                    serial = f"127.0.0.1:{port}"
            except ValueError:
                pass
        # MuMu模拟器12127.0.0.1:16384
        if "模拟" in serial:
            res = re.search(r"(127\.\d+\.\d+\.\d+:\d+)", serial)
            if res:
                serial = res.group(1)
        # 12127.0.0.1:16384
        serial = serial.replace("12127.0.0.1", "127.0.0.1")
        # auto127.0.0.1:16384
        serial = serial.replace("auto127.0.0.1", "127.0.0.1").replace("autoemulator", "emulator")
        return str(serial)

    def serial_check(self):
        """
        检查并修正 serial。
        """
        # 兼容常见手填错误。
        new = self.revise_serial(self.serial)
        if new != self.serial:
            logger.warning(f'Serial "{self.config.Emulator_Serial}" is revised to "{new}"')
            self.config.Emulator_Serial = new
            self.serial = new

    @cached_property
    def port(self) -> int:
        try:
            return int(self.serial.split(":")[1])
        except IndexError, ValueError:
            return 0

    @cached_property
    def is_mumu12_family(self):
        # 127.0.0.1:16384 + 32*n，最多按 32 个实例估算。
        return 16384 <= self.port <= 17408

    @cached_property
    def is_mumu_family(self):
        # 127.0.0.1:7555
        # 127.0.0.1:16384 + 32*n
        return self.serial == "127.0.0.1:7555" or self.is_mumu12_family

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
