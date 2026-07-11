from typing import TYPE_CHECKING

import cv2
import numpy as np

from module.base.base import ModuleBase
from module.base.button import ButtonGrid
from module.base.utils import _cv_scalar
from module.logger import logger
from module.ocr.ocr import Digit

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray
    from module.config.config import AzurLaneConfig
    from module.device.device import Device


class Level(ModuleBase):
    def __init__(
        self,
        config: AzurLaneConfig | str,
        device: Device | str | None = None,
        task: str | None = None,
    ) -> None:
        self._lv = [-1] * 6
        self._lv_before_battle = [-1] * 6
        super().__init__(config=config, device=device, task=task)

    @property
    def lv(self) -> list[int]:
        return self._lv

    @lv.setter
    def lv(self, value: list[int]) -> None:
        self._lv = value

    def lv_reset(self) -> None:
        """进入地图后清空战前、战后等级缓存。"""
        self._lv = [-1] * 6
        self._lv_before_battle = [-1] * 6

    @staticmethod
    def _lv_grid() -> ButtonGrid:
        return ButtonGrid(origin=(58, 128), delta=(0, 100), button_shape=(46, 19), grid_shape=(1, 6))

    def lv_get(self, *, after_battle: bool = False) -> None:
        if not self.config.StopCondition_ReachLevel and not self.config.STOP_IF_REACH_LV32:
            return

        self._lv_before_battle = self.lv if after_battle else [-1] * 6

        ocr = LevelOcr(self._lv_grid().buttons, name="LevelOcr")
        self.lv = ocr.ocr_regions(self.device.image)
        logger.attr("LEVEL", ", ".join(str(data) for data in self.lv))

        if after_battle:
            self.lv_triggered()
            self.lv32_triggered()

    def lv_triggered(self) -> bool:
        limit = self.config.StopCondition_ReachLevel
        if not limit:
            return False

        for i in range(6):
            before, after = self._lv_before_battle[i], self.lv[i]
            if after > before > 0:
                logger.info(f"Position {i} LV.{before} -> LV.{after}")
            if after >= limit > before > 0:
                if after - before == 1 or after < 35:
                    logger.info(f"Position {i} LV.{limit} Reached")
                    self.config.LV_TRIGGERED = True
                    return True
                logger.warning(
                    f"Level gap between {before} and {after} is too large. This will not be considered as a trigger"
                )

        return False

    def lv32_triggered(self) -> bool:
        if not self.config.STOP_IF_REACH_LV32:
            return False

        if self.lv[0] >= 32:
            logger.info("Position 0 LV.32 Reached")
            self.config.LV32_TRIGGERED = True
            return True

        return False


class LevelOcr(Digit):
    COLOR_WHITE = (255, 255, 255)
    COLOR_MASKED = (107, 105, 107)

    def pre_process(self, image: ImageArray) -> ImageArray:
        # 仅检查上方 8 行：避开“需要维修”图标并保留 V 的上部；红通道最大值不超过 107 即视为遮罩。
        max_red = image[:8, :, 0].max()
        if max_red <= self.COLOR_MASKED[0]:
            # 低血量遮罩将白色 (255, 255, 255) 压成 (107, 105, 107)，按均值比例放大各通道以还原。
            scalar = np.mean(self.COLOR_WHITE) / np.mean(self.COLOR_MASKED)
            image = cv2.addWeighted(image, scalar, image, 0, 0).astype(np.uint8, copy=False)

        # 半透明蓝底将黑色变为 (33, 65, 115)、白色变为 (107, 138, 189)，取中点 (70, 102, 152) 消除背景。
        bg = (70, 102, 152)
        # 按 BT.601 亮度系数转为灰度。
        luma_trans = (0.299, 0.587, 0.114)
        luma_bg = np.dot(bg, luma_trans)
        image = cv2.subtract(image, _cv_scalar((*bg, 0))).dot(luma_trans).round().astype(np.uint8)
        image = cv2.subtract(
            _cv_scalar((255, 255, 255, 255)),
            cv2.multiply(image, _cv_scalar((255 / (255 - luma_bg),) * 4)),
        ).astype(np.uint8, copy=False)
        # 定位 L 后裁掉 LV. 前缀；找不到 L 时返回空白图。
        letter_l = np.nonzero(image[9:15, :].max(axis=0) < 127)[0]
        if len(letter_l):
            first_digit = letter_l[0] + 17
            if first_digit + 3 < 46:  # 等于等级按钮宽度。
                return image[:, first_digit:]
        return np.array([[255]], dtype=np.uint8)
