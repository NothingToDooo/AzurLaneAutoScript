from itertools import chain
from typing import TYPE_CHECKING

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.template import Template
from module.logger import logger
from module.map_detection.utils import Points
from module.os_handler.map_event import MapEventHandler
from module.os_handler.os_status import OSStatus
from module.os_shop.item import OSShopItem as Item
from module.os_shop.item import OSShopItemGrid as ItemGrid
from module.os_shop.selector import Selector
from module.os_shop.ui import OS_SHOP_SCROLL, OSShopUI
from module.statistics.utils import load_folder

if TYPE_CHECKING:
    from module.base.type_alias import NumericArray


class PortShop(OSStatus, OSShopUI, Selector, MapEventHandler):
    OS_SHOP_COST_ASSET_FOLDER = "./assets/shop/os_cost"
    OS_SHOP_COST_SOLD_OUT_ASSET_FOLDER = "./assets/shop/os_cost_sold_out"
    OS_SHOP_ITEM_ASSET_FOLDER = "./assets/shop/os"

    @cached_property
    def templates(self) -> list[Template]:
        coins = load_folder(self.OS_SHOP_COST_ASSET_FOLDER)
        coins_sold_out = load_folder(self.OS_SHOP_COST_SOLD_OUT_ASSET_FOLDER)
        templates = [Template(c) for c in coins.values()]
        templates.extend(Template(c) for c in coins_sold_out.values())
        return templates

    def _get_os_shop_cost(self) -> NumericArray:
        """返回各货币图标左上角坐标。"""
        image = self.image_crop((360, 320, 410, 700))
        result = list(chain.from_iterable(template.match_multi(image) for template in self.templates))
        logger.attr("Costs", f"{result}")
        return Points([(0.0, m.area[1]) for m in result]).group(threshold=5)

    @cached_property
    def os_shop_items(self) -> ItemGrid:
        os_shop_items = ItemGrid(
            grids=None,
            templates={},
            amount_area=(77, 77, 96, 96),
            counter_area=(70, 167, 134, 186),
            price_area=(52, 132, 130, 165),
        )
        os_shop_items.load_template_folder(self.OS_SHOP_ITEM_ASSET_FOLDER)
        os_shop_items.load_cost_template_folder(self.OS_SHOP_COST_ASSET_FOLDER)
        return os_shop_items

    def _get_os_shop_grid(self) -> ButtonGrid:
        costs = self._get_os_shop_cost()
        row = len(costs)
        y = 0
        delta_y = 0

        if row == 1:
            y = 320 + costs[0][1] - 130
        elif row == 2:
            y = 320 + min(costs[0][1], costs[1][1]) - 130
            delta_y = abs(costs[0][1] - costs[1][1])

        return ButtonGrid(
            origin=(356, y), delta=(160, delta_y), button_shape=(98, 98), grid_shape=(5, row), name="OS_SHOP_GRID"
        )

    def os_shop_get_items(
        self,
        *,
        shop_index: int | None = None,
        scroll_pos: float | None = None,
    ) -> list[Item]:
        self.os_shop_items.grids = self._get_os_shop_grid()
        if self.config.SHOP_EXTRACT_TEMPLATE:
            self.os_shop_items.extract_template(self.device.image, "./assets/shop/os")
        self.os_shop_items.predict(self.device.image, counter=True, shop_index=shop_index, scroll_pos=scroll_pos)
        shop_items = self.os_shop_items.items

        if len(shop_items):
            min_row = self.os_shop_items.grids[0, 0].area[1]
            row = [str(item) for item in shop_items if item.button[1] == min_row]
            logger.info(f"Shop row 1: {row}")
            row = [str(item) for item in shop_items if item.button[1] != min_row]
            logger.info(f"Shop row 2: {row}")
            return shop_items
        logger.info("No shop items found")

        return []

    def os_shop_get_items_to_buy(self, name: str, price: int) -> Item | None:
        items = self.os_shop_get_items()
        for _ in range(2):
            if not len(items) or any(not item.is_known_item() for item in items):
                logger.warning("Empty OS shop or empty items, confirming")
                self.device.sleep((0.3, 0.5))
                self.device.screenshot()
                items = self.os_shop_get_items()
                continue
            matching_items = [item for item in items if item.name == name and item.price == price]
            if matching_items:
                return matching_items.pop()

        return None

    def scan_all(self) -> list[Item]:
        items = []
        self.device.click_record.clear()

        for i in range(4):
            logger.hr(f"OpsiShop scan {i}")
            self.os_shop_side_navbar_ensure(upper=i + 1)
            pre_pos, cur_pos = self.init_slider()

            while True:
                pre_pos = self.pre_scroll(pre_pos, cur_pos)

                page_items = []
                for _ in range(3):
                    page_items = self.os_shop_get_items(shop_index=i, scroll_pos=cur_pos)
                    if not len(page_items) or any(not item.is_known_item() for item in page_items):
                        logger.warning("Empty OS shop or empty items, confirming")
                        self.device.sleep((0.3, 0.5))
                        self.device.screenshot()
                        continue
                    logger.info(f"Found {len(page_items)} items in shop {i + 1} at pos {cur_pos:.2f}")
                    break
                # 即使最后一轮含未知商品，也保留其中已识别的商品。
                items += page_items

                if OS_SHOP_SCROLL.at_bottom(main=self):
                    logger.info("OS shop reach bottom, stop")
                    break
                OS_SHOP_SCROLL.next_page(main=self, page=0.5, skip_first_screenshot=False)
                cur_pos = OS_SHOP_SCROLL.cal_position(main=self)
                continue
            self.device.click_record.clear()

        return items
