import re
from typing import TYPE_CHECKING, override

import cv2
import numpy as np

from module.base.timer import Timer
from module.base.utils import _cv_scalar, color_similar, get_color
from module.campaign.assets import OCR_COIN as OCR_COIN_BUTTON
from module.campaign.assets import OCR_EVENT_PT, OCR_OIL, OCR_OIL_CHECK
from module.logger import logger
from module.ocr.ocr import Digit, Ocr
from module.ui.ui import UI

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray

OCR_COIN = Digit(OCR_COIN_BUTTON, name="OCR_COIN", letter=(239, 239, 239), threshold=128)


class PtOcr(Ocr[str]):
    @override
    def pre_process(self, image: ImageArray) -> ImageArray:
        """把 (高, 宽, 通道) 图像转为同尺寸二维 uint8 OCR 灰度图。"""
        # 按 RGB 三通道最大值构造反色灰度图。
        r, g, b = cv2.split(cv2.subtract(_cv_scalar((255, 255, 255, 0)), image))
        grayscale = cv2.min(cv2.min(r, g), b)
        # 去除背景并把 0～192 拉伸到 0～255。
        processed = cv2.multiply(grayscale, _cv_scalar((255 / 192, 255 / 192, 255 / 192, 255 / 192)))

        return processed.astype(np.uint8)


OCR_PT = PtOcr(OCR_EVENT_PT, lang="azur_lane", alphabet="X0123456789")


class CampaignStatus(UI):
    def get_event_pt(self) -> int:
        pt = OCR_PT.ocr_single(self.device.image)

        res = re.search(r"X(\d+)", pt)
        if res:
            pt = int(res.group(1))
            logger.attr("Event_PT", pt)
            return pt
        logger.warning(f"Invalid pt result: {pt}")
        return 0

    def get_coin(self, *, skip_first_screenshot: bool = True) -> int:
        amount = 0
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning("Get coin timeout")
                break

            amount = OCR_COIN.ocr_single(self.device.image)
            if amount >= 100:
                break

        return amount

    def _get_oil(self) -> int:
        # appear 会更新按钮偏移，后续取色依赖该位置。
        _ = self.appear(OCR_OIL_CHECK)

        color = get_color(self.device.image, OCR_OIL_CHECK.button)
        if color_similar(color, OCR_OIL_CHECK.color):
            # 原始颜色。
            ocr = Digit(OCR_OIL, name="OCR_OIL", letter=(247, 247, 247), threshold=128)
        elif color_similar(color, (59, 59, 64)):
            # 黑色遮罩颜色。
            ocr = Digit(OCR_OIL, name="OCR_OIL", letter=(165, 165, 165), threshold=128)
        else:
            logger.warning("Unexpected OCR_OIL_CHECK color")
            ocr = Digit(OCR_OIL, name="OCR_OIL", letter=(247, 247, 247), threshold=128)

        return ocr.ocr_single(self.device.image)

    def get_oil(self, *, skip_first_screenshot: bool = True) -> int:
        amount = 0
        timeout = Timer(1, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning("Get oil timeout")
                break

            if not self.appear(OCR_OIL_CHECK, offset=(10, 2)):
                logger.info("No oil icon")
                continue

            amount = self._get_oil()
            if amount >= 100:
                break

        return amount

    def is_balancer_task(self) -> bool:
        tasks = [
            "Event",
            "Event2",
            "Raid",
            "Coalition",
            "GemsFarming",
        ]
        command = self.config.Scheduler_Command
        return command in tasks and self.config.Campaign_Event != "campaign_main"
