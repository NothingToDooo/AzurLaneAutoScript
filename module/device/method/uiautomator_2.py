import time
from dataclasses import dataclass
from functools import wraps
from json.decoder import JSONDecodeError
from subprocess import list2cmdline

import cv2
import numpy as np
import requests
import uiautomator2 as u2
import uiautomator2.exceptions as u2_exc
from adbutils.errors import AdbError
from lxml import etree

from module.base.utils import point2str, random_line_segments, random_rectangle_point
from module.config.server import DICT_PACKAGE_TO_ACTIVITY
from module.device.connection import Connection
from module.device.method.utils import (
    RETRY_TRIES,
    ImageTruncated,
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
        参数：
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
            # 图片数据损坏。
            except ImageTruncated as e:
                logger.error(e)

                def init():
                    pass
            # uiautomator2/RPC/HTTP 或本地图像/XML 解析失败时重试。
            except (
                u2_exc.BaseException,
                requests.exceptions.RequestException,
                cv2.error,
                etree.XMLSyntaxError,
                OSError,
            ) as e:
                logger.error(e)

                def init():
                    self.install_uiautomator2()

        logger.critical(f"Retry {func.__name__}() failed")
        raise RequestHumanTakeover

    return retry_wrapper


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    thread_count: int
    cmdline: str
    name: str


@dataclass
class ShellBackgroundResponse:
    success: bool
    pid: int
    description: str


class Uiautomator2(Connection):
    @retry
    def screenshot_uiautomator2(self):
        image = self.u2.screenshot(format="raw")
        image = np.frombuffer(image, np.uint8)
        if image is None:
            raise ImageTruncated("Empty image after reading from buffer")

        image = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if image is None:
            raise ImageTruncated("Empty image after cv2.imdecode")

        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, dst=image)
        if image is None:
            raise ImageTruncated("Empty image after cv2.cvtColor")

        return image

    @retry
    def click_uiautomator2(self, x, y):
        self.u2.click(x, y)

    @retry
    def long_click_uiautomator2(self, x, y, duration=(1, 1.2)):
        self.u2.long_click(x, y, duration=duration)

    @retry
    def swipe_uiautomator2(self, p1, p2, duration=0.1):
        self.u2.swipe(*p1, *p2, duration=duration)

    @retry
    def _drag_along(self, path):
        """按路径滑动。

        参数：
            path (list)：(x, y, sleep)。

        示例：
            al.drag_along([
                (403, 421, 0.2),
                (821, 326, 0.1),
                (821, 326-10, 0.1),
                (821, 326+10, 0.1),
                (821, 326, 0),
            ])
            等价于：
            al.device.touch.down(403, 421)
            time.sleep(0.2)
            al.device.touch.move(821, 326)
            time.sleep(0.1)
            al.device.touch.move(821, 326-10)
            time.sleep(0.1)
            al.device.touch.move(821, 326+10)
            time.sleep(0.1)
            al.device.touch.up(821, 326)
        """
        length = len(path)
        for index, data in enumerate(path):
            x, y, second = data
            if index == 0:
                self.u2.touch.down(x, y)
                logger.info(point2str(x, y) + " down")
            elif index - length == -1:
                self.u2.touch.up(x, y)
                logger.info(point2str(x, y) + " up")
            else:
                self.u2.touch.move(x, y)
                logger.info(point2str(x, y) + " move")
            self.sleep(second)

    def drag_uiautomator2(
        self,
        p1,
        p2,
        segments=1,
        shake=(0, 15),
        point_random=(-10, -10, 10, 10),
        shake_random=(-5, -5, 5, 5),
        swipe_duration=0.25,
        shake_duration=0.1,
    ):
        """拖拽并在终点附近轻微晃动，例如:
                     /\\
        +-----------+  +  +
                        \\/
        普通滑动或拖拽只有两个点，效果不够稳定。
        增加一些路径点，让它更接近真实滑动。

        参数：
            p1 (tuple)：起点 (x, y)。
            p2 (tuple)：终点 (x, y)。
            segments (int):
            shake (tuple)：到达终点后的晃动幅度。
            point_random：给起点和终点增加随机偏移。
            shake_random：给晃动点增加随机偏移。
            swipe_duration：路径点之间的间隔。
            shake_duration：晃动点之间的间隔。
        """
        p1 = np.array(p1) - random_rectangle_point(point_random)
        p2 = np.array(p2) - random_rectangle_point(point_random)
        path = [(x, y, swipe_duration) for x, y in random_line_segments(p1, p2, n=segments, random_range=point_random)]
        path += [
            (*p2 + shake + random_rectangle_point(shake_random), shake_duration),
            (*p2 - shake - random_rectangle_point(shake_random), shake_duration),
            (*p2, shake_duration),
        ]
        path = [(int(x), int(y), d) for x, y, d in path]
        self._drag_along(path)

    @retry
    def app_current_uiautomator2(self):
        """
        返回：
            str：包名。
        """
        result = self.u2.app_current()
        return result["package"]

    @retry
    def _app_start_u2_monkey(self, package_name=None, allow_failure=False):
        """
        参数：
            package_name (str):
            allow_failure (bool):

        返回：
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

    # _app_start_adb_am 和 _app_start_adb_monkey 已有 @retry，这里不再添加。
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

    @retry
    def proc_list_uiautomator2(self) -> list[ProcessInfo]:
        """
        Get info about current processes.
        """
        resp = self.u2.http.get("/proc/list", timeout=10)
        resp.raise_for_status()
        return [
            ProcessInfo(
                pid=proc["pid"],
                ppid=proc["ppid"],
                thread_count=proc["threadCount"],
                cmdline=" ".join(proc["cmdline"]) if proc["cmdline"] is not None else "",
                name=proc["name"],
            )
            for proc in resp.json()
        ]

    @retry
    def u2_shell_background(self, cmdline, timeout=10) -> ShellBackgroundResponse:
        """
        Run at background.

        Note that this function will always return a success response,
        as this is a untested and hidden method in ATX.
        """
        if isinstance(cmdline, (list, tuple)):
            cmdline = list2cmdline(cmdline)
        elif not isinstance(cmdline, str):
            raise TypeError("cmdargs type invalid", type(cmdline))

        data = {"command": cmdline, "timeout": str(timeout)}
        ret = self.u2.http.post("/shell/background", data=data, timeout=timeout + 10)
        ret.raise_for_status()

        resp = ret.json()
        return ShellBackgroundResponse(
            success=bool(resp.get("success", False)), pid=resp.get("pid", 0), description=resp.get("description", "")
        )
