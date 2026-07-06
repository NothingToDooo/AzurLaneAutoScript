from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import *
from module.device.method.minitouch import Minitouch
from module.device.method.nemu_ipc import NemuIpc
from module.logger import logger


class Control(Minitouch, NemuIpc):
    def handle_control_check(self, button):
        # Device 会覆盖这个检查入口。
        pass

    @cached_property
    def click_methods(self):
        return {
            "minitouch": self.click_minitouch,
            "nemu_ipc": self.click_nemu_ipc,
        }

    def click(self, button, control_check=True):
        """Method to click a button.

        Args:
            button (button.Button): AzurLane Button instance.
            control_check (bool):
        """
        if control_check:
            self.handle_control_check(button)
        x, y = random_rectangle_point(button.button)
        x, y = ensure_int(x, y)
        logger.info("Click %s @ %s" % (point2str(x, y), button))
        method = self.click_methods.get(self.config.Emulator_ControlMethod, self.click_minitouch)
        method(x, y)

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
        """Method to long click a button.

        Args:
            button (button.Button): AzurLane Button instance.
            duration(int, float, tuple):
        """
        self.handle_control_check(button)
        x, y = random_rectangle_point(button.button)
        x, y = ensure_int(x, y)
        duration = ensure_time(duration)
        logger.info("Click %s @ %s, %s" % (point2str(x, y), button, duration))
        method = self.config.Emulator_ControlMethod
        if method == "nemu_ipc":
            self.long_click_nemu_ipc(x, y, duration)
        else:
            self.long_click_minitouch(x, y, duration)

    def swipe(self, p1, p2, duration=(0.1, 0.2), name="SWIPE", distance_check=True):
        self.handle_control_check(name)
        p1, p2 = ensure_int(p1, p2)
        duration = ensure_time(duration)
        method = self.config.Emulator_ControlMethod
        if method in ["minitouch", "nemu_ipc"]:
            logger.info("Swipe %s -> %s" % (point2str(*p1), point2str(*p2)))
        else:
            logger.info("Swipe %s -> %s" % (point2str(*p1), point2str(*p2)))

        if distance_check:
            if np.linalg.norm(np.subtract(p1, p2)) < 10:
                # 距离过短会被游戏当作点击。
                logger.info("Swipe distance < 10px, dropped")
                return

        if method == "nemu_ipc":
            self.swipe_nemu_ipc(p1, p2)
        else:
            self.swipe_minitouch(p1, p2)

    def swipe_vector(
        self,
        vector,
        box=(123, 159, 1175, 628),
        random_range=(0, 0, 0, 0),
        padding=15,
        duration=(0.1, 0.2),
        whitelist_area=None,
        blacklist_area=None,
        name="SWIPE",
        distance_check=True,
    ):
        """Method to swipe.

        Args:
            box (tuple): Swipe in box (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
            vector (tuple): (x, y).
            random_range (tuple): (x_min, y_min, x_max, y_max).
            padding (int):
            duration (int, float, tuple):
            whitelist_area: (list[tuple[int]]):
                A list of area that safe to click. Swipe path will end there.
            blacklist_area: (list[tuple[int]]):
                If none of the whitelist_area satisfies current vector, blacklist_area will be used.
                Delete random path that ends in any blacklist_area.
            name (str): Swipe name
            distance_check: (bool):
        """
        p1, p2 = random_rectangle_vector_opted(
            vector,
            box=box,
            random_range=random_range,
            padding=padding,
            whitelist_area=whitelist_area,
            blacklist_area=blacklist_area,
        )
        self.swipe(p1, p2, duration=duration, name=name, distance_check=distance_check)

    def drag(
        self,
        p1,
        p2,
        segments=1,
        shake=(0, 15),
        point_random=(-10, -10, 10, 10),
        shake_random=(-5, -5, 5, 5),
        swipe_duration=0.25,
        shake_duration=0.1,
        name="DRAG",
    ):
        self.handle_control_check(name)
        p1, p2 = ensure_int(p1, p2)
        logger.info("Drag %s -> %s" % (point2str(*p1), point2str(*p2)))
        method = self.config.Emulator_ControlMethod
        if method == "nemu_ipc":
            self.drag_nemu_ipc(p1, p2, point_random=point_random)
        else:
            self.drag_minitouch(p1, p2, point_random=point_random)
