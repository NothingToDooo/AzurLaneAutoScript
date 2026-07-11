from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.logger import logger
from module.private_quarters import assets as pq_assets
from module.private_quarters.ui import PQShopUI
from module.shop.clerk import ShopClerk

if TYPE_CHECKING:
    from module.statistics.item import Item


class PQShopClerk(ShopClerk, PQShopUI):
    def shop_interval_clear(self) -> None:
        self.interval_clear(
            [
                pq_assets.PRIVATE_QUARTERS_SHOP_CHECK,
                pq_assets.PRIVATE_QUARTERS_SHOP_AMOUNT_MAX,
                pq_assets.PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT,
            ]
        )

    def shop_buy_execute(self, item: Item, *, skip_first_screenshot: bool = True) -> None:
        self._pq_shop_prepare_buy()
        self._pq_shop_enter_purchase_confirm(item, skip_first_screenshot=skip_first_screenshot)
        self._pq_shop_finish_purchase_confirm()

    def _pq_shop_prepare_buy(self) -> None:
        self.shop_interval_clear()
        pq_assets.PRIVATE_QUARTERS_SHOP_CHECK.clear_offset()

    def _pq_shop_after_confirm_state(self) -> bool:
        return self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET, offset=(20, 20)) or self.appear(
            pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET, offset=(20, 20)
        )

    def _pq_shop_after_purchase_state(self) -> bool:
        return (
            not self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET, offset=(20, 20))
            and not self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET, offset=(20, 20))
            and self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_CHECK)
        )

    def _pq_shop_enter_purchase_confirm(self, item: Item, *, skip_first_screenshot: bool) -> None:
        for _ in self.loop(skip_first=skip_first_screenshot):
            if self._pq_shop_after_confirm_state():
                break

            if self._pq_shop_handle_purchase_confirm_step(item):
                continue

    def _pq_shop_handle_purchase_confirm_step(self, item: Item) -> bool:
        if self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_CHECK, interval=3):
            self.device.click(item)
            return True
        if self.appear_then_click(pq_assets.PRIVATE_QUARTERS_SHOP_AMOUNT_MAX, offset=(20, 20), interval=1):
            return True
        return self.appear_then_click(pq_assets.PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT, offset=(20, 20), interval=1)

    def _pq_shop_finish_purchase_confirm(self) -> None:
        click_timer = Timer(3, count=6)
        for _ in self.loop():
            if self._pq_shop_after_purchase_state():
                break

            if self._pq_shop_click_confirm_when_ready(click_timer):
                continue

    def _pq_shop_click_confirm_when_ready(self, click_timer: Timer) -> bool:
        if not click_timer.reached():
            return False
        if not self._pq_shop_after_confirm_state():
            return False

        self.device.click(pq_assets.PRIVATE_QUARTERS_SHOP_CHECK)
        click_timer.reset()
        return True

    def shop_buy(self) -> bool:
        """购买可选商品；资金不足返回 False，正常扫描完成返回 True。"""
        for _ in range(12):
            logger.hr("Shop buy", level=2)
            # 先读取商品，给货币 OCR 留出内部延迟。
            items = self.shop_get_items()
            self.shop_currency()
            if self._currency <= 0:
                logger.warning(f"Current funds: {self._currency}, stopped")
                return False

            item = self.shop_get_item_to_buy(items)
            if item is None:
                logger.info("Shop buy finished")
                return True
            self.shop_buy_execute(item)

            # 购买后导航栏会重置到默认位置，需要移回去继续扫描。
            self.shop_left_navbar_ensure(2)
            self.shop_bottom_navbar_ensure(2)

            continue

        logger.warning("Too many items to buy, stopped")
        return True
