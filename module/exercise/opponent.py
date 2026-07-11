import numpy as np

from module.base.button import ButtonGrid
from module.base.utils import image_left_strip
from module.exercise.assets import EXERCISE_PREPARATION, NEW_OPPONENT
from module.logger import logger
from module.ocr.ocr import Digit
from module.ui.assets import BACK_ARROW
from module.ui.ui import UI

OPPONENT = ButtonGrid(origin=(104, 77), delta=(244, 0), button_shape=(212, 304), grid_shape=(4, 1))

# easiest 模式以满编最高等级 6×125 为上限，并把战力缩放到等级评分量级。
MAX_LVL_SUM = 750
PWR_FACTOR = 100


class Level(Digit):
    def pre_process(self, image):
        image = super().pre_process(image)
        image = image_left_strip(image, threshold=85, length=22)

        image = np.pad(image, ((5, 6), (0, 5)), mode="constant", constant_values=255)
        return image.astype(np.uint8)


class Opponent:
    def __init__(self, main_image, fleet_image, index):
        self.index = index
        self.power = self.get_power(image=main_image)
        self.level = self.get_level(image=fleet_image)

        level = [str(x).rjust(3, " ") for x in self.level]
        power = ["(" + str(x).rjust(5, " ") + ")" for x in self.power]
        logger.attr(f"OPPONENT_{index}", " ".join([power[0], *level[:3], "|", power[1], *level[3:]]))

    @staticmethod
    def get_level(image):
        """从 EXERCISE_PREPARATION 截图返回六个舰船等级。"""
        level = []
        level += ButtonGrid(
            origin=(130, 259), delta=(168, 0), button_shape=(58, 21), grid_shape=(3, 1), name="LEVEL"
        ).buttons
        level += ButtonGrid(
            origin=(832, 259), delta=(168, 0), button_shape=(58, 21), grid_shape=(3, 1), name="LEVEL"
        ).buttons

        level = Level(level, name="LEVEL", letter=(255, 255, 255), threshold=128)
        return level.ocr(image)

    def get_power(self, image):
        """从演习主页截图返回当前对手的前后排战力。"""
        grids = ButtonGrid(origin=(222, 257), delta=(244, 30), button_shape=(72, 28), grid_shape=(4, 2), name="POWER")
        power = [grids[self.index, 0], grids[self.index, 1]]

        power = Digit(power, name="POWER", letter=(255, 223, 57), threshold=128)
        return power.ocr(image)

    def get_priority(self, method="max_exp"):
        """按选择策略计算当前对手评分；数值越高越优先。"""
        if "easiest" in method:
            level = (1 - (np.sum(self.level) / MAX_LVL_SUM)) * 100
            team_pwr_div = np.count_nonzero(self.level) * PWR_FACTOR
            avg_team_pwr = np.sum(self.power) / team_pwr_div
            priority = level - avg_team_pwr
        else:
            priority = np.sum(self.level) / 6
        return priority


class OpponentChoose(UI):
    def __init__(self, *args, **kwargs):
        self.main_image = None
        self.opponents = []
        super().__init__(*args, **kwargs)

    def _opponent_fleet_check_all(self):
        self.opponents = []
        self.main_image = self.device.image

        for index in range(4):
            self.ui_click(
                click_button=OPPONENT[index, 0],
                check_button=EXERCISE_PREPARATION,
                appear_button=NEW_OPPONENT,
                skip_first_screenshot=True,
            )

            self.opponents.append(Opponent(main_image=self.main_image, fleet_image=self.device.image, index=index))

            self.ui_click(
                click_button=BACK_ARROW,
                check_button=NEW_OPPONENT,
                appear_button=EXERCISE_PREPARATION,
                skip_first_screenshot=True,
            )

    def _opponent_sort(self, method="max_exp"):
        """按评分从高到低返回四个对手索引。"""
        order = np.argsort([-x.get_priority(method) for x in self.opponents])
        logger.attr("Order", str(order))
        return order
