from typing import TYPE_CHECKING, Never

from adbutils.errors import AdbError

from module.device.app_package import AppPackage
from module.device.mumu import MUMU12_SERIAL_EXAMPLE, MuMuSerial, mumu12_endpoint_candidates
from module.exception import EmulatorNotRunningError, HumanTakeoverRequiredError
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.device.adb_session import AdbDeviceWithStatus
    from module.map.map_grids import SelectedGrids


class MumuEndpointAmbiguousError(HumanTakeoverRequiredError):
    """同一 MuMu 实例暴露了多个可用邻居 endpoint。"""


def select_mumu_endpoint(configured_serial: str, devices: Iterable[AdbDeviceWithStatus]) -> str | None:
    """从配置实例允许的 exact、±1、±2 中选择唯一在线 endpoint。"""
    configured = MuMuSerial.parse(configured_serial)
    if configured is None:
        message = f"invalid configured MuMu12 serial: {configured_serial!r}"
        raise ValueError(message)
    candidates = configured.endpoint_candidates()

    available = {device.serial for device in devices if device.status == "device"}
    exact, *neighbors = candidates
    if exact in available:
        return exact

    matches = sorted(serial for serial in neighbors if serial in available)
    if len(matches) > 1:
        joined = ", ".join(matches)
        message = f"multiple online MuMu endpoints for configured MuMu instance {configured.instance_id}: {joined}"
        raise MumuEndpointAmbiguousError(message)
    return matches[0] if matches else None


class MumuTcpConnection(AppPackage):
    def _cleanup_adb_device_statuses(self, devices: SelectedGrids) -> None:
        allowed = set(mumu12_endpoint_candidates(self.config.Emulator_Serial))
        for device in devices:
            if device.serial not in allowed:
                logger.info(f"Ignore ADB device outside configured MuMu instance: {device.serial} ({device.status})")
                continue
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

    def _ensure_configured_mumu_serial(self) -> MuMuSerial:
        configured_serial = self.config.Emulator_Serial
        parsed = MuMuSerial.parse(configured_serial)
        if parsed is not None:
            return parsed
        logger.critical(
            f'当前个人分支只支持 MuMu12 TCP serial，例如 "{MUMU12_SERIAL_EXAMPLE}"，当前为 "{configured_serial}"'
        )
        raise HumanTakeoverRequiredError

    def _list_adb_devices(self) -> SelectedGrids:
        devices = self.list_device()
        self._cleanup_adb_device_statuses(devices)
        return devices

    def _bind_available_endpoint(self, devices: SelectedGrids) -> bool:
        endpoint = select_mumu_endpoint(self.config.Emulator_Serial, devices)
        if endpoint is None:
            return False
        if endpoint != self.serial:
            logger.info(f"MuMu12 live endpoint switched {self.serial} -> {endpoint}")
            self.bind_serial(endpoint)
        return True

    def _probe_configured_instance(self) -> None:
        for serial in mumu12_endpoint_candidates(self.config.Emulator_Serial):
            try:
                msg = self.adb_client.connect(serial)
            except (AdbError, OSError) as error:
                logger.info(error)
                continue
            logger.info(msg)

    def _diagnose_adb_connect_refused(self) -> None:
        """连接拒绝后由 Device 的 MuMu runtime 补充诊断。"""

    def _raise_emulator_not_running(self, instance_id: int, devices: SelectedGrids) -> Never:
        self._diagnose_adb_connect_refused()
        observed = ", ".join(f"{device.serial} ({device.status})" for device in devices) or "<none>"
        message = f"no online endpoint for configured MuMu instance {instance_id}; observed: {observed}"
        logger.warning(message)
        raise EmulatorNotRunningError(message)

    def adb_connect(self) -> bool:
        configured = self._ensure_configured_mumu_serial()
        devices = self._list_adb_devices()
        if self._bind_available_endpoint(devices):
            return True

        for _ in range(3):
            self._probe_configured_instance()
            devices = self._list_adb_devices()
            if self._bind_available_endpoint(devices):
                return True

        return self._raise_emulator_not_running(configured.instance_id, devices)
