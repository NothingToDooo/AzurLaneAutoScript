from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

import cv2
import numpy as np
from PIL import Image

from module.base.button import Button
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import area_offset, color_similarity_2d, crop, get_color, image_size, load_image
from module.combat.emotion import Emotion
from module.logger import logger
from module.map_detection.utils import fit_points

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.button import MatchOffset
    from module.base.type_alias import Area, Color, ImageArray
    from module.config.config import AzurLaneConfig
    from module.device.device import Device


@runtime_checkable
class _HasArea(Protocol):
    @property
    def area(self) -> Area: ...


class _HasName(Protocol):
    @property
    def name(self) -> str: ...


class ModuleBase:
    config: AzurLaneConfig
    device: Device

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
    ) -> None:
        self.config = config
        self.device = device

        self.interval_timer: dict[str, Timer] = {}

    @cached_property
    def emotion(self) -> Emotion:
        return Emotion(config=self.config)

    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        """循环产出最新截图；skip_first 可复用已有截图，timeout 可传秒数或 Timer。"""
        if timeout is not None:
            if isinstance(timeout, Timer):
                timeout.reset()
            else:
                timeout = Timer.from_seconds(timeout).start()

        while 1:
            if timeout is not None and timeout.reached():
                return

            if skip_first:
                skip_first = False
            else:
                self.device.screenshot()

            try:
                yield self.device.image
            except AttributeError:
                self.device.screenshot()
                yield self.device.image

    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        """offset 启用模板匹配，否则按区域颜色判断；interval 限制连续触发频率。

        similarity 范围为 0～1；threshold 范围为 0～255，且越小越相似。
        """
        self.device.stuck_record_add(button)

        if interval:
            if button.name in self.interval_timer:
                if self.interval_timer[button.name].limit != interval:
                    self.interval_timer[button.name] = Timer(interval)
            else:
                self.interval_timer[button.name] = Timer(interval)
            if not self.interval_timer[button.name].reached():
                return False

        if offset:
            if isinstance(offset, bool):
                offset = self.config.BUTTON_OFFSET
            appear = button.match(self.device.image, offset=offset, similarity=similarity)
        else:
            appear = button.appear_on(self.device.image, threshold=threshold)

        if appear and interval:
            self.interval_timer[button.name].reset()

        return appear

    def match_template_color(
        self,
        button: Button,
        offset: MatchOffset = (20, 20),
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        """先匹配模板再校验颜色；interval 限制连续触发频率。"""
        self.device.stuck_record_add(button)

        if interval:
            if button.name in self.interval_timer:
                if self.interval_timer[button.name].limit != interval:
                    self.interval_timer[button.name] = Timer(interval)
            else:
                self.interval_timer[button.name] = Timer(interval)
            if not self.interval_timer[button.name].reached():
                return False

        appear = button.match_template_color(
            self.device.image, offset=offset, similarity=similarity, threshold=threshold
        )

        if appear and interval:
            self.interval_timer[button.name].reset()

        return appear

    def appear_then_click(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        appear = self.appear(button, offset=offset, interval=interval, similarity=similarity, threshold=threshold)
        if appear:
            self.device.click(button)
        return appear

    def wait_until_appear(
        self, button: Button, offset: MatchOffset | None = 0, *, skip_first_screenshot: bool = False
    ) -> None:
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(button, offset=offset):
                break

    def wait_until_appear_then_click(self, button: Button, offset: MatchOffset | None = 0) -> None:
        self.wait_until_appear(button, offset=offset)
        self.device.click(button)

    def wait_until_disappear(self, button: Button, offset: MatchOffset | None = 0) -> None:
        while 1:
            self.device.screenshot()
            if not self.appear(button, offset=offset):
                break

    def wait_until_stable(
        self,
        button: Button,
        timer: Timer | None = None,
        timeout: Timer | None = None,
        *,
        skip_first_screenshot: bool = True,
    ) -> None:
        button.reset_match_state()
        if timer is None:
            timer = Timer(0.3, count=1)
        if timeout is None:
            timeout = Timer(5, count=10)
        timeout.reset()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if button.is_match_initialized:
                if button.match(self.device.image, offset=(0, 0)):
                    if timer.reached():
                        break
                else:
                    button.load_color(self.device.image)
                    timer.reset()
            else:
                button.load_color(self.device.image)
                button.mark_match_initialized()

            if timeout.reached():
                logger.warning(f"wait_until_stable({button}) timeout")
                break

    def image_crop(self, button: Button | _HasArea | Area, *, copy: bool = True) -> ImageArray:
        if isinstance(button, (Button, _HasArea)):
            return crop(self.device.image, button.area, copy=copy)
        return crop(self.device.image, button, copy=copy)

    def image_color_count(
        self,
        button: ImageArray | Button | _HasArea | Area,
        color: Color,
        threshold: int = 221,
        count: int = 50,
    ) -> bool:
        """判断区域内是否有超过 count 个像素达到颜色阈值；255 表示完全相同。"""
        if isinstance(button, np.ndarray) and button.ndim >= 2:
            image = cast("ImageArray", button)
        else:
            area_or_button = cast("Button | _HasArea | Area", button)
            image = self.image_crop(area_or_button, copy=False)
        mask = color_similarity_2d(image, color=color)
        cv2.inRange(mask, threshold, 255, dst=mask)
        sum_ = cv2.countNonZero(mask)
        return sum_ > count

    def image_color_button(
        self,
        area: Area,
        color: Color,
        color_threshold: int = 250,
        encourage: int = 5,
        name: str = "COLOR_BUTTON",
    ) -> Button | None:
        """在区域内查找纯色块并生成按钮；color_threshold 为 0～255，encourage 为半径。

        没有足够匹配像素时返回 None。
        """
        image = color_similarity_2d(self.image_crop(area, copy=False), color=color)
        points = np.array(np.where(image > color_threshold)).T[:, ::-1]
        if points.shape[0] < encourage**2:
            return None

        point = fit_points(points, mod=image_size(image), encourage=encourage)
        point = (int(point[0] + area[0]), int(point[1] + area[1]))
        button_area = area_offset((-encourage, -encourage, encourage, encourage), offset=point)
        color = get_color(self.device.image, button_area)
        return Button(area=button_area, color=color, button=button_area, name=name)

    def get_interval_timer(
        self,
        button: _HasName | str,
        interval: float = 5,
        *,
        renew: bool = False,
    ) -> Timer:
        name = button if isinstance(button, str) else button.name

        try:
            timer = self.interval_timer[name]
            if renew and timer.limit != interval:
                timer = Timer(interval)
                self.interval_timer[name] = timer
        except KeyError:
            timer = Timer(interval)
            self.interval_timer[name] = timer
            return timer
        else:
            return timer

    def interval_reset(self, button: Button | list[Button] | tuple[Button, ...] | None, interval: float = 3) -> None:
        if isinstance(button, (list, tuple)):
            for b in cast("list[Button] | tuple[Button, ...]", button):
                self.interval_reset(b)
            return

        if button is not None:
            if button.name in self.interval_timer:
                self.interval_timer[button.name].reset()
            else:
                self.interval_timer[button.name] = Timer(interval).reset()

    def interval_clear(self, button: Button | list[Button] | tuple[Button, ...] | None, interval: float = 3) -> None:
        if isinstance(button, (list, tuple)):
            for b in cast("list[Button] | tuple[Button, ...]", button):
                self.interval_clear(b)
            return

        if button is not None:
            if button.name in self.interval_timer:
                self.interval_timer[button.name].clear()
            else:
                self.interval_timer[button.name] = Timer(interval).clear()

    _image_file = ""

    @property
    def image_file(self) -> str:
        return self._image_file

    @image_file.setter
    def image_file(self, value: str | Image.Image | ImageArray) -> None:
        """开发调试入口：用本地文件或 PIL 图像替换设备截图。"""
        if isinstance(value, Image.Image):
            value = np.array(value)
        elif isinstance(value, str):
            value = load_image(value)

        self.device.image = value
