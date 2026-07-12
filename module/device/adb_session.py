import re
import subprocess
import time
from functools import wraps
from typing import TYPE_CHECKING, ClassVar, Literal, overload

from adbutils import AdbClient, AdbConnection, AdbDevice, ForwardItem
from adbutils.errors import AdbError

from module.base.decorator import cached_property
from module.base.utils import ensure_time
from module.device.connection_attr import ConnectionAttr
from module.device.contracts import AdbRecoverySession
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

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Concatenate

type AdbCommand = str | Iterable[str | int]
type Recovery = Callable[[], None]


def _noop_recovery() -> None:
    pass


def _start_adb_server(device: AdbRecoverySession) -> None:
    _ = device.adb_start_server()


def _restart_adb_server_and_reconnect(device: AdbRecoverySession) -> None:
    device.adb_start_server()
    device.adb_reconnect()


def _adb_error_recovery(device: AdbRecoverySession, error: AdbError) -> Recovery | None:
    if handle_adb_error(error):
        return device.adb_reconnect
    if handle_unknown_host_service(error):
        return lambda: _restart_adb_server_and_reconnect(device)
    return None


def _connection_error_recovery(
    device: AdbRecoverySession, error: AdbError | PackageNotInstalled | OSError
) -> Recovery | None:
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
        if isinstance(error, ConnectionRefusedError) or getattr(error, "winerror", None) == 10061:
            return lambda: _start_adb_server(device)
        return _noop_recovery
    return None


def retry[SessionT: AdbRecoverySession, **P, ResultT](
    func: Callable[Concatenate[SessionT, P], ResultT],
) -> Callable[Concatenate[SessionT, P], ResultT]:
    @wraps(func)
    def retry_wrapper(self: SessionT, *args: P.args, **kwargs: P.kwargs) -> ResultT:
        recovery: Recovery | None = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(recovery):
                    time.sleep(retry_sleep(_))
                    recovery()
                return func(self, *args, **kwargs)
            except RequestHumanTakeover:
                break
            except (AdbError, PackageNotInstalled, OSError) as e:
                recovery = _connection_error_recovery(self, e)
                if recovery is None:
                    break

        func_name = getattr(func, "__name__", type(func).__name__)
        logger.critical(f"Retry {func_name}() failed")
        raise RequestHumanTakeover

    return retry_wrapper


class AdbDeviceWithStatus(AdbDevice):
    def __init__(self, client: AdbClient, serial: str, status: str) -> None:
        self.status = status
        super().__init__(client, serial)

    def __str__(self) -> str:
        return f"AdbDevice({self.serial}, {self.status})"

    __repr__ = __str__

    def __bool__(self) -> bool:
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
    def may_mumu12_family(self) -> bool:
        return is_mumu12_serial(self.serial or "")


class AdbSession(ConnectionAttr):
    _serial_bound_cached_properties = ("cpu_abi", "sdk_ver")

    def adb_reconnect(self) -> None:
        message = f"adb_reconnect() is not implemented for {type(self).__name__}"
        raise NotImplementedError(message)

    def detect_package(self) -> None:
        message = f"detect_package() is not implemented for {type(self).__name__}"
        raise NotImplementedError(message)

    def adb_start_server(self) -> int:
        command = [self.adb_binary, "-P", str(self.adb_server_port), "start-server"]
        logger.info(f"Start ADB server: {command}")
        completed = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True,
            timeout=10,
        )
        for output in (completed.stdout.strip(), completed.stderr.strip()):
            if output:
                logger.info(output)

        version = self.adb_client.server_version()
        logger.info(f"ADB server version: {version}")
        return version

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[False] = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str: ...

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[True],
        recvall: Literal[True] = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> bytes: ...

    @overload
    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: Literal[True],
        recvall: Literal[False],
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> AdbConnection: ...

    def adb_shell(
        self,
        cmd: AdbCommand,
        *,
        stream: bool = False,
        recvall: bool = True,
        timeout: float | None = 10,
        rstrip: bool = True,
    ) -> str | bytes | AdbConnection:
        """stream=False 返回 str；否则按 recvall 返回 bytes 或 socket。"""
        if not isinstance(cmd, str):
            cmd = list(map(str, cmd))

        if stream:
            result = self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip)
            if recvall:
                return recv_all(result)
            return result
        return remove_shell_warning(self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip))

    def adb_getprop(self, name: str) -> str:
        return self.adb_shell(["getprop", name]).strip()

    @retry
    def resolution_adb(self, *, cal_rotation: bool = True) -> tuple[int, int]:
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
        """可能值为 arm64-v8a、armeabi-v7a、x86 或 x86_64。"""
        abi = self.adb_getprop("ro.product.cpu.abi")
        if not len(abi):
            logger.error(f'CPU ABI invalid: "{abi}"')
        return abi

    @cached_property
    @retry
    def sdk_ver(self) -> int:
        """Android SDK/API 等级，见 https://apilevels.com/。"""
        sdk = self.adb_getprop("ro.build.version.sdk")
        try:
            return int(sdk)
        except ValueError:
            logger.error(f"SDK version invalid: {sdk}")

        return 0

    def adb_forward(self, remote: str) -> int:
        """复用同 remote 的唯一 TCP forward，否则从 FORWARD_PORT_RANGE 分配端口。

        remote 遵循 ADB 的 tcp、localabstract、localreserved、localfilesystem、dev 或 jdwp 格式。
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
        port = random_port(self.config.FORWARD_PORT_RANGE)
        forward = ForwardItem(self.serial, f"tcp:{port}", remote)
        logger.info(f"Create forward: {forward}")
        self.adb.forward(forward.local, forward.remote)
        return port

    def adb_forward_remove(self, local: str) -> None:
        """移除 ADB forward；目标不存在时仅记录警告。

        协议见 https://cs.android.com/android/platform/superproject/+/master:packages/modules/adb/SERVICES.TXT。
        """
        try:
            self.adb.forward_remove(local)
        except AdbError as e:
            msg = str(e)
            if re.search(r"listener .*? not found", msg):
                logger.warning(f"{type(e).__name__}: {msg}")
            else:
                raise

    def adb_push(self, local: str, remote: str) -> None:
        logger.info(f"ADB push: {local} -> {remote}")
        return self.adb.push(local, remote)

    @staticmethod
    def sleep(second: float | str | tuple[float, float]) -> None:
        time.sleep(float(ensure_time(second)))

    _orientation_description: ClassVar[dict[int, str]] = {
        0: "Normal",
        1: "HOME key on the right",
        2: "HOME key on the top",
        3: "HOME key on the left",
    }
    orientation = 0

    @retry
    def get_orientation(self) -> int:
        """返回旋转方向：0 为正常，1/2/3 分别表示 HOME 键在右/上/左。"""
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
    def list_device(self) -> SelectedGrids:
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
