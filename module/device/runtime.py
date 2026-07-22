import ctypes
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psutil
from adbutils.errors import AdbError

from module.base.decorator import cached_property, del_cached_property, run_once
from module.base.failure import raise_cleanup_errors
from module.base.timer import Timer
from module.config.deep import deep_get
from module.device.mumu_instance import MuMuInstance, resolve_mumu_instance
from module.device.service_retry import session_retry
from module.device.services import AppController, MinitouchController, NemuIpcCapture
from module.exception import HumanTakeoverRequiredError
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from module.device.connection import AdbDeviceWithStatus
    from module.device.contracts import (
        AppControllerService,
        CaptureService,
        ControllerService,
        DeviceSession,
    )


def get_focused_window() -> int:
    return ctypes.windll.user32.GetForegroundWindow()


def set_focus_window(hwnd: int) -> None:
    ctypes.windll.user32.SetForegroundWindow(hwnd)


def minimize_window(hwnd: int) -> None:
    ctypes.windll.user32.ShowWindow(hwnd, 6)


def get_window_title(hwnd: int) -> str:
    text_len_in_characters = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    string_buffer = ctypes.create_unicode_buffer(
        text_len_in_characters + 1
    )  # +1 for the \0 at the end of the null-terminated string.
    ctypes.windll.user32.GetWindowTextW(hwnd, string_buffer, text_len_in_characters + 1)
    return string_buffer.value


def flash_window(hwnd: int, *, flash: bool = True) -> None:
    ctypes.windll.user32.FlashWindow(hwnd, flash)


class MumuRuntime:
    """依赖同一 ADB session 的 MuMu 实例与生命周期服务。"""

    _serial_bound_cached_properties = (
        "nemud_app_keep_alive",
        "nemud_player_version",
        "is_mumu_over_version_400",
        "is_mumu_over_version_356",
    )

    def __init__(self, session: DeviceSession) -> None:
        self.session = session

    @property
    def serial(self) -> str:
        return self.session.serial

    @property
    def is_mumu_family(self) -> bool:
        return self.session.is_mumu_family

    @property
    def is_mumu12_family(self) -> bool:
        return self.session.is_mumu12_family

    def invalidate_serial(self) -> None:
        """清除由旧 live serial 派生的 MuMu 运行时缓存。"""
        for name in self._serial_bound_cached_properties:
            del_cached_property(self, name)

    @cached_property
    def emulator_instance(self) -> MuMuInstance:
        config = self.session.config
        return resolve_mumu_instance(config.Emulator_MuMuPath, config.Emulator_Serial)

    def check_after_connected(self) -> None:
        self.check_mumu_app_keep_alive()

    @cached_property
    @session_retry
    def nemud_app_keep_alive(self) -> str:
        value = self.session.adb_getprop("nemud.app_keep_alive")
        logger.attr("nemud.app_keep_alive", value)
        return value

    @cached_property
    @session_retry
    def nemud_player_version(self) -> str:
        value = self.session.adb_getprop("nemud.player_version")
        logger.attr("nemud.player_version", value)
        return value

    def check_mumu_app_keep_alive(self) -> bool:
        if not self.is_mumu_family:
            return False
        if self.is_mumu_over_version_400:
            return self.check_mumu_app_keep_alive_400()

        value = self.nemud_app_keep_alive
        if value == "":
            return True
        if value == "false":
            return True
        if value == "true":
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise HumanTakeoverRequiredError
        logger.warning(f"Invalid nemud.app_keep_alive value: {value}")
        return False

    def check_mumu_app_keep_alive_400(self) -> bool:
        file = self.emulator_instance.config_path("customer_config.json")
        try:
            content = json.loads(file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning(f"Failed to check check_mumu_app_keep_alive, file {file} not exists")
            return False

        value = deep_get(content, keys="customer.app_keptlive", default=None)
        logger.attr("customer.app_keptlive", value)
        if str(value).lower() == "true":
            logger.critical('Please turn off "Keep alive in the background" in the settings or MuMuPlayer')
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise HumanTakeoverRequiredError
        return True

    @cached_property
    def is_mumu_over_version_400(self) -> bool:
        if not self.is_mumu_family:
            return False
        return self.nemud_player_version == ""

    @cached_property
    def is_mumu_over_version_356(self) -> bool:
        if not self.is_mumu_family:
            return False
        if self.is_mumu_over_version_400:
            return True
        return self.nemud_app_keep_alive != ""

    def diagnose_adb_connect_refused(self) -> None:
        self.check_mumu_bridge_network()

    def check_mumu_bridge_network(self) -> bool:
        """False 表示配置文件不存在，无法执行检查。"""
        if not self.is_mumu12_family:
            return True

        file = self.emulator_instance.config_path("customer_config.json")
        try:
            content = json.loads(file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning(f"Failed to check check_mumu_bridge_network, file {file} not exists")
            return False

        value = deep_get(content, keys="customer.network_bridge_opened", default=None)
        logger.attr("customer.network_bridge_opened", value)
        if str(value).lower() == "true":
            logger.critical('Please turn off "Network Bridging" in the settings of MuMuPlayer')
            logger.critical("请在MuMU模拟器设置中关闭 网络桥接")
            raise HumanTakeoverRequiredError
        return True

    @classmethod
    def execute(cls, command: Sequence[str]) -> psutil.Popen:
        logger.info(f"Execute: {command}")
        # 让模拟器进程脱离 ALAS，避免 ALAS 退出时连带结束模拟器。
        return psutil.Popen(command, close_fds=True, start_new_session=True)

    def _emulator_start(self, instance: MuMuInstance) -> None:
        # 通过 MuMuManager 启动，避免多个 MuMuNxMain.exe 同时启动时请求被吞掉。
        self.execute([instance.manager_executable.as_posix(), "api", "-v", str(instance.instance_id), "launch_player"])

    def _emulator_stop(self, instance: MuMuInstance) -> None:
        self.execute(
            [instance.manager_executable.as_posix(), "api", "-v", str(instance.instance_id), "shutdown_player"]
        )

    def _emulator_function_wrapper(self, func: Callable[[MuMuInstance], None]) -> bool:
        instance = self.emulator_instance

        try:
            func(instance)
        except OSError as e:
            msg = str(e)
            # OSError: [WinError 740] 请求的操作需要提升。
            if "WinError 740" in msg:
                logger.error("To start/stop MuMuPlayer, ALAS needs to be run as administrator")
            else:
                logger.error(e)
        except psutil.Error as e:
            logger.error(e)
        else:
            return True

        func_name = getattr(func, "__name__", type(func).__name__)
        logger.error(f"Emulator function {func_name}() failed")
        return False

    def _adb_connect_for_start_watch(self) -> bool:
        msg = self.session.adb_client.connect(self.serial)
        if "connected" in msg:
            # 已连接时会输出：Connected to 127.0.0.1:59865。
            # 重复连接会输出：Already connected to 127.0.0.1:59865。
            return False
        # 10061 表示本机端口拒绝连接，不算成功连接。
        return "(10061)" not in msg

    @staticmethod
    def _log_emulator_online(device: AdbDeviceWithStatus) -> None:
        logger.info(f"Emulator online: {device}")

    @staticmethod
    def _log_command_ping(pong: str) -> None:
        logger.info(f"Command ping: {pong}")

    @staticmethod
    def _log_package_found(packages: list[str]) -> None:
        logger.info(f"Found azurlane packages: {packages}")

    @staticmethod
    def _focus_back_from_new_window(current_window: int, new_window: int) -> int:
        if current_window == 0 or new_window != 0:
            return new_window

        detected_window = get_focused_window()
        if current_window != detected_window:
            logger.info(f"New window showing up: {detected_window}, focus back")
            set_focus_window(current_window)
            return detected_window
        return 0

    def _check_start_watch_device(self, serial: str) -> AdbDeviceWithStatus | None:
        devices = self.session.list_device().select(serial=serial)
        if not devices:
            self._adb_connect_for_start_watch()
            return None

        device: AdbDeviceWithStatus | None = devices.first_or_none()
        if device is None:
            self._adb_connect_for_start_watch()
            return None
        if device.status == "offline":
            self.session.adb_client.disconnect(serial)
            self._adb_connect_for_start_watch()
            return None
        return device

    def _check_start_watch_shell(self) -> str | None:
        try:
            return self.session.adb_shell(["echo", "pong"])
        except (AdbError, ConnectionResetError, OSError) as e:
            logger.info(e)
            return None

    def _check_start_watch_package(self) -> list[str] | None:
        packages = self.session.list_known_packages(show_log=False)
        if len(packages):
            return packages
        return None

    @staticmethod
    def _finish_start_watch_window_state(current_window: int, new_window: int) -> None:
        if new_window not in (0, current_window):
            logger.info(f"Minimize new window: {new_window}")
            minimize_window(new_window)
        if current_window:
            logger.info(f"De-flash current window: {current_window}")
            flash_window(current_window, flash=False)
        if new_window:
            logger.info(f"Flash new window: {new_window}")
            flash_window(new_window, flash=True)

    def emulator_start_watch(self) -> bool:
        """模拟器启动完成返回 True，180 秒超时返回 False。"""
        logger.hr("Emulator start", level=2)
        current_window = get_focused_window()
        serial = self.serial
        logger.info(f"Current window: {current_window}")

        show_online = run_once(self._log_emulator_online)
        show_ping = run_once(self._log_command_ping)
        show_package = run_once(self._log_package_found)

        interval = Timer(0.5).start()
        timeout = Timer(180).start()
        new_window = 0
        while 1:
            interval.wait()
            interval.reset()
            if timeout.reached():
                logger.warning("Emulator start timeout")
                return False

            new_window = self._focus_back_from_new_window(current_window, new_window)

            device = self._check_start_watch_device(serial)
            if device is None:
                continue
            show_online(device)

            pong = self._check_start_watch_shell()
            if pong is None:
                continue
            show_ping(pong)

            packages = self._check_start_watch_package()
            if packages is None:
                continue
            show_package(packages)

            break

        self._finish_start_watch_window_state(current_window, new_window)
        logger.info("Emulator start completed")
        return True

    def emulator_start(self) -> bool:
        logger.hr("Emulator start", level=1)
        for _ in range(3):
            if not self._emulator_function_wrapper(self._emulator_stop):
                return False
            if self._emulator_function_wrapper(self._emulator_start):
                if self.emulator_start_watch():
                    return True
                continue
            if self._emulator_function_wrapper(self._emulator_stop):
                continue
            return False

        logger.error("Failed to start emulator 3 times, stopped")
        return False

    def emulator_stop(self) -> bool:
        logger.hr("Emulator stop", level=1)
        for _ in range(3):
            if self._emulator_function_wrapper(self._emulator_stop):
                return True
            if self._emulator_function_wrapper(self._emulator_start):
                continue
            return False

        logger.error("Failed to stop emulator 3 times, stopped")
        return False


@dataclass(slots=True)
class DeviceRuntime:
    """Device 背后的显式服务所有权图。"""

    adb_session: DeviceSession
    mumu_runtime: MumuRuntime
    capture: CaptureService
    controller: ControllerService
    app_controller: AppControllerService

    def __post_init__(self) -> None:
        if not (
            self.mumu_runtime.session is self.adb_session
            and self.controller.session is self.adb_session
            and self.app_controller.session is self.adb_session
            and self.capture.mumu_runtime is self.mumu_runtime
        ):
            message = "Device services must share the same ADB session"
            raise ValueError(message)

    @classmethod
    def create(cls, adb_session: DeviceSession) -> DeviceRuntime:
        """只建立对象引用；构造阶段不访问设备或文件系统。"""
        mumu_runtime = MumuRuntime(adb_session)
        return cls(
            adb_session=adb_session,
            mumu_runtime=mumu_runtime,
            capture=NemuIpcCapture(mumu_runtime),
            controller=MinitouchController(adb_session),
            app_controller=AppController(adb_session),
        )

    def release_serial(self) -> None:
        """按旧 serial 资源依赖顺序释放并失效缓存。"""
        errors: list[BaseException] = []
        for cleanup in (
            self.controller.release,
            self.capture.release,
            self.mumu_runtime.invalidate_serial,
        ):
            try:
                cleanup()
            except BaseException as error:  # ruff:ignore[blind-except] - 独立清理步骤失败后仍须继续释放其余资源。
                errors.append(error)
        raise_cleanup_errors(errors, message="device serial resource cleanup failed")

    def release(self) -> None:
        self.release_serial()
