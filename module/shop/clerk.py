import re

import cv2

from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter
from module.retire.retirement import Retirement
from module.shop.assets import (
    AMOUNT_MAX,
    AMOUNT_MINUS,
    AMOUNT_PLUS,
    SELECT_MINUS,
    SELECT_PLUS,
    SHOP_AMOUNT,
    SHOP_BUY_CONFIRM,
    SHOP_BUY_CONFIRM_AMOUNT,
    SHOP_BUY_CONFIRM_SELECT,
    SHOP_SELECT_PR1,
    SHOP_SELECT_PR2,
    SHOP_SELECT_PR3,
    SHOP_SELECT_STOCK,
)
from module.shop.base import ShopBase
from module.shop.shop_select_globals import SELECT_ITEM_INFO_MAP
from module.ui.assets import SHOP_BACK_ARROW
from module.ui.ui import UiIndexControls


class StockCounter(DigitCounter):
    def pre_process(self, image):
        r, g, b = cv2.split(image)
        image = cv2.max(cv2.max(r, g), b)

        return 255 - image

    def after_process(self, result):
        result = super().after_process(result)

        if re.match(r"^\d\d$", result):
            # 55 -> 5/5
            new = f"{result[0]}/{result[1]}"
            logger.info(f"StockCounter result {result} is revised to {new}")
            result = new
        if re.match(r"^\d{4,}$", result):
            # 1515 -> 15/15
            new = f"{result[0:2]}/{result[2:4]}"
            logger.info(f"StockCounter result {result} is revised to {new}")
            result = new

        return result


SHOP_SELECT_PR = [SHOP_SELECT_PR1, SHOP_SELECT_PR2, SHOP_SELECT_PR3]
OCR_SHOP_SELECT_STOCK = StockCounter(SHOP_SELECT_STOCK)

OCR_SHOP_AMOUNT = Digit(SHOP_AMOUNT, letter=(239, 239, 239), name="OCR_SHOP_AMOUNT")


class ShopClerk(ShopBase, Retirement):
    def shop_get_choice(self, item):
        """读取对应商店变体的商品配置；配置不存在时抛出异常。"""
        group = item.group
        if group == "pr":
            postfix = None
            for _ in range(3):
                if _:
                    self.device.sleep((0.3, 0.5))
                    self.device.screenshot()

                for idx, btn in enumerate(SHOP_SELECT_PR):
                    if self.appear(btn, offset=(20, 20)):
                        postfix = f"{idx + 1}"
                        break

                if postfix is not None:
                    break
                logger.warning("Failed to detect PR series, app may be lagging or frozen")
        else:
            postfix = f"_{item.tier.upper()}"

        ugroup = group.upper()
        # 2025-08-14 新 UI 类名带 _250814，配置名仍使用下划线前的原类名。
        class_name = self.__class__.__name__.split("_")[0]
        try:
            return getattr(self.config, f"{class_name}_{ugroup}{postfix}")
        except Exception:
            logger.critical(f"No configuration with name '{class_name}_{ugroup}{postfix}'")
            raise

    def shop_get_select(self, item):
        """按商品组和配置选择网格按钮；映射无效时抛出 ScriptError。"""
        group = item.group
        if group not in SELECT_ITEM_INFO_MAP:
            logger.critical(f"Unexpected item group '{group}'; expected one of {SELECT_ITEM_INFO_MAP.keys()}")
            raise ScriptError

        choice = self.shop_get_choice(item)

        try:
            item_info = SELECT_ITEM_INFO_MAP[group]
            index = item_info["choices"][choice]
        except Exception as e:
            logger.critical(f"SELECT_ITEM_INFO_MAP may be malformed; item group '{group}' entry is compromised")
            raise ScriptError from e

        grid = item_info["grid"]
        if group == "pr":
            if not isinstance(grid, dict):
                logger.critical(f"SELECT_ITEM_INFO_MAP for item group '{group}' should define series grids")
                raise ScriptError
            try:
                for idx, btn in enumerate(SHOP_SELECT_PR):
                    if self.appear(btn, offset=(20, 20)):
                        series_key = f"s{idx + 1}"
                        return grid[series_key].buttons[index]
            except Exception as e:
                logger.critical(f"SELECT_ITEM_INFO_MAP may be malformed; item group '{group}' entry is compromised")
                raise ScriptError from e
        else:
            if isinstance(grid, dict):
                logger.critical(f"SELECT_ITEM_INFO_MAP for item group '{group}' should define a single grid")
                raise ScriptError
            try:
                return grid.buttons[index]
            except Exception as e:
                logger.critical(f"SELECT_ITEM_INFO_MAP may be malformed; item group '{group}' entry is compromised")
                raise ScriptError from e

    def shop_buy_select_execute(self, item):
        select = self.shop_get_select(item)
        limit = self._read_shop_select_stock_limit(item)
        self._wait_shop_select_amount_controls(select)
        limit = self._limit_shop_select_amount_by_currency(limit, item)

        self.ui_ensure_index(
            limit,
            UiIndexControls(
                letter=self._shop_select_stock_letter(item, limit),
                prev_button=SELECT_MINUS,
                next_button=SELECT_PLUS,
            ),
            skip_first_screenshot=True,
        )
        self.device.click(SHOP_BUY_CONFIRM_SELECT)
        return True

    def _read_shop_select_stock_limit(self, item):
        timeout = Timer(5, count=10).start()
        skip_first_screenshot = True
        limit = 0
        while 1:
            if timeout.reached():
                break
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            _, _, limit = OCR_SHOP_SELECT_STOCK.ocr(self.device.image)
            if limit:
                break

        if not limit:
            logger.critical(
                f"{item.name}'s stock count cannot be extracted. Advised to re-cut the asset OCR_SHOP_SELECT_STOCK"
            )
            raise ScriptError
        return limit

    def _wait_shop_select_amount_controls(self, select):
        click_timer = Timer(3, count=6)
        select_offset = (500, 400)
        while 1:
            if click_timer.reached():
                self.device.click(select)
                click_timer.reset()

            # 在偏移范围内查找加减按钮，顺便刷新后续点击坐标。
            self.device.screenshot()
            if self.appear(SELECT_MINUS, offset=select_offset) and self.appear(SELECT_PLUS, offset=select_offset):
                break
            continue

    def _limit_shop_select_amount_by_currency(self, limit, item):
        total = int(self._currency // item.price)
        diff = limit - total
        if diff > 0:
            return total
        return limit

    def _shop_select_stock_letter(self, item, limit):
        # 适配 ui_ensure_index，避免库存耗尽时继续加购。
        def read_remain(image):
            current, remain, _ = OCR_SHOP_SELECT_STOCK.ocr(image)
            if not current:
                group_case = item.group.title() if len(item.group) > 2 else item.group.upper()
                logger.info(f"{group_case}(s) out of stock; exit to prevent overbuying")
                return limit
            return remain

        return read_remain

    def shop_buy_amount_execute(self, item):
        """按库存和货币设置购买数量；数量 OCR 失败时抛出 ScriptError。"""
        index_offset = (40, 20)

        # 加减按钮可能移位，先刷新偏移再缩小数量 OCR 区域。
        self.appear(AMOUNT_MINUS, offset=index_offset)
        self.appear(AMOUNT_PLUS, offset=index_offset)
        area = OCR_SHOP_AMOUNT.buttons[0]
        OCR_SHOP_AMOUNT.buttons = [(AMOUNT_MINUS.button[2] + 3, area[1], AMOUNT_PLUS.button[0] - 3, area[3])]

        # 点击最大值后等待图像稳定，再读取可购总数。
        self.appear_then_click(AMOUNT_MAX, offset=(50, 50))
        self.device.sleep((0.3, 0.5))
        timeout = Timer(5, count=10).start()
        limit = 0
        while 1:
            if timeout.reached():
                break
            self.device.screenshot()
            limit = OCR_SHOP_AMOUNT.ocr(self.device.image)
            if limit:
                break

        if not limit:
            logger.critical("OCR_SHOP_AMOUNT resulted in zero (0); asset may be compromised")
            raise ScriptError

        total = int(self._currency // item.price)
        diff = limit - total
        if diff > 0:
            limit = total

        self.ui_ensure_index(
            limit,
            UiIndexControls(letter=OCR_SHOP_AMOUNT, prev_button=AMOUNT_MINUS, next_button=AMOUNT_PLUS),
            skip_first_screenshot=True,
        )
        self.device.click(SHOP_BUY_CONFIRM_AMOUNT)
        return True

    def shop_interval_clear(self):
        """变体可覆盖以清理额外资源的间隔计时。"""
        self.interval_clear(SHOP_BACK_ARROW)
        self.interval_clear(SHOP_BUY_CONFIRM)

    def shop_buy_handle(self, _item):
        """供变体处理特殊购买弹窗。"""
        return False

    def shop_buy_execute(self, item, skip_first_screenshot=True):
        success = False
        self.shop_interval_clear()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(SHOP_BACK_ARROW, offset=(30, 30), interval=3):
                self.device.click(item)
                continue
            if self.appear_then_click(SHOP_BUY_CONFIRM, offset=(20, 20), interval=3):
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.shop_buy_handle(item):
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.handle_retirement():
                self.interval_reset(SHOP_BACK_ARROW)
                continue
            if self.shop_obstruct_handle():
                self.interval_reset(SHOP_BACK_ARROW)
                success = True
                continue
            if self.info_bar_count():
                self.interval_reset(SHOP_BACK_ARROW)
                success = True
                continue

            if success and self.appear(SHOP_BACK_ARROW, offset=(30, 30)):
                break

    def shop_buy(self):
        """购买完成返回 True；货币无法识别或耗尽时返回 False。"""
        for _ in range(12):
            logger.hr("Shop buy", level=2)
            # 先识别商品，利用其加载时间等待货币 OCR 稳定。
            items = self.shop_get_items()
            self.shop_currency()
            if self._currency <= 0:
                logger.warning(f"Current funds: {self._currency}, stopped")
                return False

            item = self.shop_get_item_to_buy(items)
            if item is None:
                logger.info("Shop buy finished")
                return True
            self.shop_buy_execute(item)
            continue

        logger.warning("Too many items to buy, stopped")
        return True
