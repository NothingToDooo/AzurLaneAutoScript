from typing import TYPE_CHECKING

from module.awaken import assets as awaken_assets
from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import Digit
from module.retire.assets import DOCK_EMPTY
from module.retire.dock import Dock
from module.ui.assets import BACK_ARROW
from module.ui.page import page_dock, page_main

if TYPE_CHECKING:
    from module.base.button import Button

UNEXPECTED_AWAKEN_COST_RESULT_TEMPLATE = "Unexpected _get_awaken_cost result: {result}"
UNEXPECTED_AWAKEN_ONCE_RESULT_TEMPLATE = "Unexpected awaken_once result: {result}"
UNEXPECTED_AWAKEN_SHIP_RESULT_TEMPLATE = "Unexpected awaken_ship result: {result}"
UNKNOWN_AWAKEN_LEVEL_CAP_TEMPLATE = "Unknown Awaken_LevelCap={level_cap}"


class ShipLevel(Digit):
    def after_process(self, result):
        result = super().after_process(result)
        if result < 100 or result > 125:
            logger.warning("Unexpected ship level")
            result = 0
        return result


class Awaken(Dock):
    def _get_button_state(self, button: Button):
        """返回资源是否充足；当前唤醒不需要该资源时返回 None。"""
        # COST_ARRAY 缺失时，COST_COIN 和 COST_CHIP 会右移 54px。
        if button.match(self.device.image, offset=(75, 20)):
            # 资源不足的红字位于按钮下方 60px。
            area = button.button
            area = (area[0], area[3], area[2], area[3] + 60)
            return not self.image_color_count(area, color=(214, 53, 33), threshold=180, count=16)
        return None

    def _get_awaken_cost(self, use_array=False):
        """返回资源是否充足，或 unexpected_array、invalid 识别状态。"""
        coin = self._get_button_state(awaken_assets.COST_COIN)
        chip = self._get_button_state(awaken_assets.COST_CHIP)
        array = self._get_button_state(awaken_assets.COST_ARRAY)

        logger.attr("AwakenCost", {"coin": coin, "chip": chip, "array": array})

        def is_right_moved(button):
            return button.button[0] - button.area[0] > 20

        if array is not None:
            if not use_array:
                logger.warning("Not going to use array but array presents")
                return "unexpected_array"
            # 如果需要心智单元 II，金币和心智单元也应该存在。
            if (
                coin is not None
                and not is_right_moved(awaken_assets.COST_COIN)
                and chip is not None
                and not is_right_moved(awaken_assets.COST_CHIP)
            ):
                result = coin and chip and array
                logger.attr("AwakenSufficient", result)
                return result
        # 如果不需要心智单元 II，金币和心智单元应同时存在且右移。
        elif (
            coin is not None
            and is_right_moved(awaken_assets.COST_COIN)
            and chip is not None
            and is_right_moved(awaken_assets.COST_CHIP)
        ):
            result = coin and chip
            logger.attr("AwakenSufficient", result)
            return result

        logger.warning("Invalid awaken cost")
        return "invalid"

    def handle_awaken_finish(self):
        return self.appear_then_click(awaken_assets.AWAKEN_FINISH, offset=(20, 20), interval=1)

    def is_in_awaken(self):
        return awaken_assets.SHIP_LEVEL_CHECK.match_luma(self.device.image, similarity=0.7)

    def awaken_popup_close(self, skip_first_screenshot=True):
        logger.info("Awaken popup close")
        self.interval_clear(awaken_assets.AWAKEN_CANCEL)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_in_awaken():
                break
            if self.appear_then_click(awaken_assets.AWAKEN_CANCEL, offset=(20, 20), interval=3):
                continue
            if self.handle_awaken_finish():
                continue

    def awaken_once(self, use_array=False, skip_first_screenshot=True):
        """在唤醒页执行一次，返回 no_exp、unexpected_array、insufficient、timeout 或 success。"""
        logger.hr("Awaken once", level=2)
        result = self._wait_awaken_confirm_button(skip_first_screenshot=skip_first_screenshot)
        if result is not None:
            return result

        result = self._wait_awaken_cost(use_array)
        if result is not None:
            return result

        return self._confirm_awaken_once()

    def _wait_awaken_confirm_button(self, skip_first_screenshot=True):
        interval = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(awaken_assets.AWAKEN_CONFIRM):
                break
            if awaken_assets.LEVEL_UP.match_luma(self.device.image):
                logger.info(f"awaken_once ended at {awaken_assets.LEVEL_UP}")
                return "no_exp"
            # 背景随机，降低相似度阈值。
            if interval.reached() and awaken_assets.AWAKENING.match_luma(self.device.image, similarity=0.7):
                self.device.click(awaken_assets.AWAKENING)
                interval.reset()
                continue

        return None

    def _wait_awaken_cost(self, use_array):
        logger.info("Get awaken cost")
        timeout = Timer(2, count=6).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            result = self._get_awaken_cost(use_array)
            if result is True:
                return None
            handled = self._handle_awaken_cost_unready(result, timeout)
            if handled is not None:
                return handled
        return None

    def _handle_awaken_cost_unready(self, result, timeout):
        if result == "unexpected_array":
            self.awaken_popup_close()
            return result
        if result is False:
            logger.info("Insufficient resources to awaken")
            self.awaken_popup_close()
            return "insufficient"
        if result != "invalid":
            message = UNEXPECTED_AWAKEN_COST_RESULT_TEMPLATE.format(result=result)
            raise ScriptError(message)

        # invalid 结果会重试，同时继续检查超时。
        if timeout.reached():
            logger.warning("Get awaken cost timeout")
            self.awaken_popup_close()
            return "timeout"
        return None

    def _confirm_awaken_once(self):
        logger.info("Awaken confirm")
        self.interval_clear(awaken_assets.AWAKEN_CONFIRM)
        # 如果经验足够到达下一次唤醒上限，唤醒弹窗可能要 10 秒才出现，点击关闭也需要约 2 秒。
        # 这里保留较长超时时间。
        timeout = Timer(30, count=30).start()
        finished = False
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            should_break, finished = self._handle_awaken_confirm_step(timeout, finished)
            if should_break:
                break

        self.device.click_record_clear()
        return "success"

    def _handle_awaken_confirm_step(self, timeout, finished):
        if timeout.reached():
            logger.warning("Awaken confirm timeout")
            self.awaken_popup_close()
            return True, finished
        if finished and self.is_in_awaken():
            logger.info("Awaken finished")
            return True, finished
        if self.appear_then_click(awaken_assets.AWAKEN_CONFIRM, offset=(20, 20), interval=3):
            return False, finished
        if self.handle_popup_confirm("AWAKEN"):
            return False, finished
        if self.handle_awaken_finish():
            return False, True
        return False, finished

    def get_ship_level(self, skip_first_screenshot=True):
        """OCR 100～125 级；识别失败时返回 0。"""
        ocr = ShipLevel(awaken_assets.OCR_SHIP_LEVEL, letter=(255, 255, 255), threshold=128, name="ShipLevel")
        timeout = Timer(2, count=4).start()
        level = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_in_awaken():
                level = ocr.ocr(self.device.image)
                if level > 0:
                    return level
            if timeout.reached():
                logger.warning("get_ship_level timeout")
                return level
        return level

    def awaken_ship(self, use_array=False, skip_first_screenshot=True):
        """在唤醒页重复唤醒至经验不足或达到 120/125 级。

        返回 level_max、insufficient、no_exp 或 timeout。
        """
        logger.hr("Awaken ship", level=1)
        logger.info(f"Awaken ship, use_array={use_array}")

        stop_level = 125 if use_array else 120

        if not skip_first_screenshot:
            self.device.screenshot()

        for _ in range(7):
            level = self.get_ship_level()
            if level > 0:
                if level >= stop_level:
                    logger.info("Awaken ship ended at stop_level")
                    return "level_max"
                result = self.awaken_once(use_array)
                if result == "success":
                    continue
                if result in ["insufficient", "no_exp"]:
                    return result
                if result == "unexpected_array":
                    # 可能只是误入唤醒确认页，重跑 awaken_once 会重新检查。
                    continue
                if result == "timeout":
                    # 获取资源超时，重试通常可以恢复。
                    continue
                message = UNEXPECTED_AWAKEN_ONCE_RESULT_TEMPLATE.format(result=result)
                raise ScriptError(message)
            return "timeout"

        logger.warning("Too many awaken trial on one ship")
        return "timeout"

    def awaken_exit(self, skip_first_screenshot=True):
        """从唤醒页退回船坞。"""
        logger.info("Awaken exit")
        interval = Timer(3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_page_appear(page_dock):
                logger.info(f"Awaken exit at {page_dock}")
                break
            if interval.reached() and self.is_in_awaken():
                logger.info(f"is_in_awaken -> {BACK_ARROW}")
                self.device.click(BACK_ARROW)
                interval.reset()
                continue
            if self.handle_awaken_finish():
                continue
            if self.appear_then_click(awaken_assets.AWAKEN_CANCEL, offset=(20, 20), interval=3):
                continue
            if self.is_in_main(interval=5):
                self.device.click(page_main.links[page_dock])
                continue

    def awaken_run(self, use_array=False, favourite=False):
        """从任意页面唤醒符合筛选的舰船，返回 insufficient、finish 或 timeout 并停在船坞。"""
        logger.hr("Awaken run", level=1)
        self.ui_ensure(page_dock)
        self.dock_favourite_set(enable=favourite, wait_loading=False)
        self.dock_sort_method_dsc_set(wait_loading=False)
        extra = ["can_awaken_plus"] if use_array else ["can_awaken"]
        self.dock_filter_set(extra=extra)

        while 1:
            if self.appear(DOCK_EMPTY, offset=(20, 20)):
                logger.info("awaken_run finished, no ships to awaken")
                result = "finish"
                break

            entered = self.dock_enter_first()
            if not entered:
                logger.info("awaken_run finished, no ships to awaken")
                result = "finish"
                break

            result = self.awaken_ship(use_array)
            self.awaken_exit()
            if result in ["no_exp", "level_max"]:
                continue
            if result == "insufficient":
                logger.info("awaken_run finished, resources exhausted")
                break
            if result == "timeout":
                logger.info(f"awaken_run finished, result={result}")
                break
            message = UNEXPECTED_AWAKEN_SHIP_RESULT_TEMPLATE.format(result=result)
            raise ScriptError(message)

        return result

    def run(self):
        favourite = self.config.Awaken_Favourite
        if self.config.Awaken_LevelCap == "level125":
            result = self.awaken_run(use_array=True, favourite=favourite)
            if result != "timeout":
                self.awaken_run(favourite=favourite)
        elif self.config.Awaken_LevelCap == "level120":
            self.awaken_run(favourite=favourite)
        else:
            message = UNKNOWN_AWAKEN_LEVEL_CAP_TEMPLATE.format(level_cap=self.config.Awaken_LevelCap)
            raise ScriptError(message)

        logger.hr("Awaken run exit", level=1)
        if favourite:
            self.dock_favourite_set(wait_loading=False)
        self.dock_filter_set(wait_loading=False)

        self.config.task_delay(server_update=True)
