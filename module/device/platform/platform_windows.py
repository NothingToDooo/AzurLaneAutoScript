import ctypes
import re
from typing import TYPE_CHECKING

import psutil
from adbutils.errors import AdbError

from module.base.decorator import run_once
from module.base.timer import Timer
from module.device.platform.emulator_windows import Emulator, EmulatorInstance, EmulatorManager
from module.device.platform.platform_base import PlatformBase
from module.device.platform.utils import DataProcessInfo
from module.logger import logger

if TYPE_CHECKING:
    from module.device.connection import AdbDeviceWithStatus


class EmulatorUnknown(Exception):
    pass


def get_focused_window():
    return ctypes.windll.user32.GetForegroundWindow()


def set_focus_window(hwnd):
    ctypes.windll.user32.SetForegroundWindow(hwnd)


def minimize_window(hwnd):
    ctypes.windll.user32.ShowWindow(hwnd, 6)


def get_window_title(hwnd):
    """Returns the window title as a string."""
    text_len_in_characters = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    string_buffer = ctypes.create_unicode_buffer(
        text_len_in_characters + 1
    )  # +1 for the \0 at the end of the null-terminated string.
    ctypes.windll.user32.GetWindowTextW(hwnd, string_buffer, text_len_in_characters + 1)
    return string_buffer.value


def flash_window(hwnd, flash=True):
    ctypes.windll.user32.FlashWindow(hwnd, flash)


class PlatformWindows(PlatformBase, EmulatorManager):
    @classmethod
    def execute(cls, command):
        """
        Args:
            command (list[str]):

        Returns:
            psutil.Popen:
        """
        logger.info(f"Execute: {command}")
        # 让模拟器进程脱离 ALAS，避免 ALAS 退出时连带结束模拟器。
        return psutil.Popen(command, close_fds=True, start_new_session=True)

    @classmethod
    def kill_process_by_regex(cls, regex: str) -> int:
        """
        Kill processes with cmdline match the given regex.

        Args:
            regex:

        Returns:
            int: Number of processes killed
        """
        count = 0

        for proc in psutil.process_iter():
            cmdline = DataProcessInfo(proc=proc, pid=proc.pid).cmdline
            if re.search(regex, cmdline):
                logger.info(f"Kill emulator: {cmdline}")
                proc.kill()
                count += 1

        return count

    def _emulator_start(self, instance: EmulatorInstance):
        """
        Start a emulator without error handling
        """
        exe: str = instance.emulator.path
        if instance == Emulator.MuMuPlayer:
            # NemuPlayer.exe
            self.execute([exe])
        elif instance == Emulator.MuMuPlayerX:
            # NemuPlayer.exe -m nemu-12.0-x64-default
            self.execute([exe, "-m", instance.name])
        elif instance == Emulator.MuMuPlayer12:
            # MuMuManager.exe api -v 0 launch_player
            # 通过 MuMuManager 启动，避免多个 MuMuNxMain.exe 同时启动时请求被吞掉。
            if instance.MuMuPlayer12_id is None:
                logger.warning(f"Cannot get MuMu instance index from name {instance.name}")
            self.execute([Emulator.single_to_console(exe), "api", "-v", str(instance.MuMuPlayer12_id), "launch_player"])
        else:
            raise EmulatorUnknown(f"Cannot start an unknown emulator instance: {instance}")

    def _emulator_stop(self, instance: EmulatorInstance):
        """
        Stop a emulator without error handling
        """
        exe: str = instance.emulator.path
        if instance == Emulator.MuMuPlayer:
            # MuMu6 does not have multi instance, kill one means kill all
            # Has 4 processes
            # "C:\Program Files\NemuVbox\Hypervisor\NemuHeadless.exe" --comment nemu-6.0-x64-default --startvm
            # "E:\ProgramFiles\MuMu\emulator\nemu\EmulatorShell\NemuPlayer.exe"
            # E:\ProgramFiles\MuMu\emulator\nemu\EmulatorShell\NemuService.exe
            # "C:\Program Files\NemuVbox\Hypervisor\NemuSVC.exe" -Embedding
            self.kill_process_by_regex(
                r"("
                r"NemuHeadless.exe"
                r"|NemuPlayer.exe\""
                r"|NemuPlayer.exe$"
                r"|NemuService.exe"
                r"|NemuSVC.exe"
                r")"
            )
        elif instance == Emulator.MuMuPlayerX:
            # MuMu X has 3 processes
            # "E:\ProgramFiles\MuMu9\emulator\nemu9\EmulatorShell\NemuPlayer.exe" -m nemu-12.0-x64-default -s 0 -l
            # "C:\Program Files\Muvm6Vbox\Hypervisor\Muvm6Headless.exe" --comment nemu-12.0-x64-default --startvm xxx
            # "C:\Program Files\Muvm6Vbox\Hypervisor\Muvm6SVC.exe" --Embedding
            self.kill_process_by_regex(
                rf"("
                rf"NemuPlayer.exe.*-m {instance.name}"
                rf"|Muvm6Headless.exe"
                rf"|Muvm6SVC.exe"
                rf")"
            )
        elif instance == Emulator.MuMuPlayer12:
            # MuMuManager.exe api -v 1 shutdown_player
            if instance.MuMuPlayer12_id is None:
                logger.warning(f"Cannot get MuMu instance index from name {instance.name}")
            self.execute(
                [Emulator.single_to_console(exe), "api", "-v", str(instance.MuMuPlayer12_id), "shutdown_player"]
            )
        else:
            raise EmulatorUnknown(f"Cannot stop an unknown emulator instance: {instance}")

    def _emulator_function_wrapper(self, func: callable):
        """
        参数：
            func：_emulator_start 或 _emulator_stop。

        返回：
            bool：是否成功。
        """
        instance = self.emulator_instance
        if instance is None:
            logger.error("未找到可启动或停止的模拟器实例")
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

        logger.error(f"Emulator function {func.__name__}() failed")
        return False

    def emulator_start_watch(self):
        """
        Returns:
            bool: True if startup completed
                False if timeout
        """
        logger.hr("Emulator start", level=2)
        current_window = get_focused_window()
        serial = self.emulator_instance.serial
        logger.info(f"Current window: {current_window}")

        def adb_connect():
            m = self.adb_client.connect(self.serial)
            if "connected" in m:
                # 已连接时会输出：Connected to 127.0.0.1:59865。
                # 重复连接会输出：Already connected to 127.0.0.1:59865。
                return False
            # 10061 表示本机端口拒绝连接，不算成功连接。
            return "(10061)" not in m

        @run_once
        def show_online(m):
            logger.info(f"Emulator online: {m}")

        @run_once
        def show_ping(m):
            logger.info(f"Command ping: {m}")

        @run_once
        def show_package(m):
            logger.info(f"Found azurlane packages: {m}")

        interval = Timer(0.5).start()
        timeout = Timer(180).start()
        new_window = 0
        while 1:
            interval.wait()
            interval.reset()
            if timeout.reached():
                logger.warning("Emulator start timeout")
                return False

            # Check emulator window showing up
            # logger.info([get_focused_window(), get_window_title(get_focused_window())])
            if current_window != 0 and new_window == 0:
                new_window = get_focused_window()
                if current_window != new_window:
                    logger.info(f"New window showing up: {new_window}, focus back")
                    set_focus_window(current_window)
                else:
                    new_window = 0

            # Check device connection
            devices = self.list_device().select(serial=serial)
            # logger.info(devices)
            if devices:
                device: AdbDeviceWithStatus = devices.first_or_none()
                if device.status == "device":
                    # Emulator online
                    pass
                if device.status == "offline":
                    self.adb_client.disconnect(serial)
                    adb_connect()
                    continue
            else:
                # Try to connect
                adb_connect()
                continue
            show_online(devices.first_or_none())

            # Check command availability
            try:
                pong = self.adb_shell(["echo", "pong"])
            except (AdbError, ConnectionResetError, OSError) as e:
                logger.info(e)
                continue
            show_ping(pong)

            # Check azuelane package
            packages = self.list_known_packages(show_log=False)
            if len(packages):
                pass
            else:
                continue
            show_package(packages)

            # All check passed
            break

        if new_window not in (0, current_window):
            logger.info(f"Minimize new window: {new_window}")
            minimize_window(new_window)
        if current_window:
            logger.info(f"De-flash current window: {current_window}")
            flash_window(current_window, flash=False)
        if new_window:
            logger.info(f"Flash new window: {new_window}")
            flash_window(new_window, flash=True)
        logger.info("Emulator start completed")
        return True

    def emulator_start(self):
        logger.hr("Emulator start", level=1)
        for _ in range(3):
            # Stop
            if not self._emulator_function_wrapper(self._emulator_stop):
                return False
            # Start
            if self._emulator_function_wrapper(self._emulator_start):
                if self.emulator_start_watch():
                    # Success
                    return True
                # Start command was sent but emulator didn't come online, stop and start again
                continue
            # Failed to start, stop and start again
            if self._emulator_function_wrapper(self._emulator_stop):
                continue
            return False

        logger.error("Failed to start emulator 3 times, stopped")
        return False

    def emulator_stop(self):
        logger.hr("Emulator stop", level=1)
        for _ in range(3):
            # Stop
            if self._emulator_function_wrapper(self._emulator_stop):
                # Success
                return True
            # Failed to stop, start and stop again
            if self._emulator_function_wrapper(self._emulator_start):
                continue
            return False

        logger.error("Failed to stop emulator 3 times, stopped")
        return False
