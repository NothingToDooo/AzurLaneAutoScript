from dataclasses import dataclass

from module.base.timer import Timer
from module.campaign.campaign_status import OCR_COIN
from module.combat.assets import GET_SHIP
from module.exception import ScriptError
from module.gacha import assets as gacha_assets
from module.gacha.ui import GachaUI
from module.handler.assets import POPUP_CONFIRM, STORY_SKIP
from module.logger import logger
from module.ocr.ocr import Digit
from module.retire.retirement import Retirement
from module.ui.ui import UiIndexControls

RECORD_GACHA_OPTION = ("RewardRecord", "gacha")
RECORD_GACHA_SINCE = (0,)
OCR_BUILD_CUBE_COUNT = Digit(gacha_assets.BUILD_CUBE_COUNT, letter=(255, 247, 247), threshold=64)
OCR_BUILD_TICKET_COUNT = Digit(gacha_assets.BUILD_TICKET_COUNT, letter=(255, 247, 247), threshold=64)
OCR_BUILD_SUBMIT_COUNT = Digit(gacha_assets.BUILD_SUBMIT_COUNT, letter=(255, 247, 247), threshold=64)
OCR_BUILD_SUBMIT_WW_COUNT = Digit(gacha_assets.BUILD_SUBMIT_WW_COUNT, letter=(255, 247, 247), threshold=64)
GACHA_PREP_OCR_ASSET_MISSING_MESSAGE = "Failed to identify ocr asset required, cannot continue prep work"
WISHING_WELL_MANUAL_CONFIG_MESSAGE = (
    "'wishing_well' must be configured manually by user, cannot continue gacha_goto_pool"
)


@dataclass(slots=True)
class _GachaFlushState:
    confirm_timer: object
    confirm_mode: bool = True
    queue_clean: bool = True


class RewardGacha(GachaUI, Retirement):
    build_coin_count = 0
    build_cube_count = 0
    build_ticket_count = 0

    def gacha_prep(self, target, skip_first_screenshot=True):
        """从任意建造页打开提交弹窗并设置订单数；无法准备时返回 False。"""
        if not target:
            return False

        if not self.appear(gacha_assets.BUILD_SUBMIT_ORDERS) and not self.appear(gacha_assets.BUILD_SUBMIT_WW_ORDERS):
            return False

        # 用 appear 更新资产实际位置，供 ui_ensure_index 使用。
        confirm_timer = Timer(1, count=2).start()
        ocr_submit = None
        index_offset = (60, 20)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(gacha_assets.BUILD_SUBMIT_ORDERS, interval=3):
                ocr_submit = OCR_BUILD_SUBMIT_COUNT
                confirm_timer.reset()
                continue

            if self.appear_then_click(gacha_assets.BUILD_SUBMIT_WW_ORDERS, interval=3):
                ocr_submit = OCR_BUILD_SUBMIT_WW_COUNT
                confirm_timer.reset()
                continue
            # 即使 UR 兑换点已满，也继续建造。
            if self.handle_popup_confirm("GACHA_PREP"):
                confirm_timer.reset()
                continue

            if (
                self.appear(gacha_assets.BUILD_PLUS, offset=index_offset)
                and self.appear(gacha_assets.BUILD_MINUS, offset=index_offset)
                and confirm_timer.reached()
            ):
                break

        # 普通池与许愿池使用不同数量 OCR 区域。
        if ocr_submit is None:
            raise ScriptError(GACHA_PREP_OCR_ASSET_MISSING_MESSAGE)
        area = ocr_submit.buttons[0]
        ocr_submit.buttons = [
            (gacha_assets.BUILD_MINUS.button[2] + 3, area[1], gacha_assets.BUILD_PLUS.button[0] - 3, area[3])
        ]
        self.ui_ensure_index(
            target,
            UiIndexControls(
                letter=ocr_submit,
                prev_button=gacha_assets.BUILD_MINUS,
                next_button=gacha_assets.BUILD_PLUS,
            ),
            skip_first_screenshot=True,
        )

        return True

    def gacha_calculate(self, target_count, gold_cost, cube_cost):
        """按当前资源返回可提交数量，并从缓存的金币和魔方中扣除消耗。"""
        while 1:
            gold_total = gold_cost * target_count
            cube_total = cube_cost * target_count

            if not target_count:
                logger.warning("Insufficient gold and/or cubes to gacha roll")
                break

            if gold_total > self.build_coin_count or cube_total > self.build_cube_count:
                target_count -= 1
                continue

            break

        logger.info(f"Able to submit up to {target_count} build orders")
        self.build_coin_count -= gold_total
        self.build_cube_count -= cube_total
        return target_count

    def gacha_goto_pool(self, target_pool):
        """切换建造池并返回实际池名；不可用时回退 light，未配置许愿池时抛错。"""
        # 先切到 light 池。
        self.gacha_bottom_navbar_ensure(right=3, is_build=True)

        if target_pool == "wishing_well":
            if self._gacha_side_navbar.get_total(main=self) != 5:
                logger.warning("'wishing_well' is not available, default to 'light' pool")
                target_pool = "light"
            else:
                self.gacha_side_navbar_ensure(upper=2)
                if self.appear(gacha_assets.BUILD_WW_CHECK):
                    raise ScriptError(WISHING_WELL_MANUAL_CONFIG_MESSAGE)
        elif target_pool == "event":
            gacha_bottom_navbar = self._gacha_bottom_navbar(is_build=True)
            if gacha_bottom_navbar.get_total(main=self) == 3:
                logger.warning("'event' is not available, default to 'light' pool")
                target_pool = "light"
            else:
                self.gacha_bottom_navbar_ensure(left=1, is_build=True)
        elif target_pool in ["heavy", "special"]:
            if target_pool == "heavy":
                self.gacha_bottom_navbar_ensure(right=2, is_build=True)
            else:
                self.gacha_bottom_navbar_ensure(right=1, is_build=True)

        return target_pool

    def gacha_flush_queue(self, skip_first_screenshot=True):
        """清空建造队列并回到建造池选择页；船坞满时可能无法完全清空。"""
        self.gacha_side_navbar_ensure(bottom=3)

        state = _GachaFlushState(confirm_timer=Timer(1, count=2).start())
        # 清除按钮偏移，否则可能点到钻石加号或 HOME。
        STORY_SKIP.clear_offset()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._gacha_queue_already_empty(state):
                break
            if self._gacha_flush_queue_step(state):
                continue

            if self._gacha_flush_submit_ready(state):
                break

        # 许愿池不显示金币，清空后回普通池以便读取资源。
        self._gacha_leave_wishing_pool()

    def _gacha_queue_already_empty(self, state):
        if self.appear(gacha_assets.BUILD_QUEUE_EMPTY, offset=(20, 20)) and state.queue_clean:
            self.gacha_side_navbar_ensure(upper=1)
            return True

        state.queue_clean = False
        return False

    def _gacha_flush_queue_step(self, state):
        if self.appear_then_click(gacha_assets.BUILD_FINISH_ORDERS, interval=3):
            state.confirm_timer.reset()
            return True
        if self.handle_retirement():
            state.confirm_timer.reset()
            return True
        if self._gacha_handle_finish_popup(state):
            return True
        if self._gacha_handle_ship_rewards(state):
            return True
        return self._gacha_handle_finish_results(state)

    def _gacha_handle_finish_popup(self, state):
        if not self.handle_popup_confirm("FINISH_ORDERS"):
            return False

        if state.confirm_mode:
            self.device.sleep((0.5, 0.8))
            self.device.click(gacha_assets.BUILD_FINISH_ORDERS)  # 跳过动画的安全区域。
            state.confirm_mode = False
        state.confirm_timer.reset()
        return True

    def _gacha_handle_ship_rewards(self, state):
        if self.appear(GET_SHIP, interval=1):
            self.device.click(STORY_SKIP)  # 多订单时快进。
            state.confirm_timer.reset()
            return True
        return self.handle_get_items_ship()

    def _gacha_handle_finish_results(self, state):
        if not self.appear(gacha_assets.BUILD_FINISH_RESULTS, offset=(20, 150), interval=3):
            return False

        self.device.click(gacha_assets.BUILD_FINISH_ORDERS)  # 安全区域。
        state.confirm_timer.reset()
        return True

    def _gacha_flush_submit_ready(self, state):
        if not (self.appear(gacha_assets.BUILD_SUBMIT_ORDERS) or self.appear(gacha_assets.BUILD_SUBMIT_WW_ORDERS)):
            return False
        return state.confirm_timer.reached()

    def _gacha_leave_wishing_pool(self):
        if not self.appear(gacha_assets.BUILD_SUBMIT_WW_ORDERS):
            return

        logger.info("In wishing pool, go back to normal pools")
        self.gacha_side_navbar_ensure(upper=1)

    def gacha_submit(self, skip_first_screenshot=True):
        """确认提交弹窗并等待建造订单页。"""
        logger.info("Submit gacha")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(POPUP_CONFIRM, offset=(20, 80), interval=3):
                # 临时修改资产名，区分这次点击。
                POPUP_CONFIRM.name = POPUP_CONFIRM.name + "_" + "GACHA_ORDER"
                self.device.click(POPUP_CONFIRM)
                POPUP_CONFIRM.name = POPUP_CONFIRM.name[: -len("GACHA_ORDER") - 1]
                continue

            if self.appear(gacha_assets.BUILD_FINISH_ORDERS):
                break

    def gacha_run(self):
        """从任意页面提交建造订单，结束于建造页并返回是否至少成功提交一次。"""
        self.ui_goto_gacha()

        self.gacha_flush_queue()

        self.build_coin_count = OCR_COIN.ocr(self.device.image)
        self.build_cube_count = OCR_BUILD_CUBE_COUNT.ocr(self.device.image)

        actual_pool = self.gacha_goto_pool(self.config.Gacha_Pool)

        gold_cost = 600
        cube_cost = 1
        if actual_pool in ["heavy", "special", "event", "wishing_well"]:
            gold_cost = 1500
            cube_cost = 2

        # buy 依次记录使用建造券和魔方/金币的次数。
        buy = [self.config.Gacha_Amount, 0]
        if actual_pool == "event" and self.config.Gacha_UseTicket:
            if self.appear(gacha_assets.BUILD_TICKET_CHECK, offset=(30, 30)):
                self.build_ticket_count = OCR_BUILD_TICKET_COUNT.ocr(self.device.image)
            else:
                logger.info("Build ticket not detected, use cubes and coins")
        if self.config.Gacha_Amount > self.build_ticket_count:
            buy[0] = self.build_ticket_count
            buy[1] = self.gacha_calculate(self.config.Gacha_Amount - self.build_ticket_count, gold_cost, cube_cost)

        # 逐组提交 buy_count。这里不能用 handle_popup_confirm，因为这个窗口没有 POPUP_CANCEL。
        result = False
        for buy_count in buy:
            if self.gacha_prep(buy_count):
                self.gacha_submit()

                if self.config.Gacha_UseDrill:
                    self.gacha_flush_queue()
                result = True

        return result

    def run(self):
        """从任意页面执行建造任务，结束于建造页。"""
        self.gacha_run()
        self.config.task_delay(server_update=True)
