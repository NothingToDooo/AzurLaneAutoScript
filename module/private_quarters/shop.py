import re

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.filter import Filter
from module.logger import logger
from module.private_quarters.clerk import PQShopClerk
from module.private_quarters.status import OCR_SHOP_PRICE, PQStatus
from module.statistics.item import ItemGrid, item_predict_options

FILTER_REGEX = re.compile(r"^(gift|furn|misc)(sirius|cake|roses)([1-9]+)?$", flags=re.IGNORECASE)
FILTER_ATTR = ("group", "sub_genre", "tier")
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)


class PQShopItemGrid(ItemGrid):
    def predict(self, image, options=None, **settings):
        """识别商品并补充筛选属性。"""
        options = item_predict_options(options, settings)
        super().predict(image, options=options)

        for item in self.items:
            item.group, item.sub_genre, item.tier = None, None, None

            name = item.name
            result = re.search(FILTER_REGEX, name)
            if result:
                item.group, item.sub_genre, item.tier = [
                    group.lower() if group is not None else None for group in result.groups()
                ]
            else:
                continue

        return self.items


class PQShop(PQShopClerk, PQStatus):
    gems = 0
    shop_template_folder = "./assets/shop/private_quarters"

    @cached_property
    def shop_filter(self):
        list_filter = []
        if self.config.PrivateQuarters_BuyRoses:
            list_filter.append("GiftRoses")
        if self.config.PrivateQuarters_BuyCake:
            list_filter.append("GiftCake")

        return " > ".join(list_filter).strip()

    @cached_property
    def shop_grid(self):
        return ButtonGrid(
            origin=(290, 215),
            delta=(230, 0),
            button_shape=(96, 96),
            grid_shape=(4, 1),
            name="PRIVATE_QUARTERS_BUTTON_GRID_ITEM",
        )

    @cached_property
    def shop_private_quarters_items(self):
        shop_grid = self.shop_grid
        shop_private_quarters_items = PQShopItemGrid(
            shop_grid, templates={}, cost_area=(-52, 330, -26, 353), price_area=(-26, 331, 36, 357)
        )
        shop_private_quarters_items.price_ocr = OCR_SHOP_PRICE
        shop_private_quarters_items.load_template_folder(self.shop_template_folder)
        shop_private_quarters_items.load_cost_template_folder("./assets/shop/private_quarters_cost")
        return shop_private_quarters_items

    def shop_items(self):
        return self.shop_private_quarters_items

    def shop_currency(self):
        self._currency = self.status_get_gold_coins()
        self.gems = self.status_get_gems()
        logger.info(f"Gold coins: {self._currency}, Gems: {self.gems}")

    def shop_check_item(self, item):
        if self.config.PrivateQuarters_BuyRoses and item.sub_genre == "roses":
            return self._currency >= 24000

        if self.config.PrivateQuarters_BuyCake and item.sub_genre == "cake":
            return self.gems >= 210

        return False

    def shop_get_item_to_buy(self, items):
        FILTER.load(self.shop_filter)
        filtered = FILTER.apply(items, self.shop_check_item)

        if not filtered:
            return None
        logger.attr("Item_sort", " > ".join([str(item) for item in filtered]))

        return filtered[0]
