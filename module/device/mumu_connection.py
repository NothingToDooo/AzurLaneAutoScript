from adbutils.errors import AdbError

from module.device.method.pool import WORKER_POOL
from module.device.method.utils import possible_reasons
from module.device.mumu import MUMU12_SERIAL_EXAMPLE, is_mumu12_serial, mumu12_shifted_serials
from module.device.mumu_discovery import MumuDeviceDiscovery
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
from module.logger import logger


class MumuTcpConnection(MumuDeviceDiscovery):
    def _cleanup_adb_device_statuses(self, devices):
        for device in devices:
            if device.status == "offline":
                logger.warning(f"Device {device.serial} is offline, disconnect it before connecting")
                msg = self.adb_client.disconnect(device.serial)
                if msg:
                    logger.info(msg)
            elif device.status == "unauthorized":
                logger.error(f"Device {device.serial} is unauthorized, please accept ADB debugging on your device")
            elif device.status == "device":
                pass
            else:
                logger.warning(f"Device {device.serial} is is having a unknown status: {device.status}")

    @staticmethod
    def _is_mumu_tcp_serial(serial: str) -> bool:
        return is_mumu12_serial(serial)

    def _ensure_mumu_tcp_serial(self):
        """个人分支不兼容 emulator-* 或真机 serial。"""
        if self._is_mumu_tcp_serial(self.serial):
            return
        logger.critical(f'当前个人分支只支持 MuMu12 TCP serial，例如 "{MUMU12_SERIAL_EXAMPLE}"，当前为 "{self.serial}"')
        raise RequestHumanTakeover

    def _recover_mumu12_shifted_port(self):
        """MuMu12 端口被占用时会漂移；返回是否已在相邻端口找到新 serial。"""
        if not self.is_mumu12_family:
            return False

        before = self.serial
        serial_list = mumu12_shifted_serials(self.serial)
        self.adb_brute_force_connect(serial_list)
        self.detect_device()
        return self.serial != before

    def _handle_adb_connect_refused(self):
        """返回 True 表示 MuMu12 已通过相邻端口恢复连接。"""
        if self._recover_mumu12_shifted_port():
            return True
        self._diagnose_adb_connect_refused()
        logger.warning("No such device exists, please restart the emulator or set a correct serial")
        raise EmulatorNotRunningError

    def _diagnose_adb_connect_refused(self) -> None:
        """
        连接拒绝后由平台层补充诊断。
        """

    def _connect_adb_tcp_serial(self):
        """最多尝试 3 次；旧 ADB server 抢占时，首次可能只会杀掉旧进程。"""
        for _ in range(3):
            msg = self.adb_client.connect(self.serial)
            logger.info(msg)
            # Connected to 127.0.0.1:59865
            # Already connected to 127.0.0.1:59865
            if "connected" in msg:
                return True
            if "bad port" in msg:
                possible_reasons("Serial incorrect, might be a typo")
                raise RequestHumanTakeover
            # cannot connect to 127.0.0.1:55555:
            # No connection could be made because the target machine actively refused it. (10061)
            if "(10061)" in msg and self._handle_adb_connect_refused():
                return True

        return False

    def adb_connect(self):
        devices = self.list_device()
        self._cleanup_adb_device_statuses(devices)
        self._ensure_mumu_tcp_serial()

        if self._connect_adb_tcp_serial():
            return True

        logger.warning(f"Failed to connect {self.serial} after 3 trial, assume connected")
        self.detect_device()
        return False

    def adb_brute_force_connect(self, serial_list):
        def connect(s):
            try:
                msg = self.adb_client.connect(s)
            except AdbError, OSError:
                return ""
            logger.info(msg)
            return msg

        with WORKER_POOL.wait_jobs() as pool:
            for serial in serial_list:
                pool.start_thread_soon(connect, serial)
