import re
from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.config.server import DICT_PACKAGE_TO_ACTIVITY
from module.device.connection import retry
from module.device.method.uiautomator_2 import Uiautomator2
from module.device.method.utils import HierarchyButton, PackageNotInstalled
from module.exception import ScriptError
from module.logger import logger

if TYPE_CHECKING:
    from lxml import etree


class AppControl(Uiautomator2):
    hierarchy: etree._Element
    _PACKAGE_RE = re.compile(r"(?P<package>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/")

    def __init__(self, *args, **kwargs):
        self._hierarchy_interval = Timer(0.1)
        super().__init__(*args, **kwargs)

    def app_current(self) -> str:
        for command in (["dumpsys", "window"], ["dumpsys", "activity", "activities"]):
            package = self._app_current_from_adb(command)
            if package:
                return package
        logger.warning("Unable to get current package")
        return ""

    @retry
    def _app_current_from_adb(self, command) -> str:
        output = self.adb_shell(command)
        for line in output.splitlines():
            if any(keyword in line for keyword in ("mCurrentFocus", "mFocusedApp", "topResumedActivity")):
                result = self._PACKAGE_RE.search(line)
                if result:
                    return result.group("package")
        return ""

    def app_is_running(self) -> bool:
        package = self.app_current()
        logger.attr("Package_name", package)
        return package == self.package

    def app_start(self):
        logger.info(f"App start: {self.package}")
        activity_name = DICT_PACKAGE_TO_ACTIVITY.get(self.package)
        if activity_name and self._app_start_adb_am(self.package, activity_name, allow_failure=True):
            return
        if self._app_start_adb_monkey(self.package, allow_failure=True):
            return
        if activity_name and self._app_start_adb_am(self.package, activity_name, allow_failure=False):
            return

        logger.error("app_start: All trials failed")

    def app_stop(self):
        logger.info(f"App stop: {self.package}")
        self.app_stop_adb()

    @retry
    def _app_start_adb_monkey(self, package_name=None, allow_failure=False):
        if not package_name:
            package_name = self.package
        output = self.adb_shell(
            ["monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "--pct-syskeys", "0", "1"]
        )
        if "No activities found" in output:
            if allow_failure:
                return False
            logger.error(output)
            raise PackageNotInstalled(package_name)
        if "inaccessible" in output:
            logger.error(output)
            return False
        return "Events injected" in output

    @retry
    def _app_start_adb_am(self, package_name=None, activity_name=None, allow_failure=False):
        if not package_name:
            package_name = self.package
        if not activity_name:
            return False

        output = self.adb_shell(
            [
                "am",
                "start",
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.LAUNCHER",
                "-n",
                f"{package_name}/{activity_name}",
            ]
        )
        if "Error: Activity class" in output or "Permission Denial" in output:
            if allow_failure:
                return False
            logger.error(output)
            return False
        if "Exception" in output:
            logger.error(output)
            return False
        return True

    @retry
    def app_stop_adb(self, package_name=None):
        if not package_name:
            package_name = self.package
        self.adb_shell(["am", "force-stop", package_name])

    def hierarchy_timer_set(self, interval=None):
        if interval is None:
            interval = 0.1
        elif isinstance(interval, (int, float)):
            # No limitation for manual set in code
            pass
        else:
            logger.warning(f"Unknown hierarchy interval: {interval}")
            raise ScriptError(f"Unknown hierarchy interval: {interval}")

        if interval != self._hierarchy_interval.limit:
            logger.info(f"Hierarchy interval set to {interval}s")
            self._hierarchy_interval.limit = interval

    def dump_hierarchy(self) -> etree._Element:
        """
        Returns:
            etree._Element: 可用 `self.hierarchy.xpath('//*[@text="确定"]')` 这类表达式选择元素。
        """
        self._hierarchy_interval.wait()
        self._hierarchy_interval.reset()

        self.hierarchy = self.dump_hierarchy_uiautomator2()
        return self.hierarchy

    def xpath_to_button(self, xpath: str) -> HierarchyButton:
        """
        Args:
            xpath (str):

        Returns:
            HierarchyButton:
                An object with methods and properties similar to Button.
                If element not found or multiple elements were found, return None.
        """
        return HierarchyButton(self.hierarchy, xpath)
