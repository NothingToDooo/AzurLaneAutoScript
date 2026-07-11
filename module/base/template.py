from pathlib import Path
from typing import ClassVar

import cv2
import imageio
import numpy as np

from module.base.button import Button
from module.base.decorator import cached_property
from module.base.resource import Resource
from module.base.utils import area_offset, load_image, rgb2luma
from module.map_detection.utils import Points


class Template(Resource):
    def __init__(self, file):
        """file 可传模板路径或按服务器选择路径的映射。"""
        self.raw_file = file
        self._image = None
        self._image_binary = None
        self._image_luma = None

        self.resource_add(self.file)

    cached: ClassVar[tuple[str, ...]] = ("file", "name", "is_gif")

    @cached_property
    def file(self):
        return self.parse_property(self.raw_file)

    @cached_property
    def name(self):
        return Path(self.file).stem.upper()

    @cached_property
    def is_gif(self):
        return Path(self.file).suffix == ".gif"

    @property
    def image(self):
        if self._image is None:
            if self.is_gif:
                self._image = []
                channel = 0
                for frame in imageio.mimread(self.file):
                    if not channel:
                        channel = len(frame.shape)
                    if channel == 3:
                        image = frame[:, :, :3].copy()
                    elif len(frame.shape) == 3:
                        # 所有帧都沿用首帧的通道数。
                        image = frame[:, :, 0].copy()
                    else:
                        image = frame

                    image = self.pre_process(image)
                    self._image += [image, cv2.flip(image, 1)]
            else:
                self._image = self.pre_process(load_image(self.file))

        return self._image

    @property
    def image_binary(self):
        if self._image_binary is None:
            if self.is_gif:
                self._image_binary = []
                for image in self.image:
                    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                    self._image_binary.append(image_binary)
            else:
                image_gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
                _, self._image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        return self._image_binary

    @property
    def image_luma(self):
        if self._image_luma is None:
            if self.is_gif:
                self._image_luma = []
                for image in self.image:
                    luma = rgb2luma(image)
                    self.image_luma.append(luma)
            else:
                self._image_luma = rgb2luma(self.image)

        return self._image_luma

    @image.setter
    def image(self, value):
        self._image = value

    def resource_release(self):
        super().resource_release()
        self._image = None
        self._image_binary = None
        self._image_luma = None

    def pre_process(self, image):
        """供子类覆盖的模板预处理钩子。"""
        return image

    @cached_property
    def size(self):
        if self.is_gif:
            return self.image[0].shape[0:2][::-1]
        return self.image.shape[0:2][::-1]

    def match(self, image, scaling=1.0, similarity=0.85):
        """按 scaling 缩放待测图后匹配模板；similarity 范围为 0～1。"""
        scaling = 1 / scaling
        if scaling != 1.0:
            image = cv2.resize(image, None, fx=scaling, fy=scaling)

        if self.is_gif:
            for template in self.image:
                res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                _, sim, _, _ = cv2.minMaxLoc(res)
                if sim > similarity:
                    return True

            return False

        res = cv2.matchTemplate(image, self.image, cv2.TM_CCOEFF_NORMED)
        _, sim, _, _ = cv2.minMaxLoc(res)
        return sim > similarity

    def match_binary(self, image, similarity=0.85):
        """在 Otsu 二值图上匹配模板。"""
        if self.is_gif:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            for template in self.image_binary:
                res = cv2.matchTemplate(template, image_binary, cv2.TM_CCOEFF_NORMED)
                _, sim, _, _ = cv2.minMaxLoc(res)
                if sim > similarity:
                    return True

            return False

        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        res = cv2.matchTemplate(self.image_binary, image_binary, cv2.TM_CCOEFF_NORMED)
        _, sim, _, _ = cv2.minMaxLoc(res)
        return sim > similarity

    def match_luma(self, image, similarity=0.85):
        if self.is_gif:
            image = rgb2luma(image)
            for template in self.image_luma:
                res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                _, sim, _, _ = cv2.minMaxLoc(res)
                if sim > similarity:
                    return True

            return False

        res = cv2.matchTemplate(image, self.image, cv2.TM_CCOEFF_NORMED)
        _, sim, _, _ = cv2.minMaxLoc(res)
        return sim > similarity

    def _point_to_button(self, point, image=None, name=None):
        if name is None:
            name = self.name
        area = area_offset(area=(0, 0, *self.size), offset=point)
        button = Button(area=area, color=(), button=area, name=name)
        if image is not None:
            button.load_color(image)
        return button

    def match_result(self, image, name=None):
        """返回最佳匹配的相似度和对应 Button。"""
        res = cv2.matchTemplate(image, self.image, cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)

        button = self._point_to_button(point, image=image, name=name)
        return sim, button

    def match_luma_result(self, image, name=None):
        image = rgb2luma(image)
        res = cv2.matchTemplate(image, self.image_luma, cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)

        button = self._point_to_button(point, image=image, name=name)
        return sim, button

    def match_multi(self, image, scaling=1.0, similarity=0.85, threshold=3, name=None):
        """返回全部匹配按钮；threshold 是合并相邻结果的像素距离。"""
        scaling = 1 / scaling
        if scaling != 1.0:
            image = cv2.resize(image, None, fx=scaling, fy=scaling)

        raw = image
        if self.is_gif:
            result = []
            for template in self.image:
                res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                res = np.array(np.where(res > similarity)).T[:, ::-1].tolist()
                result += res
            result = np.array(result)
        else:
            result = cv2.matchTemplate(image, self.image, cv2.TM_CCOEFF_NORMED)
            result = np.array(np.where(result > similarity)).T[:, ::-1]

        # result 形状为 (n, 2)，每行是一个 (x, y) 坐标。
        if scaling != 1.0:
            result = np.round(result / scaling).astype(int)
        result = Points(result).group(threshold=threshold)
        return [self._point_to_button(point, image=raw, name=name) for point in result]
