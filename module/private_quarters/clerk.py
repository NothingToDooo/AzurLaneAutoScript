from module.base.timer import Timer
from module.logger import logger
from module.private_quarters import assets as pq_assets
from module.private_quarters.ui import PQShopUI
from module.shop.clerk import ShopClerk


class PQShopClerk(ShopClerk, PQShopUI):
    def shop_interval_clear(self):
        """
        清理私人宿舍商店特有的按钮间隔。
        """
        self.interval_clear(
            [
                pq_assets.PRIVATE_QUARTERS_SHOP_CHECK,
                pq_assets.PRIVATE_QUARTERS_SHOP_AMOUNT_MAX,
                pq_assets.PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT,
            ]
        )

    def shop_buy_execute(self, item, skip_first_screenshot=True):
        """
        Args:
            item: Item to check
            skip_first_screenshot: bool

        Returns:
            None: exits appropriately therefore successful
        """

        # 确认购买前后需要等待的状态。
        def after_confirm_state():
            return self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET, offset=(20, 20)) or self.appear(
                pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET, offset=(20, 20)
            )

        def after_purchase_state():
            return (
                not self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET, offset=(20, 20))
                and not self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET, offset=(20, 20))
                and self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_CHECK)
            )

        self.shop_interval_clear()
        pq_assets.PRIVATE_QUARTERS_SHOP_CHECK.clear_offset()

        for _ in self.loop():
            # 已进入确认后状态。
            if after_confirm_state():
                break

            if self.appear(pq_assets.PRIVATE_QUARTERS_SHOP_CHECK, interval=3):
                self.device.click(item)
                continue
            if self.appear_then_click(pq_assets.PRIVATE_QUARTERS_SHOP_AMOUNT_MAX, offset=(20, 20), interval=1):
                continue
            if self.appear_then_click(pq_assets.PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT, offset=(20, 20), interval=1):
                continue

        click_timer = Timer(3, count=6)
        for _ in self.loop():
            # 购买完成。
            if after_purchase_state():
                break

            if click_timer.reached() and after_confirm_state():
                self.device.click(pq_assets.PRIVATE_QUARTERS_SHOP_CHECK)
                click_timer.reset()
                continue

    def shop_buy(self):
        """
        Returns:
            bool: If success, and able to continue.
        """
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
            else:
                self.shop_buy_execute(item)

                # 购买后导航栏会重置到默认位置，需要移回去继续扫描。
                self.shop_left_navbar_ensure(2)
                self.shop_bottom_navbar_ensure(2)

                continue

        logger.warning("Too many items to buy, stopped")
        return True
