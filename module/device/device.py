import collections
from datetime import datetime
from typing import TYPE_CHECKING

from module.device.env import IS_WINDOWS

if TYPE_CHECKING:
    from lxml import etree

# 在导入 adbutils 和 uiautomator2 之前先修补 pkg_resources。
from module.device.pkg_resources import get_distribution

# 避免导入优化移除上面的修补。
_ = get_distribution

from module.base.timer import Timer
from module.config.utils import get_server_next_update
from module.device.app_control import AppControl
from module.device.control import Control
from module.device.screenshot import Screenshot
from module.exception import (
    EmulatorNotRunningError,
    GameNotRunningError,
    GameStuckError,
    GameTooManyClickError,
    RequestHumanTakeover,
)
from module.handler.assets import GET_MISSION
from module.logger import logger


def show_function_call():
    """
    INFO     21:07:31.554 │ Function calls:
                       <string>   L1 <module>
                   spawn.py L116 spawn_main()
                   spawn.py L129 _main()
                 process.py L314 _bootstrap()
                 process.py L108 run()
         process_manager.py L149 run_process()
                    alas.py L285 loop()
                    alas.py  L69 run()
                     src.py  L55 rogue()
                   rogue.py  L36 run()
                   rogue.py  L18 rogue_once()
                   entry.py L335 rogue_world_enter()
                    path.py L193 rogue_path_select()
    """
    import os
    import traceback

    stack = traceback.extract_stack()
    func_list = []
    for row in stack:
        filename, line_number, function_name, _ = row
        filename = os.path.basename(filename)
        # /tasks/character/switch.py:64 character_update()
        func_list.append([filename, str(line_number), function_name])
    max_filename = max([len(row[0]) for row in func_list])
    max_linenum = max([len(row[1]) for row in func_list]) + 1

    def format_(file, line, func):
        file = file.rjust(max_filename, " ")
        line = f"L{line}".rjust(max_linenum, " ")
        if not func.startswith("<"):
            func = f"{func}()"
        return f"{file} {line} {func}"

    func_list = [f"\n{format_(*row)}" for row in func_list]
    logger.info("Function calls:" + "".join(func_list))


class Device(Screenshot, Control, AppControl):
    _screen_size_checked = False
    detect_record = set()
    click_record = collections.deque(maxlen=15)
    stuck_timer = Timer(60, count=60).start()
    stuck_timer_long = Timer(180, count=180).start()
    stuck_long_wait_list = ["BATTLE_STATUS_S", "PAUSE", "LOGIN_CHECK"]

    def __init__(self, *args, **kwargs):
        for trial in range(4):
            try:
                super().__init__(*args, **kwargs)
                break
            except EmulatorNotRunningError as e:
                if trial >= 3:
                    logger.critical("Failed to start emulator after 3 trial")
                    raise RequestHumanTakeover from e
                # 尝试启动模拟器。
                if self.emulator_instance is not None:
                    self.emulator_start()
                else:
                    logger.critical(
                        f'No emulator with serial "{self.config.Emulator_Serial}" found, please set a correct serial'
                    )
                    raise RequestHumanTakeover from e

        # 自动补全模拟器信息。
        if IS_WINDOWS and self.config.EmulatorInfo_Emulator == "auto":
            _ = self.emulator_instance

        self.method_check()
        self.screenshot_interval_set()

        # 提前初始化 minitouch，避免第一次点击时才安装服务。
        if self.config.is_actual_task and self.config.Emulator_ControlMethod == "minitouch":
            self.early_minitouch_init()

    def run_simple_screenshot_benchmark(self):
        """
        固定使用 nemu_ipc，并保留旧入口给调用方兼容。
        """
        logger.info("run_simple_screenshot_benchmark")
        # 先确认分辨率，再固定使用 nemu_ipc。
        self.resolution_check_uiautomator2()
        with self.config.multi_set():
            self.config.Emulator_ScreenshotMethod = "nemu_ipc"

    def method_check(self):
        """
        检查当前个人版保留的截图和控制方案。
        """
        if self.config.Emulator_ScreenshotMethod != "nemu_ipc":
            logger.warning("当前个人版只保留截图方案 nemu_ipc，已自动改为 nemu_ipc")
            self.config.Emulator_ScreenshotMethod = "nemu_ipc"
        if self.config.Emulator_ControlMethod != "minitouch":
            logger.warning("当前个人版只保留控制方案 minitouch，已自动改为 minitouch")
            self.config.Emulator_ControlMethod = "minitouch"

        if not IS_WINDOWS:
            logger.critical("nemu_ipc 仅支持 Windows")
            raise RequestHumanTakeover
        if not (self.is_emulator and self.is_mumu_family):
            logger.critical("当前个人版只保留 MuMu + nemu_ipc 运行路径")
            raise RequestHumanTakeover

    def handle_night_commission(self, daily_trigger="21:00", threshold=30):
        """
        Args:
            daily_trigger (int): Time for commission refresh.
            threshold (int): Seconds around refresh time.

        Returns:
            bool: If handled.
        """
        update = get_server_next_update(daily_trigger=daily_trigger)
        now = datetime.now()
        diff = (update.timestamp() - now.timestamp()) % 86400
        if threshold < diff < 86400 - threshold:
            return False

        if GET_MISSION.match(self.image, offset=True):
            logger.info("Night commission appear.")
            self.click(GET_MISSION)
            return True

        return False

    def screenshot(self):
        """
        Returns:
            np.ndarray:
        """
        self.stuck_record_check()

        super().screenshot()

        if self.handle_night_commission():
            super().screenshot()

        return self.image

    def dump_hierarchy(self) -> etree._Element:
        self.stuck_record_check()
        return super().dump_hierarchy()

    def release_during_wait(self):
        if self.config.Emulator_ScreenshotMethod == "nemu_ipc":
            self.nemu_ipc_release()

    def get_orientation(self):
        """
        Callbacks when orientation changed.
        """
        return super().get_orientation()

    def stuck_record_add(self, button):
        self.detect_record.add(str(button))

    def stuck_record_clear(self):
        self.detect_record = set()
        self.stuck_timer.reset()
        self.stuck_timer_long.reset()

    def stuck_record_check(self):
        """
        Raises:
            GameStuckError:
        """
        reached = self.stuck_timer.reached()
        reached_long = self.stuck_timer_long.reached()

        if not reached:
            return False
        if not reached_long:
            for button in self.stuck_long_wait_list:
                if button in self.detect_record:
                    return False

        show_function_call()
        logger.warning("Wait too long")
        logger.warning(f"Waiting for {self.detect_record}")
        self.stuck_record_clear()

        if self.app_is_running():
            raise GameStuckError("Wait too long")
        raise GameNotRunningError("Game died")

    def handle_control_check(self, button):
        self.stuck_record_clear()
        self.click_record_add(button)
        self.click_record_check()

    def click_record_add(self, button):
        self.click_record.append(str(button))

    def click_record_clear(self):
        self.click_record.clear()

    def click_record_remove(self, button):
        """
        Remove a button from `click_record`

        Args:
            button (Button):

        Returns:
            int: Number of button removed
        """
        removed = 0
        for _ in range(self.click_record.maxlen):
            try:
                self.click_record.remove(str(button))
                removed += 1
            except ValueError:
                # Value not in queue
                break

        return removed

    def click_record_check(self):
        """
        Raises:
            GameTooManyClickError:
        """
        count = collections.Counter(self.click_record).most_common(2)
        if count[0][1] >= 12:
            show_function_call()
            logger.warning(f"Too many click for a button: {count[0][0]}")
            logger.warning(f"History click: {[str(prev) for prev in self.click_record]}")
            self.click_record_clear()
            raise GameTooManyClickError(f"Too many click for a button: {count[0][0]}")
        if len(count) >= 2 and count[0][1] >= 6 and count[1][1] >= 6:
            show_function_call()
            logger.warning(f"Too many click between 2 buttons: {count[0][0]}, {count[1][0]}")
            logger.warning(f"History click: {[str(prev) for prev in self.click_record]}")
            self.click_record_clear()
            raise GameTooManyClickError(f"Too many click between 2 buttons: {count[0][0]}, {count[1][0]}")

    def disable_stuck_detection(self):
        """
        Disable stuck detection and its handler. Usually uses in semi auto and debugging.
        """
        logger.info("Disable stuck detection")

        def empty_function(*_args, **_kwargs):
            return False

        self.click_record_check = empty_function
        self.stuck_record_check = empty_function

    def app_start(self):
        if not self.config.Error_HandleError:
            logger.critical("No app stop/start, because HandleError disabled")
            logger.critical("Please enable Alas.Error.HandleError or manually login to AzurLane")
            raise RequestHumanTakeover
        super().app_start()
        self.stuck_record_clear()
        self.click_record_clear()

    def app_stop(self):
        if not self.config.Error_HandleError:
            logger.critical("No app stop/start, because HandleError disabled")
            logger.critical("Please enable Alas.Error.HandleError or manually login to AzurLane")
            raise RequestHumanTakeover
        super().app_stop()
        self.stuck_record_clear()
        self.click_record_clear()
