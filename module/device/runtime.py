import ctypes
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, cast

import psutil
from adbutils.errors import AdbError

from module.base.decorator import run_once
from module.base.timer import Timer
from module.device.mumu_runtime_base import MumuRuntimeBase
from module.device.platform.emulator_windows import Emulator, EmulatorInstance, EmulatorManager
from module.device.services import AppController, MinitouchController, NemuIpcCapture
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from module.device.connection import AdbDeviceWithStatus
    from module.device.contracts import (
        AppControllerService,
        CaptureService,
        ControllerService,
        DeviceSession,
        MumuRuntimeService,
    )


class EmulatorUnknown(Exception):
    pass


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


class MumuRuntime(MumuRuntimeBase):
    """依赖同一 ADB session 的 MuMu 实例与生命周期服务。"""

    @cached_property
    def emulator_manager(self) -> EmulatorManager:
        session = cast("DeviceSession", self.session)
        return EmulatorManager(session.config.Emulator_MuMuPath)

    @classmethod
    def execute(cls, command: Sequence[str]) -> psutil.Popen:
        logger.info(f"Execute: {command}")
        # 让模拟器进程脱离 ALAS，避免 ALAS 退出时连带结束模拟器。
        return psutil.Popen(command, close_fds=True, start_new_session=True)

    def _emulator_start(self, instance: EmulatorInstance) -> None:
        exe: str = instance.emulator.path
        if instance != Emulator.MuMuPlayer12:
            message = f"Cannot start an unknown emulator instance: {instance}"
            raise EmulatorUnknown(message)
        # 通过 MuMuManager 启动，避免多个 MuMuNxMain.exe 同时启动时请求被吞掉。
        if instance.mumu_player_12_id is None:
            logger.warning(f"Cannot get MuMu instance index from name {instance.name}")
        self.execute([Emulator.single_to_console(exe), "api", "-v", str(instance.mumu_player_12_id), "launch_player"])

    def _emulator_stop(self, instance: EmulatorInstance) -> None:
        exe: str = instance.emulator.path
        if instance != Emulator.MuMuPlayer12:
            message = f"Cannot stop an unknown emulator instance: {instance}"
            raise EmulatorUnknown(message)
        if instance.mumu_player_12_id is None:
            logger.warning(f"Cannot get MuMu instance index from name {instance.name}")
        self.execute([Emulator.single_to_console(exe), "api", "-v", str(instance.mumu_player_12_id), "shutdown_player"])

    def _emulator_function_wrapper(self, func: Callable[[EmulatorInstance], None]) -> bool:
        instance = self.emulator_instance
        if instance is None:
            logger.error("未找到可启动或停止的模拟器实例")
            return False
        if not isinstance(instance, EmulatorInstance):
            logger.error(f"不支持的模拟器实例类型：{instance}")
            return False

        try:
            func(instance)
        except OSError as e:
            msg = str(e)
            # OSError: [WinError 740] 请求的操作需要提升。
            if "WinError 740" in msg:
                logger.error("To start/stop MuMuPlayer, ALAS needs to be run as administrator")
            else:
                logger.error(e)
        except (EmulatorUnknown, psutil.Error) as e:
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
        instance = self.emulator_instance
        if instance is None:
            logger.error("未找到可监听启动状态的模拟器实例")
            return False
        serial = instance.serial
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
    mumu_runtime: MumuRuntimeService
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
        first_error: Exception | None = None
        try:
            self.controller.release()
        except Exception as error:  # noqa: BLE001
            first_error = error
        try:
            self.capture.release()
        except Exception as error:  # noqa: BLE001
            if first_error is None:
                first_error = error
        finally:
            self.mumu_runtime.invalidate_serial()
        if first_error is not None:
            raise first_error

    def release(self) -> None:
        self.release_serial()
