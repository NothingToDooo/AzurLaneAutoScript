import re
import time
from functools import wraps
from typing import ClassVar

from adbutils import AdbClient, AdbDevice, ForwardItem
from adbutils.errors import AdbError

from module.base.decorator import cached_property
from module.base.utils import ensure_time
from module.device.connection_attr import ConnectionAttr
from module.device.method.remove_warning import remove_shell_warning
from module.device.method.utils import (
    RETRY_TRIES,
    PackageNotInstalled,
    handle_adb_error,
    handle_unknown_host_service,
    random_port,
    recv_all,
    retry_sleep,
)
from module.device.mumu import is_mumu12_serial
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.map.map_grids import SelectedGrids


def _noop_recovery():
    pass


def _restart_adb_server_and_reconnect(device):
    device.adb_start_server()
    device.adb_reconnect()


def _adb_error_recovery(device, error):
    if handle_adb_error(error):
        return device.adb_reconnect
    if handle_unknown_host_service(error):
        return lambda: _restart_adb_server_and_reconnect(device)
    return None


def _connection_error_recovery(device, error):
    if isinstance(error, ConnectionResetError):
        logger.error(error)
        return device.adb_reconnect
    if isinstance(error, AdbError):
        return _adb_error_recovery(device, error)
    if isinstance(error, PackageNotInstalled):
        logger.error(error)
        return device.detect_package
    if isinstance(error, OSError):
        logger.error(error)
        return _noop_recovery
    return None


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (AdbSession):
        """
        recovery = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(recovery):
                    time.sleep(retry_sleep(_))
                    recovery()
                return func(self, *args, **kwargs)
            # 无法自动处理。
            except RequestHumanTakeover:
                break
            except (AdbError, PackageNotInstalled, OSError) as e:
                recovery = _connection_error_recovery(self, e)
                if recovery is None:
                    break

        logger.critical(f"Retry {func.__name__}() failed")
        raise RequestHumanTakeover

    return retry_wrapper


class AdbDeviceWithStatus(AdbDevice):
    def __init__(self, client: AdbClient, serial: str, status: str):
        self.status = status
        super().__init__(client, serial)

    def __str__(self):
        return f"AdbDevice({self.serial}, {self.status})"

    __repr__ = __str__

    def __bool__(self):
        return True

    @cached_property
    def port(self) -> int:
        serial = self.serial or ""
        _, sep, port = serial.partition(":")
        if not sep:
            return 0
        try:
            return int(port)
        except ValueError:
            return 0

    @cached_property
    def may_mumu12_family(self):
        return is_mumu12_serial(self.serial or "")


class AdbSession(ConnectionAttr):
    def adb_start_server(self):
        """
        触发 adbutils 启动 ADB server。
        """
        version = self.adb_client.server_version()
        logger.info(f"ADB server version: {version}")
        return version

    def adb_shell(self, cmd, stream=False, recvall=True, timeout=10, rstrip=True):
        """
        等价于 `adb -s <serial> shell <*cmd>`。

        参数：
            cmd (list, str):
            stream (bool)：返回流而不是字符串输出，默认 False。
            recvall (bool)：stream=True 时读取全部数据，默认 True。
            timeout (int)：默认 10。
            rstrip (bool)：移除末尾空行，默认 True。

        返回：
            stream=False 时返回 str。
            stream=True 且 recvall=True 时返回 bytes。
            stream=True 且 recvall=False 时返回 socket。
        """
        if not isinstance(cmd, str):
            cmd = list(map(str, cmd))

        if stream:
            result = self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip)
            if recvall:
                # bytes。
                return recv_all(result)
            # socket。
            return result
        # str。
        return remove_shell_warning(self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip))

    def adb_getprop(self, name):
        """
        获取 Android 系统属性，等价于 `getprop <name>`。

        参数：
            name (str)：属性名。

        返回：
            str:
        """
        return self.adb_shell(["getprop", name]).strip()

    @retry
    def resolution_adb(self, cal_rotation=True) -> tuple[int, int]:
        """
        使用 ADB 获取设备分辨率。
        """
        output = self.adb_shell(["wm", "size"])
        result = re.search(r"Physical size:\s*(?P<width>\d+)x(?P<height>\d+)", output)
        if result is None:
            logger.error(output)
            logger.critical("Unable to get emulator resolution from `wm size`")
            raise RequestHumanTakeover

        width = int(result.group("width"))
        height = int(result.group("height"))
        if cal_rotation:
            rotation = self.get_orientation()
            if (width > height) != (rotation % 2 == 1):
                width, height = height, width
        return width, height

    def resolution_check(self) -> tuple[int, int]:
        """
        检查模拟器分辨率是否为 1280x720。
        """
        width, height = self.resolution_adb()
        logger.attr("Screen_size", f"{width}x{height}")
        if (width, height) in {(1280, 720), (720, 1280)}:
            return (width, height)

        logger.critical(f"Resolution not supported: {width}x{height}")
        logger.critical("Please set emulator resolution to 1280x720")
        raise RequestHumanTakeover

    @cached_property
    @retry
    def cpu_abi(self) -> str:
        """
        返回：
            str：arm64-v8a、armeabi-v7a、x86、x86_64。
        """
        abi = self.adb_getprop("ro.product.cpu.abi")
        if not len(abi):
            logger.error(f'CPU ABI invalid: "{abi}"')
        return abi

    @cached_property
    @retry
    def sdk_ver(self) -> int:
        """
        Android SDK/API 等级，见 https://apilevels.com/。
        """
        sdk = self.adb_getprop("ro.build.version.sdk")
        try:
            return int(sdk)
        except ValueError:
            logger.error(f"SDK version invalid: {sdk}")

        return 0

    def adb_forward(self, remote):
        """
        执行 `adb forward <local> <remote>`。

        从 FORWARD_PORT_RANGE 中随机选择端口，或复用已有 forward，同时移除多余的 forward。

        参数：
            remote (str):
                tcp:<port>
                localabstract:<unix domain socket name>
                localreserved:<unix domain socket name>
                localfilesystem:<unix domain socket name>
                dev:<character device name>
                jdwp:<process pid> (remote only)

        返回：
            int：端口。
        """
        port = 0
        for forward in self.adb.forward_list():
            if forward.serial == self.serial and forward.remote == remote and forward.local.startswith("tcp:"):
                if not port:
                    logger.info(f"Reuse forward: {forward}")
                    port = int(forward.local[4:])
                else:
                    logger.info(f"Remove redundant forward: {forward}")
                    self.adb_forward_remove(forward.local)

        if port:
            return port
        # 创建新的 forward。
        port = random_port(self.config.FORWARD_PORT_RANGE)
        forward = ForwardItem(self.serial, f"tcp:{port}", remote)
        logger.info(f"Create forward: {forward}")
        self.adb.forward(forward.local, forward.remote)
        return port

    def adb_forward_remove(self, local):
        """
        等价于 `adb -s <serial> forward --remove <local>`。

        移除不存在的 forward 时不抛错。

        ADB server 命令参考：
        https://cs.android.com/android/platform/superproject/+/master:packages/modules/adb/SERVICES.TXT

        参数：
            local (str)：例如 'tcp:2437'。
        """
        try:
            self.adb.forward_remove(local)
        except AdbError as e:
            # 移除不存在的 forward 时不抛错。
            # adbutils.errors.AdbError: listener 'tcp:8888' not found
            msg = str(e)
            if re.search(r"listener .*? not found", msg):
                logger.warning(f"{type(e).__name__}: {msg}")
            else:
                raise

    def adb_push(self, local, remote):
        """
        参数：
            local (str):
            remote (str):

        返回：
            None:
        """
        logger.info(f"ADB push: {local} -> {remote}")
        return self.adb.push(local, remote)

    @staticmethod
    def sleep(second):
        """
        参数：
            second(int, float, tuple):
        """
        time.sleep(ensure_time(second))

    _orientation_description: ClassVar[dict[int, str]] = {
        0: "Normal",
        1: "HOME key on the right",
        2: "HOME key on the top",
        3: "HOME key on the left",
    }
    orientation = 0

    @retry
    def get_orientation(self):
        """
        获取设备旋转方向。

        返回：
            int:
                0：正常。
                1：HOME 键在右侧。
                2：HOME 键在顶部。
                3：HOME 键在左侧。
        """
        display_re = re.compile(
            r".*DisplayViewport{.*valid=true, .*orientation=(?P<orientation>\d+), "
            r".*deviceWidth=(?P<width>\d+), deviceHeight=(?P<height>\d+).*"
        )
        output = self.adb_shell(["dumpsys", "display"])

        res = display_re.search(output, 0)

        if res:
            o = int(res.group("orientation"))
            if o in self._orientation_description:
                pass
            else:
                o = 0
                logger.warning(f"Invalid device orientation: {o}, assume it is normal")
        else:
            o = 0
            logger.warning("Unable to get device orientation, assume it is normal")

        self.orientation = o
        logger.attr("Device Orientation", f"{o} ({self._orientation_description.get(o, 'Unknown')})")
        return o

    @retry
    def list_device(self):
        """
        Returns:
            SelectedGrids[AdbDeviceWithStatus]:
        """
        devices = []
        try:
            devices.extend(
                AdbDeviceWithStatus(self.adb_client, info.serial, info.state) for info in self.adb_client.list()
            )
        except ConnectionResetError as e:
            # 通常只发生在国内网络环境。
            # ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接。
            logger.error(e)
            if "强迫关闭" in str(e):
                logger.critical(
                    "无法连接至ADB服务，请关闭UU加速器、原神私服、以及一些劣质代理软件。"
                    "它们会劫持电脑上所有的网络连接，包括Alas与模拟器之间的本地连接。"
                )
        return SelectedGrids(devices)
