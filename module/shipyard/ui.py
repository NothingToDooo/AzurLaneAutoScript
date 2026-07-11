from dataclasses import dataclass

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import area_pad
from module.campaign.campaign_status import OCR_COIN
from module.combat.assets import GET_SHIP
from module.handler.assets import LOGIN_ANNOUNCE
from module.logger import logger
from module.shipyard.assets import (
    SHIPYARD_CONFIRM_DEV,
    SHIPYARD_CONFIRM_FATE,
    SHIPYARD_GO_FATE,
    SHIPYARD_IN_DEV,
    SHIPYARD_IN_FATE,
    SHIPYARD_LEVEL_NOT_ENOUGH_DEV,
    SHIPYARD_LEVEL_NOT_ENOUGH_FATE,
    SHIPYARD_MINUS_DEV,
    SHIPYARD_MINUS_FATE,
    SHIPYARD_PLUS_DEV,
    SHIPYARD_PLUS_FATE,
    SHIPYARD_PROGRESS_DEV,
    SHIPYARD_PROGRESS_FATE,
    SHIPYARD_RESEARCH_COMPLETE,
    SHIPYARD_RESEARCH_IN_PROGRESS,
    SHIPYARD_RESEARCH_INCOMPLETE,
    SHIPYARD_SERIES_SELECT_CHECK,
    SHIPYARD_SERIES_SELECT_ENTER,
)
from module.shipyard.ui_globals import (
    MAIN_OCR_COIN,
    OCR_SHIPYARD_BP_COUNT_GRID,
    OCR_SHIPYARD_TOTAL_DEV,
    OCR_SHIPYARD_TOTAL_FATE,
    SHIPYARD_BP_COUNT_GRID,
    SHIPYARD_FACE_GRID,
    SHIPYARD_SERIES_GRID,
)
from module.ui.assets import SHIPYARD_CHECK
from module.ui.navbar import Navbar, NavbarColorRule, NavbarTarget, NavbarVisualRules
from module.ui.page import page_main_white
from module.ui.ui import UI

SHIPYARD_TOTAL_OCR = {
    "DEV": OCR_SHIPYARD_TOTAL_DEV,
    "FATE": OCR_SHIPYARD_TOTAL_FATE,
}
SHIPYARD_MINUS_BUTTONS = {
    "DEV": SHIPYARD_MINUS_DEV,
    "FATE": SHIPYARD_MINUS_FATE,
}
SHIPYARD_PLUS_BUTTONS = {
    "DEV": SHIPYARD_PLUS_DEV,
    "FATE": SHIPYARD_PLUS_FATE,
}
SHIPYARD_CONFIRM_BUTTONS = {
    "DEV": SHIPYARD_CONFIRM_DEV,
    "FATE": SHIPYARD_CONFIRM_FATE,
}


@dataclass(slots=True)
class _ShipyardBuyConfirmState:
    button: object
    ocr_timer: Timer
    confirm_timer: Timer
    success: bool = False


class ShipyardNavbar(Navbar):
    def is_button_active(self, button, main):
        active_blue = main.image_color_count(button, color=(33, 113, 222), threshold=221, count=400)
        odin_shoulder = main.image_color_count(button, color=(41, 85, 165), threshold=221, count=400)
        return active_blue or odin_shoulder


class ShipyardUI(UI):
    def _shipyard_cannot_strengthen(self):
        if (
            self.appear(SHIPYARD_PROGRESS_DEV, offset=(20, 20))
            or self.appear(SHIPYARD_PROGRESS_FATE, offset=(20, 20))
            or self.appear(SHIPYARD_LEVEL_NOT_ENOUGH_FATE, offset=(20, 20))
            or self.appear(SHIPYARD_LEVEL_NOT_ENOUGH_DEV, offset=(20, 20))
        ):
            logger.info("Ship at full strength for current level, no more BPs can be consumed")
            return True
        return False

    def _shipyard_get_append(self):
        """返回当前界面的 FATE 或 DEV 后缀。"""
        if self.appear(SHIPYARD_IN_FATE, offset=(20, 20)):
            return "FATE"
        return "DEV"

    def _shipyard_get_total(self):
        """按当前 DEV/FATE 布局返回加号、减号和 OCR 数量。"""
        # 这里的游戏 UI 很乱，DEV/FATE 和 MAX 按钮组合都会改变布局。
        # 有 MAX 按钮时形态类似：
        # | - |   0   | + | | MAX |
        # 没有 MAX 按钮时形态类似：
        # | - |       0       | + |
        # 因此先检测当前模式，再生成新的 OCR 区域。
        append = self._shipyard_get_append()
        ocr = SHIPYARD_TOTAL_OCR[append]
        minus = SHIPYARD_MINUS_BUTTONS[append]
        plus = SHIPYARD_PLUS_BUTTONS[append]
        self.wait_until_appear(minus, offset=(20, 20), skip_first_screenshot=True)
        self.wait_until_appear(plus, offset=(150, 20), skip_first_screenshot=True)
        area = ocr.buttons[0]
        ocr.buttons = [(minus.button[2] + 3, area[1], plus.button[0] - 3, area[3])]

        return plus, minus, ocr.ocr(self.device.image)

    def _shipyard_ensure_index(self, count, skip_first_screenshot=True):
        """尽量把数量调到 count，返回界面无法消耗的剩余蓝图数。"""
        if count < 0:
            logger.warning("_shipyard_ensure_index --> Non-positive 'count' cannot continue")
            return None

        current = diff = 0
        for _ in range(3):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            plus, minus, current = self._shipyard_get_total()
            if current == count:
                logger.info(f"Capable of consuming all {count} BPs")
                return 0

            diff = count - current
            button = plus if diff > 0 else minus
            self.device.multi_click(button, n=diff, interval=(0.3, 0.5))
            self.device.sleep((0.3, 0.5))

        logger.info(f"Current interface does not allow consumption of {count} BPs\n")
        logger.info(f"Capable of consuming at most {current} of the {count} BPs")
        return diff

    def _shipyard_get_bp_count(self, index=0):
        """OCR 从 1 开始的舰船索引对应蓝图数；索引无效时返回 -1。"""
        if index <= 0 or index > len(SHIPYARD_BP_COUNT_GRID.buttons):
            logger.warning(f"Cannot parse for count from index {index}")
            return -1

        result = OCR_SHIPYARD_BP_COUNT_GRID.ocr(self.device.image)

        return result[index - 1]

    def _shipyard_in_ui(self):
        """返回当前是否位于船坞开发界面。"""
        return (
            self.appear(SHIPYARD_CHECK, offset=(20, 20))
            or self.appear(SHIPYARD_IN_DEV, offset=(20, 20))
            or self.appear(SHIPYARD_IN_FATE, offset=(20, 20))
        )

    def _shipyard_set_series(self, series=1, skip_first_screenshot=True):
        """切换到指定科研系列；索引越界时返回 False。"""
        if series <= 0 or series > len(SHIPYARD_SERIES_GRID.buttons):
            logger.warning(f"Research Series {series} is not selectable")
            return False

        self.ui_click(
            SHIPYARD_SERIES_SELECT_ENTER,
            appear_button=self._shipyard_in_ui,
            check_button=SHIPYARD_SERIES_SELECT_CHECK,
            skip_first_screenshot=skip_first_screenshot,
        )
        series_button = SHIPYARD_SERIES_GRID.buttons[series - 1]
        self.ui_click(
            series_button,
            appear_button=SHIPYARD_SERIES_SELECT_CHECK,
            check_button=self._shipyard_in_ui,
            skip_first_screenshot=skip_first_screenshot,
        )

        return True

    @cached_property
    def _shipyard_bottom_navbar(self):
        """系列内舰船导航位置会随科研进度变化。"""
        return ShipyardNavbar(
            grids=SHIPYARD_FACE_GRID,
            visual=NavbarVisualRules(inactive=NavbarColorRule(color=(49, 60, 82), threshold=221, count=50)),
        )

    def shipyard_bottom_navbar_ensure(self, left=None, right=None, skip_first_screenshot=True):
        """按左右索引切换舰船并等待延迟资源加载完成。"""
        if left is None and right is not None:
            left = right
            right = None
        if left is not None and (left <= 0 or left > len(SHIPYARD_FACE_GRID.buttons)):
            logger.warning(f"Index for bottom Navbar {left} is not selectable")
            return False

        ensured = False
        if self._shipyard_bottom_navbar.set(
            self, NavbarTarget(left=left, right=right), skip_first_screenshot=skip_first_screenshot
        ):
            ensured = True

        confirm_timer = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._shipyard_in_ui():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        return ensured

    def shipyard_set_focus(self, series=1, index=1, skip_first_screenshot=True):
        """聚焦系列和舰船索引；第三系列起仅支持 1～5。"""
        if series > 2 and index > 5:
            logger.warning(f"Research Series {series} is limited to indexes 1-5, cannot set focus to index {index}")
            return False
        return self._shipyard_set_series(series, skip_first_screenshot) and self.shipyard_bottom_navbar_ensure(
            left=index, skip_first_screenshot=skip_first_screenshot
        )

    def _shipyard_get_ship(self, skip_first_screenshot=True):
        """处理科研完成到获得舰船的过渡页面。"""
        confirm_timer = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(SHIPYARD_RESEARCH_COMPLETE, interval=1, offset=(20, 20)):
                confirm_timer.reset()
                continue

            if self.story_skip():
                confirm_timer.reset()
                continue

            if self.appear_then_click(GET_SHIP, interval=1):
                confirm_timer.reset()
                continue

            if self.handle_popup_confirm("LOCK_SHIP"):
                confirm_timer.reset()
                continue

            if self.appear(SHIPYARD_CONFIRM_DEV, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def _shipyard_buy_confirm(self, text, skip_first_screenshot=True):
        append = self._shipyard_get_append()
        state = _ShipyardBuyConfirmState(
            button=SHIPYARD_CONFIRM_BUTTONS[append],
            ocr_timer=Timer(10, count=10).start(),
            confirm_timer=Timer(1, count=2).start(),
        )
        self.interval_clear(state.button)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._handle_shipyard_confirm_ocr_check(state):
                continue
            if self.appear_then_click(state.button, offset=(20, 20), interval=3):
                continue
            if self._handle_shipyard_confirm_popups(text, state):
                continue
            if self._shipyard_buy_confirm_finished(state):
                break

    def _handle_shipyard_confirm_ocr_check(self, state):
        if not state.ocr_timer.reached():
            return False

        logger.warning("Failed to detect for normal exit routine, resort to OCR check")
        _, _, current = self._shipyard_get_total()
        if not current:
            logger.info("Confirm action has completed, setting flag for exit")
            self.interval_reset(state.button)
            state.success = True
        state.ocr_timer.reset()
        return True

    def _handle_shipyard_confirm_popups(self, text, state):
        if self.handle_popup_confirm(text):
            self._reset_shipyard_confirm_timers(state)
            return True
        if self.story_skip():
            self._mark_shipyard_confirm_success(state)
            return True
        if self.handle_info_bar():
            self._mark_shipyard_confirm_success(state)
            return True
        # 舰船 DEV 完成并进入 FATE 时，会出现 FATE 信息弹窗。
        if self.appear_then_click(LOGIN_ANNOUNCE, offset=area_pad((-300, 127, -300, 127), pad=-50), interval=3):
            self._mark_shipyard_confirm_success(state)
            return True
        return False

    def _mark_shipyard_confirm_success(self, state) -> None:
        self.interval_reset(state.button)
        state.success = True
        self._reset_shipyard_confirm_timers(state)

    def _reset_shipyard_confirm_timers(self, state) -> None:
        state.ocr_timer.reset()
        state.confirm_timer.reset()

    def _shipyard_buy_confirm_finished(self, state):
        if state.success and self._shipyard_in_ui():
            return state.confirm_timer.reached()
        state.confirm_timer.reset()
        return False

    def _shipyard_buy_enter(self):
        if self.appear(SHIPYARD_RESEARCH_INCOMPLETE, offset=(20, 20)) or self.appear(
            SHIPYARD_RESEARCH_IN_PROGRESS, offset=(20, 20)
        ):
            logger.warning("Cannot enter buy interface, focused ship has not yet been fully researched")
            return False

        if self.appear(SHIPYARD_RESEARCH_COMPLETE, offset=(20, 20)):
            self._shipyard_get_ship()

        if self.appear(SHIPYARD_GO_FATE, offset=(20, 20)):
            self.device.click(SHIPYARD_GO_FATE)
            self.wait_until_appear(SHIPYARD_IN_FATE, offset=(20, 20))

        return True

    def _shipyard_get_coin(self):
        if self.ui_page_appear(page_main_white):
            return MAIN_OCR_COIN.ocr(self.device.image)
        return OCR_COIN.ocr(self.device.image)
