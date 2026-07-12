from calendar import day_name
from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.campaign.campaign_status import CampaignStatus
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.config.utils import get_server_weekday
from module.freebies.assets import BUY_CONFIRM, FREE_SUPPLY_PACK
from module.logger import logger
from module.ocr.ocr import Digit
from module.shop.assets import SHOP_OCR_OIL, SHOP_OCR_OIL_CHECK
from module.ui.page import page_shop, page_supply_pack

if TYPE_CHECKING:
    from module.base.button import Button


class SupplyPack(CampaignStatus):
    def _clear_supply_pack_intervals(self, supply_pack: Button) -> None:
        for asset in [GET_ITEMS_1, GET_ITEMS_2, supply_pack, BUY_CONFIRM]:
            self.interval_clear(asset)

    def _handle_visible_supply_pack(
        self, supply_pack: Button, click_count: int, confirm_timer: Timer
    ) -> tuple[int, bool, bool]:
        if not self.appear(supply_pack, offset=(200, 20), interval=3):
            return click_count, False, False
        if click_count >= 3:
            logger.warning(f"Failed to buy {supply_pack} after 3 trail, probably reached resource limit, skip")
            return click_count, True, True

        self.device.click(supply_pack)
        confirm_timer.reset()
        return click_count + 1, True, False

    def _handle_supply_pack_reward_popup(self, confirm_timer: Timer) -> bool:
        for button in [GET_ITEMS_1, GET_ITEMS_2]:
            if self.appear_then_click(button, offset=(30, 30), interval=3):
                confirm_timer.reset()
                return True
        return False

    def _supply_pack_buy_finished(self, supply_pack: Button, confirm_timer: Timer) -> bool:
        if self.appear(page_supply_pack.check_button, offset=(20, 20)) and not self.appear(
            supply_pack, offset=(20, 20)
        ):
            return confirm_timer.reached()
        confirm_timer.reset()
        return False

    def supply_pack_buy(self, supply_pack: Button, *, skip_first_screenshot: bool = True) -> bool:
        """购买指定补给包；确认成功返回 True，连续点击三次仍未完成则放弃。"""
        logger.hr("Supply pack buy")
        self._clear_supply_pack_intervals(supply_pack)

        logger.info(f"Buying {supply_pack}")
        executed = False
        click_count = 0
        confirm_timer = Timer(1, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            click_count, handled, failed = self._handle_visible_supply_pack(
                supply_pack=supply_pack, click_count=click_count, confirm_timer=confirm_timer
            )
            if failed:
                break
            if handled:
                continue
            if self.appear_then_click(BUY_CONFIRM, offset=(20, 20), interval=3):
                confirm_timer.reset()
                continue
            if self.handle_popup_confirm("BUY_SUPPLY_PACK"):
                self.interval_reset(supply_pack)
                self.interval_reset(BUY_CONFIRM)
                executed = True
                continue
            if self._handle_supply_pack_reward_popup(confirm_timer):
                continue

            if self._supply_pack_buy_finished(supply_pack=supply_pack, confirm_timer=confirm_timer):
                break

        logger.info(f"Supply pack buy finished, executed={executed}")
        return executed

    def goto_supply_pack(self) -> None:
        """从商店进入补给包页签。"""
        self.ui_goto(page_supply_pack)

    def run(self) -> None:
        """从任意页面进入补给包页签，按油量和星期配置领取周礼包。"""
        self.ui_ensure(page_shop)
        self.goto_supply_pack()
        if self.get_oil() < 21000:
            server_today = get_server_weekday()
            target = self.config.SupplyPack_DayOfWeek
            target_name = day_name[target]
            if server_today >= target:
                self.supply_pack_buy(FREE_SUPPLY_PACK)
            else:
                logger.info(f"Delaying free week supply pack to {target_name}")
        else:
            logger.info("Oil > 21000, unable to buy free weekly supply pack")


class SupplyPack250814(SupplyPack):
    def get_oil(self, *, skip_first_screenshot: bool = True) -> int:
        """返回商店页油量；超时或识别失败时为 0。"""
        amount = 0
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning("Get oil timeout")
                break

            if not self.appear(SHOP_OCR_OIL_CHECK, offset=(10, 2)):
                logger.info("No oil icon")
                continue
            ocr = Digit(SHOP_OCR_OIL, name="OCR_OIL", letter=(247, 247, 247), threshold=128)
            result = ocr.ocr(self.device.image)
            if isinstance(result, list):
                message = "supply-pack oil OCR must contain exactly one region"
                raise TypeError(message)
            amount = result
            if amount >= 100:
                break

        return amount

    def goto_supply_pack(self) -> None:
        """从商店通过动态页签按钮进入补给包页。"""
        logger.info("Goto supply pack")
        for _ in self.loop():
            if self.match_template_color(page_supply_pack.check_button, offset=(20, 20)):
                logger.info("At supply pack")
                break

            if self.appear_then_click(page_supply_pack.check_button, offset=(20, 20), interval=3):
                continue
