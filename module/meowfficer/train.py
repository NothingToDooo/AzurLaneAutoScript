from typing import TYPE_CHECKING

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.logger import logger
from module.meowfficer import assets as meow_assets
from module.meowfficer.collect import MeowfficerCollect
from module.meowfficer.enhance import MeowfficerEnhance
from module.ocr.ocr import Digit, DigitCounter

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.device.device import Device

MEOWFFICER_CAPACITY = DigitCounter(meow_assets.OCR_MEOWFFICER_CAPACITY, letter=(131, 121, 123), threshold=64)
MEOWFFICER_QUEUE = DigitCounter(meow_assets.OCR_MEOWFFICER_QUEUE, letter=(131, 121, 123), threshold=64)
MEOWFFICER_BOX_GRID = ButtonGrid(
    origin=(460, 210), delta=(160, 0), button_shape=(30, 30), grid_shape=(3, 1), name="MEOWFFICER_BOX_GRID"
)
MEOWFFICER_BOX_COUNT_GRID = ButtonGrid(
    origin=(776, 21), delta=(133, 0), button_shape=(65, 27), grid_shape=(3, 1), name="MEOWFFICER_BOX_COUNT_GRID"
)
MEOWFFICER_BOX_COUNT = Digit(
    MEOWFFICER_BOX_COUNT_GRID.buttons, letter=(99, 69, 41), threshold=128, name="MEOWFFICER_BOX_COUNT"
)


class MeowfficerTrain(MeowfficerCollect, MeowfficerEnhance):
    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
    ) -> None:
        self._box_count: list[int] = [0, 0, 0]
        super().__init__(config, device)

    def _meow_queue_enter(self, *, skip_first_screenshot: bool = True) -> bool:
        """进入猫箱排队页，最多尝试三次。"""
        timeout_count = 3
        self.handle_info_bar()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.appear(meow_assets.MEOWFFICER_TRAIN_FILL_QUEUE, offset=(20, 20)) and self.appear(
                meow_assets.MEOWFFICER_TRAIN_START, offset=(20, 20), interval=3
            ):
                if timeout_count > 0:
                    self.device.click(meow_assets.MEOWFFICER_TRAIN_START)
                    timeout_count -= 1
                else:
                    return False

            if self.appear(meow_assets.MEOWFFICER_TRAIN_FILL_QUEUE, offset=(20, 20)):
                return True
            if self.info_bar_count():
                logger.info("No more slots to train, exit")
                return False
        return False

    def _meow_nqueue(self, *, skip_first_screenshot: bool = True) -> None:
        """在训练页自动填满空槽，稀有猫箱优先。"""
        # 循环处理上一步操作可能引发的页面跳转。
        confirm_timer = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.info_bar_count():
                confirm_timer.reset()
                continue
            if self.appear_then_click(meow_assets.MEOWFFICER_TRAIN_FILL_QUEUE, offset=(20, 20), interval=5):
                self.device.sleep(0.3)
                self.device.click(meow_assets.MEOWFFICER_TRAIN_START)
                confirm_timer.reset()
                continue
            if self.handle_meow_popup_confirm():
                confirm_timer.reset()
                continue

            if self.appear(meow_assets.MEOWFFICER_TRAIN_START, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def _meow_rqueue(self) -> None:
        """在训练页手动填满空槽，普通猫箱优先。"""
        # 使用本地箱数保证多次点击后的计数准确。
        local_count = self._box_count.copy()
        buttons = MEOWFFICER_BOX_GRID.buttons
        while 1:
            # 可排队数量。
            _current, remain, _total = MEOWFFICER_QUEUE.ocr(self.device.image)
            if not remain:
                break

            for i, j in ((0, 2), (1, 1)):
                logger.attr(f"Meowfficer_box_count_rqueue_during (index {i})", local_count)
                count = local_count[i] - remain
                if count < 0:
                    self.device.multi_click(buttons[j], remain + count)
                    local_count[i] -= remain + count
                    remain = abs(count)
                else:
                    self.device.multi_click(buttons[j], remain)
                    local_count[i] -= remain
                    break

            logger.attr("Meowfficer_box_count_rqueue_done", local_count)
            self.device.sleep((0.3, 0.5))
            self.device.screenshot()

        self._meow_nqueue()

    def meow_queue(self, *, ascending: bool = True) -> None:
        """在训练页排队；ascending=True 按蓝、紫、金顺序，否则反向。"""
        logger.hr("Meowfficer queue", level=1)
        if not self._meow_queue_enter():
            return

        common_sum = self._box_count[0] + self._box_count[1]

        if sum(self._box_count) <= 0:
            logger.info("No more meowfficer boxes to train")
            return

        # 普通箱超过 20 时优先消耗；库存较低则仍按稀有度倒序自动排队。
        if ascending:
            if common_sum > 20:
                logger.info("Queue in ascending order (Blue > Purple > Gold)")
                self._meow_rqueue()
            else:
                logger.info("Low stock of common cat boxes")
                logger.info("Queue in descending order (Gold > Purple > Blue)")
                self._meow_nqueue()
        else:
            logger.info("Queue in descending order (Gold > Purple > Blue)")
            self._meow_nqueue()

    def meow_train(self) -> bool:
        """在指挥喵主页领取训练结果并重新排队猫箱。"""
        logger.hr("Meowfficer train", level=1)

        # 读取容量，用来判断是否可以领取。
        _current, remain, _total = MEOWFFICER_CAPACITY.ocr(self.device.image)
        logger.attr("Meowfficer_capacity_remain", remain)

        # 读取箱子数量，供其他辅助函数使用。
        self._box_count = MEOWFFICER_BOX_COUNT.ocr_regions(self.device.image)

        logger.attr("MeowfficerTrain_Mode", self.config.MeowfficerTrain_Mode)
        collected = False
        if self.config.MeowfficerTrain_Mode == "seamlessly":
            self.meow_enter(meow_assets.MEOWFFICER_TRAIN_ENTER, check_button=meow_assets.MEOWFFICER_TRAIN_START)
            if remain > 0:
                collected = self.meow_collect(collect_all=True)
            self.meow_queue(ascending=False)
            self.meow_menu_close()
        else:
            self.meow_enter(meow_assets.MEOWFFICER_TRAIN_ENTER, check_button=meow_assets.MEOWFFICER_TRAIN_START)
            if remain > 0:
                collected = self.meow_collect(collect_all=self.meow_is_sunday())
            self.meow_queue(ascending=False)
            self.meow_menu_close()

        return collected
