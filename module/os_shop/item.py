from module.logger import logger
from module.ocr.ocr import DigitYuv, Ocr, ocr_options
from module.statistics.item import Item, ItemGrid, item_grid_areas


class PriceOcr(DigitYuv):
    def after_process(self, result):
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        result = result.replace("B", "8")

        prev = result
        if result.startswith("0"):
            result = "1" + result
            logger.warning(f"OS shop amount {prev} is revised to {result}")

        return super().after_process(result)


class CounterOcr(Ocr):
    def __init__(self, buttons, options=None, **settings):
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789/IDSB"))

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        return result.replace("B", "8")

    def ocr(self, image, direct_ocr=False):
        """
        Do OCR on a counter, such as `14/15`, and returns 14, 15

        Args:
            image:
            direct_ocr:

        Returns:
            list[list[int]: [[current, total]].
        """
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        if isinstance(result_list, list):
            parsed = []
            for i in result_list:
                if not i or "/" not in i:
                    logger.warning(f"Invalid OCR result format: {i}")
                    parsed.append([0, 0])
                    continue

                parts = i.split("/")
                if len(parts) != 2:
                    logger.warning(f"Invalid counter format: {i}")
                    parsed.append([0, 0])
                    continue
                parsed.append([int(j) for j in parts])

            return parsed
        if not result_list or "/" not in result_list:
            logger.warning(f"Invalid OCR result: {result_list}")
            return [0, 0]

        parts = result_list.split("/")
        if len(parts) != 2:
            logger.warning(f"Invalid counter format: {result_list}")
            return [0, 0]

        return [int(i) for i in parts]


COUNTER_OCR = CounterOcr([], threshold=96, name="Counter_ocr")
PRICE_OCR = PriceOcr([], letter=(255, 223, 57), threshold=32, name="Price_ocr")


class OSShopItem(Item):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shop_index = None
        self._scroll_pos = None
        self.total_count = -1
        self.count = -1

    @property
    def shop_index(self):
        return self._shop_index

    @shop_index.setter
    def shop_index(self, value):
        self._shop_index = value

    @property
    def scroll_pos(self):
        return self._scroll_pos

    @scroll_pos.setter
    def scroll_pos(self, value):
        self._scroll_pos = value

    def is_known_item(self) -> bool:
        return self.name != "DefaultItem" and "Empty" not in self.name and not self.name.isdigit()

    def __str__(self):
        if self.name != "DefaultItem" and self.cost == "DefaultCost":
            name = f"{self.name}_x{self.amount}"
        elif self.name == "DefaultItem" and self.cost != "DefaultCost":
            name = f"{self.cost}_x{self.price}"
        else:
            name = f"{self.name}_{self.amount}x{self.count}_{self.cost}_{self.price}"

        if self.tag is not None:
            name = f"{name}_{self.tag}"

        return name

    def __eq__(self, other):
        return id(self) == id(other)

    __hash__ = None


class OSShopItemGrid(ItemGrid):
    item_class = OSShopItem
    items: list[OSShopItem]

    def __init__(self, grids, templates, areas=None, **area_settings):
        counter_area = area_settings.pop("counter_area", (85, 170, 134, 186))
        super().__init__(grids, templates, areas=item_grid_areas(areas, area_settings))
        self.counter_ocr = COUNTER_OCR
        self.price_ocr = PRICE_OCR
        self.counter_area = counter_area

    def predict(self, image, counter=False, shop_index=None, scroll_pos=None) -> list[OSShopItem]:
        """
        Args:
            image (np.ndarray):
            counter (bool): If predict item counter.
            shop_index (bool): If predict shop index.
            scroll_pos (bool): If predict scroll position.

        Returns:
            list[Item]:
        """
        super().predict(image, name=True, amount=True, cost=True, price=True)
        if counter and len(self.items):
            counter_list = [item.crop(self.counter_area) for item in self.items]
            counter_list = self.counter_ocr.ocr(counter_list, direct_ocr=True)
            for i, t in zip(self.items, counter_list, strict=False):
                i.count, i.total_count = t

        if isinstance(shop_index, int) and isinstance(scroll_pos, float) and len(self.items):
            for i in self.items:
                i.shop_index = shop_index
                i.scroll_pos = scroll_pos

        return self.items
