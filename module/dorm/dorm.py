import re
from typing import TYPE_CHECKING, cast

import cv2
import numpy as np

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.filter import Filter
from module.base.mask import Mask
from module.base.timer import Timer
from module.base.utils import _cv_scalar, color_similarity_2d, random_rectangle_point, rgb2gray
from module.dorm import assets as dorm_assets
from module.dorm.buy_furniture import BuyFurniture
from module.handler.assets import POPUP_CONFIRM
from module.logger import logger
from module.ocr.failure_store import OCR_FAILURE_STORE
from module.ocr.ocr import Digit, DigitCounter
from module.template.assets import TEMPLATE_DORM_COIN, TEMPLATE_DORM_LOVE
from module.ui.assets import DORM_CHECK
from module.ui.page import page_dorm, page_dormmenu
from module.ui.ui import UI, UiIndexControls

if TYPE_CHECKING:
    from module.base.button import Button
    from module.base.type_alias import ImageArray

MASK_DORM = Mask(file="./assets/mask/MASK_DORM.png")
DORM_CAMERA_SWIPE = (300, 250)
DORM_CAMERA_RANDOM = (-20, -20, 20, 20)
OCR_SLOT = DigitCounter(dorm_assets.OCR_DORM_SLOT, letter=(107, 89, 82), threshold=128, name="OCR_DORM_SLOT")
OCR_BUY_FOOD_AMOUNT = Digit(
    dorm_assets.OCR_DORM_BUY_FOOD_AMOUNT, letter=(96, 96, 100), threshold=128, name="OCR_DORM_BUY_FOOD_AMOUNT"
)


class OcrDormFood(DigitCounter):
    def pre_process(self, image: ImageArray) -> ImageArray:
        """融合橙字与灰字通道，并按当前 OCR 阈值归一化。"""
        orange = color_similarity_2d(image, color=(239, 158, 49))
        gray = color_similarity_2d(image, color=(99, 97, 99))
        difference = cv2.subtract(_cv_scalar((255, 255, 255, 255)), cv2.max(orange, gray))
        scale = 256 / self.threshold
        return cast("ImageArray", cv2.multiply(difference, _cv_scalar((scale,) * 4)))

    @staticmethod
    def normalize_text(result: str) -> str:
        result = DigitCounter.normalize_text(result)

        if "/" not in result:
            for exp in range(40000, 90001, 1000):
                res = re.match(rf"^(\d+){exp}$", result)
                if res:
                    # OCR 可能漏掉 current/total 之间的斜杠。
                    new = f"{res.group(1)}/{exp}"
                    logger.info(f"OcrDormFood result {result} is revised to {new}")
                    result = new
                    break

        return result


OCR_FILL = OcrDormFood(dorm_assets.OCR_DORM_FILL, name="OCR_DORM_FILL")


class Food:
    def __init__(self, feed: int, amount: int) -> None:
        self.feed = feed
        self.amount = amount

    def __str__(self) -> str:
        return f"Food_{self.feed}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Food):
            return NotImplemented
        return str(self) == str(other)

    __hash__ = None


FOOD_FEED_AMOUNT = (1000, 2000, 3000, 5000, 10000, 20000)
FOOD_FILTER: Filter[Food] = Filter(regex=re.compile(r"(\d+)"), attr=["feed"])


class RewardDorm(UI):
    _dorm_food = ButtonGrid(
        origin=(395, 410),
        delta=(129, 0),
        button_shape=(105, 70),
        grid_shape=(6, 1),
        name="FOOD",
    )

    def _dorm_receive_click(self) -> int:
        """在宿舍点击金币和爱心，返回领取数并留下 info_bar。"""
        image = MASK_DORM.apply(self.device.image)
        loves = TEMPLATE_DORM_LOVE.match_multi(image, name="DORM_LOVE")
        coins = TEMPLATE_DORM_COIN.match_multi(image, name="DORM_COIN")
        logger.info(f"Dorm loves: {len(loves)}, Dorm coins: {len(coins)}")
        # 宿舍背景复杂，误匹配时把两类资源都限制为最多 6 个。
        if len(loves) > 6:
            logger.warning("Too many dorm loves, limited to 6")
            loves = loves[:6]
        if len(coins) > 6:
            logger.warning("Too many dorm coins, limited to 6")
            coins = coins[:6]

        count = 0
        for button in loves:
            count += 1
            # 金币或爱心可能很多，禁用点击记录检查。
            self.device.click(button, control_check=False)
            self.device.sleep((0.5, 0.8))
        for button in coins:
            count += 1
            self.device.click(button, control_check=False)
            self.device.sleep((0.5, 0.8))

        return count

    def _dorm_feed_long_tap(self, button: Button, count: int) -> None:
        # 长按喂食依赖 minitouch 的 DOWN/UP 事件。
        timeout = Timer(count // 5 + 5).start()
        x, y = random_rectangle_point(button.button)
        builder = self.device.minitouch_builder
        builder.down(x, y).commit()
        builder.send()

        while 1:
            builder.move(x, y).commit().wait(10)
            builder.send()
            self.device.screenshot()

            if (
                not self._dorm_has_food(button)
                or self.handle_info_bar()
                or self.appear(POPUP_CONFIRM, offset=self._popup_offset)
            ):
                break
            if timeout.reached():
                logger.warning("Wait dorm feed timeout")
                break

        builder.up().commit()
        builder.send()

    def dorm_view_reset(self) -> None:
        """通过宿舍管理页往返重置宿舍视角。"""
        logger.info("Dorm view reset")
        for _ in self.loop():
            if self.appear(dorm_assets.DORM_MANAGE_CHECK, offset=(20, 20)):
                break

            if self.appear_then_click(dorm_assets.DORM_MANAGE, offset=(20, 20), interval=3):
                continue
            if self.ui_additional(get_ship=False):
                continue
            if self.appear_then_click(dorm_assets.DORM_FURNITURE_CONFIRM, offset=(30, 30), interval=3):
                continue

        for _ in self.loop():
            if self.appear(dorm_assets.DORM_MANAGE, offset=(20, 20)):
                break

            if self.appear(dorm_assets.DORM_MANAGE_CHECK, offset=(20, 20), interval=3):
                self.device.click(dorm_assets.DORM_FURNITURE_SHOP_QUIT)
                continue

    def dorm_collect(self) -> None:
        """在宿舍页一键领取所有金币和爱心。"""
        logger.hr("Dorm collect")

        self.ensure_no_info_bar()

        # 设置超时，避免信息条漏检导致循环卡住。
        timeout = Timer(1.5, count=3).start()

        for _ in self.loop():
            if self.ui_additional(get_ship=False):
                continue

            if self.appear_then_click(dorm_assets.DORM_QUICK_COLLECT, offset=(20, 20), interval=1):
                continue

            if self.info_bar_count() > 0:
                break

            if timeout.reached():
                logger.warning("Dorm collect timeout, probably because Alas did not detect the info_bar")
                break

    @cached_property
    def _dorm_food_ocr(self) -> Digit:
        grids = self._dorm_food.crop((54, 41, 101, 66), name="FOOD_AMOUNT")
        return Digit(grids.buttons, letter=(255, 255, 255), threshold=128, name="OCR_DORM_FOOD")

    def _dorm_has_food(self, button: Button) -> bool:
        return np.min(rgb2gray(self.image_crop(button, copy=False))) < 127

    def _dorm_feed_click(self, button: Button, count: int) -> None:
        logger.info(f"Dorm feed {button} x {count}")
        if count <= 3:
            for _ in range(count):
                self.device.click(button)
                self.device.sleep((0.5, 0.8))
            skip_first_screenshot = False

        else:
            self._dorm_feed_long_tap(button, count)
            skip_first_screenshot = True

        self.popup_interval_clear()
        for _ in self.loop(skip_first=skip_first_screenshot):
            if self.appear(dorm_assets.DORM_FEED_CHECK, offset=(20, 20)):
                break
            if self.handle_popup_cancel("DORM_FEED"):
                continue

    def dorm_food_get(self) -> tuple[list[Food], int]:
        """在喂食页返回食物列表和待补充量；OCR 无总量时待补充量为 -1。"""
        has_food = [self._dorm_has_food(button) for button in self._dorm_food.buttons]
        occupied_slots = [
            (index, area)
            for index, (area, is_present) in enumerate(zip(self._dorm_food_ocr.buttons, has_food, strict=True))
            if is_present
        ]
        amounts = [0] * len(has_food)
        amounts_valid = True
        if occupied_slots:
            images = [self.image_crop(area, copy=False) for _, area in occupied_slots]
            results = self._dorm_food_ocr.recognize(
                images,
                direct_ocr=True,
                failure_store=OCR_FAILURE_STORE,
            )
            results = results if isinstance(results, list) else [results]
            for (index, _), result in zip(occupied_slots, results, strict=True):
                if result.valid and result.value is not None:
                    amounts[index] = result.value
                else:
                    amounts_valid = False

        food = [Food(feed=feed, amount=amount) for feed, amount in zip(FOOD_FEED_AMOUNT, amounts, strict=True)]
        fill = -1
        if amounts_valid:
            fill_result = OCR_FILL.recognize(self.device.image, failure_store=OCR_FAILURE_STORE)
            if fill_result.valid and fill_result.value is not None:
                _, fill, total = fill_result.value
                if total == 0:
                    fill = -1
        logger.info(f"Dorm food: {[f.amount for f in food]}, to fill: {fill}")
        return food, fill

    def dorm_feed_once(self) -> bool:
        timeout = Timer(1.5, count=3).start()
        food: list[Food] = []
        fill: int = 0
        for _ in self.loop():
            if timeout.reached():
                logger.warning("Get dorm food timeout, probably because food is empty")
                break

            if self.handle_info_bar():
                continue

            food, fill = self.dorm_food_get()
            if fill == -1:
                continue
            if sum(f.amount for f in food) > 0:
                break
        fill = max(fill, 0)

        FOOD_FILTER.load(self.config.Dorm_FeedFilter)
        for selected in FOOD_FILTER.apply(food):
            if isinstance(selected, str):
                continue
            button = self._dorm_food.buttons[food.index(selected)]
            if selected.amount > 0 and fill > selected.feed:
                count = min(fill // selected.feed, selected.amount)
                self._dorm_feed_click(button=button, count=count)
                return True

        return False

    def dorm_feed(self) -> int:
        """在喂食页最多执行十轮，返回执行轮数。"""
        logger.hr("Dorm feed")

        for n in range(10):
            if not self.dorm_feed_once():
                logger.info("Dorm feed finished")
                return n

        logger.warning("Dorm feed run count reached")
        return 10

    def dorm_feed_enter(self) -> None:
        """从宿舍页进入喂食页，并处理误入的家具页面。"""
        self.interval_clear(DORM_CHECK)
        for _ in self.loop(skip_first=False):
            if self.appear(dorm_assets.DORM_FEED_CHECK, offset=(20, 20)):
                break

            if self.ui_additional(get_ship=False):
                self.interval_clear(DORM_CHECK)
                continue
            if self.appear(DORM_CHECK, offset=(20, 20), interval=5):
                self.device.click(dorm_assets.DORM_FEED_ENTER)
                continue
            if self.appear(dorm_assets.DORM_MANAGE_CHECK, offset=(20, 20), interval=5):
                self.device.click(dorm_assets.DORM_FURNITURE_SHOP_QUIT)
                logger.info(f"{dorm_assets.DORM_MANAGE_CHECK} -> {dorm_assets.DORM_FURNITURE_SHOP_QUIT}")
                continue
            if self.appear(dorm_assets.DORM_FURNITURE_SHOP_FIRST, offset=(20, 20), interval=5):
                self.device.click(dorm_assets.DORM_FURNITURE_SHOP_QUIT)
                logger.info(f"{dorm_assets.DORM_FURNITURE_SHOP_FIRST} -> {dorm_assets.DORM_FURNITURE_SHOP_QUIT}")
                continue
            if self.appear(dorm_assets.DORM_FURNITURE_SHOP_FIRST_SELECTED, offset=(20, 20), interval=5):
                self.device.click(dorm_assets.DORM_FURNITURE_SHOP_QUIT)
                logger.info(
                    f"{dorm_assets.DORM_FURNITURE_SHOP_FIRST_SELECTED} -> {dorm_assets.DORM_FURNITURE_SHOP_QUIT}"
                )
                continue

    def dorm_feed_quit(self) -> None:
        """从喂食页返回宿舍页。"""
        self.interval_clear(dorm_assets.DORM_FEED_CHECK)
        for _ in self.loop():
            if self.appear(DORM_CHECK):
                break

            if self.appear(dorm_assets.DORM_FEED_CHECK, offset=(20, 20), interval=5):
                self.device.click(dorm_assets.DORM_FEED_ENTER)
                continue
            if self.handle_popup_cancel("DORM_FEED"):
                self.interval_clear(DORM_CHECK)
                continue
            if self.ui_additional(get_ship=False):
                self.interval_clear(DORM_CHECK)
                continue

    def dorm_buy_food_enter(self) -> None:
        """从喂食页进入食物购买页。"""
        self.interval_clear(dorm_assets.DORM_FEED_CHECK)
        for _ in self.loop():
            if self.appear(dorm_assets.DORM_BUY_FOOD_CHECK, offset=(20, 20)):
                break

            if self.match_template_color(dorm_assets.DORM_FEED_CHECK, offset=(20, 20), interval=5):
                self.device.click(dorm_assets.DORM_BUY_FOOD_ENTER)
                continue

    def dorm_buy_food(self, amount: int) -> None:
        """在食物购买页设置购买数量。"""
        logger.hr("Dorm buy food")
        index_offset = (20, 20)
        # 防止加减按钮位置偏移，先用船坞索引 OCR 的方式定位真实按钮。
        self.appear(dorm_assets.FOOD_PLUS, offset=index_offset)
        self.appear(dorm_assets.FOOD_MINUS, offset=index_offset)

        self.ui_ensure_index(
            amount,
            UiIndexControls(
                letter=OCR_BUY_FOOD_AMOUNT,
                prev_button=dorm_assets.FOOD_MINUS,
                next_button=dorm_assets.FOOD_PLUS,
            ),
            skip_first_screenshot=True,
        )

    def dorm_buy_food_confirm(self) -> None:
        """确认购买食物并回到喂食页。"""
        self.interval_clear(dorm_assets.DORM_BUY_FOOD_CONFIRM)
        for _ in self.loop():
            if self.match_template_color(dorm_assets.DORM_FEED_CHECK, offset=(20, 20)):
                break

            if self.appear_then_click(dorm_assets.DORM_BUY_FOOD_CONFIRM, offset=(20, 20), interval=5):
                continue

    def dorm_food_run(self, amount: int) -> None:
        """从任意页面购买指定数量的食物，最后回到宿舍页。"""
        if amount <= 0:
            return

        self.ui_ensure(page_dormmenu)
        self.handle_info_bar()
        self.ui_goto(page_dorm, skip_first_screenshot=True)
        logger.hr("Dorm buy food", level=1)
        self.dorm_feed_enter()
        self.dorm_buy_food_enter()
        self.dorm_buy_food(amount=amount)
        self.dorm_buy_food_confirm()
        self.dorm_feed_quit()

    def dorm_run(self, *, feed: bool = True, collect: bool = True, buy_furniture: bool = False) -> None:
        """从任意页面执行已启用的喂食、收集和家具购买，最后停在宿舍页。"""
        if not feed and not collect and not buy_furniture:
            return

        self.ui_ensure(page_dormmenu)
        self.handle_info_bar()
        # 宿舍卡片红点动画较慢，不再用 DORM_RED_DOT 跳过收集。
        self.ui_goto(page_dorm, skip_first_screenshot=True)

        # 先喂食以处理 DORM_INFO；它可能遮挡宿舍金币和爱心。
        if feed:
            logger.hr("Dorm feed", level=1)
            self.dorm_feed_enter()
            self.dorm_feed()
            self.dorm_feed_quit()

        if collect:
            logger.hr("Dorm collect", level=1)
            self.dorm_collect()

        if buy_furniture:
            logger.hr("Dorm buy furniture", level=1)
            BuyFurniture(self.config, self.device).run()

    def get_dorm_ship_amount(self) -> int:
        """在宿舍页 OCR 当前舰船数。"""
        timeout = Timer(2, count=4).start()
        current = 0
        for _ in self.loop():
            if self.appear_then_click(dorm_assets.DORM_FURNITURE_CONFIRM, offset=(30, 30), interval=3):
                timeout.reset()
                continue
            if self.ui_additional(get_ship=False):
                timeout.reset()
                continue

            current, _, total = OCR_SLOT.ocr(self.device.image)

            if timeout.reached():
                logger.warning("Get dorm slots timeout")
                break
            if total == 0:
                continue
            if current not in [0, 1, 2, 3, 4, 5, 6]:
                logger.warning(f"Invalid dorm slot amount: {current}")
                continue
            break

        return current
