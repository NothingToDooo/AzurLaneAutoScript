import re

from module.config.server import CN_PACKAGE
from module.device.adb_session import AdbSession, retry
from module.exception import RequestHumanTakeover
from module.logger import logger


class AppPackage(AdbSession):
    @retry
    def list_package(self, show_log=True):
        """优先用较快的 dumpsys，无结果时回退到 pm。"""
        if show_log:
            logger.info("Get package list")
        output = self.adb_shell(r'dumpsys package | grep "Package \["')
        packages = re.findall(r"Package \[([^\s]+)\]", output)
        if len(packages):
            return packages

        if show_log:
            logger.info("Get package list")
        output = self.adb_shell(["pm", "list", "packages"])
        return re.findall(r"package:([^\s]+)", output)

    def list_known_packages(self, show_log=True):
        packages = self.list_package(show_log=show_log)
        return [CN_PACKAGE] if CN_PACKAGE in packages else []

    def ensure_package_installed(self, show_log=True) -> None:
        if self.list_known_packages(show_log=show_log):
            return

        logger.critical(f'未在设备 "{self.serial}" 上找到国服客户端包名 "{CN_PACKAGE}"，请确认碧蓝航线国服已安装')
        raise RequestHumanTakeover

    def confirm_fixed_package(self) -> None:
        self.package = CN_PACKAGE
        self.ensure_package_installed()
        logger.attr("PackageName", self.package)

    def detect_package(self):
        logger.hr("Check package")
        self.confirm_fixed_package()
        logger.info(f'找到固定国服客户端包名 "{self.package}"')
