import json
import re
import time
from functools import wraps
from importlib import import_module
from pathlib import Path
from typing import ClassVar

from adbutils import AdbClient, AdbDevice, ForwardItem
from adbutils.errors import AdbError

from module.base.decorator import cached_property, del_cached_property, run_once
from module.base.utils import ensure_time
from module.config.deep import deep_get
from module.config.server import CN_PACKAGE
from module.device.connection_attr import ConnectionAttr
from module.device.method.pool import WORKER_POOL
from module.device.method.remove_warning import remove_shell_warning
from module.device.method.utils import (
    RETRY_TRIES,
    PackageNotInstalled,
    handle_adb_error,
    handle_unknown_host_service,
    possible_reasons,
    random_port,
    recv_all,
    retry_sleep,
)
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
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
            self (Adb):
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
        # 127.0.0.1:16XXX
        return 16384 <= self.port <= 17408


class Connection(ConnectionAttr):
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

        # 确认固定国服客户端包名。
        self.package = CN_PACKAGE
        self.ensure_package_installed()
        logger.attr("PackageName", self.package)
        logger.attr("Server", self.config.SERVER)

        self.check_mumu_app_keep_alive()

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

    @cached_property
    @retry
    def nemud_app_keep_alive(self) -> str:
        res = self.adb_getprop("nemud.app_keep_alive")
        logger.attr("nemud.app_keep_alive", res)
        return res

    @cached_property
    @retry
    def nemud_player_version(self) -> str:
        # [nemud.player_product_version]: [3.8.27.2950]
        res = self.adb_getprop("nemud.player_version")
        logger.attr("nemud.player_version", res)
        return res

    def check_mumu_app_keep_alive(self):
        if not self.is_mumu_family:
            return False

        res = self.nemud_app_keep_alive
        if res == "":
            # 旧版 MuMu 无法通过该属性判断后台保活。
            return True
        if res == "false":
            # 已关闭。
            return True
        if res == "true":
            # https://mumu.163.com/help/20230802/35047_1102450.html
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover
        logger.warning(f"Invalid nemud.app_keep_alive value: {res}")
        return False

    @cached_property
    def is_mumu_over_version_400(self) -> bool:
        if not self.is_mumu_family:
            return False
        # 4.0 及以上版本没有 getprop 信息。
        return self.nemud_player_version == ""

    @cached_property
    def is_mumu_over_version_356(self) -> bool:
        """
        返回：
            bool：MuMu12 版本是否不低于 3.5.6。
        """
        if not self.is_mumu_family:
            return False
        if self.is_mumu_over_version_400:
            return True
        return self.nemud_app_keep_alive != ""

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

    def _cleanup_adb_device_statuses(self, devices):
        """
        参数：
            devices (list[AdbDeviceWithStatus]): 当前 ADB 设备列表。
        """
        for device in devices:
            if device.status == "offline":
                logger.warning(f"Device {device.serial} is offline, disconnect it before connecting")
                msg = self.adb_client.disconnect(device.serial)
                if msg:
                    logger.info(msg)
            elif device.status == "unauthorized":
                logger.error(f"Device {device.serial} is unauthorized, please accept ADB debugging on your device")
            elif device.status == "device":
                pass
            else:
                logger.warning(f"Device {device.serial} is is having a unknown status: {device.status}")

    @staticmethod
    def _is_mumu_tcp_serial(serial: str) -> bool:
        """
        判断 serial 是否是个人分支支持的 MuMu TCP serial。
        """
        return re.fullmatch(r"127\.0\.0\.1:\d+", serial) is not None

    def _ensure_mumu_tcp_serial(self):
        """
        个人分支只支持 MuMu TCP serial，旧的 emulator-* 和真机 serial 不再兼容。
        """
        if self._is_mumu_tcp_serial(self.serial):
            return
        logger.critical(f'当前个人分支只支持 MuMu TCP serial，例如 "127.0.0.1:16384"，当前为 "{self.serial}"')
        raise RequestHumanTakeover

    def _recover_mumu12_shifted_port(self):
        """
        MuMu12 端口被占用时可能切换 serial，这里尝试连接相邻端口。

        返回：
            bool：是否通过相邻端口找到了新的 serial。
        """
        if not self.is_mumu12_family:
            return False

        before = self.serial
        serial_list = [self.serial.replace(str(self.port), str(self.port + offset)) for offset in [1, -1, 2, -2]]
        self.adb_brute_force_connect(serial_list)
        self.detect_device()
        return self.serial != before

    def _handle_adb_connect_refused(self):
        """
        处理 TCP 连接被拒绝。

        返回：
            bool：True 表示 MuMu12 已通过相邻端口恢复连接。
        """
        if self._recover_mumu12_shifted_port():
            return True
        run_once(self.check_mumu_bridge_network)()
        # 设备不存在。
        logger.warning("No such device exists, please restart the emulator or set a correct serial")
        raise EmulatorNotRunningError

    def _connect_adb_tcp_serial(self):
        """
        对 TCP serial 执行 `adb connect`，最多尝试 3 次。

        国产模拟器里经常有旧 ADB server 和当前 ADB 抢占，第一次连接可能只是杀掉旧进程，
        第二次才是真正连接。

        返回：
            bool：是否连接成功。
        """
        for _ in range(3):
            msg = self.adb_client.connect(self.serial)
            logger.info(msg)
            # Connected to 127.0.0.1:59865
            # Already connected to 127.0.0.1:59865
            if "connected" in msg:
                return True
            # bad port number '598265' in '127.0.0.1:598265'
            if "bad port" in msg:
                possible_reasons("Serial incorrect, might be a typo")
                raise RequestHumanTakeover
            # cannot connect to 127.0.0.1:55555:
            # No connection could be made because the target machine actively refused it. (10061)
            if "(10061)" in msg and self._handle_adb_connect_refused():
                return True

        return False

    def adb_connect(self):
        """
        连接当前 MuMu TCP serial。

        返回：
            bool：是否连接成功。
        """
        devices = self.list_device()
        self._cleanup_adb_device_statuses(devices)
        self._ensure_mumu_tcp_serial()

        if self._connect_adb_tcp_serial():
            return True

        logger.warning(f"Failed to connect {self.serial} after 3 trial, assume connected")
        self.detect_device()
        return False

    def adb_brute_force_connect(self, serial_list):
        """
        参数：
            serial_list (list[str]):
        """

        def connect(s):
            try:
                msg = self.adb_client.connect(s)
            except AdbError, OSError:
                return ""
            logger.info(msg)
            return msg

        with WORKER_POOL.wait_jobs() as pool:
            for serial in serial_list:
                pool.start_thread_soon(connect, serial)

    def check_mumu_bridge_network(self):
        """
        返回：
            bool：True 表示检查通过，False 表示跳过检查。
        """
        if not self.is_mumu12_family:
            return True
        find_emulator_instance = getattr(self, "find_emulator_instance", None)
        if not callable(find_emulator_instance):
            return False
        # 该方法在继承了 PlatformBase 的实例上可用。
        instance = find_emulator_instance(
            serial=self.serial,
        )
        if instance is None:
            logger.warning("Failed to check check_mumu_bridge_network, emulator instance not found")
            return False
        file = instance.mumu_vms_config("customer_config.json")
        try:
            with Path(file).open(encoding="utf-8") as f:
                s = f.read()
                data = json.loads(s)
        except FileNotFoundError:
            logger.warning(f"Failed to check check_mumu_bridge_network, file {file} not exists")
            return False
        value = deep_get(data, keys="customer.network_bridge_opened", default=None)
        logger.attr("customer.network_bridge_opened", value)
        if str(value).lower() == "true":
            logger.critical('Please turn off "Network Bridging" in the settings of MuMuPlayer')
            logger.critical("请在MuMU模拟器设置中关闭 网络桥接")
            raise RequestHumanTakeover
        return True

    def release_resource(self):
        del_cached_property(self, "_minitouch_builder")

    def adb_disconnect(self):
        msg = self.adb_client.disconnect(self.serial)
        if msg:
            logger.info(msg)
        self.release_resource()

    def adb_restart(self):
        """
        重启 ADB client。
        """
        logger.info("Restart adb")
        # 杀掉当前 client。
        self.adb_client.server_kill()
        # 重新初始化 ADB client。
        del_cached_property(self, "adb_client")
        self.release_resource()
        _ = self.adb_client

    def adb_reconnect(self):
        """
        如果找不到设备则重启 ADB，否则尝试重连设备。
        """
        if self.config.Emulator_AdbRestart and len(self.list_device()) == 0:
            # 重启 ADB。
            self.adb_restart()
            # 重新连接设备。
            self.adb_connect()
            self.detect_device()
        else:
            self.adb_disconnect()
            self.adb_connect()
            self.detect_device()

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
            if o in Connection._orientation_description:
                pass
            else:
                o = 0
                logger.warning(f"Invalid device orientation: {o}, assume it is normal")
        else:
            o = 0
            logger.warning("Unable to get device orientation, assume it is normal")

        self.orientation = o
        logger.attr("Device Orientation", f"{o} ({Connection._orientation_description.get(o, 'Unknown')})")
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

    def _brute_force_connect_emulators(self):
        logger.info("Brute force connect")
        emulator_manager_class = import_module("module.device.platform.emulator_windows").EmulatorManager
        self.adb_brute_force_connect(emulator_manager_class().all_emulator_serials)

    @staticmethod
    def _log_available_devices(available):
        for device in available:
            logger.info(device.serial)
        if not len(available):
            logger.info("No available devices")

    @staticmethod
    def _log_unavailable_devices(devices, available):
        unavailable = devices.delete(available)
        if len(unavailable):
            logger.info("Here are the devices detected but unavailable")
            for device in unavailable:
                logger.info(f"{device.serial} ({device.status})")

    def _list_and_log_detected_devices(self):
        logger.info(
            'Here are the available devices, copy to Alas.Emulator.Serial to use it or set Alas.Emulator.Serial="auto"'
        )
        devices = self.list_device()
        available = devices.select(status="device")
        self._log_available_devices(available)
        self._log_unavailable_devices(devices, available)
        return devices, available

    def _detect_available_devices(self, brute_force_connect):
        available = SelectedGrids([])
        devices = SelectedGrids([])
        for _ in range(2):
            devices, available = self._list_and_log_detected_devices()

            # 暴力尝试连接 MuMu 实例。
            if self.config.Emulator_Serial == "auto" and available.count == 0:
                logger.warning("No available device found")
                brute_force_connect()
                continue
            break
        return devices, available

    def _apply_auto_detected_device(self, available):
        """
        根据可用设备处理 `auto` serial。
        """
        if self.config.Emulator_Serial != "auto":
            return
        if available.count == 0:
            logger.critical(
                "No available device found, auto device detection cannot work, "
                'please set an exact serial in Alas.Emulator.Serial instead of using "auto"'
            )
            raise RequestHumanTakeover
        if available.count == 1:
            logger.info("Auto device detection found only one device, using it")
            self.config.Emulator_Serial = self.serial = available[0].serial
            del_cached_property(self, "adb")
            return
        if (
            available.count == 2
            and available.select(serial="127.0.0.1:7555")
            and available.select(may_mumu12_family=True)
        ):
            logger.info("Auto device detection found MuMu12 device, using it")
            # 对 127.0.0.1:7555 和 127.0.0.1:16384 这类 MuMu12 serial，
            # 忽略 7555，使用 16384。
            remain = available.select(may_mumu12_family=True).first_or_none()
            self.config.Emulator_Serial = self.serial = remain.serial
            del_cached_property(self, "adb")
            return

        logger.critical(
            "Multiple devices found, auto device detection cannot decide which to choose, "
            "please copy one of the available devices listed above to Alas.Emulator.Serial"
        )
        raise RequestHumanTakeover

    def _redirect_mumu12_from_7555(self, available, brute_force_connect):
        """
        将 MuMu12 从 127.0.0.1:7555 重定向到 127.0.0.1:16xxx。

        返回：
            SelectedGrids：可能刷新过的可用设备列表。
        """
        if self.serial != "127.0.0.1:7555":
            return available

        for _ in range(2):
            mumu12 = available.select(may_mumu12_family=True)
            if mumu12.count == 1:
                emu_serial = mumu12.first_or_none().serial
                logger.warning(f"Redirect MuMu12 {self.serial} to {emu_serial}")
                self.config.Emulator_Serial = self.serial = emu_serial
                break
            if mumu12.count >= 2:
                logger.warning("Multiple MuMu12 serial found, cannot redirect")
                break
            # 只有 127.0.0.1:7555。
            if self.is_mumu_over_version_356:
                # is_mumu_over_version_356 和 nemud_app_keep_alive 已被缓存。
                # 这里仍是同一个设备，可以接受。
                logger.warning(f"Device {self.serial} is MuMu12 but corresponding port not found")
                brute_force_connect()
                devices = self.list_device()
                available = devices.select(status="device")
                self._log_available_devices(available)
                continue
            # 不是当前可确认的 MuMu12 端口形态。
            break
        return available

    def _redirect_shifted_mumu12_port(self, available):
        """
        如果 MuMu12 动态端口发生小范围切换，只更新运行时 serial。
        """
        if not self.is_mumu12_family:
            return

        matched = False
        for device in available.select(may_mumu12_family=True):
            if device.port == self.port:
                # 精确匹配。
                matched = True
                break
        if matched:
            return

        for device in available.select(may_mumu12_family=True):
            if -2 <= device.port - self.port <= 2:
                # 端口发生切换。
                logger.info(f"MuMu12 serial switched {self.serial} -> {device.serial}")
                del_cached_property(self, "port")
                del_cached_property(self, "is_mumu12_family")
                del_cached_property(self, "is_mumu_family")
                self.serial = device.serial
                break

    def detect_device(self):
        """
        查找可用设备。

        如果 serial=='auto' 且只检测到 1 个设备，则使用它。
        """
        logger.hr("Detect device")
        brute_force_connect = run_once(self._brute_force_connect_emulators)
        _, available = self._detect_available_devices(brute_force_connect)

        # 自动检测设备。
        self._apply_auto_detected_device(available)

        # 将 MuMu12 从 127.0.0.1:7555 重定向到 127.0.0.1:16xxx。
        available = self._redirect_mumu12_from_7555(available, brute_force_connect)

        # 如果 16384 被占用，MuMu12 会使用 16385，这里自动重定向。
        # 这是动态端口，不写回配置。
        self._redirect_shifted_mumu12_port(available)

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

    def detect_package(self):
        """
        重新检查固定国服客户端包名。
        """
        logger.hr("Check package")
        self.ensure_package_installed()
        self.package = CN_PACKAGE
        logger.info(f'找到固定国服客户端包名 "{self.package}"')
