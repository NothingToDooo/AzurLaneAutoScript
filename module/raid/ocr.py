from typing import TYPE_CHECKING

import cv2
import numpy as np

from module.logger import logger
from module.ocr.ocr import Digit, DigitCounter, DigitCounterValue

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray


class PaddedRaidCounter(DigitCounter):
    def pre_process(self, image: ImageArray) -> ImageArray:
        image = super().pre_process(image)
        return np.pad(image, ((2, 2), (0, 0)), mode="constant", constant_values=255)


class CompactRaidCounter(DigitCounter):
    @staticmethod
    def normalize_text(result: str) -> str:
        """修复缺少分隔符的 915/、1515 等紧凑读数。"""
        result = DigitCounter.normalize_text(result)
        result = result.strip("/")
        if result.isdigit() and len(result) > 2 and result.endswith("15"):
            result = f"{result[:-2]}/15"
        return result


class HuanChangRemainCounter(DigitCounter):
    """寰昌 profile 的次数纵向排列，单个数字表示已用次数。"""

    def after_process(self, result: str) -> DigitCounterValue:
        normalized = self.normalize_text(result)
        value = int(normalized) if normalized else 0
        if self.SHOW_REVISE_WARNING and str(value) != normalized:
            logger.warning(f'OCR {self.name}: Result "{normalized}" is revised to "{value}"')
        return value, 0, 15


class HuanChangPointOcr(Digit):
    """寰昌 profile 的 PT 区域使用连通域提取数字。"""

    def pre_process(self, image: ImageArray) -> ImageArray:
        gray = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
        binary = np.asarray(cv2.threshold(gray, self.threshold, 255, cv2.THRESH_BINARY_INV)[1], dtype=np.uint8)
        count, connected = cv2.connectedComponents(binary)
        # 面积大于 60 的连通域视为数字；英语服需同时排除右上、右下背景连通域。
        digit_indexes = [
            index
            for index in range(1, count + 1)
            if index != connected[0, -1] and index != connected[-1, -1] and np.count_nonzero(connected == index) > 60
        ]
        mask = ~(np.isin(connected, digit_indexes) * 255)
        return mask.astype(np.uint8)
