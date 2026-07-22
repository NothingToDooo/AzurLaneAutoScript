from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

import cv2
import numpy as np

from module.base.utils import area_offset, color_similar, crop, extract_white_letters, load_image, rgb2gray, save_image
from module.logger import logger
from module.ocr.ocr import Digit
from module.project_paths import project_path
from module.statistics.utils import load_folder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.base.button import Button, ButtonGrid
    from module.base.template import Template
    from module.base.type_alias import Area, FilePath, ImageArray


class AmountOcr(Digit):
    def pre_process(self, image: ImageArray) -> ImageArray:
        """把 (高, 宽, 通道) 图像转为同宽高的二维 uint8 白字图。"""
        image = extract_white_letters(image, threshold=self.threshold)
        return image.astype(np.uint8)


AMOUNT_OCR = AmountOcr([], threshold=96, name="Amount_ocr")
PRICE_OCR = Digit([], letter=(255, 255, 255), threshold=128, name="Price_ocr")


class Item:
    IMAGE_SHAPE = (96, 96)

    def __init__(self, image: ImageArray, button: Button) -> None:
        self.image_raw = image
        self._button = button
        image = crop(image, button.area)
        if image.shape == self.IMAGE_SHAPE:
            self.image = image
        else:
            self.image = cast("ImageArray", cv2.resize(image, self.IMAGE_SHAPE, interpolation=cv2.INTER_CUBIC))
        self.is_valid = self.predict_valid()
        self._name = "DefaultItem"
        self.amount = 1
        self._cost = "DefaultCost"
        self.price = 0
        self.tag: str | None = None
        self.group: str | None = None
        self.sub_genre: str | None = None
        self.tier: str | None = None

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        """移除模板名末尾的数字变体后缀，例如 Javelin_2 归一化为 Javelin。"""
        if "_" in value:
            pre, suffix = value.rsplit("_", 1)
            if suffix.isdigit():
                value = pre
        self._name = value

    @property
    def cost(self) -> str:
        return self._cost

    @cost.setter
    def cost(self, value: str) -> None:
        if "_" in value:
            pre, suffix = value.rsplit("_", 1)
            if suffix.isdigit():
                value = pre
        self._cost = value

    def is_known_item(self) -> bool:
        return self.name != "DefaultItem" and not self.name.isdigit()

    def __str__(self) -> str:
        if self.name != "DefaultItem" and self.cost == "DefaultCost":
            name = f"{self.name}_x{self.amount}"
        elif self.name == "DefaultItem" and self.cost != "DefaultCost":
            name = f"{self.cost}_x{self.price}"
        else:
            name = f"{self.name}_x{self.amount}_{self.cost}_x{self.price}"

        if self.tag is not None:
            name = f"{name}_{self.tag}"

        return name

    def predict_valid(self) -> bool:
        return bool(np.mean(rgb2gray(self.image) > 127) > 0.1)

    @property
    def button(self) -> Area:
        return self._button.button

    @property
    def source_button(self) -> Button:
        return self._button

    def crop(self, area: Area) -> ImageArray:
        return crop(self.image_raw, area_offset(area, offset=self._button.area[:2]))

    def __eq__(self, other: object) -> bool:
        # Filter.apply() 按完整展示值去重。
        if not isinstance(other, Item):
            return NotImplemented
        return str(self) == str(other)

    def __hash__(self) -> int:
        # 合并多张掉落截图时按物品名去重。
        return hash(self.name)


@dataclass(frozen=True, slots=True)
class ItemGridAreas:
    template_area: tuple[int, int, int, int] = (40, 21, 89, 70)
    amount_area: tuple[int, int, int, int] = (60, 71, 91, 92)
    cost_area: tuple[int, int, int, int] = (6, 123, 84, 166)
    price_area: tuple[int, int, int, int] = (52, 132, 132, 156)
    tag_area: tuple[int, int, int, int] = (81, 4, 91, 8)


class ItemGridAreaSettings(TypedDict, total=False):
    template_area: tuple[int, int, int, int]
    amount_area: tuple[int, int, int, int]
    cost_area: tuple[int, int, int, int]
    price_area: tuple[int, int, int, int]
    tag_area: tuple[int, int, int, int]


def item_grid_areas(
    areas: ItemGridAreas | None = None,
    settings: ItemGridAreaSettings | None = None,
) -> ItemGridAreas:
    areas = ItemGridAreas() if areas is None else areas
    if settings:
        areas = replace(areas, **settings)
    return areas


@dataclass(frozen=True, slots=True)
class ItemPredictOptions:
    name: bool = True
    amount: bool = True
    cost: bool = False
    price: bool = False
    tag: bool = False


class ItemPredictSettings(TypedDict, total=False):
    name: bool
    amount: bool
    cost: bool
    price: bool
    tag: bool


def item_predict_options(
    options: ItemPredictOptions | None = None,
    settings: ItemPredictSettings | None = None,
) -> ItemPredictOptions:
    options = ItemPredictOptions() if options is None else options
    if settings:
        options = replace(options, **settings)
    return options


class ItemGrid[ItemT: Item = Item]:
    item_class = cast("type[ItemT]", Item)
    similarity = 0.92
    extract_similarity = 0.92
    cost_similarity = 0.75

    def __init__(
        self,
        grids: ButtonGrid | None,
        templates: Mapping[str, Template],
        areas: ItemGridAreas | None = None,
        **area_settings: Unpack[ItemGridAreaSettings],
    ) -> None:
        """初始化商品网格和名称模板；area_settings 覆盖 ItemGridAreas。"""
        areas = item_grid_areas(areas, area_settings)
        self.amount_ocr = AMOUNT_OCR
        self.price_ocr = PRICE_OCR
        self.grids = grids
        self.template_area = areas.template_area
        self.amount_area = areas.amount_area
        self.cost_area = areas.cost_area
        self.price_area = areas.price_area
        self.tag_area = areas.tag_area

        self.colors: dict[str, tuple[float, float, float]] = {}
        self.templates: dict[str, ImageArray] = {}
        self.templates_hit: dict[str, int] = {}
        self.next_template_index = len(self.templates.keys())
        for name, template in templates.items():
            template_image = template.image
            if isinstance(template_image, list):
                message = "item templates must contain exactly one image"
                raise TypeError(message)
            self.templates[name] = crop(template_image, area=self.template_area)
            self.colors[name] = cv2.mean(self.templates[name])[:3]
            self.templates_hit[name] = 0
            if name.isdigit() and int(name) > self.next_template_index:
                self.next_template_index = int(name)

        self.cost_templates: dict[str, ImageArray] = {}
        self.cost_templates_hit: dict[str, int] = {}
        self.next_cost_template_index = len(self.cost_templates.keys())

        self.items: list[ItemT] = []

    def _load_image(self, image: ImageArray) -> None:
        self.items = []
        if self.grids is None:
            message = "item grid buttons must be set before loading an image"
            raise RuntimeError(message)
        for button in self.grids.buttons:
            item = self.item_class(image, button)
            if item.is_valid:
                self.items.append(item)

    def load_template_folder(self, folder: FilePath) -> None:
        logger.info(f"Loading template folder: {folder}")
        max_digit = 0
        data = load_folder(folder)
        for name, image_path in data.items():
            if name in self.templates:
                continue
            image = load_image(image_path)
            image = crop(image, area=self.template_area)
            self.colors[name] = cv2.mean(image)[:3]
            self.templates[name] = image
            self.templates_hit[name] = 0
            if name.isdigit():
                max_digit = max(max_digit, int(name))
            self.next_template_index += 1
        self.next_template_index = max(self.next_template_index, max_digit + 1)
        logger.attr("next_template_index", self.next_template_index)

    def load_cost_template_folder(self, folder: FilePath) -> None:
        max_digit = 0
        data = load_folder(folder)
        for name, image_path in data.items():
            if name in self.cost_templates:
                continue
            image = load_image(image_path)
            self.cost_templates[name] = image
            self.cost_templates_hit[name] = 0
            if name.isdigit():
                max_digit = max(max_digit, int(name))
            self.next_cost_template_index += 1
        self.next_cost_template_index = max(self.next_cost_template_index, max_digit + 1)

    def match_template(self, image: ImageArray, similarity: float | None = None) -> str:
        """优先匹配高命中和已知模板；未命中时登记新数字模板并返回编号。"""
        if similarity is None:
            similarity = self.similarity
        color = cv2.mean(crop(image, self.template_area))[:3]
        names = sorted(self.templates, key=self.templates_hit.__getitem__, reverse=True)
        names = [name for name in names if not name.isdigit()] + [name for name in names if name.isdigit()]
        for name in names:
            if color_similar(color1=color, color2=self.colors[name], threshold=30):
                res = cv2.matchTemplate(image, self.templates[name], cv2.TM_CCOEFF_NORMED)
                _, sim, _, _ = cv2.minMaxLoc(res)
                if sim > similarity:
                    self.templates_hit[name] += 1
                    return name

        self.next_template_index += 1
        name = str(self.next_template_index)
        logger.info(f"New template: {name}")
        image = crop(image, self.template_area)
        self.colors[name] = cv2.mean(image)[:3]
        self.templates[name] = image
        self.templates_hit[name] = self.templates_hit.get(name, 0) + 1
        return name

    def extract_template(self, image: ImageArray, folder: FilePath | None = None) -> dict[str, ImageArray]:
        """返回本次新增的模板图映射；提供 folder 时同时保存为 PNG。"""
        self._load_image(image)
        prev = set(self.templates.keys())
        new: dict[str, ImageArray] = {}
        for item in self.items:
            name = self.match_template(item.image, similarity=self.extract_similarity)
            if name not in prev:
                new[name] = item.image

        if folder is not None:
            output_folder = project_path(folder)
            for name, im in new.items():
                save_image(im, output_folder / f"{name}.png")

        return new

    def match_cost_template(self, item: ItemT) -> str | None:
        """按命中频次匹配成本模板；未匹配时返回 None 且不创建模板。"""
        image = item.crop(self.cost_area)
        names = sorted(self.cost_templates, key=self.cost_templates_hit.__getitem__, reverse=True)
        for name in names:
            res = cv2.matchTemplate(image, self.cost_templates[name], cv2.TM_CCOEFF_NORMED)
            _, similarity, _, _ = cv2.minMaxLoc(res)
            if similarity > self.cost_similarity:
                self.cost_templates_hit[name] += 1
                return name

        return None

    @staticmethod
    def predict_tag(image: ImageArray) -> str | None:
        """按标签区域颜色返回 catchup、bonus、event；未匹配时返回 None。"""
        threshold = 50
        color = cv2.mean(np.array(image))[:3]
        if color_similar(color1=color, color2=(49, 125, 222), threshold=threshold):
            return "catchup"
        if color_similar(color1=color, color2=(33, 199, 239), threshold=threshold):
            return "bonus"
        if color_similar(color1=color, color2=(255, 85, 41), threshold=threshold):
            return "event"
        return None

    def _predict_amounts(self) -> None:
        amount_list = [item.crop(self.amount_area) for item in self.items]
        amount_list = self.amount_ocr.ocr_many(amount_list)
        for item, amount in zip(self.items, amount_list, strict=True):
            item.amount = amount

    def _predict_names(self) -> None:
        name_list = [self.match_template(item.image) for item in self.items]
        for item, name in zip(self.items, name_list, strict=True):
            item.name = name

    def _predict_costs(self) -> None:
        cost_list = [self.match_cost_template(item) for item in self.items]
        self.items = [item for item, cost in zip(self.items, cost_list, strict=True) if cost is not None]
        cost_list = [cost for cost in cost_list if cost is not None]
        for item, cost in zip(self.items, cost_list, strict=True):
            item.cost = cost

    def _predict_prices(self) -> None:
        if not self.items:
            return
        price_list = [item.crop(self.price_area) for item in self.items]
        price_list = self.price_ocr.ocr_many(price_list)
        for item, price in zip(self.items, price_list, strict=True):
            item.price = price

    def _predict_tags(self) -> None:
        tag_list = [self.predict_tag(item.crop(self.tag_area)) for item in self.items]
        for item, tag in zip(self.items, tag_list, strict=True):
            item.tag = tag

    def _discard_invalid_prices(self) -> None:
        items = [item for item in self.items if item.price > 0]
        diff = len(self.items) - len(items)
        if diff > 0:
            logger.warning(f"Ignore {diff} items, because price <= 0")
            self.items = items

    def predict(
        self,
        image: ImageArray,
        options: ItemPredictOptions | None = None,
        **settings: Unpack[ItemPredictSettings],
    ) -> list[ItemT]:
        """按选项识别截图中的有效商品并返回列表；settings 覆盖 ItemPredictOptions。"""
        options = item_predict_options(options, settings)
        self._load_image(image)
        if options.amount:
            self._predict_amounts()
        if options.name:
            self._predict_names()
        if options.cost:
            self._predict_costs()
        if options.price:
            self._predict_prices()
        if options.tag:
            self._predict_tags()

        if options.price:
            self._discard_invalid_prices()

        return self.items
