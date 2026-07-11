from module.combat.assets import GET_ITEMS_1
from module.exception import ScriptError
from module.logger import logger
from module.meowfficer import assets as meow_assets
from module.meowfficer.base import MeowfficerBase
from module.ocr.failure_store import OCR_FAILURE_STORE
from module.ocr.ocr import Digit, DigitCounter
from module.ui.assets import MEOWFFICER_GOTO_DORMMENU
from module.ui.ui import UiIndexControls

BUY_MAX = 15
BUY_PRIZE = 1500
MEOWFFICER = DigitCounter(meow_assets.OCR_MEOWFFICER, letter=(140, 113, 99), threshold=64)
MEOWFFICER_CHOOSE = Digit(meow_assets.OCR_MEOWFFICER_CHOOSE, letter=(140, 113, 99), threshold=64)
MEOWFFICER_COINS = Digit(meow_assets.OCR_MEOWFFICER_COINS, letter=(99, 69, 41), threshold=64)


def _calculate_meow_buy_count(bought, total, coins, buy_amount, overflow_th):
    """按每日基准和金币溢出阈值计算购买数；首箱免费，负阈值禁用溢出购买。"""
    today_left = max(0, total - bought)
    if today_left <= 0:
        logger.info(f"Already bought {bought}/{total} today, stopped")
        return 0

    baseline = min(max(0, buy_amount - bought), today_left)

    extra = 0
    if overflow_th >= 0 and coins > overflow_th:
        if bought == 0:
            # 首箱免费，需多计一箱才能把金币降到阈值。
            extra = -(-(coins - overflow_th + BUY_PRIZE) // BUY_PRIZE)
        else:
            extra = -(-(coins - overflow_th) // BUY_PRIZE)
        extra = min(extra, today_left - baseline)
        extra = max(0, extra)

    count = baseline + extra

    # 可购买量仍受金币约束，首箱不计费用。
    free = 1 if bought == 0 else 0
    affordable = coins // BUY_PRIZE + free
    if count > affordable:
        logger.info(f"Current coins only afford to buy {affordable}")
        count = affordable

    logger.info(
        f"Meowfficer buy plan: count={count}, baseline={baseline}, "
        f"overflow={extra}, bought={bought}/{total}, coins={coins}"
    )
    return count


class MeowfficerBuy(MeowfficerBase):
    def meow_get_buy_count(self, buy_amount, overflow_th):
        """在指挥喵主页 OCR 剩余次数和金币，返回本次购买的 0～15 箱。"""
        failure_store = OCR_FAILURE_STORE if self.config.Error_SaveError else None
        for _ in self.loop(timeout=2):
            counter_result = MEOWFFICER.recognize(
                self.device.image,
                expected_total=BUY_MAX,
                failure_store=failure_store,
            )
            if not counter_result.valid or counter_result.value is None:
                continue
            remain, bought, total = counter_result.value

            coins_result = MEOWFFICER_COINS.recognize(self.device.image, failure_store=failure_store)
            if isinstance(coins_result, list):
                message = "MEOWFFICER_COINS 必须使用单个 OCR 区域"
                raise ScriptError(message)
            if not coins_result.valid or coins_result.value is None:
                continue
            coins = coins_result.value
            break
        else:
            logger.warning("Failed to get meowfficer buy status")
            return 0

        logger.attr("Meowfficer_remain", remain)
        logger.attr("Meowfficer_coins", coins)

        return _calculate_meow_buy_count(bought, total, coins, buy_amount, overflow_th)

    def meow_choose(self, count) -> None:
        """从主页进入购买页，并把数量设为 1～15。"""
        self.meow_enter(meow_assets.MEOWFFICER_BUY_ENTER, check_button=meow_assets.MEOWFFICER_BUY)

        # info_bar 可能遮挡 OCR_MEOWFFICER_CHOOSE，
        # 导致 OCR_MEOWFFICER_CHOOSE 被识别为 0 并触发额外点击。
        # info_bar 通常来自上一个后宅任务或指挥喵后宅。
        self.handle_info_bar()

        self.ui_ensure_index(
            count,
            UiIndexControls(
                letter=MEOWFFICER_CHOOSE,
                prev_button=meow_assets.MEOWFFICER_BUY_PREV,
                next_button=meow_assets.MEOWFFICER_BUY_NEXT,
            ),
            skip_first_screenshot=True,
        )

    def meow_confirm(self, skip_first_screenshot=True) -> None:
        """从购买页确认并返回指挥喵主页。"""
        # 这里用简单点击，避免重复点击 MEOWFFICER_BUY。
        logger.hr("Meow confirm")
        executed = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(meow_assets.MEOWFFICER_BUY, offset=(20, 20), interval=3):
                if executed:
                    self.device.click(MEOWFFICER_GOTO_DORMMENU)
                else:
                    self.device.click(meow_assets.MEOWFFICER_BUY)
                continue
            if self.handle_meow_popup_confirm():
                executed = True
                continue
            if self.appear_then_click(meow_assets.MEOWFFICER_BUY_SKIP, interval=3):
                executed = True
                continue
            if self.appear(GET_ITEMS_1, offset=5, interval=3):
                self.device.click(meow_assets.MEOWFFICER_BUY_SKIP)
                self.interval_clear(meow_assets.MEOWFFICER_BUY)
                executed = True
                continue
            # 少见情况下这里会弹出 MEOWFFICER_INFO。
            if self.meow_additional():
                continue

            if self.match_template_color(meow_assets.MEOWFFICER_BUY_ENTER, offset=(20, 20)):
                break

    def meow_buy(self) -> None:
        """在指挥喵主页按每日基准和可选溢出策略购买猫箱。"""
        logger.hr("Meowfficer buy", level=1)

        buy_amount = self.config.Meowfficer_BuyAmount
        buy_amount = max(min(buy_amount, 15), 1)
        overflow_th = self.config.Meowfficer_OverflowCoins

        count = self.meow_get_buy_count(buy_amount, overflow_th)
        if count <= 0:
            return
        self.meow_choose(count)
        self.meow_confirm()

        logger.warning("Too many trial in meowfficer buy, stopped.")
