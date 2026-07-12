import re
from typing import TYPE_CHECKING, Unpack

import numpy as np

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.filter import Filter
from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_3, GET_SHIP
from module.logger import logger
from module.shop.assets import SHOP_CLICK_SAFE_AREA
from module.statistics.item import Item, ItemGrid, ItemPredictOptions, ItemPredictSettings, item_predict_options
from module.tactical.tactical_class import Book
from module.ui.ui import UI

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray

FILTER_REGEX = re.compile(
    r"^(array|book|box|bulin|cat"
    r"|chip|coin|cube|drill|food"
    r"|plate|retrofit|pr|dr|specializedcore"
    r"|logger|tuning"
    r"|hecombatplan|fragment|hiddenzonedatalogger"
    r"|albacore|bataan|bearn|bluegill|carabiniere|casablanca|contedicavour|dukeofyork"
    r"|echo|eldridge|gangut|glorious|grenville|hibiki|hunter|icarus"
    r"|kawakaze|kinggeorgev|kinu|kuroshio|lagalissonniere|lemalinmuse|letemeraire|littorio"
    r"|mikuma|minsk|newcastle|oyashio|quincy|ryuujou|sanjuan|sheffieldmuse"
    r"|trento|u37|vincennes|z24|z26|z28|z36"
    r")"
    r"(neptune|monarch|ibuki|izumo|roon|saintlouis"
    r"|seattle|georgia|kitakaze|azuma|friedrich"
    r"|gascogne|champagne|cheshire|drake|mainz|odin"
    r"|anchorage|hakuryu|agir|august|marcopolo"
    r"|plymouth|rupprecht|harbin|chkalov|brest"
    r"|red|blue|yellow"
    r"|general|gun|torpedo|antiair|plane|wild"
    r"|dd|cl|bb|cv"
    r"|iris"
    r"|abyssal|archive|obscure|unlock"
    r"|combat|offense|survival)?"
    r"(s[1-5]|t[1-6])?$",
    flags=re.IGNORECASE,
)
FILTER_ATTR = ("group", "sub_genre", "tier")
FILTER: Filter[Item] = Filter(FILTER_REGEX, FILTER_ATTR)


class ShopItem250814(Item):
    """未售商品计算值为 0.36，已售低于 0.2，因此有效阈值取 0.3。"""

    def predict_valid(self) -> bool:
        mean = np.mean(np.max(self.image, axis=2) > 139)
        return bool(mean > 0.3)


class ShopItemGrid(ItemGrid[Item]):
    @property
    def shop_grids(self) -> ButtonGrid:
        """商店商品网格必须绑定可点击按钮。"""
        if self.grids is None:
            message = "shop item grid requires button grids"
            raise RuntimeError(message)
        return self.grids

    def predict(
        self,
        image: ImageArray,
        options: ItemPredictOptions | None = None,
        **settings: Unpack[ItemPredictSettings],
    ) -> list[Item]:
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

            # 书本颜色和等级容易误识别，使用 Book 模板二次匹配。
            if item.group == "book":
                book = Book(image, item.source_button)
                if item.sub_genre is not None:
                    item.sub_genre = book.genre_str
                item.tier = book.tier_str.lower()
                item.name = "".join(
                    [part.title() if part is not None else "" for part in [item.group, item.sub_genre, item.tier]]
                )

        return self.items


class ShopItemGrid250814(ShopItemGrid):
    item_class = ShopItem250814

    def get_soldout_count(self, image: ImageArray) -> int:
        count = 0
        for button in self.shop_grids.buttons:
            item = self.item_class(image, button)
            if not item.is_valid:
                count += 1
        logger.attr("Item soldout", count)
        return count


class ShopBase(UI):
    _currency = 0
    shop_template_folder = ""
    shop_filter_default = ""
    shop_item_grid: ShopItemGrid | None = None
    shop_grid_origin = (265, 238)
    shop_grid_delta = (169, 223)

    @cached_property
    def shop_filter(self) -> str:
        return self.shop_filter_default

    @cached_property
    def shop_grid(self) -> ButtonGrid:
        """2025-08-14 新版商店 UI 的商品网格。"""
        return ButtonGrid(
            origin=self.shop_grid_origin,
            delta=self.shop_grid_delta,
            button_shape=(64, 64),
            grid_shape=(5, 2),
            name="SHOP_GRID",
        )

    def shop_items(self) -> ShopItemGrid | None:
        """基类返回 None，商店变体返回各自的 ShopItemGrid。"""
        return self.shop_item_grid

    def shop_currency(self) -> int:
        return self._currency

    @staticmethod
    def shop_has_loaded(_items: list[Item]) -> bool:
        """变体加载检查钩子；用于等待默认商品和价格被真实数据替换。"""
        return True

    def shop_detect_items(self, image: ImageArray | None = None) -> list[Item]:
        """在指定截图上识别商品，供测试使用。"""
        if image is None:
            image = self.device.image

        shop_items = self.shop_items()
        if shop_items is None:
            logger.warning("Expected type 'ShopItemGrid' but was None")
            return []

        self._shop_extract_template(shop_items, image)
        shop_items.predict(image, name=True, amount=False, cost=True, price=True, tag=False)
        return self._log_shop_items(shop_items.items, shop_items.shop_grids)

    def _shop_extract_template(self, shop_items: ShopItemGrid, image: ImageArray) -> None:
        if not self.config.SHOP_EXTRACT_TEMPLATE:
            return
        if self.shop_template_folder:
            logger.info(f"Extract item templates to {self.shop_template_folder}")
            shop_items.extract_template(image, self.shop_template_folder)
            return
        logger.warning("SHOP_EXTRACT_TEMPLATE enabled but shop_template_folder is not set, skip extracting")

    @staticmethod
    def _log_shop_items(items: list[Item], grids: ButtonGrid) -> list[Item]:
        if len(items):
            min_row = grids[0, 0].area[1]
            row = [str(item) for item in items if item.button[1] == min_row]
            logger.info(f"Shop row 1: {row}")
            row = [str(item) for item in items if item.button[1] != min_row]
            logger.info(f"Shop row 2: {row}")
            return items
        logger.info("No shop items found")
        return []

    def shop_obstruct_handle(self) -> bool:
        if self.appear(GET_SHIP, interval=1):
            logger.info(f"Shop obstruct: {GET_SHIP} -> {SHOP_CLICK_SAFE_AREA}")
            self.device.click(SHOP_CLICK_SAFE_AREA)
            return True
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

    @staticmethod
    def _shop_items_still_loading(items: list[Item], record: int) -> tuple[bool, int]:
        known = len([item for item in items if item.is_known_item()])
        logger.attr("Item detected", known)
        return known == 0 or known != record, known

    def _wait_shop_items_loaded(self, shop_items: ShopItemGrid, *, skip_first_screenshot: bool) -> None:
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

    def shop_get_items(self, *, skip_first_screenshot: bool = True) -> list[Item]:
        shop_items = self.shop_items()
        if shop_items is None:
            logger.warning("Expected type 'ShopItemGrid' but was None")
            return []

        self._wait_shop_items_loaded(shop_items, skip_first_screenshot=skip_first_screenshot)
        return self._log_shop_items(shop_items.items, shop_items.shop_grids)

    def shop_check_item(self, item: Item) -> bool:
        return item.price <= self._currency

    @staticmethod
    def shop_check_custom_item(_item: Item) -> bool:
        """供变体处理无法用过滤字符串描述的商品。"""
        return False

    def shop_get_item_to_buy(self, items: list[Item]) -> Item | None:
        for item in items:
            if self.shop_check_custom_item(item):
                return item

        FILTER.load(self.shop_filter)
        filtered = [item for item in FILTER.apply(items, self.shop_check_item) if not isinstance(item, str)]

        if not filtered:
            return None
        logger.attr("Item_sort", " > ".join([str(item) for item in filtered]))

        return filtered[0]
