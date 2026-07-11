from module.base.decorator import cached_property
from module.logger import logger
from module.shop.base import ShopItemGrid250814
from module.shop.clerk import ShopClerk
from module.shop.shop_status import ShopStatus
from module.shop.ui import ShopUI


class MeritShop250814(ShopClerk, ShopUI, ShopStatus):
    shop_template_folder = "./assets/shop/merit"

    @cached_property
    def shop_filter(self) -> str:
        return self.config.MeritShop_Filter.strip()

    @cached_property
    def shop_merit_items(self) -> ShopItemGrid250814:
        shop_grid = self.shop_grid
        shop_merit_items = ShopItemGrid250814(
            shop_grid,
            templates={},
            template_area=(25, 20, 82, 72),
            amount_area=(42, 50, 65, 65),
            cost_area=(-12, 115, 60, 155),
            price_area=(18, 121, 85, 150),
        )
        shop_merit_items.load_template_folder(self.shop_template_folder)
        shop_merit_items.load_cost_template_folder("./assets/shop/cost")
        return shop_merit_items

    def shop_items(self) -> ShopItemGrid250814:
        return self.shop_merit_items

    def shop_currency(self) -> int:
        self._currency = self.status_get_merit()
        logger.info(f"Merit: {self._currency}")
        return self._currency

    def run(self) -> None:
        if not self.shop_filter:
            return

        logger.hr("Merit Shop", level=1)

        refresh = self.config.MeritShop_Refresh
        for _ in range(2):
            success = self.shop_buy()
            if not success:
                break
            if refresh and self.shop_refresh():
                continue
            break
