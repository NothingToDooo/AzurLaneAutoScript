import re
from typing import TYPE_CHECKING, Unpack

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.filter import Filter
from module.logger import logger
from module.private_quarters.clerk import PQShopClerk
from module.private_quarters.status import OCR_SHOP_PRICE, PQStatus
from module.shop.base import ShopItemGrid
from module.statistics.item import (
    Item,
    ItemPredictOptions,
    ItemPredictSettings,
    item_predict_options,
)

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray

FILTER_REGEX = re.compile(r"^(gift|furn|misc)(sirius|cake|roses)([1-9]+)?$", flags=re.IGNORECASE)
FILTER_ATTR = ("group", "sub_genre", "tier")
FILTER = Filter[Item](FILTER_REGEX, FILTER_ATTR)
SHOP_GRID = ButtonGrid(
    origin=(290, 215),
    delta=(230, 0),
    button_shape=(96, 96),
    grid_shape=(4, 1),
    name="PRIVATE_QUARTERS_BUTTON_GRID_ITEM",
)
UNEXPECTED_FILTER_PRESET_MESSAGE = "Private quarters filter returned a preset token"


class PQShopItemGrid(ShopItemGrid):
    def predict(
        self,
        image: ImageArray,
        options: ItemPredictOptions | None = None,
        **settings: Unpack[ItemPredictSettings],
    ) -> list[Item]:
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
    gems: int = 0
    shop_template_folder = "./assets/shop/private_quarters"

    @cached_property
    def shop_filter(self) -> str:
        list_filter = []
        if self.config.PrivateQuarters_BuyRoses:
            list_filter.append("GiftRoses")
        if self.config.PrivateQuarters_BuyCake:
            list_filter.append("GiftCake")

        return " > ".join(list_filter).strip()

    @cached_property
    def shop_private_quarters_items(self) -> PQShopItemGrid:
        shop_private_quarters_items = PQShopItemGrid(
            SHOP_GRID, templates={}, cost_area=(-52, 330, -26, 353), price_area=(-26, 331, 36, 357)
        )
        shop_private_quarters_items.price_ocr = OCR_SHOP_PRICE
        shop_private_quarters_items.load_template_folder(self.shop_template_folder)
        shop_private_quarters_items.load_cost_template_folder("./assets/shop/private_quarters_cost")
        return shop_private_quarters_items

    def shop_items(self) -> PQShopItemGrid:
        return self.shop_private_quarters_items

    def shop_currency(self) -> int:
        self._currency = self.status_get_gold_coins()
        self.gems = self.status_get_gems()
        logger.info(f"Gold coins: {self._currency}, Gems: {self.gems}")
        return self._currency

    def shop_check_item(self, item: Item) -> bool:
        if self.config.PrivateQuarters_BuyRoses and item.sub_genre == "roses":
            return self._currency >= 24000

        if self.config.PrivateQuarters_BuyCake and item.sub_genre == "cake":
            return self.gems >= 210

        return False

    def shop_get_item_to_buy(self, items: list[Item]) -> Item | None:
        FILTER.load(self.shop_filter)
        filtered_with_presets = FILTER.apply(items, self.shop_check_item)
        filtered = [item for item in filtered_with_presets if isinstance(item, Item)]
        if len(filtered) != len(filtered_with_presets):
            raise TypeError(UNEXPECTED_FILTER_PRESET_MESSAGE)

        if not filtered:
            return None
        logger.attr("Item_sort", " > ".join([str(item) for item in filtered]))

        return filtered[0]
