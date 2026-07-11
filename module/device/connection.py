from module.base.decorator import del_cached_property
from module.device.adb_session import AdbDeviceWithStatus, retry
from module.device.mumu_connection import MumuTcpConnection
from module.logger import logger

__all__ = ["AdbDeviceWithStatus", "Connection", "retry"]


class Connection(MumuTcpConnection):
    def __init__(self, config):
        super().__init__(config)
        self.detect_device()

        self.adb_connect()
        logger.attr("AdbDevice", self.adb)

        self.confirm_fixed_package()
        logger.attr("Server", self.config.SERVER)

        self._check_after_connected()

    def _check_after_connected(self) -> None:
        """
        ADB 连接建立后由平台层补充检查。
        """

    def release_resource(self):
        """释放当前 serial 关联的截图与控制资源。"""
        runtime = self.__dict__.get("_runtime")
        if runtime is not None:
            try:
                runtime.release_serial()
            except Exception as error:  # noqa: BLE001
                # 资源回收失败不能截断 ADB 主状态迁移或新 serial 发布。
                logger.exception(error)

    def adb_disconnect(self):
        self.release_resource()
        msg = self.adb_client.disconnect(self.serial)
        if msg:
            logger.info(msg)

    def adb_restart(self):
        logger.info("Restart adb")
        self.release_resource()
        self.adb_client.server_kill()
        del_cached_property(self, "adb_client")
        _ = self.adb_client

    def adb_reconnect(self):
        if len(self.list_device()) == 0:
            self.adb_restart()
            self.adb_connect()
            self.detect_device()
        else:
            self.adb_disconnect()
            self.adb_connect()
            self.detect_device()
