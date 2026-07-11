from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

import cv2
import imageio
import numpy as np

from module.base.button import Button
from module.base.decorator import cached_property
from module.base.resource import Resource
from module.base.utils import area_offset, load_image, rgb2luma
from module.map_detection.utils import Points

if TYPE_CHECKING:
    from module.base.type_alias import FilePath, ImageArray, Point, Scalar


class Template(Resource):
    def __init__(self, file: FilePath) -> None:
        """file 可传模板路径或按服务器选择路径的映射。"""
        self.raw_file = file
        self._image: ImageArray | list[ImageArray] | None = None
        self._image_binary: ImageArray | list[ImageArray] | None = None
        self._image_luma: ImageArray | list[ImageArray] | None = None

        self.resource_add(self.file)

    cached: ClassVar[tuple[str, ...]] = ("file", "name", "is_gif")

    @cached_property
    def file(self) -> FilePath:
        return self.parse_property(self.raw_file)

    @cached_property
    def name(self) -> str:
        return Path(self.file).stem.upper()

    @cached_property
    def is_gif(self) -> bool:
        return Path(self.file).suffix == ".gif"

    @property
    def image(self) -> ImageArray | list[ImageArray]:
        if self._image is None:
            if self.is_gif:
                images: list[ImageArray] = []
                channel = 0
                for frame in imageio.mimread(Path(self.file)):
                    if not channel:
                        channel = len(frame.shape)
                    if channel == 3:
                        image = frame[:, :, :3].copy()
                    elif len(frame.shape) == 3:
                        # 所有帧都沿用首帧的通道数。
                        image = frame[:, :, 0].copy()
                    else:
                        image = frame

                    image = self.pre_process(cast("ImageArray", image))
                    images.extend((image, cast("ImageArray", cv2.flip(image, 1))))
                self._image = images
            else:
                self._image = self.pre_process(load_image(self.file))

        return self._image

    @property
    def image_binary(self) -> ImageArray | list[ImageArray]:
        if self._image_binary is None:
            if self.is_gif:
                binary_images: list[ImageArray] = []
                for image in cast("list[ImageArray]", self.image):
                    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                    binary_images.append(cast("ImageArray", image_binary))
                self._image_binary = binary_images
            else:
                image_gray = cv2.cvtColor(cast("ImageArray", self.image), cv2.COLOR_BGR2GRAY)
                _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                self._image_binary = cast("ImageArray", image_binary)

        return self._image_binary

    @property
    def image_luma(self) -> ImageArray | list[ImageArray]:
        if self._image_luma is None:
            if self.is_gif:
                self._image_luma = [rgb2luma(image) for image in cast("list[ImageArray]", self.image)]
            else:
                self._image_luma = rgb2luma(cast("ImageArray", self.image))

        return self._image_luma

    @image.setter
    def image(self, value: ImageArray | list[ImageArray]) -> None:
        self._image = value

    def resource_release(self) -> None:
        super().resource_release()
        self._image = None
        self._image_binary = None
        self._image_luma = None

    @staticmethod
    def pre_process(image: ImageArray) -> ImageArray:
        """供子类覆盖的模板预处理钩子。"""
        return image

    @cached_property
    def size(self) -> tuple[int, int]:
        shape = cast("list[ImageArray]", self.image)[0].shape if self.is_gif else cast("ImageArray", self.image).shape
        return int(shape[1]), int(shape[0])

    def match(self, image: ImageArray, scaling: float = 1.0, similarity: float = 0.85) -> bool:
        """按 scaling 缩放待测图后匹配模板；similarity 范围为 0～1。"""
        scaling = 1 / scaling
        if scaling != 1.0:
            image = cast("ImageArray", cv2.resize(image, None, fx=scaling, fy=scaling))

        if self.is_gif:
            for template in cast("list[ImageArray]", self.image):
                res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                _, sim, _, _ = cv2.minMaxLoc(res)
                if sim > similarity:
                    return True

            return False

        res = cv2.matchTemplate(image, cast("ImageArray", self.image), cv2.TM_CCOEFF_NORMED)
        _, sim, _, _ = cv2.minMaxLoc(res)
        return sim > similarity

    def match_binary(self, image: ImageArray, similarity: float = 0.85) -> bool:
        """在 Otsu 二值图上匹配模板。"""
        if self.is_gif:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            for template in cast("list[ImageArray]", self.image_binary):
                res = cv2.matchTemplate(template, image_binary, cv2.TM_CCOEFF_NORMED)
                _, sim, _, _ = cv2.minMaxLoc(res)
                if sim > similarity:
                    return True

            return False

        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        res = cv2.matchTemplate(cast("ImageArray", self.image_binary), image_binary, cv2.TM_CCOEFF_NORMED)
        _, sim, _, _ = cv2.minMaxLoc(res)
        return sim > similarity

    def match_luma(self, image: ImageArray, similarity: float = 0.85) -> bool:
        if self.is_gif:
            image = rgb2luma(image)
            for template in cast("list[ImageArray]", self.image_luma):
                res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                _, sim, _, _ = cv2.minMaxLoc(res)
                if sim > similarity:
                    return True

            return False

        res = cv2.matchTemplate(image, cast("ImageArray", self.image), cv2.TM_CCOEFF_NORMED)
        _, sim, _, _ = cv2.minMaxLoc(res)
        return sim > similarity

    def _point_to_button(self, point: Point, image: ImageArray | None = None, name: str | None = None) -> Button:
        if name is None:
            name = self.name
        area = area_offset(area=(0, 0, *self.size), offset=point)
        button = Button(area=area, color=(), button=area, name=name)
        if image is not None:
            button.load_color(image)
        return button

    def match_result(self, image: ImageArray, name: str | None = None) -> tuple[float, Button]:
        """返回最佳匹配的相似度和对应 Button。"""
        res = cv2.matchTemplate(image, cast("ImageArray", self.image), cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)

        button = self._point_to_button((int(point[0]), int(point[1])), image=image, name=name)
        return sim, button

    def match_luma_result(self, image: ImageArray, name: str | None = None) -> tuple[float, Button]:
        image = rgb2luma(image)
        res = cv2.matchTemplate(image, cast("ImageArray", self.image_luma), cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)

        button = self._point_to_button((int(point[0]), int(point[1])), image=image, name=name)
        return sim, button

    def match_multi(
        self,
        image: ImageArray,
        scaling: float = 1.0,
        similarity: float = 0.85,
        threshold: Scalar = 3,
        name: str | None = None,
    ) -> list[Button]:
        """返回全部匹配按钮；threshold 是合并相邻结果的像素距离。"""
        scaling = 1 / scaling
        if scaling != 1.0:
            image = cast("ImageArray", cv2.resize(image, None, fx=scaling, fy=scaling))

        raw = image
        if self.is_gif:
            result = []
            for template in cast("list[ImageArray]", self.image):
                res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                res = np.array(np.where(res > similarity)).T[:, ::-1].tolist()
                result += res
            result = np.array(result)
        else:
            result = cv2.matchTemplate(image, cast("ImageArray", self.image), cv2.TM_CCOEFF_NORMED)
            result = np.array(np.where(result > similarity)).T[:, ::-1]

        # result 形状为 (n, 2)，每行是一个 (x, y) 坐标。
        if scaling != 1.0:
            result = np.round(result / scaling).astype(int)
        result = Points(result).group(threshold=threshold)
        return [self._point_to_button((int(point[0]), int(point[1])), image=raw, name=name) for point in result]
