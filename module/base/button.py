import traceback
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

import cv2
import imageio
import numpy as np
from PIL import Image, ImageDraw

from module.base.decorator import cached_property
from module.base.resource import Resource
from module.base.utils import area_offset, color_similar, crop, get_color, load_image, rgb2luma

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from module.base.type_alias import Area, Color, FilePath, ImageArray, NumericArray, Point, Scalar, Size

type ButtonArea = Area | tuple[()]
type MatchOffset = Scalar | tuple[Scalar, Scalar] | tuple[Scalar, Scalar, Scalar, Scalar]

MISSING_BUTTON_AREA_MESSAGE = "button has no clickable area"
MISSING_DETECTION_AREA_MESSAGE = "button has no detection area"
MISSING_BUTTON_COLOR_MESSAGE = "button has no detection color"
MISSING_TEMPLATE_FILE_MESSAGE = "button has no template file"


def _match_offset(offset: MatchOffset) -> NumericArray:
    if isinstance(offset, int | float | np.integer | np.floating):
        return np.array((-3, -offset, 3, offset))
    if len(offset) == 2:
        return np.array((-offset[0], -offset[1], offset[0], offset[1]))
    return np.array(offset)


def _offset_area(area: Area, offset: NumericArray) -> Area:
    return (
        area[0] + offset[0],
        area[1] + offset[1],
        area[2] + offset[2],
        area[3] + offset[3],
    )


def _offset_point(offset: NumericArray, point: Sequence[int]) -> Point:
    return offset[0] + point[0], offset[1] + point[1]


class Button(Resource):
    def __init__(
        self,
        area: ButtonArea,
        color: Color | tuple[()],
        button: ButtonArea,
        file: FilePath | None = None,
        name: str | None = None,
    ) -> None:
        """area 和 button 均为左上、右下坐标，color 为 RGB；三者也可按服务器提供映射。

        button 为空元组时实例仅用于检测，不用于点击。
        """
        self.raw_area = area
        self.raw_color = color
        self.raw_button = button
        self.raw_file = file
        self.raw_name = name

        self._button_offset: Area | None = None
        self._match_init = False
        self._match_binary_init = False
        self._match_luma_init = False
        self.image: ImageArray | list[ImageArray] | None = None
        self.image_binary: ImageArray | list[ImageArray] | None = None
        self.image_luma: ImageArray | list[ImageArray] | None = None

        if self.file:
            self.resource_add(key=self.file)

    cached: ClassVar[tuple[str, ...]] = ("area", "color", "_button", "file", "name", "is_gif")

    @cached_property
    def area(self) -> Area:
        area = self.parse_property(self.raw_area)
        if len(area) == 0:
            raise ValueError(MISSING_DETECTION_AREA_MESSAGE)
        return area

    @cached_property
    def color(self) -> Color:
        color = self.parse_property(self.raw_color)
        if len(color) == 0:
            raise ValueError(MISSING_BUTTON_COLOR_MESSAGE)
        return color

    @cached_property
    def _button(self) -> Area:
        button = self.parse_property(self.raw_button)
        if len(button) == 0:
            raise ValueError(MISSING_BUTTON_AREA_MESSAGE)
        return button

    @cached_property
    def file(self) -> FilePath | None:
        return self.parse_property(self.raw_file)

    @cached_property
    def name(self) -> str:
        if self.raw_name:
            return self.raw_name
        if self.file:
            return Path(self.file).stem
        return "BUTTON"

    @cached_property
    def is_gif(self) -> bool:
        if self.file:
            return Path(self.file).suffix == ".gif"
        return False

    def __str__(self) -> str:
        return self.name

    __repr__ = __str__

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)

    def __hash__(self) -> int:
        return hash(self.name)

    def __bool__(self) -> bool:
        return True

    @property
    def button(self) -> Area:
        if self._button_offset is None:
            return self._button
        return self._button_offset

    @property
    def base_button(self) -> Area:
        return self._button

    @property
    def is_match_initialized(self) -> bool:
        return self._match_init

    def mark_match_initialized(self) -> None:
        self._match_init = True

    def reset_match_state(self) -> None:
        self._match_init = False

    def set_button_area(self, button: Area) -> None:
        self.raw_button = button
        self.__dict__["_button"] = self.parse_property(button)
        self._button_offset = None

    def appear_on(self, image: ImageArray, threshold: Scalar = 10) -> bool:
        return color_similar(color1=get_color(image, self.area), color2=self.color, threshold=threshold)

    def load_color(self, image: ImageArray) -> Color:
        """用截图区域永久替换预设颜色和模板，并返回 RGB。"""
        self.__dict__["color"] = get_color(image, self.area)
        self.image = crop(image, self.area)
        self.__dict__["is_gif"] = False
        return self.color

    def load_offset(self, button: Button) -> None:
        offset = (
            button.button[0] - button.base_button[0],
            button.button[1] - button.base_button[1],
        )
        self._button_offset = area_offset(self._button, offset=offset)

    def clear_offset(self) -> None:
        self._button_offset = None

    def _require_file(self) -> Path:
        if self.file is None:
            raise ValueError(MISSING_TEMPLATE_FILE_MESSAGE)
        return Path(self.file)

    def ensure_template(self) -> None:
        """按需加载匹配模板；GIF 会保留全部帧。"""
        if not self._match_init:
            file = self._require_file()
            if self.is_gif:
                frames: list[ImageArray] = []
                for frame in imageio.mimread(file):
                    image = frame[:, :, :3].copy() if len(frame.shape) == 3 else frame
                    frames.append(crop(cast("ImageArray", image), self.area))
                self.image = frames
            else:
                self.image = load_image(file, self.area)
            self._match_init = True

    def ensure_binary_template(self) -> None:
        """按需生成 Otsu 二值化模板；调用前必须已加载原模板。"""
        if not self._match_binary_init:
            if self.is_gif:
                binary_frames: list[ImageArray] = []
                for image in cast("list[ImageArray]", self.image):
                    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                    binary_frames.append(cast("ImageArray", image_binary))
                self.image_binary = binary_frames
            else:
                image_gray = cv2.cvtColor(cast("ImageArray", self.image), cv2.COLOR_BGR2GRAY)
                _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                self.image_binary = cast("ImageArray", image_binary)
            self._match_binary_init = True

    def ensure_luma_template(self) -> None:
        if not self._match_luma_init:
            if self.is_gif:
                self.image_luma = [rgb2luma(image) for image in cast("list[ImageArray]", self.image)]
            else:
                self.image_luma = rgb2luma(cast("ImageArray", self.image))
            self._match_luma_init = True

    def resource_release(self) -> None:
        super().resource_release()
        self.image = None
        self.image_binary = None
        self.image_luma = None
        self._match_init = False
        self._match_binary_init = False
        self._match_luma_init = False

    def match(self, image: ImageArray, offset: MatchOffset = 30, similarity: float = 0.85) -> bool:
        """在 offset 扩展区域内匹配模板，并把点击区域偏移到最佳位置；similarity 为 0～1。"""
        self.ensure_template()

        match_offset = _match_offset(offset)
        image = crop(image, _offset_area(self.area, match_offset), copy=False)

        if self.is_gif:
            for template in cast("list[ImageArray]", self.image):
                res = cv2.matchTemplate(template, image, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, _offset_point(match_offset, point))
                if sim > similarity:
                    return True
            return False
        res = cv2.matchTemplate(cast("ImageArray", self.image), image, cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)
        self._button_offset = area_offset(self._button, _offset_point(match_offset, point))
        return sim > similarity

    def match_binary(self, image: ImageArray, offset: MatchOffset = 30, similarity: float = 0.85) -> bool:
        """在 Otsu 二值图上匹配模板，并把点击区域偏移到最佳位置。"""
        self.ensure_template()
        self.ensure_binary_template()

        match_offset = _match_offset(offset)
        image = crop(image, _offset_area(self.area, match_offset), copy=False)

        if self.is_gif:
            for template in cast("list[ImageArray]", self.image_binary):
                image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                res = cv2.matchTemplate(template, image_binary, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, _offset_point(match_offset, point))
                if sim > similarity:
                    return True
            return False
        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, image_binary = cv2.threshold(image_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        res = cv2.matchTemplate(cast("ImageArray", self.image_binary), image_binary, cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)
        self._button_offset = area_offset(self._button, _offset_point(match_offset, point))
        return sim > similarity

    def match_luma(self, image: ImageArray, offset: MatchOffset = 30, similarity: float = 0.85) -> bool:
        """在 YUV 的亮度通道上匹配模板，并把点击区域偏移到最佳位置。"""
        self.ensure_template()
        self.ensure_luma_template()

        match_offset = _match_offset(offset)
        image = crop(image, _offset_area(self.area, match_offset), copy=False)

        if self.is_gif:
            image_luma = rgb2luma(image)
            for template in cast("list[ImageArray]", self.image_luma):
                res = cv2.matchTemplate(template, image_luma, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, _offset_point(match_offset, point))
                if sim > similarity:
                    return True
            return False

        image_luma = rgb2luma(image)
        res = cv2.matchTemplate(cast("ImageArray", self.image_luma), image_luma, cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)
        self._button_offset = area_offset(self._button, _offset_point(match_offset, point))
        return sim > similarity

    def match_template_color(
        self,
        image: ImageArray,
        offset: MatchOffset = (20, 20),
        similarity: float = 0.85,
        threshold: Scalar = 30,
    ) -> bool:
        """先匹配亮度模板，再校验偏移后区域的颜色。"""
        if self.match_luma(image, offset=offset, similarity=similarity):
            diff = (self.button[0] - self._button[0], self.button[1] - self._button[1])
            area = area_offset(self.area, offset=diff)
            color = get_color(image, area)
            return color_similar(color1=color, color2=self.color, threshold=threshold)
        return False

    def crop(self, area: Area, image: ImageArray | None = None, name: str | None = None) -> Button:
        """按当前检测区和点击区的相对坐标生成按钮；传入 image 时同时重采样颜色。"""
        if name is None:
            name = self.name
        new_area = area_offset(area, offset=self.area[:2])
        new_button = area_offset(area, offset=self.button[:2])
        button = Button(area=new_area, color=self.color, button=new_button, file=self.file, name=name)
        if image is not None:
            button.load_color(image)
        return button

    def move(self, vector: Point, image: ImageArray | None = None, name: str | None = None) -> Button:
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
    def __init__(
        self, origin: Point, delta: Point, button_shape: Size, grid_shape: Size, name: str | None = None
    ) -> None:
        self.origin = (origin[0], origin[1])
        self.delta = (delta[0], delta[1])
        self.button_shape = (int(button_shape[0]), int(button_shape[1]))
        self.grid_shape = (int(grid_shape[0]), int(grid_shape[1]))
        if name:
            self._name = name
        else:
            text = traceback.extract_stack()[-2].line or ""
            self._name = text[: text.find("=")].strip()

    @property
    def name(self) -> str:
        return self._name

    def __getitem__(self, item: Sequence[int]) -> Button:
        base = (
            round(item[0] * self.delta[0] + self.origin[0]),
            round(item[1] * self.delta[1] + self.origin[1]),
        )
        area = (base[0], base[1], base[0] + self.button_shape[0], base[1] + self.button_shape[1])
        return Button(area=area, color=(), button=area, name=f"{self._name}_{item[0]}_{item[1]}")

    def generate(self) -> Iterator[tuple[int, int, Button]]:
        for y in range(self.grid_shape[1]):
            for x in range(self.grid_shape[0]):
                yield x, y, self[x, y]

    @cached_property
    def buttons(self) -> list[Button]:
        return [button for _, _, button in self.generate()]

    def crop(self, area: Area, name: str | None = None) -> ButtonGrid:
        if name is None:
            name = self._name
        origin = (self.origin[0] + area[0], self.origin[1] + area[1])
        button_shape = (int(area[2] - area[0]), int(area[3] - area[1]))
        return ButtonGrid(
            origin=origin, delta=self.delta, button_shape=button_shape, grid_shape=self.grid_shape, name=name
        )

    def move(self, vector: Point, name: str | None = None) -> ButtonGrid:
        if name is None:
            name = self._name
        origin = (self.origin[0] + vector[0], self.origin[1] + vector[1])
        return ButtonGrid(
            origin=origin, delta=self.delta, button_shape=self.button_shape, grid_shape=self.grid_shape, name=name
        )

    def gen_mask(self) -> Image.Image:
        """生成 1280×720 的调试掩码：按钮区域为白色，背景为黑色。"""
        image = Image.new("RGB", (1280, 720), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        for button in self.buttons:
            box = [float(button.area[index]) for index in (0, 1)]
            box.extend(float(button.button[index]) for index in (2, 3))
            draw.rectangle(box, fill=(255, 255, 255), outline=None)
        return image

    def show_mask(self) -> None:
        self.gen_mask().show()

    def save_mask(self) -> None:
        self.gen_mask().save(f"{self._name}.png")
