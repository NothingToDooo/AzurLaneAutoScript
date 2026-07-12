from typing import TYPE_CHECKING, Protocol

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
from module.replay.trace import ClickAction, RecordedAction, SwipeAction

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.base.type_alias import Area, Point
    from module.device.contracts import ControllerService
    from module.device.control_options import Duration
    from module.device.minitouch_service import CommandBuilder


class ButtonTarget(Protocol):
    @property
    def button(self) -> Area: ...


def _ensure_point(point: Point) -> tuple[int, int]:
    converted = ensure_int(point)
    return converted[0], converted[1]


class Control:
    controller: ControllerService
    sleep: Callable[[Duration], None]

    def handle_control_check(self, button: ButtonTarget | str) -> None:
        # Device 会覆盖这个检查入口。
        pass

    def replay_record_action(self, action: RecordedAction) -> None:
        # Device 会把动作绑定到最近截图。
        del self, action

    def replay_mark_unsupported_action(self, action: str) -> None:
        # ReplayDevice 尚不支持的控制会阻止错误包发布伪完整 trace。
        del self, action

    @property
    def minitouch_builder(self) -> CommandBuilder:
        return self.controller.minitouch_builder

    def early_minitouch_init(self) -> None:
        return self.controller.early_init()

    def click_minitouch(self, x: int, y: int) -> None:
        return self.controller.click(x, y)

    def long_click_minitouch(self, x: int, y: int, duration: float = 1.0) -> None:
        return self.controller.long_click(x, y, duration)

    def swipe_minitouch(self, p1: Point, p2: Point) -> None:
        return self.controller.swipe(p1, p2)

    def drag_minitouch(self, p1: Point, p2: Point, point_random: Area = (-10, -10, 10, 10)) -> None:
        return self.controller.drag(p1, p2, point_random=point_random)

    def click(self, button: ButtonTarget, *, control_check: bool = True) -> None:
        if control_check:
            self.handle_control_check(button)
        x, y = random_rectangle_point(button.button)
        x, y = ensure_int(x, y)
        self.replay_record_action(ClickAction(target=str(button)))
        logger.info(f"Click {point2str(x, y)} @ {button}")
        self.click_minitouch(x, y)

    def multi_click(self, button: ButtonTarget, n: int, interval: Duration = (0.1, 0.2)) -> None:
        self.handle_control_check(button)
        click_timer = Timer(0.1)
        for _ in range(n):
            remain = float(ensure_time(interval)) - click_timer.current_time()
            if remain > 0:
                self.sleep(remain)
            click_timer.reset()

            self.click(button, control_check=False)

    def long_click(self, button: ButtonTarget, duration: Duration = (1, 1.2)) -> None:
        self.handle_control_check(button)
        x, y = random_rectangle_point(button.button)
        x, y = ensure_int(x, y)
        duration_value = float(ensure_time(duration))
        self.replay_mark_unsupported_action("long_click")
        logger.info(f"Click {point2str(x, y)} @ {button}, {duration_value}")
        self.long_click_minitouch(x, y, duration_value)

    def swipe(
        self,
        p1: Point,
        p2: Point,
        duration: Duration = (0.1, 0.2),
        name: str = "SWIPE",
        *,
        distance_check: bool = True,
    ) -> None:
        self.handle_control_check(name)
        start = _ensure_point(p1)
        end = _ensure_point(p2)
        _ = float(ensure_time(duration))
        logger.info(f"Swipe {point2str(*start)} -> {point2str(*end)}")

        if distance_check and np.linalg.norm(np.subtract(start, end)) < 10:
            # 距离过短会被游戏当作点击。
            logger.info("Swipe distance < 10px, dropped")
            return

        self.replay_record_action(SwipeAction(start=start, end=end))
        self.swipe_minitouch(start, end)

    def swipe_vector(self, vector: Point, options: SwipeVectorOptions | None = None) -> None:
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
        p1: Point,
        p2: Point,
        point_random: Area = (-10, -10, 10, 10),
        name: str = "DRAG",
    ) -> None:
        self.handle_control_check(name)
        start = _ensure_point(p1)
        end = _ensure_point(p2)
        self.replay_mark_unsupported_action("drag")
        logger.info(f"Drag {point2str(*start)} -> {point2str(*end)}")
        self.drag_minitouch(start, end, point_random=point_random)
