from module.base.decorator import del_cached_property
from module.device.adb_session import AdbDeviceWithStatus, retry
from module.device.mumu_connection import MumuTcpConnection
from module.logger import logger

__all__ = ["AdbDeviceWithStatus", "Connection", "retry"]


class Connection(MumuTcpConnection):
    def __init__(self, config):
        """
        参数：
            config (AzurLaneConfig, str)：./config 下的用户配置名。
        """
        super().__init__(config)
        self.detect_device()

        # 建立 ADB 连接。
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
            runtime.release_serial()

    def adb_disconnect(self):
        self.release_resource()
        msg = self.adb_client.disconnect(self.serial)
        if msg:
            logger.info(msg)

    def adb_restart(self):
        """
        重启 ADB client。
        """
        logger.info("Restart adb")
        self.release_resource()
        # 杀掉当前 client。
        self.adb_client.server_kill()
        # 重新初始化 ADB client。
        del_cached_property(self, "adb_client")
        _ = self.adb_client

    def adb_reconnect(self):
        """
        如果找不到设备则重启 ADB，否则尝试重连设备。
        """
        if len(self.list_device()) == 0:
            # 重启 ADB。
            self.adb_restart()
            # 重新连接设备。
            self.adb_connect()
            self.detect_device()
        else:
            self.adb_disconnect()
            self.adb_connect()
            self.detect_device()
