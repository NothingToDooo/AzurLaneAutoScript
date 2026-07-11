from typing import TYPE_CHECKING, Unpack, override

from module.logger import logger
from module.ocr.ocr import DigitYuv, Ocr, OcrOptions, OcrRegions, ocr_options
from module.statistics.item import (
    Item,
    ItemGrid,
    ItemGridAreaSettings,
    ItemPredictSettings,
    item_grid_areas,
    item_predict_options,
)

if TYPE_CHECKING:
    from module.base.button import Button, ButtonGrid
    from module.base.template import Template
    from module.base.type_alias import ImageArray
    from module.statistics.item import ItemGridAreas, ItemPredictOptions

type PixelArea = tuple[int, int, int, int]


class OSShopItemGridAreas(ItemGridAreaSettings, total=False):
    counter_area: PixelArea


class OSShopPredictOptions(ItemPredictSettings, total=False):
    counter: bool
    shop_index: int | None
    scroll_pos: float | None


class PriceOcr(DigitYuv):
    def after_process(self, result: str) -> int:
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        result = result.replace("B", "8")

        prev = result
        if result.startswith("0"):
            result = "1" + result
            logger.warning(f"OS shop amount {prev} is revised to {result}")

        return super().after_process(result)


class CounterOcr(Ocr[list[int]]):
    def __init__(
        self,
        buttons: OcrRegions,
        options: OcrOptions | None = None,
        **settings: Unpack[OcrOptions],
    ) -> None:
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789/IDSB"))

    @override
    def after_process(self, result: str) -> list[int]:
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        result = result.replace("B", "8")
        if not result or "/" not in result:
            logger.warning(f"Invalid OCR result: {result}")
            return [0, 0]

        parts = result.split("/")
        if len(parts) != 2:
            logger.warning(f"Invalid counter format: {result}")
            return [0, 0]
        return [int(part) for part in parts]


COUNTER_OCR = CounterOcr([], threshold=96, name="Counter_ocr")
PRICE_OCR = PriceOcr([], letter=(255, 223, 57), threshold=32, name="Price_ocr")


class OSShopItem(Item):
    def __init__(self, image: ImageArray, button: Button) -> None:
        super().__init__(image, button)
        self._shop_index: int | None = None
        self._scroll_pos: float | None = None
        self.total_count = -1
        self.count = -1

    @property
    def shop_index(self) -> int:
        if self._shop_index is None:
            message = "OS shop item has no shop index"
            raise RuntimeError(message)
        return self._shop_index

    @shop_index.setter
    def shop_index(self, value: int) -> None:
        self._shop_index = value

    @property
    def scroll_pos(self) -> float:
        if self._scroll_pos is None:
            message = "OS shop item has no scroll position"
            raise RuntimeError(message)
        return self._scroll_pos

    @scroll_pos.setter
    def scroll_pos(self, value: float) -> None:
        self._scroll_pos = value

    def is_known_item(self) -> bool:
        return self.name != "DefaultItem" and "Empty" not in self.name and not self.name.isdigit()

    def __str__(self) -> str:
        if self.name != "DefaultItem" and self.cost == "DefaultCost":
            name = f"{self.name}_x{self.amount}"
        elif self.name == "DefaultItem" and self.cost != "DefaultCost":
            name = f"{self.cost}_x{self.price}"
        else:
            name = f"{self.name}_{self.amount}x{self.count}_{self.cost}_{self.price}"

        if self.tag is not None:
            name = f"{name}_{self.tag}"

        return name

    def __eq__(self, other: object) -> bool:
        return id(self) == id(other)

    __hash__ = None


class OSShopItemGrid(ItemGrid[OSShopItem]):
    item_class = OSShopItem
    items: list[OSShopItem]

    def __init__(
        self,
        grids: ButtonGrid | None,
        templates: dict[str, Template],
        areas: ItemGridAreas | None = None,
        **area_settings: Unpack[OSShopItemGridAreas],
    ) -> None:
        counter_area = area_settings.pop("counter_area", (85, 170, 134, 186))
        super().__init__(grids, templates, areas=item_grid_areas(areas, area_settings))
        self.counter_ocr = COUNTER_OCR
        self.price_ocr = PRICE_OCR
        self.counter_area = counter_area

    def predict(
        self,
        image: ImageArray,
        options: ItemPredictOptions | None = None,
        **settings: Unpack[OSShopPredictOptions],
    ) -> list[OSShopItem]:
        """settings 额外支持 counter、shop_index 和 scroll_pos 识别元数据。"""
        counter = settings.pop("counter", False)
        shop_index = settings.pop("shop_index", None)
        scroll_pos = settings.pop("scroll_pos", None)
        options = item_predict_options(options, {"name": True, "amount": True, "cost": True, "price": True} | settings)
        super().predict(image, options=options)
        if counter and len(self.items):
            counter_images = [item.crop(self.counter_area) for item in self.items]
            counter_list = self.counter_ocr.ocr_many(counter_images)
            for i, t in zip(self.items, counter_list, strict=False):
                i.count, i.total_count = t

        if isinstance(shop_index, int) and isinstance(scroll_pos, float) and len(self.items):
            for i in self.items:
                i.shop_index = shop_index
                i.scroll_pos = scroll_pos

        return self.items
