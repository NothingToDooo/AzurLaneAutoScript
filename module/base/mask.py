from typing import TYPE_CHECKING, cast

import cv2

from module.base.template import Template
from module.base.utils import image_channel, load_image, rgb2gray

if TYPE_CHECKING:
    import numpy as np


class Mask(Template):
    @property
    def image(self):
        if self._image is None:
            image = load_image(self.file)
            if image_channel(image) == 3:
                image = rgb2gray(image)
            self._image = image

        return self._image

    @image.setter
    def image(self, value):
        self._image = value

    def set_channel(self, channel):
        """把掩码切换为单通道 0 或 RGB 三通道 3；实际发生转换时返回 True。"""
        mask_channel = image_channel(self.image)
        if channel == 0:
            if mask_channel == 0:
                return False
            self._image, _, _ = cv2.split(cast("np.ndarray", self._image))
            return True
        if mask_channel == 0:
            self._image = cv2.merge([cast("np.ndarray", self._image)] * 3)
            return True
        return False

    def apply(self, image):
        self.set_channel(image_channel(image))
        return cv2.bitwise_and(image, self.image)
