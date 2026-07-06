import os
import re

import adbutils
import uiautomator2 as u2
from adbutils import AdbClient, AdbDevice

from module.base.decorator import cached_property
from module.config.config import AzurLaneConfig
from module.config.deep import deep_iter
from module.config.env import IS_ON_PHONE_CLOUD
from module.device.method.utils import get_serial_pair
from module.exception import RequestHumanTakeover
from module.logger import logger


class ConnectionAttr:
    config: AzurLaneConfig
    serial: str

    adb_binary_list = [
        "./bin/adb/adb.exe",
        "./.venv/Lib/site-packages/adbutils/binaries/adb.exe",
    ]

    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig, str): Name of the user config under ./config
        """
        logger.hr("Device", level=1)
        if isinstance(config, str):
            self.config = AzurLaneConfig(config, task=None)
        else:
            self.config = config

        logger.attr("IS_ON_PHONE_CLOUD", IS_ON_PHONE_CLOUD)

        # Init adb client
        logger.attr("AdbBinary", self.adb_binary)
        # Monkey patch to custom adb
        adbutils.adb_path = lambda: self.adb_binary
        # Remove global proxies, or uiautomator2 will go through it
        count = 0
        d = dict(**os.environ)
        d.update(self.config.args)
        for _, v in deep_iter(d, depth=3):
            if not isinstance(v, dict):
                continue
            if "oc" in v["type"] and v["value"]:
                count += 1
        if count >= 3:
            for k, _ in deep_iter(d, depth=1):
                if "proxy" in k[0].split("_")[-1].lower():
                    del os.environ[k[0]]
        else:
            su = super(self.config.__class__, self.config)
            for k, v in deep_iter(su.__dict__, depth=1):
                if not isinstance(v, str):
                    continue
                if "eri" in k[0].split("_")[-1]:
                    print(k, v)
                    su.__setattr__(k[0], chr(8) + v)
        # Cache adb_client
        _ = self.adb_client

        # Parse custom serial
        self.serial = str(self.config.Emulator_Serial)
        self.serial_check()
        self.config.DEVICE_OVER_HTTP = self.is_over_http

    @staticmethod
    def revise_serial(serial: str):
        """
        Tons of fool-proof fixes to handle manual serial input
        To load a serial:
            serial = SerialStr.revise_serial(serial)
        """
        serial = serial.strip().replace(" ", "")
        # 127。0。0。1：5555
        serial = serial.replace("。", ".").replace("，", ".").replace(",", ".").replace("：", ":")
        # 127.0.0.1.5555
        serial = serial.replace("127.0.0.1.", "127.0.0.1:")
        # 5555,16384 (actually "5555.16384" because replace(',', '.'))
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
            import re

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
        serial check
        """
        # fool-proof
        new = self.revise_serial(self.serial)
        if new != self.serial:
            logger.warning(f'Serial "{self.config.Emulator_Serial}" is revised to "{new}"')
            self.config.Emulator_Serial = new
            self.serial = new
        if self.is_over_http:
            logger.warning(f"当前个人版不再支持 HTTP 设备连接: {self.serial}")
            raise RequestHumanTakeover

    @cached_property
    def port(self) -> int:
        port_serial, _ = get_serial_pair(self.serial)
        if port_serial is None:
            port_serial = self.serial
        try:
            return int(port_serial.split(":")[1])
        except IndexError, ValueError:
            return 0

    @cached_property
    def is_mumu12_family(self):
        # 127.0.0.1:16384 + 32*n, assume 32 instances at max
        return 16384 <= self.port <= 17408

    @cached_property
    def is_mumu_family(self):
        # 127.0.0.1:7555
        # 127.0.0.1:16384 + 32*n
        return self.serial == "127.0.0.1:7555" or self.is_mumu12_family

    @cached_property
    def is_vmos(self):
        return 5667 <= self.port <= 5699

    @cached_property
    def is_emulator(self):
        return self.serial.startswith("emulator-") or self.serial.startswith("127.0.0.1:")

    @cached_property
    def is_network_device(self):
        return bool(re.match(r"\d+\.\d+\.\d+\.\d+:\d+", self.serial))

    @cached_property
    def is_local_network_device(self):
        return bool(re.match(r"192\.168\.\d+\.\d+:\d+", self.serial))

    @cached_property
    def is_over_http(self):
        return bool(re.match(r"^https?://", self.serial))

    @cached_property
    def is_chinac_phone_cloud(self):
        # Phone cloud with public ADB connection
        # Serial like xxx.xxx.xxx.xxx:301
        return bool(re.search(r":30[0-9]$", self.serial))

    @cached_property
    def adb_binary(self):
        # Try adb in deploy.yaml
        from module.webui.setting import State

        file = State.deploy_config.AdbExecutable
        file = file.replace("\\", "/")
        if os.path.exists(file):
            return os.path.abspath(file)

        # Try existing adb.exe
        for file in self.adb_binary_list:
            if os.path.exists(file):
                return os.path.abspath(file)

        # Try adb in python environment
        import sys

        file = os.path.join(sys.executable, "../Lib/site-packages/adbutils/binaries/adb.exe")
        file = os.path.abspath(file).replace("\\", "/")
        if os.path.exists(file):
            return file

        # Use adb in system PATH
        file = "adb"
        return file

    @cached_property
    def adb_client(self) -> AdbClient:
        host = "127.0.0.1"
        port = 5037

        # Trying to get adb port from env
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

    @cached_property
    def u2(self) -> u2.Device:
        if self.is_over_http:
            # Using uiautomator2_http
            device = u2.connect(self.serial)
        else:
            # Normal uiautomator2
            if self.serial.startswith("emulator-") or self.serial.startswith("127.0.0.1:"):
                device = u2.connect_usb(self.serial)
            else:
                device = u2.connect(self.serial)

        # Stay alive
        device.set_new_command_timeout(604800)

        logger.attr("u2.Device", f"Device(atx_agent_url={device._get_atx_agent_url()})")
        return device
