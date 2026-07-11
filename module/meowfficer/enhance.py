from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.logger import logger
from module.meowfficer import assets as meow_assets
from module.meowfficer.base import MeowfficerBase
from module.meowfficer.buy import MEOWFFICER_COINS
from module.ocr.ocr import Digit, DigitCounter, ocr_options
from module.ui.assets import MEOWFFICER_GOTO_DORMMENU
from module.ui.page import page_meowfficer

MEOWFFICER_SELECT_GRID = ButtonGrid(
    origin=(751, 237), delta=(130, 147), button_shape=(70, 20), grid_shape=(4, 3), name="MEOWFFICER_SELECT_GRID"
)
MEOWFFICER_FEED_GRID = ButtonGrid(
    origin=(783, 189), delta=(130, 148), button_shape=(46, 46), grid_shape=(4, 3), name="MEOWFFICER_FEED_GRID"
)
MEOWFICER_FEED_LEVEL_GRID = ButtonGrid(
    origin=(738, 211), delta=(130, 148), button_shape=(20, 22), grid_shape=(4, 3), name="MEOWFFICER_FEED_LEVEL_GRID"
)
MEOWFFICER_FEED = DigitCounter(meow_assets.OCR_MEOWFFICER_FEED, letter=(131, 121, 123), threshold=64)


class MeowfficerLevelOcr(Digit):
    def __init__(self, buttons, options=None, **settings):
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789IDSLV"))

    def after_process(self, result):
        result = result.replace("L", "").replace("V", "").replace(".", "")
        return super().after_process(result)


OCR_MEOWFFICER_ENHANCE_LEVEL = MeowfficerLevelOcr(
    meow_assets.OCR_MEOWFFICER_ENHANCE_LEVEL, name="OCR_MEOWFFICER_ENHANCE_LEVEL"
)


class MeowfficerEnhance(MeowfficerBase):
    def _meow_select(self, skip_first_screenshot=True):
        """在 4×3 网格选择强化目标，并以黄白虚线圆确认选中。"""
        index = self.config.MeowfficerTrain_EnhanceIndex - 1
        x = index if index < 4 else index % 4
        y = index // 4

        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.meow_additional():
                click_timer.reset()
                continue

            if self.image_color_count(MEOWFFICER_SELECT_GRID[x, y], color=(255, 255, 255), threshold=246, count=100):
                break

            if click_timer.reached():
                self.device.click(MEOWFFICER_FEED_GRID[x, y])
                click_timer.reset()

    def meow_feed_scan(self):
        """在 4×3 喂养网格返回未选中且不超过等级上限的可点击按钮。"""
        clickable = []

        reset_max_feed_level = -1
        if self.config.MeowfficerTrain_MaxFeedLevel < 1:
            reset_max_feed_level = 1
        elif self.config.MeowfficerTrain_MaxFeedLevel > 30:
            reset_max_feed_level = 30

        if reset_max_feed_level != -1:
            logger.warning(
                f"Condition '1 <= MeowfficerTrain_MaxFeedLevel <= 30' needs to be satisfied, "
                f"now MeowfficerTrain_MaxFeedLevel is {self.config.MeowfficerTrain_MaxFeedLevel}, "
                f"reset to {reset_max_feed_level}"
            )
            self.config.MeowfficerTrain_MaxFeedLevel = reset_max_feed_level

        feed_level_list = Digit(
            MEOWFICER_FEED_LEVEL_GRID.buttons, letter=(49, 48, 49), name="FEED_MEOWFFICER_LEVEL"
        ).ocr(self.device.image)

        for index, (button, level) in enumerate(zip(MEOWFFICER_FEED_GRID.buttons, feed_level_list, strict=False)):
            # 到第 11 个按钮时退出；后续位置无法点击，不需要继续验证。
            if index >= 10:
                break

            # 遇到空槽位时退出。
            if self.image_color_count(button, color=(231, 223, 221), threshold=235, count=450):
                break

            if self.image_color_count(button, color=(95, 229, 108), threshold=221, count=150):
                continue

            if level > self.config.MeowfficerTrain_MaxFeedLevel:
                continue

            clickable.append(button)

        logger.info(f"Total feed material found: {len(clickable)}")
        return clickable

    def meow_feed_select(self):
        """在喂养页选择材料并回到强化页，返回选中数量。"""
        self.interval_clear(
            [
                meow_assets.MEOWFFICER_FEED_CONFIRM,
                meow_assets.MEOWFFICER_FEED_CANCEL,
                meow_assets.MEOWFFICER_ENHANCE_CONFIRM,
            ]
        )
        current = 0
        retry = Timer(1, count=2)
        skip_first_screenshot = True

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            current, remain, _total = MEOWFFICER_FEED.ocr(self.device.image)
            if not remain:
                break

            buttons = self.meow_feed_scan()
            if not len(buttons):
                break

            if retry.reached():
                for button in buttons:
                    self.device.click(button)
                retry.reset()

        if current:
            logger.info(f"Confirm selected feed material, total: {current} / 10")
            self.ui_click(
                meow_assets.MEOWFFICER_FEED_CONFIRM,
                check_button=meow_assets.MEOWFFICER_ENHANCE_CONFIRM,
                offset=(20, 20),
                skip_first_screenshot=True,
            )
        else:
            logger.info("Lack of feed material to complete enhancement, cancelling")
            self.ui_click(
                meow_assets.MEOWFFICER_FEED_CANCEL,
                check_button=meow_assets.MEOWFFICER_ENHANCE_CONFIRM,
                offset=(10, 10),
                skip_first_screenshot=True,
            )
        return current

    def meow_feed_enter(self, skip_first_screenshot=True):
        """进入喂养选择页；连续三次失败通常表示目标已到 30 级。"""
        click_count = 0
        confirm_timer = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(meow_assets.MEOWFFICER_FEED_ENTER, offset=(20, 20), interval=3):
                click_count += 1
                continue

            if self.appear(meow_assets.MEOWFFICER_FEED_CONFIRM, offset=(20, 20)) and confirm_timer.reached():
                return True
            if click_count >= 3:
                logger.warning(
                    "Unable to enter meowfficer feed, probably because the meowfficer to enhance has reached LV.30"
                )
                return False
        return False

    def meow_enhance_confirm(self, skip_first_screenshot=True):
        """在强化页确认喂养材料，并等待回到同一页面。"""
        self.interval_clear(
            [
                meow_assets.MEOWFFICER_FEED_ENTER,
                meow_assets.MEOWFFICER_ENHANCE_CONFIRM,
                meow_assets.MEOWFFICER_CONFIRM,
            ]
        )
        confirm_timer = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(meow_assets.MEOWFFICER_FEED_ENTER, offset=(20, 20)):
                if confirm_timer.reached():
                    break
                continue

            if self.handle_meow_popup_confirm():
                confirm_timer.reset()
                continue
            if self.appear_then_click(meow_assets.MEOWFFICER_ENHANCE_CONFIRM, offset=(20, 20), interval=3):
                confirm_timer.reset()
                continue

    def meow_enhance_enter(self, skip_first_screenshot=True):
        """从强化入口进入喂养页；目标出战时多次点击后返回 False。"""
        count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(meow_assets.MEOWFFICER_FEED_ENTER, offset=(20, 20)):
                return True
            if count > 3:
                logger.warning("Too many click on MEOWFFICER_ENHANCE_ENTER, meowfficer may in battle")
                return False

            if self.appear_then_click(meow_assets.MEOWFFICER_ENHANCE_ENTER, offset=(20, 20), interval=3):
                count += 1
                continue
            if self.meow_additional():
                continue
            if self.handle_game_tips():
                continue
        return False

    def _meow_get_level(self):
        """在强化入口 OCR 1～30 级；无法识别时返回 0。"""
        level = OCR_MEOWFFICER_ENHANCE_LEVEL.ocr(self.device.image)
        if level > 30:
            logger.warning(f"Invalid meowfficer level: {level}")
        return level

    def _meow_enhance(self):
        """在主页强化指挥喵，返回 invalid、coin_limit、leveled_max、in_battle 或 success。"""
        logger.hr("Meowfficer enhance", level=1)
        logger.attr("MeowfficerTrain_EnhanceIndex", self.config.MeowfficerTrain_EnhanceIndex)

        if not (1 <= self.config.MeowfficerTrain_EnhanceIndex <= 12):
            logger.warning(
                f"Meowfficer_EnhanceIndex={self.config.MeowfficerTrain_EnhanceIndex} "
                f"is out of bounds. Please limit to 1~12, skip"
            )
            return "invalid"

        coins = MEOWFFICER_COINS.ocr(self.device.image)
        if coins < 1000:
            logger.info(f"Coins ({coins}) < 1000. Not enough coins to complete enhancement, skip")
            return "coin_limit"

        for _ in range(2):
            self._meow_select()

            if self._meow_get_level() >= 30:
                logger.info("Current meowfficer is already leveled max")
                return "leveled_max"

            # 选择后进入 MEOWFFICER_FEED；由于 meow_additional 明显延迟，这里拆开处理。
            if self.meow_enhance_enter():
                break
            self.ui_goto_campaign()
            self.ui_goto(page_meowfficer)
            continue

        while 1:
            logger.hr("Enhance once", level=2)
            if not self.meow_feed_enter():
                self.ui_click(
                    MEOWFFICER_GOTO_DORMMENU,
                    check_button=meow_assets.MEOWFFICER_ENHANCE_ENTER,
                    appear_button=meow_assets.MEOWFFICER_ENHANCE_CONFIRM,
                    offset=None,
                    skip_first_screenshot=True,
                )
                self.ui_goto_main()
                self.ui_goto(page_meowfficer)
                return "in_battle"
            if not self.meow_feed_select():
                break
            self.meow_enhance_confirm()

            coins = MEOWFFICER_COINS.ocr(self.device.image)
            if coins < 1000:
                logger.info(f"Remaining coins ({coins}) < 1000. Not enough coins for next enhancement, skip")
                break

        self.ui_click(
            MEOWFFICER_GOTO_DORMMENU,
            check_button=meow_assets.MEOWFFICER_ENHANCE_ENTER,
            appear_button=meow_assets.MEOWFFICER_ENHANCE_CONFIRM,
            offset=None,
            skip_first_screenshot=True,
        )
        return "success"

    def meow_enhance(self):
        """目标达到 30 级时自动递增强化索引。"""
        while 1:
            result = self._meow_enhance()
            if result != "leveled_max":
                break

            if self.config.MeowfficerTrain_EnhanceIndex < 12:
                self.config.MeowfficerTrain_EnhanceIndex += 1
                logger.info(f"Increase MeowfficerTrain_EnhanceIndex to {self.config.MeowfficerTrain_EnhanceIndex}")
                continue
            logger.warning("The 12th meowfficer reached LV.30, disable MeowfficerTrain")
            self.config.MeowfficerTrain_Enable = False
            break
