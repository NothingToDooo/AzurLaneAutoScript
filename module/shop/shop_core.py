from typing import TYPE_CHECKING

from module.base.decorator import cached_property
from module.logger import logger
from module.shop.assets import SHOP_BUY_CONFIRM_AMOUNT
from module.shop.base import ShopItemGrid250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus

if TYPE_CHECKING:
    from module.statistics.item import Item


class CoreShop250814(ShopClerk, ShopStatus):
    shop_template_folder = "./assets/shop/core"

    @cached_property
    def shop_filter(self) -> str:
        return self.config.CoreShop_Filter.strip()

    @cached_property
    def shop_core_items(self) -> ShopItemGrid250814:
        shop_grid = self.shop_grid
        shop_core_items = ShopItemGrid250814(
            shop_grid,
            templates={},
            template_area=(25, 20, 82, 72),
            amount_area=(42, 50, 65, 65),
            cost_area=(-12, 115, 60, 155),
            price_area=(18, 121, 85, 150),
        )
        shop_core_items.load_template_folder(self.shop_template_folder)
        shop_core_items.load_cost_template_folder("./assets/shop/cost")
        return shop_core_items

    def shop_items(self) -> ShopItemGrid250814:
        return self.shop_core_items

    def shop_currency(self) -> int:
        self._currency = self.status_get_core()
        logger.info(f"Core: {self._currency}")
        return self._currency

    def shop_interval_clear(self) -> None:
        super().shop_interval_clear()
        self.interval_clear(SHOP_BUY_CONFIRM_AMOUNT)

    def shop_buy_handle(self, _item: Item) -> bool:
        """处理核心商店的数量确认弹窗。"""
        if self.appear(SHOP_BUY_CONFIRM_AMOUNT, offset=(20, 20), interval=3):
            self.shop_buy_amount_execute(_item)
            self.interval_reset(SHOP_BUY_CONFIRM_AMOUNT)
            return True

        return False

    def run(self) -> None:
        if not self.shop_filter:
            return

        logger.hr("Core Shop", level=1)
        self.shop_buy()
