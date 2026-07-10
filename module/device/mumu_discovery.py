from module.device.app_package import AppPackage
from module.logger import logger


class MumuDeviceDiscovery(AppPackage):
    @staticmethod
    def _log_available_devices(available):
        for device in available:
            logger.info(device.serial)
        if not len(available):
            logger.info("No available devices")

    @staticmethod
    def _log_unavailable_devices(devices, available):
        unavailable = devices.delete(available)
        if len(unavailable):
            logger.info("Here are the devices detected but unavailable")
            for device in unavailable:
                logger.info(f"{device.serial} ({device.status})")

    def _list_and_log_detected_devices(self):
        logger.info("Here are the available MuMu12 TCP serials, copy one to Alas.Emulator.Serial")
        devices = self.list_device()
        available = devices.select(status="device", may_mumu12_family=True)
        self._log_available_devices(available)
        self._log_unavailable_devices(devices, available)
        return devices, available

    def _redirect_shifted_mumu12_port(self, available):
        """
        如果 MuMu12 动态端口发生小范围切换，只更新运行时 serial。
        """
        if not self.is_mumu12_family:
            return

        matched = False
        for device in available.select(may_mumu12_family=True):
            if device.port == self.port:
                # 精确匹配。
                matched = True
                break
        if matched:
            return

        for device in available.select(may_mumu12_family=True):
            if -2 <= device.port - self.port <= 2:
                # 端口发生切换。
                logger.info(f"MuMu12 serial switched {self.serial} -> {device.serial}")
                self.bind_serial(device.serial)
                break

    def detect_device(self):
        """
        查找当前可用的 MuMu12 TCP serial。
        """
        logger.hr("Detect device")
        _, available = self._list_and_log_detected_devices()

        # 如果 16384 被占用，MuMu12 会使用 16385，这里自动重定向。
        # 这是动态端口，不写回配置。
        self._redirect_shifted_mumu12_port(available)
