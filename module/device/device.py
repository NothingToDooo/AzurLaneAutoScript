import collections
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from module.base.timer import Timer
from module.config.utils import get_server_next_update
from module.device.connection import Connection
from module.device.control import Control
from module.device.runtime import DeviceRuntime
from module.device.screenshot import Screenshot
from module.exception import (
    EmulatorNotRunningError,
    GameNotRunningError,
    GameStuckError,
    GameTooManyClickError,
    HumanTakeoverRequiredError,
)
from module.handler.assets import GET_MISSION
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.type_alias import ImageArray
    from module.config.config import AzurLaneConfig
    from module.device.contracts import AppControllerService, CaptureService, ControllerService, MumuRuntimeService
    from module.device.control import ButtonTarget
    from module.device.mumu_instance import MuMuInstance


def show_function_call() -> None:
    stack = traceback.extract_stack()
    func_list = []
    for row in stack:
        filename, line_number, function_name, _ = row
        filename = Path(filename).name
        func_list.append([filename, str(line_number), function_name])
    max_filename = max(len(row[0]) for row in func_list)
    max_linenum = max(len(row[1]) for row in func_list) + 1

    def format_(file: str, line: str, func: str) -> str:
        file = file.rjust(max_filename, " ")
        line = f"L{line}".rjust(max_linenum, " ")
        if not func.startswith("<"):
            func = f"{func}()"
        return f"{file} {line} {func}"

    func_list = [f"\n{format_(*row)}" for row in func_list]
    logger.info("Function calls:" + "".join(func_list))


class Device(Screenshot, Control, Connection):
    stuck_long_wait_list: ClassVar[tuple[str, ...]] = ("BATTLE_STATUS_S", "PAUSE", "LOGIN_CHECK")

    def __init__(self, config: AzurLaneConfig) -> None:
        self.detect_record: set[str] = set()
        self.click_record: collections.deque[str] = collections.deque(maxlen=15)
        self.stuck_detection_enabled = True
        self.stuck_timer = Timer(60, count=60).start()
        self.stuck_timer_long = Timer(180, count=180).start()
        self._init_screenshot_state()
        self._runtime = DeviceRuntime.create(self)

        for trial in range(4):
            try:
                super().__init__(config)
                break
            except EmulatorNotRunningError as e:
                if trial >= 3:
                    logger.critical("Failed to start emulator after 3 trial")
                    raise HumanTakeoverRequiredError from e
                self.emulator_start()

        self.screenshot_interval_set()

    @property
    def runtime(self) -> DeviceRuntime:
        return self._runtime

    @property
    def mumu_runtime(self) -> MumuRuntimeService:
        return self.runtime.mumu_runtime

    @property
    def capture(self) -> CaptureService:
        return self.runtime.capture

    @property
    def controller(self) -> ControllerService:
        return self.runtime.controller

    @property
    def app_controller(self) -> AppControllerService:
        return self.runtime.app_controller

    @property
    def emulator_instance(self) -> MuMuInstance:
        return self.mumu_runtime.emulator_instance

    def emulator_start(self) -> bool:
        return self.mumu_runtime.emulator_start()

    def _check_after_connected(self) -> None:
        self.mumu_runtime.check_after_connected()

    def _diagnose_adb_connect_refused(self) -> None:
        self.mumu_runtime.diagnose_adb_connect_refused()

    def screenshot_nemu_ipc(self) -> ImageArray:
        return self.capture.screenshot()

    def app_is_running(self) -> bool:
        return self.app_controller.is_running()

    def _app_start_service(self) -> None:
        return self.app_controller.start()

    def _app_stop_service(self) -> None:
        return self.app_controller.stop()

    def handle_night_commission(self, daily_trigger: str = "21:00", threshold: int = 30) -> bool:
        """仅在 daily_trigger 前后 threshold 秒内处理夜间委托。"""
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

    def screenshot(self) -> ImageArray:
        self.stuck_record_check()

        super().screenshot()

        if self.handle_night_commission():
            super().screenshot()

        return self.image

    def get_orientation(self) -> int:
        """屏幕方向变化时触发底层回调。"""
        return super().get_orientation()

    def stuck_record_add(self, button: ButtonTarget | str) -> None:
        self.detect_record.add(str(button))

    def stuck_record_clear(self) -> None:
        self.detect_record = set()
        self.stuck_timer.reset()
        self.stuck_timer_long.reset()

    def stuck_record_check(self) -> bool:
        """检测到长时间无进展时抛出 GameStuckError。"""
        if not self.stuck_detection_enabled:
            return False

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
            message = "Wait too long"
            raise GameStuckError(message)
        message = "Game died"
        raise GameNotRunningError(message)

    def handle_control_check(self, button: ButtonTarget | str) -> None:
        self.stuck_record_clear()
        self.click_record_add(button)
        self.click_record_check()

    def click_record_add(self, button: ButtonTarget | str) -> None:
        self.click_record.append(str(button))

    def click_record_clear(self) -> None:
        self.click_record.clear()

    def click_record_check(self) -> bool:
        """点击模式异常重复时抛出 GameTooManyClickError。"""
        if not self.stuck_detection_enabled:
            return False

        count = collections.Counter(self.click_record).most_common(2)
        if not count:
            return False
        if count[0][1] >= 12:
            show_function_call()
            logger.warning(f"Too many click for a button: {count[0][0]}")
            logger.warning(f"History click: {[str(prev) for prev in self.click_record]}")
            self.click_record_clear()
            message = f"Too many click for a button: {count[0][0]}"
            raise GameTooManyClickError(message)
        if len(count) >= 2 and count[0][1] >= 6 and count[1][1] >= 6:
            show_function_call()
            logger.warning(f"Too many click between 2 buttons: {count[0][0]}, {count[1][0]}")
            logger.warning(f"History click: {[str(prev) for prev in self.click_record]}")
            self.click_record_clear()
            message = f"Too many click between 2 buttons: {count[0][0]}, {count[1][0]}"
            raise GameTooManyClickError(message)
        return False

    @contextmanager
    def suspend_stuck_detection(self) -> Iterator[None]:
        """在当前操作内暂停卡死检测，结束后恢复原状态。"""
        was_enabled = self.stuck_detection_enabled
        if was_enabled:
            logger.info("Disable stuck detection")
            self.stuck_detection_enabled = False
        try:
            yield
        finally:
            if was_enabled:
                self.stuck_record_clear()
                self.click_record_clear()
            self.stuck_detection_enabled = was_enabled
            if was_enabled:
                logger.info("Enable stuck detection")

    def app_start(self) -> None:
        if not self.config.Error_HandleError:
            logger.critical("No app stop/start, because HandleError disabled")
            logger.critical("Please enable Alas.Error.HandleError or manually login to AzurLane")
            raise HumanTakeoverRequiredError
        result = self._app_start_service()
        self.stuck_record_clear()
        self.click_record_clear()
        return result

    def app_stop(self) -> None:
        if not self.config.Error_HandleError:
            logger.critical("No app stop/start, because HandleError disabled")
            logger.critical("Please enable Alas.Error.HandleError or manually login to AzurLane")
            raise HumanTakeoverRequiredError
        result = self._app_stop_service()
        self.stuck_record_clear()
        self.click_record_clear()
        return result
