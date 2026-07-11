from module.base.decorator import cached_property
from module.logger import logger
from module.shop.base import ShopItemGrid250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus
from module.shop.ui import ShopUI


class GeneralShop250814(ShopClerk, ShopUI, ShopStatus):
    gems = 0
    shop_template_folder = "./assets/shop/general"

    @cached_property
    def shop_filter(self):
        return self.config.GeneralShop_Filter.strip()

    @cached_property
    def shop_general_items(self):
        shop_grid = self.shop_grid

        shop_general_items = ShopItemGrid250814(
            shop_grid,
            templates={},
            template_area=(25, 20, 82, 72),
            amount_area=(42, 50, 65, 65),
            cost_area=(-12, 115, 60, 155),
            price_area=(14, 121, 85, 150),
        )
        shop_general_items.load_template_folder(self.shop_template_folder)
        shop_general_items.load_cost_template_folder("./assets/shop/cost")
        return shop_general_items

    def shop_items(self):
        return self.shop_general_items

    currency_rechecked = 0

    def shop_currency(self):
        while 1:
            self._currency = self.status_get_gold_coins()
            self.gems = self.status_get_gems()
            logger.info(f"Gold coins: {self._currency}, Gems: {self.gems}")

            if self.currency_rechecked >= 3:
                logger.warning("Failed to handle fix currency bug in general shop, skip")
                break

            break

        return self._currency

    def shop_check_item(self, item):
        if item.cost == "Coins":
            return item.price <= self._currency

        if self.config.GeneralShop_UseGems and item.cost == "Gems":
            return item.price <= self.gems

        return False

    def shop_check_custom_item(self, _item):
        if self.config.GeneralShop_ConsumeCoins and self._currency >= 550000 and _item.cost == "Coins":
            return True

        if not self.config.GeneralShop_BuySkinBox:
            return False
        if _item.is_known_item() or _item.amount != 1 or _item.cost != "Coins" or _item.price != 7000:
            return False

        # 装备皮肤箱无法用颜色模板稳定匹配，而且外观设计经常变化。
        logger.info(f"Item {_item} is considered to be an equip skin box")
        return self._currency >= _item.price

    def run(self):
        if not self.shop_filter:
            return

        logger.hr("General Shop", level=1)

        refresh = self.config.GeneralShop_Refresh
        for _ in range(2):
            success = self.shop_buy()
            if not success:
                break
            if refresh and self.shop_refresh():
                continue
            break
