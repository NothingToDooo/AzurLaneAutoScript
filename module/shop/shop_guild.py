from module.base.decorator import cached_property
from module.logger import logger
from module.shop.assets import SHOP_BUY_CONFIRM_SELECT
from module.shop.base import ShopItemGrid250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus
from module.shop.ui import ShopUI


class GuildShop250814(ShopClerk, ShopUI, ShopStatus):
    shop_template_folder = "./assets/shop/guild"

    @cached_property
    def shop_filter(self):
        return self.config.GuildShop_Filter.strip()

    @cached_property
    def shop_guild_items(self):
        shop_grid = self.shop_grid
        shop_guild_items = ShopItemGrid250814(
            shop_grid,
            templates={},
            template_area=(25, 20, 82, 72),
            amount_area=(42, 50, 65, 65),
            cost_area=(-12, 115, 60, 155),
            price_area=(14, 121, 85, 150),
        )
        self.shop_template_folder = "./assets/shop/guild"
        shop_guild_items.load_template_folder(self.shop_template_folder)
        shop_guild_items.load_cost_template_folder("./assets/shop/cost")
        return shop_guild_items

    def shop_items(self):
        return self.shop_guild_items

    def shop_currency(self):
        self._currency = self.status_get_guild_coins()
        logger.info(f"Guild coins: {self._currency}")
        return self._currency

    def shop_interval_clear(self):
        super().shop_interval_clear()
        self.interval_clear(SHOP_BUY_CONFIRM_SELECT)

    def shop_buy_handle(self, _item):
        """处理舰队商店的商品选择弹窗。"""
        if self.appear(SHOP_BUY_CONFIRM_SELECT, offset=(20, 20), interval=3):
            self.shop_buy_select_execute(_item)
            self.interval_reset(SHOP_BUY_CONFIRM_SELECT)
            return True

        return False

    def run(self):
        if not self.shop_filter:
            return

        logger.hr("Guild Shop", level=1)

        refresh = self.config.GuildShop_Refresh
        for _ in range(2):
            success = self.shop_buy()
            if not success:
                break
            if refresh:
                # 刷新消耗 50，PlateT4 消耗 60，至少保留 110 舰队币。
                if self._currency >= 110:
                    if self.shop_refresh():
                        continue
                else:
                    logger.info("Guild coins < 110, skip refreshing")
            break
