from typing import TYPE_CHECKING, cast

import cv2
import numpy as np

from module.base.decorator import cached_property
from module.base.mask import Mask
from module.base.utils import crop

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray

UI_MASK = Mask(file="./assets/mask/MASK_MAP_UI.png")
UI_MASK_OS = Mask(file="./assets/mask/MASK_OS_MAP_UI.png")
TILE_CENTER = Mask(file="./assets/map_detection/TILE_CENTER.png")
TILE_CORNER = Mask(file="./assets/map_detection/TILE_CORNER.png")
DETECTING_AREA = (123, 55, 1280, 720)


class Assets:
    _ui_mask = UI_MASK
    _ui_mask_os = UI_MASK_OS
    _tile_center = TILE_CENTER
    _tile_corner = TILE_CORNER

    @cached_property
    def ui_mask(self) -> ImageArray:
        return self._ui_mask.image

    @cached_property
    def ui_mask_os(self) -> ImageArray:
        return self._ui_mask_os.image

    @cached_property
    def ui_mask_stroke(self) -> ImageArray:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        return cast("ImageArray", cv2.erode(self.ui_mask, kernel).astype("uint8"))

    @cached_property
    def ui_mask_in_map(self) -> ImageArray:
        area = np.append(np.subtract(0, DETECTING_AREA[:2]), self.ui_mask.shape[::-1])
        return crop(self.ui_mask, area)

    @cached_property
    def ui_mask_os_in_map(self) -> ImageArray:
        area = np.append(np.subtract(0, DETECTING_AREA[:2]), self.ui_mask.shape[::-1])
        return crop(self.ui_mask_os, area)

    @cached_property
    def tile_center_image(self) -> ImageArray:
        return self._tile_center.image

    @cached_property
    def tile_corner_image(self) -> ImageArray:
        return self._tile_corner.image

    @cached_property
    def tile_corner_image_list(self) -> list[ImageArray]:
        # 顺序：左上、右上、左下、右下。
        return [
            cast("ImageArray", cv2.flip(self.tile_corner_image, -1)),
            cast("ImageArray", cv2.flip(self.tile_corner_image, 0)),
            cast("ImageArray", cv2.flip(self.tile_corner_image, 1)),
            self.tile_corner_image,
        ]


ASSETS = Assets()
