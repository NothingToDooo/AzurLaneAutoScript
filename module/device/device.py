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
from module.device.platform.emulator_base import EmulatorBase
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
    from module.device.platform.emulator_base import EmulatorInstanceBase, EmulatorManagerBase


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


class Device(Screenshot, Control, Connection):  # ruff:ignore[too-many-public-methods] - 设备服务门面。
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
                if self.emulator_instance is not None:
                    self.emulator_start()
                else:
                    logger.critical(
                        f'No emulator with serial "{self.config.Emulator_Serial}" found, please set a correct serial'
                    )
                    raise HumanTakeoverRequiredError from e

        self.method_check()
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
    def emulator_manager(self) -> EmulatorManagerBase:
        return self.mumu_runtime.emulator_manager

    @property
    def emulator_instance(self) -> EmulatorInstanceBase | None:
        return self.mumu_runtime.emulator_instance

    @emulator_instance.setter
    def emulator_instance(self, value: EmulatorInstanceBase | None) -> None:
        self.mumu_runtime.__dict__["emulator_instance"] = value

    def find_emulator_instance(self, serial: str) -> EmulatorInstanceBase | None:
        return self.mumu_runtime.find_emulator_instance(serial)

    def emulator_start(self) -> bool:
        return self.mumu_runtime.emulator_start()

    def emulator_stop(self) -> bool:
        return self.mumu_runtime.emulator_stop()

    def emulator_start_watch(self) -> bool:
        return self.mumu_runtime.emulator_start_watch()

    def check_mumu_app_keep_alive(self) -> bool:
        return self.mumu_runtime.check_mumu_app_keep_alive()

    def check_mumu_bridge_network(self) -> bool:
        return self.mumu_runtime.check_mumu_bridge_network()

    def _check_after_connected(self) -> None:
        self.mumu_runtime.check_after_connected()

    def _diagnose_adb_connect_refused(self) -> None:
        self.mumu_runtime.diagnose_adb_connect_refused()

    def screenshot_nemu_ipc(self) -> ImageArray:
        return self.capture.screenshot()

    def nemu_ipc_release(self) -> None:
        self.capture.release()

    def app_current(self) -> str:
        return self.app_controller.current()

    def app_is_running(self) -> bool:
        return self.app_controller.is_running()

    def _app_start_service(self) -> None:
        return self.app_controller.start()

    def _app_stop_service(self) -> None:
        return self.app_controller.stop()

    def method_check(self) -> None:
        instance = self.emulator_instance
        if instance is None or instance.type != EmulatorBase.MuMuPlayer12:
            logger.critical("当前个人版只保留 MuMu + nemu_ipc 截图 + minitouch 控制，当前需要 MuMu12 实例")
            raise HumanTakeoverRequiredError

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

    def release_during_wait(self) -> None:
        self.capture.release()

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

    def click_record_remove(self, button: ButtonTarget | str) -> int:
        """移除所有匹配记录并返回移除数量。"""
        removed = 0
        maxlen = self.click_record.maxlen
        limit = maxlen if maxlen is not None else len(self.click_record)
        for _ in range(limit):
            try:
                self.click_record.remove(str(button))
                removed += 1
            except ValueError:
                break

        return removed

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
