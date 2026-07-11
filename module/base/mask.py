from typing import TYPE_CHECKING, cast

import cv2

from module.base.template import Template
from module.base.utils import image_channel, load_image, rgb2gray

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray


class Mask(Template):
    @property
    def image(self) -> ImageArray:
        if self._image is None:
            image = load_image(self.file)
            if image_channel(image) == 3:
                image = rgb2gray(image)
            self._image = image

        return cast("ImageArray", self._image)

    @image.setter
    def image(self, value: ImageArray) -> None:
        self._image = value

    def set_channel(self, channel: int) -> bool:
        """把掩码切换为单通道 0 或 RGB 三通道 3；实际发生转换时返回 True。"""
        mask_channel = image_channel(self.image)
        if channel == 0:
            if mask_channel == 0:
                return False
            first_channel, _, _ = cv2.split(cast("ImageArray", self._image))
            self._image = cast("ImageArray", first_channel)
            return True
        if mask_channel == 0:
            merged = cv2.merge([cast("ImageArray", self._image)] * 3)
            self._image = cast("ImageArray", merged)
            return True
        return False

    def apply(self, image: ImageArray) -> ImageArray:
        self.set_channel(image_channel(image))
        return cast("ImageArray", cv2.bitwise_and(image, self.image))
