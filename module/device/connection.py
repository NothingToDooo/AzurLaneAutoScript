import ipaddress
import json
import logging
import re
import socket
import subprocess
import time
from functools import wraps

import uiautomator2 as u2
from adbutils import AdbClient, AdbDevice, AdbTimeout, ForwardItem, ReverseItem
from adbutils.errors import AdbError

from module.base.decorator import cached_property, del_cached_property, run_once
from module.base.timer import Timer
from module.base.utils import ensure_time
from module.config.deep import deep_get
from module.config.server import VALID_CHANNEL_PACKAGE, VALID_PACKAGE, set_server
from module.device.connection_attr import ConnectionAttr
from module.device.env import IS_LINUX, IS_MACINTOSH, IS_WINDOWS
from module.device.method.pool import WORKER_POOL
from module.device.method.remove_warning import remove_shell_warning
from module.device.method.utils import (
    RETRY_TRIES,
    PackageNotInstalled,
    get_serial_pair,
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


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Adb):
        """
        init = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # Can't handle
            except RequestHumanTakeover:
                break
            # When adb server was killed
            except ConnectionResetError as e:
                logger.error(e)

                def init():
                    self.adb_reconnect()
            # AdbError
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
            # Package not installed
            except PackageNotInstalled as e:
                logger.error(e)

                def init():
                    self.detect_package()
            # Unknown, probably a trucked image
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

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
        try:
            return int(self.serial.split(":")[1])
        except IndexError, ValueError:
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
        self.adb_connect(wait_device=False)
        logger.attr("AdbDevice", self.adb)

        # 确认游戏包名。
        self.package = self.config.Emulator_PackageName
        if self.package == "auto":
            self.detect_package()
        else:
            set_server(self.package)
        logger.attr("PackageName", self.package)
        logger.attr("Server", self.config.SERVER)

        self.check_mumu_app_keep_alive()

    def adb_command(self, cmd, timeout=10):
        """
        在子进程中执行 ADB 命令，通常用于拉取或推送大文件。

        参数：
            cmd (list):
            timeout (int):

        返回：
            str:
        """
        cmd = list(map(str, cmd))
        cmd = [self.adb_binary, "-s", self.serial] + cmd
        return self.subprocess_run(cmd, timeout=timeout)

    def subprocess_run(self, cmd, timeout=10):
        """
        参数：
            cmd (list):
            timeout (int):

        返回：
            str:
        """
        logger.info(f"Execute: {cmd}")
        # 旧 GUI 需要 shell=True 来隐藏控制台窗口。
        # Gooey 在停止运行时仍可能弹窗，需要改 gooey/gui/util/taskkill.py 才能彻底避免。

        # 现在已经没有 Gooey，直接使用 shell=False。
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.warning(f"TimeoutExpired when calling {cmd}, stdout={stdout}, stderr={stderr}")
        return stdout

    def adb_start_server(self):
        """
        用 `adb devices` 触发 `adb start-server`，命令结果本身没有实际用途。

        这里用子进程启动 ADB，而不是通过 socket 连接，避免误杀其他 ADB。
        """
        stdout = self.subprocess_run([self.adb_binary, "devices"])
        logger.info(stdout)
        return stdout

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
            else:
                # socket。
                return result
        else:
            result = self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip)
            result = remove_shell_warning(result)
            # str。
            return result

    def adb_getprop(self, name):
        """
        获取 Android 系统属性，等价于 `getprop <name>`。

        参数：
            name (str)：属性名。

        返回：
            str:
        """
        return self.adb_shell(["getprop", name]).strip()

    @cached_property
    @retry
    def cpu_abi(self) -> str:
        """
        Returns:
            str: arm64-v8a, armeabi-v7a, x86, x86_64
        """
        abi = self.adb_getprop("ro.product.cpu.abi")
        if not len(abi):
            logger.error(f'CPU ABI invalid: "{abi}"')
        return abi

    @cached_property
    @retry
    def sdk_ver(self) -> int:
        """
        Android SDK/API levels, see https://apilevels.com/
        """
        sdk = self.adb_getprop("ro.build.version.sdk")
        try:
            return int(sdk)
        except ValueError:
            logger.error(f"SDK version invalid: {sdk}")

        return 0

    @cached_property
    @retry
    def is_avd(self):
        if get_serial_pair(self.serial)[0] is None:
            return False
        if "ranchu" in self.adb_getprop("ro.hardware"):
            return True
        if "goldfish" in self.adb_getprop("ro.hardware.audio.primary"):
            return True
        return False

    @cached_property
    @retry
    def is_waydroid(self):
        res = self.adb_getprop("ro.product.brand")
        logger.attr("ro.product.brand", res)
        return "waydroid" in res.lower()

    @cached_property
    @retry
    def is_mumu_pro(self):
        # MuMU Pro is the Mac version of MuMu
        if not IS_MACINTOSH:
            return False
        if not self.is_mumu_family:
            return False
        logger.attr("is_mumu_pro", True)
        return True

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

    @cached_property
    @retry
    def nemud_player_engine(self) -> str:
        # NEMUX or MACPRO
        res = self.adb_getprop("nemud.player_engine")
        logger.attr("nemud.player_engine", res)
        return res

    def check_mumu_app_keep_alive(self):
        if not self.is_mumu_family:
            return False

        res = self.nemud_app_keep_alive
        if res == "":
            # Empty property, probably MuMu6 or MuMu12 version < 3.5.6
            return True
        elif res == "false":
            # Disabled
            return True
        elif res == "true":
            # https://mumu.163.com/help/20230802/35047_1102450.html
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover
        else:
            logger.warning(f"Invalid nemud.app_keep_alive value: {res}")
            return False

    @cached_property
    def is_mumu_over_version_400(self) -> bool:
        if not self.is_mumu_family:
            return False
        # >= 4.0 has no info in getprop
        if self.nemud_player_version == "":
            return True
        return False

    @cached_property
    def is_mumu_over_version_356(self) -> bool:
        """
        Returns:
            bool: If MuMu12 version >= 3.5.6,
                which has nemud.app_keep_alive and always be a vertical device
                MuMu PRO on mac has the same feature
        """
        if not self.is_mumu_family:
            return False
        if self.is_mumu_over_version_400:
            return True
        if self.nemud_app_keep_alive != "":
            return True
        if IS_MACINTOSH:
            if "MACPRO" in self.nemud_player_engine:
                return True
        return False

    @cached_property
    def _nc_server_host_port(self):
        """
        Returns:
            str, int, str, int:
                server_listen_host, server_listen_port, client_connect_host, client_connect_port
        """
        # 模拟器场景监听当前主机。
        if self.is_emulator:
            # Mac 模拟器。
            if self.is_mumu_pro:
                logger.info("Connecting to local emulator, using host 127.0.0.1")
                port = random_port(self.config.FORWARD_PORT_RANGE)
                return "127.0.0.1", port, "10.0.2.2", port
            # 获取主机 IP。
            try:
                host = socket.gethostbyname(socket.gethostname())
            except socket.gaierror as e:
                logger.error(e)
                logger.error(f"Unknown host name: {socket.gethostname()}")
                host = "127.0.0.1"
            # 修正 Linux AVD 的主机地址。
            if IS_LINUX and host == "127.0.1.1":
                host = "127.0.0.1"
            logger.info(f"Connecting to local emulator, using host {host}")
            port = random_port(self.config.FORWARD_PORT_RANGE)
            # AVD 实例需要连接 10.0.2.2。
            if self.is_avd:
                return host, port, "10.0.2.2", port
            return host, port, host, port
        # 局域网设备需要监听在同网段主机地址上。
        if self.is_network_device:
            hosts = socket.gethostbyname_ex(socket.gethostname())[2]
            logger.info(f"Current hosts: {hosts}")
            ip = ipaddress.ip_address(self.serial.split(":")[0])
            for host in hosts:
                if ip in ipaddress.ip_interface(f"{host}/24").network:
                    logger.info(f"Connecting to local network device, using host {host}")
                    port = random_port(self.config.FORWARD_PORT_RANGE)
                    return host, port, host, port
        # 其他设备通过 ADB reverse 转发到 127.0.0.1。
        host = "127.0.0.1"
        logger.info(f"Connecting to unknown device, using host {host}")
        port = self.adb_reverse(f"tcp:{self.config.REVERSE_SERVER_PORT}")
        return host, port, host, self.config.REVERSE_SERVER_PORT

    @cached_property
    def reverse_server(self):
        """
        Setup a server on Alas, access it from emulator.
        This will bypass adb shell and be faster.
        """
        del_cached_property(self, "_nc_server_host_port")
        host_port = self._nc_server_host_port
        logger.info(
            f"Reverse server listening on {host_port[0]}:{host_port[1]}, "
            f"client can send data to {host_port[2]}:{host_port[3]}"
        )
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(host_port[:2])
        server.settimeout(5)
        server.listen(5)
        return server

    @cached_property
    def nc_command(self):
        """
        Returns:
            list[str]: ['nc'] or ['busybox', 'nc']
        """
        if self.is_emulator:
            sdk = self.sdk_ver
            logger.info(f"sdk_ver: {sdk}")
            if sdk >= 28:
                trial = [
                    ["busybox", "nc"],
                    ["nc"],
                ]
            else:
                trial = [
                    ["nc"],
                    ["busybox", "nc"],
                ]
        else:
            trial = [
                ["nc"],
                ["busybox", "nc"],
            ]
        for command in trial:
            # About 3ms
            # Result should be command help if success
            # nc: bad argument count (see "nc --help")
            result = self.adb_shell(command)
            # `/system/bin/sh: nc: not found`
            if "not found" in result:
                continue
            # `/system/bin/sh: busybox: inaccessible or not found\n`
            if "inaccessible" in result:
                continue
            logger.attr("nc command", command)
            return command

        logger.error("No `netcat` command available, please use screenshot methods without `_nc` suffix")
        raise RequestHumanTakeover

    def adb_shell_nc(self, cmd, timeout=5, chunk_size=262144):
        """
        Args:
            cmd (list):
            timeout (int):
            chunk_size (int): Default to 262144

        Returns:
            bytes:
        """
        # Server start listening
        server = self.reverse_server
        server.settimeout(timeout)
        # Client send data, waiting for server accept
        # <command> | nc 127.0.0.1 {port}
        cmd += ["|", *self.nc_command, *self._nc_server_host_port[2:]]
        stream = self.adb_shell(cmd, stream=True, recvall=False)
        try:
            # Server accept connection
            conn, conn_port = server.accept()
        except TimeoutError:
            output = recv_all(stream, chunk_size=chunk_size)
            logger.warning(str(output))
            raise AdbTimeout("reverse server accept timeout")

        # Server receive data
        data = recv_all(conn, chunk_size=chunk_size, recv_interval=0.001)

        # Server close connection
        conn.close()
        return data

    def adb_exec_out(self, cmd, serial=None):
        cmd.insert(0, "exec-out")
        return self.adb_command(cmd, serial)

    def adb_forward(self, remote):
        """
        Do `adb forward <local> <remote>`.
        choose a random port in FORWARD_PORT_RANGE or reuse an existing forward,
        and also remove redundant forwards.

        Args:
            remote (str):
                tcp:<port>
                localabstract:<unix domain socket name>
                localreserved:<unix domain socket name>
                localfilesystem:<unix domain socket name>
                dev:<character device name>
                jdwp:<process pid> (remote only)

        Returns:
            int: Port
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
        else:
            # Create new forward
            port = random_port(self.config.FORWARD_PORT_RANGE)
            forward = ForwardItem(self.serial, f"tcp:{port}", remote)
            logger.info(f"Create forward: {forward}")
            self.adb.forward(forward.local, forward.remote)
            return port

    def _adb_reverse_transport(self, remote: str, local: str, norebind: bool = False):
        """
        Backport fixes from https://github.com/openatx/adbutils/pull/116
        Don't use self.adb.reverse(), use this method.
        """
        args = ["reverse:forward"]
        if norebind:
            args.append("norebind")
        args.append(remote + ";" + local)
        cmd = ":".join(args)
        with self.adb_client._connect() as c:
            c.send_command(f"host:transport:{self.serial}")
            c.check_okay()
            c.send_command(cmd)
            c.check_okay()

    def adb_reverse(self, remote):
        port = 0
        for reverse in self.adb.reverse_list():
            if reverse.remote == remote and reverse.local.startswith("tcp:"):
                if not port:
                    logger.info(f"Reuse reverse: {reverse}")
                    port = int(reverse.local[4:])
                else:
                    logger.info(f"Remove redundant forward: {reverse}")
                    self.adb_reverse_remove(reverse.remote)

        if port:
            return port
        else:
            # Create new reverse
            port = random_port(self.config.FORWARD_PORT_RANGE)
            reverse = ReverseItem(remote, f"tcp:{port}")
            logger.info(f"Create reverse: {reverse}")
            self._adb_reverse_transport(reverse.remote, reverse.local)
            return port

    def adb_forward_remove(self, local):
        """
        Equivalent to `adb -s <serial> forward --remove <local>`
        No error raised when removing a non-existent forward

        More about the commands send to ADB server, see:
        https://cs.android.com/android/platform/superproject/+/master:packages/modules/adb/SERVICES.TXT

        Args:
            local (str): Such as 'tcp:2437'
        """
        try:
            with self.adb_client._connect() as c:
                list_cmd = f"host-serial:{self.serial}:killforward:{local}"
                c.send_command(list_cmd)
                c.check_okay()
        except AdbError as e:
            # No error raised when removing a non-existed forward
            # adbutils.errors.AdbError: listener 'tcp:8888' not found
            msg = str(e)
            if re.search(r"listener .*? not found", msg):
                logger.warning(f"{type(e).__name__}: {msg}")
            else:
                raise

    def adb_reverse_remove(self, local):
        """
        Equivalent to `adb -s <serial> reverse --remove <local>`
        No error raised when removing a non-existent reverse

        Args:
            local (str): Such as 'tcp:2437'
        """
        try:
            with self.adb_client._connect() as c:
                c.send_command(f"host:transport:{self.serial}")
                c.check_okay()
                list_cmd = f"reverse:killforward:{local}"
                c.send_command(list_cmd)
                c.check_okay()
        except AdbError as e:
            # No error raised when removing a non-existed forward
            # adbutils.errors.AdbError: listener 'tcp:8888' not found
            msg = str(e)
            if re.search(r"listener .*? not found", msg):
                logger.warning(f"{type(e).__name__}: {msg}")
            else:
                raise

    def adb_push(self, local, remote):
        """
        Args:
            local (str):
            remote (str):

        Returns:
            str:
        """
        cmd = ["push", local, remote]
        return self.adb_command(cmd)

    def _wait_device_appear(self, serial, first_devices=None):
        """
        参数：
            serial:
            first_devices (list[AdbDeviceWithStatus]):

        返回：
            bool：设备是否已出现。
        """
        # 比 5 秒略长一点，避开边界误判。
        timeout = Timer(5.2).start()
        first_log = True
        while 1:
            if first_devices is not None:
                devices = first_devices
                first_devices = None
            else:
                devices = self.list_device()
            # 检查设备是否已经出现。
            for device in devices:
                if device.serial == serial and device.status == "device":
                    return True
            # 稍后重试。
            if timeout.reached():
                break
            if first_log:
                logger.info(f"Waiting device appear: {serial}")
                first_log = False
            time.sleep(0.05)

        return False

    def adb_connect(self, wait_device=True):
        """
        连接指定 serial，最多尝试 3 次。

        国产模拟器里经常有旧 ADB server 和当前 ADB 抢占，第一次连接可能只是杀掉旧进程，
        第二次才是真正连接。

        参数：
            serial (str):
            wait_device：是否等待 emulator-* 和 Android 真机出现。

        返回：
            bool：是否连接成功。
        """
        # 连接前先断开 offline 设备。
        devices = self.list_device()
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

        # emulator-* 和 Android 真机通常会自动连接，不需要 adb connect。
        if "emulator-" in self.serial:
            if wait_device:
                if self._wait_device_appear(self.serial, first_devices=devices):
                    logger.info(f"Serial {self.serial} connected")
                    return True
                else:
                    logger.info(f"Serial {self.serial} is not connected")
            logger.info(f'"{self.serial}" is a `emulator-*` serial, skip adb connect')
            return True
        if re.match(r"^[a-zA-Z0-9]+$", self.serial):
            if wait_device:
                if self._wait_device_appear(self.serial, first_devices=devices):
                    logger.info(f"Serial {self.serial} connected")
                    return True
                else:
                    logger.info(f"Serial {self.serial} is not connected")
            logger.info(f'"{self.serial}" seems to be a Android serial, skip adb connect')
            return True

        # 尝试连接。
        for _ in range(3):
            msg = self.adb_client.connect(self.serial)
            logger.info(msg)
            # Connected to 127.0.0.1:59865
            # Already connected to 127.0.0.1:59865
            if "connected" in msg:
                return True
            # bad port number '598265' in '127.0.0.1:598265'
            elif "bad port" in msg:
                possible_reasons("Serial incorrect, might be a typo")
                raise RequestHumanTakeover
            # cannot connect to 127.0.0.1:55555:
            # No connection could be made because the target machine actively refused it. (10061)
            elif "(10061)" in msg:
                # MuMu12 端口被占用时可能切换 serial。
                # 这里尝试连接相邻端口来处理动态切换。
                if self.is_mumu12_family:
                    before = self.serial
                    serial_list = [
                        self.serial.replace(str(self.port), str(self.port + offset)) for offset in [1, -1, 2, -2]
                    ]
                    self.adb_brute_force_connect(serial_list)
                    self.detect_device()
                    if self.serial != before:
                        return True
                run_once(self.check_mumu_bridge_network)()
                # 设备不存在。
                logger.warning("No such device exists, please restart the emulator or set a correct serial")
                raise EmulatorNotRunningError

        # 连接失败。
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
            except Exception:
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
        if not hasattr(self, "find_emulator_instance"):
            return False
        # 该方法在继承了 PlatformBase 的实例上可用。
        instance = self.find_emulator_instance(
            serial=self.serial,
        )
        if instance is None:
            logger.warning("Failed to check check_mumu_bridge_network, emulator instance not found")
            return False
        file = instance.mumu_vms_config("customer_config.json")
        try:
            with open(file, encoding="utf-8") as f:
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
        del_cached_property(self, "reverse_server")

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

    def install_uiautomator2(self):
        """
        初始化 uiautomator2，并移除 minicap。
        """
        logger.info("Install uiautomator2")
        init = u2.init.Initer(self.adb, loglevel=logging.DEBUG)
        # MuMu X 没有 ro.product.cpu.abi，需要从 ro.product.cpu.abilist 选 ABI。
        if init.abi not in ["x86_64", "x86", "arm64-v8a", "armeabi-v7a", "armeabi"]:
            init.abi = init.abis[0]
        init.set_atx_agent_addr("127.0.0.1:7912")
        try:
            init.install()
        except ConnectionError:
            u2.init.GITHUB_BASEURL = "http://tool.appetizer.io/openatx"
            init.install()
        self.uninstall_minicap()

    def uninstall_minicap(self):
        """部分模拟器上 minicap 不可用，或会返回压缩图片。"""
        logger.info("Removing minicap")
        self.adb_shell(["rm", "/data/local/tmp/minicap"])
        self.adb_shell(["rm", "/data/local/tmp/minicap.so"])

    def restart_atx(self):
        """
        minitouch 同时只支持一个连接。

        重启 ATX 可以踢掉已有连接。
        """
        logger.info("Restart ATX")
        atx_agent_path = "/data/local/tmp/atx-agent"
        self.adb_shell([atx_agent_path, "server", "--stop"])
        self.adb_shell([atx_agent_path, "server", "--nouia", "-d", "--addr", "127.0.0.1:7912"])

    @staticmethod
    def sleep(second):
        """
        Args:
            second(int, float, tuple):
        """
        time.sleep(ensure_time(second))

    _orientation_description = {
        0: "Normal",
        1: "HOME key on the right",
        2: "HOME key on the top",
        3: "HOME key on the left",
    }
    orientation = 0

    @retry
    def get_orientation(self):
        """
        Rotation of the phone

        Returns:
            int:
                0: 'Normal'
                1: 'HOME key on the right'
                2: 'HOME key on the top'
                3: 'HOME key on the left'
        """
        _DISPLAY_RE = re.compile(
            r".*DisplayViewport{.*valid=true, .*orientation=(?P<orientation>\d+), .*deviceWidth=(?P<width>\d+), deviceHeight=(?P<height>\d+).*"
        )
        output = self.adb_shell(["dumpsys", "display"])

        res = _DISPLAY_RE.search(output, 0)

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
            with self.adb_client._connect() as c:
                c.send_command("host:devices")
                c.check_okay()
                output = c.read_string_block()
                for line in output.splitlines():
                    parts = line.strip().split("\t")
                    if len(parts) != 2:
                        continue
                    device = AdbDeviceWithStatus(self.adb_client, parts[0], parts[1])
                    devices.append(device)
        except ConnectionResetError as e:
            # Happens only on CN users.
            # ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接。
            logger.error(e)
            if "强迫关闭" in str(e):
                logger.critical(
                    "无法连接至ADB服务，请关闭UU加速器、原神私服、以及一些劣质代理软件。"
                    "它们会劫持电脑上所有的网络连接，包括Alas与模拟器之间的本地连接。"
                )
        return SelectedGrids(devices)

    def detect_device(self):
        """
        Find available devices
        If serial=='auto' and only 1 device detected, use it
        """
        logger.hr("Detect device")
        available = SelectedGrids([])
        devices = SelectedGrids([])

        @run_once
        def brute_force_connect():
            logger.info("Brute force connect")
            from deploy.Windows.emulator import EmulatorManager

            manager = EmulatorManager()
            manager.brute_force_connect()

        for _ in range(2):
            logger.info(
                "Here are the available devices, "
                'copy to Alas.Emulator.Serial to use it or set Alas.Emulator.Serial="auto"'
            )
            devices = self.list_device()

            # Show available devices
            available = devices.select(status="device")
            for device in available:
                logger.info(device.serial)
            if not len(available):
                logger.info("No available devices")

            # Show unavailable devices if having any
            unavailable = devices.delete(available)
            if len(unavailable):
                logger.info("Here are the devices detected but unavailable")
                for device in unavailable:
                    logger.info(f"{device.serial} ({device.status})")

            # brute_force_connect
            if self.config.Emulator_Serial == "auto" and available.count == 0:
                logger.warning("No available device found")
                if IS_WINDOWS:
                    brute_force_connect()
                    continue
                else:
                    break
            else:
                break

        # Auto device detection
        if self.config.Emulator_Serial == "auto":
            if available.count == 0:
                logger.critical(
                    "No available device found, auto device detection cannot work, "
                    'please set an exact serial in Alas.Emulator.Serial instead of using "auto"'
                )
                raise RequestHumanTakeover
            elif available.count == 1:
                logger.info("Auto device detection found only one device, using it")
                self.config.Emulator_Serial = self.serial = available[0].serial
                del_cached_property(self, "adb")
            elif (
                available.count == 2
                and available.select(serial="127.0.0.1:7555")
                and available.select(may_mumu12_family=True)
            ):
                logger.info("Auto device detection found MuMu12 device, using it")
                # For MuMu12 serials like 127.0.0.1:7555 and 127.0.0.1:16384
                # ignore 7555 use 16384
                remain = available.select(may_mumu12_family=True).first_or_none()
                self.config.Emulator_Serial = self.serial = remain.serial
                del_cached_property(self, "adb")
            else:
                logger.critical(
                    "Multiple devices found, auto device detection cannot decide which to choose, "
                    "please copy one of the available devices listed above to Alas.Emulator.Serial"
                )
                raise RequestHumanTakeover

        # Redirect MuMu12 from 127.0.0.1:7555 to 127.0.0.1:16xxx
        if self.serial == "127.0.0.1:7555":
            for _ in range(2):
                mumu12 = available.select(may_mumu12_family=True)
                if mumu12.count == 1:
                    emu_serial = mumu12.first_or_none().serial
                    logger.warning(f"Redirect MuMu12 {self.serial} to {emu_serial}")
                    self.config.Emulator_Serial = self.serial = emu_serial
                    break
                elif mumu12.count >= 2:
                    logger.warning("Multiple MuMu12 serial found, cannot redirect")
                    break
                else:
                    # Only 127.0.0.1:7555
                    if self.is_mumu_over_version_356:
                        # is_mumu_over_version_356 and nemud_app_keep_alive was cached
                        # Acceptable since it's the same device
                        logger.warning(f"Device {self.serial} is MuMu12 but corresponding port not found")
                        if IS_WINDOWS:
                            brute_force_connect()
                        devices = self.list_device()
                        # Show available devices
                        available = devices.select(status="device")
                        for device in available:
                            logger.info(device.serial)
                        if not len(available):
                            logger.info("No available devices")
                        continue
                    else:
                        # MuMu6
                        break

        # MuMu12 uses 127.0.0.1:16385 if port 16384 is occupied, auto redirect
        # No config write since it's dynamic
        if self.is_mumu12_family:
            matched = False
            for device in available.select(may_mumu12_family=True):
                if device.port == self.port:
                    # Exact match
                    matched = True
                    break
            if not matched:
                for device in available.select(may_mumu12_family=True):
                    if -2 <= device.port - self.port <= 2:
                        # Port switched
                        logger.info(f"MuMu12 serial switched {self.serial} -> {device.serial}")
                        del_cached_property(self, "port")
                        del_cached_property(self, "is_mumu12_family")
                        del_cached_property(self, "is_mumu_family")
                        self.serial = device.serial
                        break

    @retry
    def list_package(self, show_log=True):
        """
        Find all packages on device.
        Use dumpsys first for faster.
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
        packages = re.findall(r"package:([^\s]+)", output)
        return packages

    def list_known_packages(self, show_log=True):
        """
        Args:
            show_log:

        Returns:
            list[str]: List of package names
        """
        packages = self.list_package(show_log=show_log)
        packages = [p for p in packages if p in VALID_PACKAGE or p in VALID_CHANNEL_PACKAGE]
        return packages

    def detect_package(self, set_config=True):
        """
        Show all game client on this device.
        """
        logger.hr("Detect package")
        packages = self.list_known_packages()

        # Show packages
        logger.info(
            f'Here are the available packages in device "{self.serial}", copy to Alas.Emulator.PackageName to use it'
        )
        if len(packages):
            for package in packages:
                logger.info(package)
        else:
            logger.info(f'No available packages on device "{self.serial}"')

        # Auto package detection
        if len(packages) == 0:
            logger.critical(
                f'No AzurLane package found, please confirm AzurLane has been installed on device "{self.serial}"'
            )
            raise RequestHumanTakeover
        if len(packages) == 1:
            logger.info("Auto package detection found only one package, using it")
            self.package = packages[0]
            # Set config
            if set_config:
                self.config.Emulator_PackageName = self.package
            # Set server
            logger.info("Server changed, release resources")
            set_server(self.package)
        else:
            logger.critical(
                "Multiple AzurLane packages found, auto package detection cannot decide which to choose, "
                "please copy one of the available devices listed above to Alas.Emulator.PackageName"
            )
            raise RequestHumanTakeover
