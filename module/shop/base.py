import re

import numpy as np

from module.base.button import ButtonGrid
from module.base.decorator import Config, cached_property
from module.base.filter import Filter
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_3, GET_SHIP
from module.logger import logger
from module.shop.assets import SHOP_CLICK_SAFE_AREA
from module.statistics.item import Item, ItemGrid
from module.tactical.tactical_class import Book
from module.ui.ui import UI

FILTER_REGEX = re.compile(
    "^(array|book|box|bulin|cat"
    "|chip|coin|cube|drill|food"
    "|plate|retrofit|pr|dr|specializedcore"
    "|logger|tuning"
    "|hecombatplan|fragment|hiddenzonedatalogger"
    "|albacore|bataan|bearn|bluegill|carabiniere|casablanca|contedicavour|dukeofyork"
    "|echo|eldridge|gangut|glorious|grenville|hibiki|hunter|icarus"
    "|kawakaze|kinggeorgev|kinu|kuroshio|lagalissonniere|lemalinmuse|letemeraire|littorio"
    "|mikuma|minsk|newcastle|oyashio|quincy|ryuujou|sanjuan|sheffieldmuse"
    "|trento|u37|vincennes|z24|z26|z28|z36"
    ")"
    "(neptune|monarch|ibuki|izumo|roon|saintlouis"
    "|seattle|georgia|kitakaze|azuma|friedrich"
    "|gascogne|champagne|cheshire|drake|mainz|odin"
    "|anchorage|hakuryu|agir|august|marcopolo"
    "|plymouth|rupprecht|harbin|chkalov|brest"
    "|red|blue|yellow"
    "|general|gun|torpedo|antiair|plane|wild"
    "|dd|cl|bb|cv"
    "|iris"
    "|abyssal|archive|obscure|unlock"
    "|combat|offense|survival)?"
    "(s[1-5]|t[1-6])?$",
    flags=re.IGNORECASE,
)
FILTER_ATTR = ("group", "sub_genre", "tier")
FILTER = Filter(FILTER_REGEX, FILTER_ATTR)


class ShopItem_250814(Item):
    """
    Calculation result of unsold ship_T2 is 0.36, so 0.3 is taken as threshold,
    result of sold product is < 0.2
    """

    def predict_valid(self):
        mean = np.mean(np.max(self.image, axis=2) > 139)
        return mean > 0.3


class ShopItemGrid(ItemGrid):
    def predict(self, image, name=True, amount=True, cost=False, price=False, tag=False):
        """
        Define new attributes to predicted Item obj for shop item filtering
        """
        super().predict(image, name, amount, cost, price, tag)
        for item in self.items:
            # Set defaults
            item.group, item.sub_genre, item.tier = None, None, None

            # Can use regular expression to quickly populate
            # the new attributes
            name = item.name
            result = re.search(FILTER_REGEX, name)
            if result:
                item.group, item.sub_genre, item.tier = [
                    group.lower() if group is not None else None for group in result.groups()
                ]
            else:
                # if not name.isnumeric():
                #     logger.warning(f'Unable to parse shop item {name}; '
                #                     'check template asset and filter regexp')
                #     raise ScriptError
                continue

            # Sometimes book's color and/or tier will be misidentified
            # Undergo a second template match using Book class
            if item.group == "book":
                book = Book(image, item.source_button)
                if item.sub_genre is not None:
                    item.sub_genre = book.genre_str
                item.tier = book.tier_str.lower()
                item.name = "".join(
                    [part.title() if part is not None else "" for part in [item.group, item.sub_genre, item.tier]]
                )

        return self.items


class ShopItemGrid_250814(ShopItemGrid):
    item_class = ShopItem_250814

    def get_soldout_count(self, image):
        count = 0
        for button in self.grids.buttons:
            item = self.item_class(image, button)
            if not item.is_valid:
                count += 1
        logger.attr("Item soldout", count)
        return count


class ShopBase(UI):
    _currency = 0
    shop_template_folder = ""

    @cached_property
    def shop_filter(self):
        """
        Returns:
            str:
        """
        return ""

    @cached_property
    @Config.when(SERVER=None)
    def shop_grid(self):
        """2025-08-14 新版商店 UI 的商品网格。"""
        return ButtonGrid(
            origin=(265, 238), delta=(169, 223), button_shape=(64, 64), grid_shape=(5, 2), name="SHOP_GRID"
        )

    def shop_items(self):
        """
        Returns:
            None, base default value
            ShopItemGrid, variant value
        """
        return

    def shop_currency(self):
        """
        Returns:
            int:
        """
        return self._currency

    def shop_has_loaded(self, _items):
        """
        变体商店的加载完成检查钩子。

        例如勋章商店刚打开时会先显示默认物品和默认价格，
        变体类可覆写该方法继续等待真实商品加载。

        Args:
            _items: 当前识别到的商品列表；默认实现不需要。

        Returns:
            bool: 是否已加载完成。
        """
        return True

    def shop_detect_items(self, image=None):
        """
        在指定截图上识别商店商品，主要用于测试。
        """
        if image is None:
            image = self.device.image

        shop_items = self.shop_items()
        if shop_items is None:
            logger.warning("Expected type 'ShopItemGrid' but was None")
            return []

        self._shop_extract_template(shop_items, image)
        shop_items.predict(image, name=True, amount=False, cost=True, price=True, tag=False)
        return self._log_shop_items(shop_items.items, shop_items.grids)

    def _shop_extract_template(self, shop_items, image):
        if not self.config.SHOP_EXTRACT_TEMPLATE:
            return
        if self.shop_template_folder:
            logger.info(f"Extract item templates to {self.shop_template_folder}")
            shop_items.extract_template(image, self.shop_template_folder)
            return
        logger.warning("SHOP_EXTRACT_TEMPLATE enabled but shop_template_folder is not set, skip extracting")

    def _log_shop_items(self, items, grids):
        if len(items):
            min_row = grids[0, 0].area[1]
            row = [str(item) for item in items if item.button[1] == min_row]
            logger.info(f"Shop row 1: {row}")
            row = [str(item) for item in items if item.button[1] != min_row]
            logger.info(f"Shop row 2: {row}")
            return items
        logger.info("No shop items found")
        return []

    def shop_obstruct_handle(self):
        """
        Remove obstructions in shop view if any

        Returns:
            bool:
        """
        # Handle shop obstructions
        if self.appear(GET_SHIP, interval=1):
            logger.info(f"Shop obstruct: {GET_SHIP} -> {SHOP_CLICK_SAFE_AREA}")
            self.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        # To lock new ships
        if self.handle_popup_confirm("SHOP_OBSTRUCT"):
            return True
        if self.appear(GET_ITEMS_1, interval=1):
            logger.info(f"Shop obstruct: {GET_ITEMS_1} -> {SHOP_CLICK_SAFE_AREA}")
            self.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        if self.appear(GET_ITEMS_3, interval=1):
            logger.info(f"Shop obstruct: {GET_ITEMS_3} -> {SHOP_CLICK_SAFE_AREA}")
            self.device.click(SHOP_CLICK_SAFE_AREA)
            return True

        return False

    def _shop_items_still_loading(self, items, record):
        known = len([item for item in items if item.is_known_item])
        logger.attr("Item detected", known)
        return known == 0 or known != record, known

    def _wait_shop_items_loaded(self, shop_items, skip_first_screenshot):
        record = 0
        timeout = Timer(3, count=9).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.shop_obstruct_handle():
                timeout.reset()
                continue

            self._shop_extract_template(shop_items, self.device.image)
            shop_items.predict(self.device.image, name=True, amount=False, cost=True, price=True, tag=False)

            if timeout.reached():
                logger.warning("Items loading timeout; continue and assumed has loaded")
                break

            items = shop_items.items
            loading, record = self._shop_items_still_loading(items, record)
            if loading:
                continue

            if self.shop_has_loaded(items):
                break

    def shop_get_items(self, skip_first_screenshot=True):
        """
        Args:
            skip_first_screenshot (bool):

        Returns:
            list[Item]:
        """
        shop_items = self.shop_items()
        if shop_items is None:
            logger.warning("Expected type 'ShopItemGrid' but was None")
            return []

        self._wait_shop_items_loaded(shop_items, skip_first_screenshot=skip_first_screenshot)
        return self._log_shop_items(shop_items.items, shop_items.grids)

    def shop_check_item(self, item):
        """返回当前货币是否足够购买物品。"""
        return item.price <= self._currency

    def shop_check_custom_item(self, _item):
        """
        自定义商品检查钩子。

        变体类可覆写该方法处理不适合通过过滤字符串描述的商品。

        Args:
            _item (Item): 待检查商品；默认实现不需要。

        Returns:
            bool: 是否命中自定义购买条件。
        """
        return False

    def shop_get_item_to_buy(self, items):
        """
        Args:
            items list(Item): acquired from shop_get_items

        Returns:
            Item: Item to buy, or None.
        """
        # First, must scan for custom items
        # as has no template or filter support
        for item in items:
            if self.shop_check_custom_item(item):
                return item

        # Second, load selection, apply filter,
        # and return 1st item in result if any
        FILTER.load(self.shop_filter)
        filtered = FILTER.apply(items, self.shop_check_item)

        if not filtered:
            return None
        logger.attr("Item_sort", " > ".join([str(item) for item in filtered]))

        return filtered[0]
