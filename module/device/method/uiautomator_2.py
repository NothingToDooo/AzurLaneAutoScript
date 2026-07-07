import time
from functools import wraps
from json.decoder import JSONDecodeError

import requests
import uiautomator2 as u2
import uiautomator2.exceptions as u2_exc
from adbutils.errors import AdbError
from lxml import etree

from module.config.server import DICT_PACKAGE_TO_ACTIVITY
from module.device.connection import Connection
from module.device.method.utils import (
    RETRY_TRIES,
    PackageNotInstalled,
    handle_adb_error,
    handle_unknown_host_service,
    retry_sleep,
)
from module.exception import RequestHumanTakeover
from module.logger import logger


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Uiautomator2):
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # 无法自动处理。
            except RequestHumanTakeover:
                break
            # ADB server 被杀掉。
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
            # uiautomator2 服务偶尔返回非 JSON 内容。
            # json.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)
            except JSONDecodeError as e:
                logger.error(e)

                def init():
                    self.install_uiautomator2()
            # ADB 错误。
            except AdbError as e:
                if handle_adb_error(e):

                    def init():
                        self.adb_reconnect()
                elif handle_unknown_host_service(e):

                    def init():
                        self.adb_start_server()
                        self.adb_reconnect()
                else:
                    break
            # RuntimeError: USB device 127.0.0.1:5555 is offline
            except RuntimeError as e:
                if handle_adb_error(e):

                    def init():
                        self.adb_reconnect()
                else:
                    break
            # 发生在 `assert c.read string(4) == _OKAY` 中。
            # 模拟器没有启用 ADB。
            except AssertionError as e:
                logger.exception(e)
                break
            # 游戏包未安装。
            except PackageNotInstalled as e:
                logger.error(e)

                def init():
                    self.detect_package()
            # uiautomator2/RPC/HTTP 或本地图像/XML 解析失败时重试。
            except (
                u2_exc.BaseException,
                requests.exceptions.RequestException,
                etree.XMLSyntaxError,
                OSError,
            ) as e:
                logger.error(e)

                def init():
                    self.install_uiautomator2()

        logger.critical(f"Retry {func.__name__}() failed")
        raise RequestHumanTakeover

    return retry_wrapper


class Uiautomator2(Connection):
    @retry
    def app_current_uiautomator2(self):
        """
        Returns:
            str：包名。
        """
        result = self.u2.app_current()
        return result["package"]

    @retry
    def _app_start_u2_monkey(self, package_name=None, allow_failure=False):
        """
        Args:
            package_name (str):
            allow_failure (bool):

        Returns:
            bool：是否启动成功。

        抛出：
            PackageNotInstalled:
        """
        if not package_name:
            package_name = self.package
        result = self.u2.shell(
            ["monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "--pct-syskeys", "0", "1"]
        )
        if "No activities found" in result.output:
            # 没有可启动 Activity 时，monkey 会输出：** No activities found to run, monkey aborted。
            if allow_failure:
                return False
            logger.error(result)
            raise PackageNotInstalled(package_name)
        # monkey 不可用时会输出：/system/bin/sh: monkey: inaccessible or not found。
        # 成功时通常输出：Events injected: 1。
        return "inaccessible" not in result.output

    @retry
    def _app_start_u2_am(self, package_name=None, activity_name=None, allow_failure=False):
        """
        Args:
            package_name (str):
            activity_name (str):
            allow_failure (bool):

        Returns:
            bool: If success to start

        Raises:
            PackageNotInstalled:
        """
        if not package_name:
            package_name = self.package
        if not activity_name:
            try:
                info = self.u2.app_info(package_name)
            except u2.BaseError as e:
                if allow_failure:
                    return False
                # BaseError('package "111" not found')
                if "not found" in str(e):
                    logger.error(e)
                    raise PackageNotInstalled(package_name) from e
                # 未知错误。
                raise
            activity_name = info["mainActivity"]

        cmd = [
            "am",
            "start",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            "-n",
            f"{package_name}/{activity_name}",
        ]
        ret = self.u2.shell(cmd)
        # Activity 无效。
        # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=... }
        # Error type 3
        # Error: Activity class {.../...} does not exist.
        if "Error: Activity class" in ret.output:
            if allow_failure:
                return False
            logger.error(ret)
            return False
        # 已经在运行。
        # Warning: Activity not started, intent has been delivered to currently running top-most instance.
        if "Warning: Activity not started" in ret.output:
            logger.info("App activity is already started")
            return True
        # Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER]
        # cmp=com.YoStarEN.AzurLane/com.manjuu.azurlane.MainActivity }
        # java.lang.SecurityException: Permission Denial: starting Intent { act=android.intent.action.MAIN
        # cat=[android.intent.category.LAUNCHER] flg=0x10000000
        # cmp=com.YoStarEN.AzurLane/com.manjuu.azurlane.MainActivity } from null (pid=5140, uid=2000)
        # not exported from uid 10064
        #         at android.os.Parcel.readException(Parcel.java:1692)
        #         at android.os.Parcel.readException(Parcel.java:1645)
        #         at android.app.ActivityManagerProxy.startActivityAsUser(ActivityManagerNative.java:3152)
        #         at com.android.commands.am.Am.runStart(Am.java:643)
        #         at com.android.commands.am.Am.onRun(Am.java:394)
        #         at com.android.internal.os.BaseCommand.run(BaseCommand.java:51)
        #         at com.android.commands.am.Am.main(Am.java:124)
        #         at com.android.internal.os.RuntimeInit.nativeFinishInit(Native Method)
        #         at com.android.internal.os.RuntimeInit.main(RuntimeInit.java:290)
        if "Permission Denial" in ret.output:
            if allow_failure:
                return False
            logger.error(ret)
            logger.error("Permission Denial while starting app, probably because activity invalid")
            return False
        # 启动成功。
        # Starting: Intent...
        return True

    # 内部启动方法已有 @retry，这里不再添加。
    # @retry
    def app_start_uiautomator2(self, package_name=None, activity_name=None, allow_failure=False):
        """
        Args:
            package_name (str):
                If None, to get from config
            activity_name (str):
                If None, to get from DICT_PACKAGE_TO_ACTIVITY
                If still None, launch from monkey
                If monkey failed, fetch activity name and launch from am
            allow_failure (bool):
                True for no PackageNotInstalled raising, just return False

        Returns:
            bool: If success to start

        Raises:
            PackageNotInstalled:
        """
        if not package_name:
            package_name = self.package
        if not activity_name:
            activity_name = DICT_PACKAGE_TO_ACTIVITY.get(package_name)

        if activity_name and self._app_start_u2_am(package_name, activity_name, allow_failure):
            return True
        if self._app_start_u2_monkey(package_name, allow_failure):
            return True
        if self._app_start_u2_am(package_name, activity_name, allow_failure):
            return True

        logger.error("app_start_uiautomator2: All trials failed")
        return False

    @retry
    def app_stop_uiautomator2(self, package_name=None):
        if not package_name:
            package_name = self.package
        self.u2.app_stop(package_name)

    @retry
    def dump_hierarchy_uiautomator2(self) -> etree._Element:
        content = self.u2.dump_hierarchy(compressed=False)
        # print(content)
        return etree.fromstring(content.encode("utf-8"))

    def uninstall_uiautomator2(self):
        logger.info("Removing uiautomator2")
        for file in [
            "app-uiautomator.apk",
            "app-uiautomator-test.apk",
            "minitouch",
            "minitouch.so",
            "atx-agent",
        ]:
            self.adb_shell(["rm", f"/data/local/tmp/{file}"])

    @retry
    def resolution_uiautomator2(self, cal_rotation=True) -> tuple[int, int]:
        """
        Faster u2.window_size(), cause that calls `dumpsys display` twice.

        Returns:
            (width, height)
        """
        info = self.u2.http.get("/info").json()
        w, h = info["display"]["width"], info["display"]["height"]
        if cal_rotation:
            rotation = self.get_orientation()
            if (w > h) != (rotation % 2 == 1):
                w, h = h, w
        return w, h

    def resolution_check_uiautomator2(self):
        """
        Alas does not actively check resolution but the width and height of screenshots.
        However, some screenshot methods do not provide device resolution, so check it here.

        Returns:
            (width, height)

        Raises:
            RequestHumanTakeover: If resolution is not 1280x720
        """
        width, height = self.resolution_uiautomator2()
        logger.attr("Screen_size", f"{width}x{height}")
        if width == 1280 and height == 720:
            return (width, height)
        if width == 720 and height == 1280:
            return (width, height)

        logger.critical(f"Resolution not supported: {width}x{height}")
        logger.critical("Please set emulator resolution to 1280x720")
        raise RequestHumanTakeover
