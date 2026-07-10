import time
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any

import cv2
from PIL import Image

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import get_color, image_size, limit_in, save_image
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np


class Screenshot:
    image: np.ndarray
    app_is_running: Callable[[], bool]
    capture: Any
    config: Any
    get_orientation: Callable[[], object]
    orientation: int
    serial: str

    def __init__(self, *args, **kwargs):
        self._screen_size_checked = False
        self._screen_black_checked = False
        self._screenshot_interval = Timer(0.1)
        super().__init__(*args, **kwargs)

    def screenshot(self):
        """
        Returns:
            np.ndarray:
        """
        self._screenshot_interval.wait()
        self._screenshot_interval.reset()

        for _ in range(2):
            self.image = self.capture.screenshot()

            self.image = self._handle_orientated_image(self.image)

            if self.config.Error_SaveError:
                self.screenshot_deque.append({"time": datetime.now(), "image": self.image})

            if self.check_screen_size() and self.check_screen_black():
                break
            continue

        return self.image

    @property
    def has_cached_image(self):
        return hasattr(self, "image") and self.image is not None

    def _handle_orientated_image(self, image):
        """
        Args:
            image (np.ndarray):

        Returns:
            np.ndarray:
        """
        width, height = image_size(self.image)
        if width == 1280 and height == 720:
            return image

        # 截图方向不为 1280x720 时再按设备方向旋转。
        if self.orientation == 0:
            pass
        elif self.orientation == 1:
            image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif self.orientation == 2:
            image = cv2.rotate(image, cv2.ROTATE_180)
        elif self.orientation == 3:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        else:
            message = f"Invalid device orientation: {self.orientation}"
            raise ScriptError(message)

        return image

    @cached_property
    def screenshot_deque(self):
        try:
            length = int(self.config.Error_ScreenshotLength)
        except ValueError as e:
            logger.error(f"Error_ScreenshotLength={self.config.Error_ScreenshotLength} is not an integer")
            raise RequestHumanTakeover from e
        # 限制在 1~300。
        length = max(1, min(length, 300))
        return deque(maxlen=length)

    def screenshot_interval_clear(self) -> None:
        self._screenshot_interval.clear()

    def screenshot_interval_set(self, interval=None):
        """
        Args:
            interval (int, float, str):
                Minimum interval between 2 screenshots in seconds.
                Or None for Optimization_ScreenshotInterval, 'combat' for Optimization_CombatScreenshotInterval
        """
        if interval is None:
            origin = self.config.Optimization_ScreenshotInterval
            interval = limit_in(origin, 0.1, 0.3)
            if interval != origin:
                logger.warning(f"Optimization.ScreenshotInterval {origin} is revised to {interval}")
                self.config.Optimization_ScreenshotInterval = interval
            # 当前个人版固定使用 nemu_ipc 截图，可以使用更低的默认截图间隔。
            interval = limit_in(origin, 0.1, 0.2)
        elif interval == "combat":
            origin = self.config.Optimization_CombatScreenshotInterval
            interval = limit_in(origin, 0.3, 1.0)
            if interval != origin:
                logger.warning(f"Optimization.CombatScreenshotInterval {origin} is revised to {interval}")
                self.config.Optimization_CombatScreenshotInterval = interval
        elif isinstance(interval, (int, float)):
            # No limitation for manual set in code
            pass
        else:
            logger.warning(f"Unknown screenshot interval: {interval}")
            message = f"Unknown screenshot interval: {interval}"
            raise ScriptError(message)
        if interval != self._screenshot_interval.limit:
            logger.info(f"Screenshot interval set to {interval}s")
            self._screenshot_interval.limit = interval

    def image_show(self, image=None):
        if image is None:
            image = self.image
        Image.fromarray(image).show()

    def image_save(self, file=None):
        if file is None:
            file = f"{int(time.time() * 1000)}.png"
        save_image(self.image, file)

    def check_screen_size(self):
        """
        Screen size must be 1280x720.
        Take a screenshot before call.
        """
        if self._screen_size_checked:
            return True

        orientated = False
        for _ in range(2):
            # Check screen size
            width, height = image_size(self.image)
            logger.attr("Screen_size", f"{width}x{height}")
            if width == 1280 and height == 720:
                self._screen_size_checked = True
                return True
            if not orientated and (width == 720 and height == 1280):
                logger.info("Received orientated screenshot, handling")
                self.get_orientation()
                self.image = self._handle_orientated_image(self.image)
                orientated = True
                width, height = image_size(self.image)
                if width == 720 and height == 1280:
                    logger.info("Unable to handle orientated screenshot, continue for now")
                    return True
                continue
            if not self.app_is_running():
                logger.warning("Received orientated screenshot, game not running")
                return True
            logger.critical(f"Resolution not supported: {width}x{height}")
            logger.critical("Please set emulator resolution to 1280x720")
            raise RequestHumanTakeover
        return False

    def check_screen_black(self):
        if self._screen_black_checked:
            return True
        # 某些模拟器偶尔会返回纯黑截图。
        color = get_color(self.image, area=(0, 0, 1280, 720))
        if sum(color) < 1:
            logger.warning(f"Received pure black screenshots from emulator, color: {color}")
            logger.warning(
                f"Screenshot method `nemu_ipc` may not work on emulator `{self.serial}`, "
                f"or the emulator is not fully started"
            )
            self._screen_black_checked = False
            return False
        self._screen_black_checked = True
        return True
