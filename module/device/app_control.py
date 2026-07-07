import re

from module.config.server import DICT_PACKAGE_TO_ACTIVITY
from module.device.connection import Connection, retry
from module.device.method.utils import PackageNotInstalled
from module.logger import logger


class AppControl(Connection):
    _PACKAGE_RE = re.compile(r"(?P<package>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/")

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
