import traceback
from pathlib import Path
from typing import ClassVar, cast

import cv2
import imageio
import numpy as np
from PIL import Image, ImageDraw

from module.base.decorator import cached_property
from module.base.resource import Resource
from module.base.utils import area_offset, color_similar, crop, get_color, load_image, rgb2luma


def _match_offset(offset):
    if not isinstance(offset, tuple):
        return np.array((-3, -offset, 3, offset))
    if len(offset) == 2:
        return np.array((-offset[0], -offset[1], offset[0], offset[1]))
    return np.array(offset)


class Button(Resource):
    def __init__(self, area, color, button, file=None, name=None):
        """area 和 button 均为左上、右下坐标，color 为 RGB；三者也可按服务器提供映射。

        button 为空元组时实例仅用于检测，不用于点击。
        """
        self.raw_area = area
        self.raw_color = color
        self.raw_button = button
        self.raw_file = file
        self.raw_name = name

        self._button_offset = None
        self._match_init = False
        self._match_binary_init = False
        self._match_luma_init = False
        self.image = None
        self.image_binary = None
        self.image_luma = None

        if self.file:
            self.resource_add(key=self.file)

    cached: ClassVar[tuple[str, ...]] = ("area", "color", "_button", "file", "name", "is_gif")

    @cached_property
    def area(self):
        return self.parse_property(self.raw_area)

    @cached_property
    def color(self):
        return self.parse_property(self.raw_color)

    @cached_property
    def _button(self):
        return self.parse_property(self.raw_button)

    @cached_property
    def file(self):
        return self.parse_property(self.raw_file)

    @cached_property
    def name(self):
        if self.raw_name:
            return self.raw_name
        if self.file:
            return Path(self.file).stem
        return "BUTTON"

    @cached_property
    def is_gif(self):
        if self.file:
            return Path(self.file).suffix == ".gif"
        return False

    def __str__(self):
        return self.name

    __repr__ = __str__

    def __eq__(self, other):
        return str(self) == str(other)

    def __hash__(self):
        return hash(self.name)

    def __bool__(self):
        return True

    @property
    def button(self):
        if self._button_offset is None:
            return self._button
        return self._button_offset

    @property
    def base_button(self):
        return self._button

    @property
    def is_match_initialized(self):
        return self._match_init

    def mark_match_initialized(self):
        self._match_init = True

    def reset_match_state(self):
        self._match_init = False

    def set_button_area(self, button):
        self.raw_button = button
        self.__dict__["_button"] = self.parse_property(button)
        self._button_offset = None

    def appear_on(self, image, threshold=10):
        return color_similar(color1=get_color(image, self.area), color2=self.color, threshold=threshold)

    def load_color(self, image):
        """用截图区域永久替换预设颜色和模板，并返回 RGB。"""
        self.__dict__["color"] = get_color(image, self.area)
        self.image = crop(image, self.area)
        self.__dict__["is_gif"] = False
        return self.color

    def load_offset(self, button):
        offset = np.subtract(button.button, button.base_button)[:2]
        self._button_offset = area_offset(self._button, offset=offset)

    def clear_offset(self):
        self._button_offset = None

    def ensure_template(self):
        """按需加载匹配模板；GIF 会保留全部帧。"""
        if not self._match_init:
            if self.is_gif:
                self.image = []
                for frame in imageio.mimread(self.file):
                    image = frame[:, :, :3].copy() if len(frame.shape) == 3 else frame
                    image = crop(image, self.area)
                    self.image.append(image)
            else:
                self.image = load_image(self.file, self.area)
            self._match_init = True

    def ensure_binary_template(self):
        """按需生成 Otsu 二值化模板；调用前必须已加载原模板。"""
        if not self._match_binary_init:
            if self.is_gif:
                self.image_binary = []
                for image in cast("list[np.ndarray]", self.image):
                    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                    self.image_binary.append(image_binary)
            else:
                image_gray = cv2.cvtColor(cast("np.ndarray", self.image), cv2.COLOR_BGR2GRAY)
                _, self.image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            self._match_binary_init = True

    def ensure_luma_template(self):
        if not self._match_luma_init:
            if self.is_gif:
                self.image_luma = []
                for image in cast("list[np.ndarray]", self.image):
                    luma = rgb2luma(image)
                    self.image_luma.append(luma)
            else:
                self.image_luma = rgb2luma(self.image)
            self._match_luma_init = True

    def resource_release(self):
        super().resource_release()
        self.image = None
        self.image_binary = None
        self.image_luma = None
        self._match_init = False
        self._match_binary_init = False
        self._match_luma_init = False

    def match(self, image, offset=30, similarity=0.85):
        """在 offset 扩展区域内匹配模板，并把点击区域偏移到最佳位置；similarity 为 0～1。"""
        self.ensure_template()

        offset = _match_offset(offset)
        image = crop(image, offset + self.area, copy=False)

        if self.is_gif:
            for template in cast("list[np.ndarray]", self.image):
                res = cv2.matchTemplate(template, image, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
                if sim > similarity:
                    return True
            return False
        res = cv2.matchTemplate(cast("np.ndarray", self.image), image, cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)
        self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
        return sim > similarity

    def match_binary(self, image, offset=30, similarity=0.85):
        """在 Otsu 二值图上匹配模板，并把点击区域偏移到最佳位置。"""
        self.ensure_template()
        self.ensure_binary_template()

        offset = _match_offset(offset)
        image = crop(image, offset + self.area, copy=False)

        if self.is_gif:
            for template in cast("list[np.ndarray]", self.image_binary):
                image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                res = cv2.matchTemplate(template, image_binary, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
                if sim > similarity:
                    return True
            return False
        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        res = cv2.matchTemplate(cast("np.ndarray", self.image_binary), image_binary, cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)
        self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
        return sim > similarity

    def match_luma(self, image, offset=30, similarity=0.85):
        """在 YUV 的亮度通道上匹配模板，并把点击区域偏移到最佳位置。"""
        self.ensure_template()
        self.ensure_luma_template()

        offset = _match_offset(offset)
        image = crop(image, offset + self.area, copy=False)

        if self.is_gif:
            image_luma = rgb2luma(image)
            for template in cast("list[np.ndarray]", self.image_luma):
                res = cv2.matchTemplate(template, image_luma, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
                if sim > similarity:
                    return True
            return False

        image_luma = rgb2luma(image)
        res = cv2.matchTemplate(cast("np.ndarray", self.image_luma), image_luma, cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)
        self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
        return sim > similarity

    def match_template_color(self, image, offset=(20, 20), similarity=0.85, threshold=30):
        """先匹配亮度模板，再校验偏移后区域的颜色。"""
        if self.match_luma(image, offset=offset, similarity=similarity):
            diff = np.subtract(self.button, self._button)[:2]
            area = area_offset(self.area, offset=diff)
            color = get_color(image, area)
            return color_similar(color1=color, color2=self.color, threshold=threshold)
        return False

    def crop(self, area, image=None, name=None):
        """按当前检测区和点击区的相对坐标生成按钮；传入 image 时同时重采样颜色。"""
        if name is None:
            name = self.name
        new_area = area_offset(area, offset=self.area[:2])
        new_button = area_offset(area, offset=self.button[:2])
        button = Button(area=new_area, color=self.color, button=new_button, file=self.file, name=name)
        if image is not None:
            button.load_color(image)
        return button

    def move(self, vector, image=None, name=None):
        """平移检测区和点击区；传入 image 时同时重采样颜色。"""
        if name is None:
            name = self.name
        new_area = area_offset(self.area, offset=vector)
        new_button = area_offset(self.button, offset=vector)
        button = Button(area=new_area, color=self.color, button=new_button, file=self.file, name=name)
        if image is not None:
            button.load_color(image)
        return button


class ButtonGrid:
    def __init__(self, origin, delta, button_shape, grid_shape, name=None):
        self.origin = np.array(origin)
        self.delta = np.array(delta)
        self.button_shape = np.array(button_shape)
        self.grid_shape = np.array(grid_shape)
        if name:
            self._name = name
        else:
            text = traceback.extract_stack()[-2].line or ""
            self._name = text[: text.find("=")].strip()

    @property
    def name(self):
        return self._name

    def __getitem__(self, item):
        base = np.round(np.array(item) * self.delta + self.origin).astype(int)
        area = tuple(np.append(base, base + self.button_shape))
        return Button(area=area, color=(), button=area, name=f"{self._name}_{item[0]}_{item[1]}")

    def generate(self):
        for y in range(self.grid_shape[1]):
            for x in range(self.grid_shape[0]):
                yield x, y, self[x, y]

    @cached_property
    def buttons(self):
        return [button for _, _, button in self.generate()]

    def crop(self, area, name=None):
        if name is None:
            name = self._name
        origin = self.origin + area[:2]
        button_shape = np.subtract(area[2:], area[:2])
        return ButtonGrid(
            origin=origin, delta=self.delta, button_shape=button_shape, grid_shape=self.grid_shape, name=name
        )

    def move(self, vector, name=None):
        if name is None:
            name = self._name
        origin = self.origin + vector
        return ButtonGrid(
            origin=origin, delta=self.delta, button_shape=self.button_shape, grid_shape=self.grid_shape, name=name
        )

    def gen_mask(self):
        """生成 1280×720 的调试掩码：按钮区域为白色，背景为黑色。"""
        image = Image.new("RGB", (1280, 720), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for button in self.buttons:
            draw.rectangle((button.area[:2], button.button[2:]), fill=(255, 255, 255), outline=None)
        return image

    def show_mask(self):
        self.gen_mask().show()

    def save_mask(self):
        self.gen_mask().save(f"{self._name}.png")
