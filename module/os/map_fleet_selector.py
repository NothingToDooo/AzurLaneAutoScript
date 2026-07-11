import numpy as np

from module.base.button import Button
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import area_offset, area_pad, get_color, image_size
from module.logger import logger
from module.os.assets import FLEET_1, FLEET_2, FLEET_3, FLEET_4, FLEET_BAR, FLEET_CHOOSE
from module.os_handler.map_event import MapEventHandler


class FleetSelector:
    FLEET_BAR_SHAPE_Y = 42
    FLEET_BAR_MARGIN_Y = 11
    FLEET_BAR_ACTIVE_STD = 45  # 选中约为 67，未选中约为 12。

    def __init__(self, main):
        self._choose = FLEET_CHOOSE
        self._bar = FLEET_BAR
        self.main = main

    def get(self):
        """返回当前舰队编号 1 至 4；无法识别时返回 0。"""
        for index, button in enumerate([FLEET_1, FLEET_2, FLEET_3, FLEET_4]):
            if self.main.appear(button, offset=(20, 20), similarity=0.75):
                return index + 1

        logger.info("Unknown OpSi fleet")
        return 0

    def bar_opened(self):
        # 只检查第 3 至 13 列，并要求至少两个灰色项和一个蓝色项。
        area = self._bar.area
        area = (area[0] + 3, area[1], area[0] + 13, area[3])
        return self.main.image_color_count(
            area, color=(239, 243, 247), threshold=221, count=400
        ) and self.main.image_color_count(area, color=(66, 125, 231), threshold=221, count=150)

    def parse_fleet_bar(self, image):
        """从下拉菜单截图返回当前选中的舰队编号列表，值域为 1 至 4。"""
        width, height = image_size(image)
        result = []
        for index, y in enumerate(range(0, height, self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y)):
            area = (0, y, width, y + self.FLEET_BAR_SHAPE_Y)
            mean = get_color(image, area)
            if np.std(mean, ddof=1) > self.FLEET_BAR_ACTIVE_STD:
                result.append(4 - index)

        logger.info(f"Current selected: {result}")
        return result

    def selected(self):
        """返回当前选中的舰队编号列表，编号范围为 1 到 4。"""
        return self.parse_fleet_bar(self.main.image_crop(self._bar, copy=False))

    def get_button(self, index):
        """把 1 至 4 的舰队编号转换为下拉菜单按钮。"""
        index = 5 - index
        area = area_offset(
            area=(
                0,
                (self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y) * (index - 1),
                self._bar.area[2] - self._bar.area[0],
                (self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y) * (index - 1) + self.FLEET_BAR_SHAPE_Y,
            ),
            offset=(self._bar.area[0:2]),
        )
        area = area_pad(area, pad=3)
        index = 5 - index
        return Button(area=(), color=(), button=area, name=f"{self._bar}_INDEX_{index}")

    def open(self):
        main = self.main
        click_timer = Timer(3, count=6)
        for _ in main.loop():
            if main.handle_map_event():
                click_timer.reset()
                continue

            if self.bar_opened():
                break

            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def close(self):
        main = self.main
        click_timer = Timer(3, count=6)
        for _ in main.loop():
            if not self.bar_opened():
                break

            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def click(self, index):
        """在下拉菜单选择编号 1 至 4 的舰队，并关闭菜单。"""
        main = self.main
        button = self.get_button(index)
        click_timer = Timer(3, count=6)
        for _ in main.loop():
            if main.handle_map_event():
                click_timer.reset()
                continue

            if not self.bar_opened():
                if self.get() == index:
                    break
                # 游戏响应没有这么快。
                if click_timer.reached():
                    self.open()

            if click_timer.reached():
                main.device.click(button)
                click_timer.reset()

    def ensure_to_be(self, index):
        """确保切换到编号 1 至 4 的舰队，并返回是否发生切换。"""
        confirm_timer = Timer(1.5, count=5).start()
        main = self.main
        for _ in main.loop():
            if confirm_timer.reached():
                break

            if main.handle_map_event():
                confirm_timer.reset()
                continue

            current = self.get()
            if current == index:
                logger.info(f"It is fleet {index} already")
                return False
            if current > 0:
                logger.info(f"Ensure fleet to be {index}")
                self.open()
                self.click(index)
                return True

        logger.warning("Unknown OpSi fleet, use current fleet instead")
        return False


class OSFleetSelector(MapEventHandler):
    @cached_property
    def fleet_selector(self):
        return FleetSelector(main=self)
