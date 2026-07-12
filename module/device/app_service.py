import re
from typing import TYPE_CHECKING

from module.config.server import CN_ACTIVITY
from module.device.method.utils import PackageNotInstalled
from module.device.service_retry import session_retry
from module.logger import logger

if TYPE_CHECKING:
    from module.device.contracts import RetrySession


class AppController:
    """通过注入的 ADB session 管理固定国服包进程。"""

    _PACKAGE_RE = re.compile(r"(?P<package>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/")

    def __init__(self, session: RetrySession) -> None:
        self.session = session

    @property
    def package(self) -> str:
        return self.session.package

    def current(self) -> str:
        return self.app_current()

    def is_running(self) -> bool:
        return self.app_is_running()

    def start(self) -> None:
        return self.app_start()

    def stop(self) -> None:
        return self.app_stop()

    def app_current(self) -> str:
        for command in (["dumpsys", "window"], ["dumpsys", "activity", "activities"]):
            package = self._app_current_from_adb(command)
            if package:
                return package
        logger.warning("Unable to get current package")
        return ""

    @session_retry
    def _app_current_from_adb(self, command: list[str]) -> str:
        output = self.session.adb_shell(command)
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

    def app_start(self) -> None:
        logger.info(f"App start: {self.package}")
        if self._app_start_adb_am(self.package, CN_ACTIVITY, allow_failure=True):
            return
        if self._app_start_adb_monkey(self.package, allow_failure=True):
            return
        if self._app_start_adb_am(self.package, CN_ACTIVITY, allow_failure=False):
            return

        logger.error("app_start: All trials failed")

    def app_stop(self) -> None:
        logger.info(f"App stop: {self.package}")
        self.app_stop_adb()

    @session_retry
    def _app_start_adb_monkey(self, package_name: str | None = None, *, allow_failure: bool = False) -> bool:
        if not package_name:
            package_name = self.package
        output = self.session.adb_shell(
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

    @session_retry
    def _app_start_adb_am(
        self, package_name: str | None = None, activity_name: str | None = None, *, allow_failure: bool = False
    ) -> bool:
        if not package_name:
            package_name = self.package
        if not activity_name:
            return False

        output = self.session.adb_shell(
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

    @session_retry
    def app_stop_adb(self, package_name: str | None = None) -> None:
        if not package_name:
            package_name = self.package
        self.session.adb_shell(["am", "force-stop", package_name])
