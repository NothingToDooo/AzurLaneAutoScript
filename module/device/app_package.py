import re

from module.config.server import CN_PACKAGE
from module.device.adb_session import AdbSession, retry
from module.exception import RequestHumanTakeover
from module.logger import logger


class AppPackage(AdbSession):
    @retry
    def list_package(self, show_log=True):
        """
        查找设备上的所有包。

        优先使用更快的 dumpsys。
        """
        # 80ms
        if show_log:
            logger.info("Get package list")
        output = self.adb_shell(r'dumpsys package | grep "Package \["')
        packages = re.findall(r"Package \[([^\s]+)\]", output)
        if len(packages):
            return packages

        # 200ms
        if show_log:
            logger.info("Get package list")
        output = self.adb_shell(["pm", "list", "packages"])
        return re.findall(r"package:([^\s]+)", output)

    def list_known_packages(self, show_log=True):
        """
        参数：
            show_log:

        返回：
            list[str]：包名列表。
        """
        packages = self.list_package(show_log=show_log)
        return [CN_PACKAGE] if CN_PACKAGE in packages else []

    def ensure_package_installed(self, show_log=True) -> None:
        """
        确认固定国服客户端已经安装。
        """
        if self.list_known_packages(show_log=show_log):
            return

        logger.critical(f'未在设备 "{self.serial}" 上找到国服客户端包名 "{CN_PACKAGE}"，请确认碧蓝航线国服已安装')
        raise RequestHumanTakeover

    def confirm_fixed_package(self) -> None:
        """
        初始化时确认个人版固定的国服客户端包名。
        """
        self.package = CN_PACKAGE
        self.ensure_package_installed()
        logger.attr("PackageName", self.package)

    def detect_package(self):
        """
        重新检查固定国服客户端包名。
        """
        logger.hr("Check package")
        self.confirm_fixed_package()
        logger.info(f'找到固定国服客户端包名 "{self.package}"')
