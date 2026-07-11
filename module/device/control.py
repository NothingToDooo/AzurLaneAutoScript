from typing import TYPE_CHECKING, Any

import numpy as np

from module.base.timer import Timer
from module.base.utils import (
    SwipePathOptions,
    ensure_int,
    ensure_time,
    point2str,
    random_rectangle_point,
    random_rectangle_vector_opted,
)
from module.device.control_options import SwipeVectorOptions
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.device.minitouch_service import MinitouchController


class Control:
    controller: MinitouchController
    sleep: Callable[[Any], None]

    def handle_control_check(self, button):
        # Device 会覆盖这个检查入口。
        pass

    @property
    def minitouch_builder(self):
        return self.controller.minitouch_builder

    def early_minitouch_init(self):
        return self.controller.early_init()

    def click_minitouch(self, x, y):
        return self.controller.click(x, y)

    def long_click_minitouch(self, x, y, duration=1.0):
        return self.controller.long_click(x, y, duration)

    def swipe_minitouch(self, p1, p2):
        return self.controller.swipe(p1, p2)

    def drag_minitouch(self, p1, p2, point_random=(-10, -10, 10, 10)):
        return self.controller.drag(p1, p2, point_random=point_random)

    def click(self, button, *, control_check=True):
        if control_check:
            self.handle_control_check(button)
        x, y = random_rectangle_point(button.button)
        x, y = ensure_int(x, y)
        logger.info(f"Click {point2str(x, y)} @ {button}")
        self.click_minitouch(x, y)

    def multi_click(self, button, n, interval=(0.1, 0.2)):
        self.handle_control_check(button)
        click_timer = Timer(0.1)
        for _ in range(n):
            remain = ensure_time(interval) - click_timer.current_time()
            if remain > 0:
                self.sleep(remain)
            click_timer.reset()

            self.click(button, control_check=False)

    def long_click(self, button, duration=(1, 1.2)):
        self.handle_control_check(button)
        x, y = random_rectangle_point(button.button)
        x, y = ensure_int(x, y)
        duration = ensure_time(duration)
        logger.info(f"Click {point2str(x, y)} @ {button}, {duration}")
        self.long_click_minitouch(x, y, duration)

    def swipe(self, p1, p2, duration=(0.1, 0.2), name="SWIPE", *, distance_check=True):
        self.handle_control_check(name)
        p1, p2 = ensure_int(p1, p2)
        duration = ensure_time(duration)
        logger.info(f"Swipe {point2str(*p1)} -> {point2str(*p2)}")

        if distance_check and np.linalg.norm(np.subtract(p1, p2)) < 10:
            # 距离过短会被游戏当作点击。
            logger.info("Swipe distance < 10px, dropped")
            return

        self.swipe_minitouch(p1, p2)

    def swipe_vector(self, vector, options=None):
        """vector 是 (x, y) 位移，options 控制路径、时长和距离校验。"""
        if options is None:
            options = SwipeVectorOptions()
        p1, p2 = random_rectangle_vector_opted(
            vector,
            SwipePathOptions(
                box=options.box,
                random_range=options.random_range,
                padding=options.padding,
                whitelist_area=options.whitelist_area,
                blacklist_area=options.blacklist_area,
            ),
        )
        self.swipe(p1, p2, duration=options.duration, name=options.name, distance_check=options.distance_check)

    def drag(
        self,
        p1,
        p2,
        point_random=(-10, -10, 10, 10),
        name="DRAG",
    ):
        self.handle_control_check(name)
        p1, p2 = ensure_int(p1, p2)
        logger.info(f"Drag {point2str(*p1)} -> {point2str(*p2)}")
        self.drag_minitouch(p1, p2, point_random=point_random)
