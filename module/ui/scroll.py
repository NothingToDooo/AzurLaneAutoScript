from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from scipy import signal

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import color_similarity_2d, random_rectangle_point, rgb2gray
from module.logger import logger

if TYPE_CHECKING:
    from module.base.base import ModuleBase
    from module.base.type_alias import Area, BoolArray, Color

type ScrollRange = tuple[float, float] | NDArray[np.float64]


class Scroll:
    color_threshold = 221
    drag_threshold = 0.05
    edge_threshold = 0.05
    edge_add = (0.3, 0.5)

    def __init__(
        self,
        area: Button | Area,
        color: Color,
        *,
        is_vertical: bool = True,
        name: str = "Scroll",
    ) -> None:
        if isinstance(area, Button):
            name = area.name
            area = area.area
        self.area = tuple(int(coordinate) for coordinate in area)
        self.color = color
        self.is_vertical = is_vertical
        self.name = name

        if self.is_vertical:
            self.total = self.area[3] - self.area[1]
        else:
            self.total = self.area[2] - self.area[0]
        self.length = self.total / 2
        self.drag_interval = Timer(1, count=2)
        self.drag_timeout = Timer(5, count=10)

    def match_color(self, main: ModuleBase) -> BoolArray:
        """返回形状为 (n,) 的布尔掩码。"""
        image = main.image_crop(self.area, copy=False)
        image = color_similarity_2d(image, color=self.color)
        mask = np.max(image, axis=1 if self.is_vertical else 0) > self.color_threshold
        self.length = float(np.sum(mask))
        return mask

    def cal_position(self, main: ModuleBase) -> float:
        """返回 0 到 1 之间的滚动位置。"""
        mask = self.match_color(main)
        middle = np.mean(np.where(mask)[0])

        position = (middle - self.length / 2) / (self.total - self.length)
        position = position if position > 0 else 0.0
        position = position if position < 1 else 1.0
        logger.attr(self.name, f"{position:.2f} ({middle}-{self.length / 2})/({self.total}-{self.length})")
        return float(position)

    def position_to_screen(
        self,
        position: float,
        random_range: ScrollRange = (-0.05, 0.05),
    ) -> tuple[int, int, int, int]:
        """调用前先用 cal_position() 或 match_color() 更新长度。

        返回 (左上 x，左上 y，右下 x，右下 y) 屏幕区域。
        """
        positions = np.add(position, random_range)
        middle = positions * (self.total - self.length) + self.length / 2
        middle = middle.astype(int)
        if self.is_vertical:
            middle += self.area[1]
            while np.max(middle) >= 720:
                middle -= 2
            while np.min(middle) <= 0:
                middle += 2
            area = (self.area[0], int(middle[0]), self.area[2], int(middle[1]))
        else:
            middle += self.area[0]
            while np.max(middle) >= 1280:
                middle -= 2
            while np.min(middle) <= 0:
                middle += 2
            area = (int(middle[0]), self.area[1], int(middle[1]), self.area[3])
        return area

    def appear(self, main: ModuleBase) -> bool:
        return bool(np.mean(self.match_color(main)) > 0.1)

    def at_top(self, main: ModuleBase) -> bool:
        return self.cal_position(main) < self.edge_threshold

    def at_bottom(self, main: ModuleBase) -> bool:
        return self.cal_position(main) > 1 - self.edge_threshold

    def set(
        self,
        position: float,
        main: ModuleBase,
        random_range: ScrollRange = (-0.05, 0.05),
        *,
        distance_check: bool = True,
        skip_first_screenshot: bool = True,
    ) -> int:
        """position 取 0 到 1；distance_check=True 时丢弃过短滑动。

        返回实际拖动次数。
        """
        logger.info(f"{self.name} set to {position}")
        self.drag_interval.clear()
        self.drag_timeout.reset()
        dragged = 0
        if position <= self.edge_threshold:
            random_range = np.subtract(0, self.edge_add)
        if position >= 1 - self.edge_threshold:
            random_range = self.edge_add

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            current = self.cal_position(main)
            if abs(position - current) < self.drag_threshold:
                break
            if self.length:
                self.drag_timeout.reset()
            else:
                if self.drag_timeout.reached():
                    logger.warning("Scroll disappeared, assume scroll set")
                    break
                continue

            if self.drag_interval.reached():
                p1 = random_rectangle_point(self.position_to_screen(current), n=1)
                p2 = random_rectangle_point(self.position_to_screen(position, random_range=random_range), n=1)
                main.device.swipe(p1, p2, name=self.name, distance_check=distance_check)
                self.drag_interval.reset()
                dragged += 1

        return dragged

    def set_top(
        self,
        main: ModuleBase,
        random_range: ScrollRange = (-0.05, 0.05),
        *,
        skip_first_screenshot: bool = True,
    ) -> int:
        return self.set(0.00, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def set_bottom(
        self,
        main: ModuleBase,
        random_range: ScrollRange = (-0.05, 0.05),
        *,
        skip_first_screenshot: bool = True,
    ) -> int:
        return self.set(1.00, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def drag_page(
        self,
        page: float,
        main: ModuleBase,
        random_range: ScrollRange = (-0.05, 0.05),
        *,
        skip_first_screenshot: bool = True,
    ) -> int:
        """page=1.0 向后一页，page=-1.0 向前一页。"""
        if not skip_first_screenshot:
            main.device.screenshot()
        current = self.cal_position(main)

        multiply = self.length / (self.total - self.length)
        target = current + page * multiply
        target = round(min(max(target, 0), 1), 3)
        return self.set(target, main=main, random_range=random_range, skip_first_screenshot=True)

    def next_page(
        self,
        main: ModuleBase,
        page: float = 0.8,
        random_range: ScrollRange = (-0.01, 0.01),
        *,
        skip_first_screenshot: bool = True,
    ) -> int:
        return self.drag_page(page, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def prev_page(
        self,
        main: ModuleBase,
        page: float = 0.8,
        random_range: ScrollRange = (-0.01, 0.01),
        *,
        skip_first_screenshot: bool = True,
    ) -> int:
        return self.drag_page(-page, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)


class AdaptiveScroll(Scroll):
    def __init__(
        self,
        area: Button | Area,
        parameters: dict[str, int | float] | None = None,
        background: int = 5,
        *,
        is_vertical: bool = True,
        name: str = "Scroll",
    ) -> None:
        """parameters 传给 scipy.find_peaks，background 是滚动条两侧的取样扩展像素数。"""
        if parameters is None:
            parameters = {}
        self.parameters = parameters
        self.background = background
        super().__init__(area, color=(255, 255, 255), is_vertical=is_vertical, name=name)

    def match_color(self, main: ModuleBase) -> BoolArray:
        if self.is_vertical:
            area = (self.area[0] - self.background, self.area[1], self.area[2] + self.background, self.area[3])
            image = main.image_crop(area, copy=False)
            image = rgb2gray(image)
            image = image.flatten()
            wlen = area[2] - area[0]
        else:
            area = (self.area[0], self.area[1] - self.background, self.area[2], self.area[3] + self.background)
            image = main.image_crop(area, copy=False)
            image = rgb2gray(image)
            image = image.flatten("F")
            wlen = area[3] - area[1]

        parameters = {
            "height": 128,
            "prominence": 30,
            "wlen": wlen,
            "width": 2,
        }
        parameters.update(self.parameters)
        peaks, _ = signal.find_peaks(image, **parameters)
        peaks //= wlen

        self.length = len(peaks)
        mask = np.zeros((self.total,), dtype=np.bool_)
        mask[peaks] = 1
        return mask
