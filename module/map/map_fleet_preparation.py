import cv2
import numpy as np
from scipy import signal

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import area_offset, color_similar, color_similarity_2d, get_color, image_size, rgb2gray
from module.exception import RequestHumanTakeover
from module.handler.assets import (
    AUTO_SEARCH_SET_ALL,
    AUTO_SEARCH_SET_BOSS,
    AUTO_SEARCH_SET_MOB,
    AUTO_SEARCH_SET_STANDBY,
    AUTO_SEARCH_SET_SUB_AUTO,
    AUTO_SEARCH_SET_SUB_STANDBY,
)
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map import assets as map_assets


class FleetOperator:
    FLEET_BAR_SHAPE_Y = 33
    FLEET_BAR_MARGIN_Y = 9
    FLEET_BAR_ACTIVE_STD = 45  # 已激活：67，未激活：12。
    FLEET_IN_USE_STD = 27  # 使用中 52，未使用为 (3, 6)。

    OFFSET = (-20, -80, 20, 5)

    def __init__(self, choose, advice, bar, clear, in_use, hard_satisfied, main):
        """
        Args:
            choose (Button): Button to activate or deactivate dropdown menu.
            advice (Button): Button to recommend ships.
            bar (Button): Dropdown menu for fleet selection。
            clear (Button): Button to clear current fleet.
            in_use (Button): Button to detect if it's using current fleet.
            hard_satisfied (Button): Area to detect if fleet satiesfies hard restrictions.
            main (InfoHandler): Alas module.
        """
        self._choose = choose
        self._advice = advice
        self._bar = bar
        self._clear = clear
        self._in_use = in_use
        self._hard_satisfied = hard_satisfied
        self.main = main

        if main.appear(clear, offset=FleetOperator.OFFSET):
            choose.load_offset(clear)
            bar.load_offset(clear)
            in_use.load_offset(clear)
            hard_satisfied.load_offset(clear)

    def __str__(self):
        return str(self._choose)[:-7]

    def parse_fleet_bar(self, image):
        """
        Args:
            image (np.ndarray): Image of dropdown menu.

        Returns:
            list: List of int. Currently selected fleet ranges from 1 to 6.
        """
        width, height = image_size(image)
        result = []
        for index, y in enumerate(range(0, height, self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y)):
            area = (0, y, width, y + self.FLEET_BAR_SHAPE_Y)
            mean = get_color(image, area)
            if np.std(mean, ddof=1) > self.FLEET_BAR_ACTIVE_STD:
                result.append(index + 1)
        logger.info(f"Current selected: {result}")
        return result

    def get_button(self, index):
        """
        Convert fleet index to the Button object on dropdown menu.

        Args:
            index (int): Fleet index, 1-6.

        Returns:
            Button: Button instance.
        """
        bar = self._bar.button
        area = area_offset(
            area=(
                0,
                (self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y) * (index - 1),
                bar[2] - bar[0],
                (self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y) * (index - 1) + self.FLEET_BAR_SHAPE_Y,
            ),
            offset=(bar[0:2]),
        )
        return Button(area=(), color=(), button=area, name=f"{self._bar}_INDEX_{index}")

    def allow(self):
        """
        Returns:
            bool: If current fleet is allow to be chosen.
        """
        return self.main.appear(self._clear, offset=FleetOperator.OFFSET)

    def is_hard(self):
        """
        Returns:
            bool: Whether to have a recommend. If so, this stage is a hard campaign.
        """
        return self.main.appear(self._advice, offset=FleetOperator.OFFSET)

    def is_hard_satisfied(self):
        """
        Detect how many light orange lines are there.
        Having lines means current map has stat limits and user has satisfied at least one of them,
        so this is a hard map.

        Returns:
            bool: If current fleet satisfies hard restrictions.
                Or None if this is not a hard mode
        """
        if not self.is_hard():
            return None

        area = self._hard_satisfied.button
        image = color_similarity_2d(self.main.image_crop(area, copy=False), color=(249, 199, 0))
        height = cv2.reduce(image, 1, cv2.REDUCE_AVG).flatten()
        parameters = {"height": 180, "distance": 5}
        peaks, _ = signal.find_peaks(height, **parameters)
        lines = len(peaks)
        # logger.attr('Light_orange_line', lines)
        return lines > 0

    def raise_hard_not_satisfied(self):
        if self.is_hard_satisfied() is False:
            stage = self.main.config.Campaign_Name
            logger.critical(
                f'Stage "{stage}" is a hard mode, please prepare your fleet "{self!s}" in game before running Alas'
            )
            raise RequestHumanTakeover

    def clear(self, skip_first_screenshot=True):
        """
        Clear chosen fleet.
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 清理困难舰队时的弹窗。
            if self.main.handle_popup_confirm(str(self._clear)):
                continue

            # 检查 CLEAR 按钮，避免在弹窗显示动画期间提前停止。
            if self.allow():
                # 结束。
                if not self.in_use():
                    break

                # 点击。
                if click_timer.reached():
                    main.device.click(self._clear)
                    click_timer.reset()

    def recommend(self, skip_first_screenshot=True):
        """
        Recommend fleet
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 结束。
            if self.in_use():
                break

            # 点击。
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def open(self, skip_first_screenshot=True):
        """
        Activate dropdown menu for fleet selection.
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 结束。
            if self.bar_opened():
                break

            # 点击。
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def close(self, skip_first_screenshot=True):
        """
        Deactivate dropdown menu for fleet selection.
        """
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 结束。
            if not self.bar_opened():
                break

            # 点击。
            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def click(self, index, skip_first_screenshot=True):
        """
        Choose a fleet on dropdown menu, and dropdown deactivated.

        Args:
            index (int): Fleet index, 1-6.
            skip_first_screenshot (bool):
        """
        main = self.main
        button = self.get_button(index)
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            if not self.bar_opened():
                # 结束。
                if self.in_use():
                    break
                self.open()

            # 点击。
            if click_timer.reached():
                main.device.click(button)
                click_timer.reset()

    def selected(self):
        """
        返回：
            list：当前选择的舰队编号，范围为 1 到 6。
        """
        return self.parse_fleet_bar(self.main.image_crop(self._bar.button, copy=False))

    def in_use(self):
        """
        Returns:
            bool: If has selected to any fleet.
        """
        # 处理自律寻敌信息条。
        # if area_cross_area(self._in_use.area, INFO_BAR_1.area):
        #     self.main.handle_info_bar()

        # 裁剪 FLEET_*_IN_USE 以避开 info_bar，也能达到同样效果。
        # 这样还能避免浪费时间处理 info_bar。
        image = self.main.image_crop(self._in_use.button, copy=False)

        # 针对英仙座皮肤的特殊修正，它的颜色过于平坦。
        # https://github.com/LmeSzinc/AzurLaneAutoScript/issues/5678
        # 没有舰船时颜色为 (71, 70, 63)。
        color = cv2.mean(image)[:3]
        if color_similar(color, (224, 154, 114), threshold=30):
            return True

        gray = rgb2gray(image)
        return np.std(gray.flatten(), ddof=1) > self.FLEET_IN_USE_STD

    def bar_opened(self):
        """
        Returns:
            bool: If dropdown menu appears.
        """
        # 检查列表区域最右列的亮度。
        luma = rgb2gray(self.main.image_crop(self._bar.button, copy=False))[:, -1]
        # FLEET_PREPARATION is about 146~155
        return np.sum(luma > 168) / luma.size > 0.5

    def ensure_to_be(self, index):
        """
        Set to a specific fleet.

        Args:
            index (int): Fleet index, 1-6.
        """
        self.open()
        if index in self.selected():
            self.close()
        else:
            self.click(index)


class FleetPreparation(InfoHandler):
    map_fleet_checked = False
    map_is_hard_mode = False

    def fleet_preparation(self):
        """Change fleets.

        Returns:
            bool: True if changed.
        """
        logger.info(f"Using fleet: {[self.config.Fleet_Fleet1, self.config.Fleet_Fleet2, self.config.Submarine_Fleet]}")
        if self.map_fleet_checked:
            return False

        if self.appear(map_assets.FLEET_1_CLEAR, offset=FleetOperator.OFFSET):
            AUTO_SEARCH_SET_MOB.load_offset(map_assets.FLEET_1_CLEAR)
            AUTO_SEARCH_SET_BOSS.load_offset(map_assets.FLEET_1_CLEAR)
            AUTO_SEARCH_SET_ALL.load_offset(map_assets.FLEET_1_CLEAR)
            AUTO_SEARCH_SET_STANDBY.load_offset(map_assets.FLEET_1_CLEAR)
        if self.appear(map_assets.SUBMARINE_CLEAR, offset=FleetOperator.OFFSET):
            AUTO_SEARCH_SET_SUB_AUTO.load_offset(map_assets.SUBMARINE_CLEAR)
            AUTO_SEARCH_SET_SUB_STANDBY.load_offset(map_assets.SUBMARINE_CLEAR)

        fleet_1 = FleetOperator(
            choose=map_assets.FLEET_1_CHOOSE,
            advice=map_assets.FLEET_1_ADVICE,
            bar=map_assets.FLEET_1_BAR,
            clear=map_assets.FLEET_1_CLEAR,
            in_use=map_assets.FLEET_1_IN_USE,
            hard_satisfied=map_assets.FLEET_1_HARD_SATIESFIED,
            main=self,
        )
        y = map_assets.FLEET_1_CLEAR.button[1] - map_assets.FLEET_1_CLEAR.area[1]
        if y < -10:
            logger.info("FLEET_1_CLEAR moves up, load W15 assets")
            in_use = map_assets.FLEET_2_IN_USE_W15
        else:
            in_use = map_assets.FLEET_2_IN_USE
        fleet_2 = FleetOperator(
            choose=map_assets.FLEET_2_CHOOSE,
            advice=map_assets.FLEET_2_ADVICE,
            bar=map_assets.FLEET_2_BAR,
            clear=map_assets.FLEET_2_CLEAR,
            in_use=in_use,
            hard_satisfied=map_assets.FLEET_2_HARD_SATIESFIED,
            main=self,
        )
        submarine = FleetOperator(
            choose=map_assets.SUBMARINE_CHOOSE,
            advice=map_assets.SUBMARINE_ADVICE,
            bar=map_assets.SUBMARINE_BAR,
            clear=map_assets.SUBMARINE_CLEAR,
            in_use=map_assets.SUBMARINE_IN_USE,
            hard_satisfied=map_assets.SUBMARINE_HARD_SATIESFIED,
            main=self,
        )

        # 检查困难模式舰船是否已准备。
        h1, h2, h3 = fleet_1.is_hard_satisfied(), fleet_2.is_hard_satisfied(), submarine.is_hard_satisfied()
        logger.info(f"Hard satisfied: Fleet_1: {h1}, Fleet_2: {h2}, Submarine: {h3}")
        if self.config.Fleet_Fleet1:
            fleet_1.raise_hard_not_satisfied()
        if self.config.Fleet_Fleet2:
            fleet_2.raise_hard_not_satisfied()
        if self.config.Submarine_Fleet:
            submarine.raise_hard_not_satisfied()

        # 困难模式跳过舰队准备。
        self.map_is_hard_mode = h1 or h2 or h3
        if self.map_is_hard_mode:
            logger.info("Hard Campaign. No fleet preparation")
            # 如果用户未设置潜艇舰队，清空潜艇。
            if submarine.allow():
                if self.config.Submarine_Fleet:
                    pass
                else:
                    submarine.clear()
            else:
                self.config.SUBMARINE = 0
            return False

        # 潜艇。
        # 缓存 submarine.allow()，避免设置 fleet_2 后结果不一致。
        # 展开的 fleet_2 可能覆盖潜艇按钮。
        map_allow_submarine = submarine.allow()
        logger.attr("map_allow_submarine", map_allow_submarine)
        if map_allow_submarine:
            if self.config.Submarine_Fleet:
                if fleet_2.allow():
                    self.device.click(fleet_2._clear)
                    # 不需要重新截图，因为潜艇检查不需要 fleet_2 部分。
                submarine.ensure_to_be(self.config.Submarine_Fleet)
            else:
                # 用简单点击同时清空 submarine 和 fleet2。
                # 这样更快，因为不需要等待点击动画消失。
                # 后续 clear() 调用可以保证点击成功。
                op = False
                if fleet_2.allow():
                    self.device.click(fleet_2._clear)
                    op = True
                if submarine.allow():
                    self.device.click(submarine._clear)
                    op = True
                if op:
                    self.device.screenshot()

        # 不需要，这可能会误清 FLEET_2；在地图配置里清理 FLEET_2。
        # if not fleet_2.allow():
        #     self.config.FLEET_2 = 0

        if self.config.Fleet_Fleet2:
            # 使用两支舰队。
            # 强制重新设置一次。
            # AL 不再把编号较小的舰队当作第一舰队，因此舰队可能被反转。
            fleet_2.clear()
            fleet_1.ensure_to_be(self.config.Fleet_Fleet1)
            fleet_2.ensure_to_be(self.config.Fleet_Fleet2)
        else:
            # 不使用 fleet 2。
            if fleet_2.allow():
                fleet_2.clear()
            fleet_1.ensure_to_be(self.config.Fleet_Fleet1)

        # 再次检查潜艇是否为空。
        if map_allow_submarine:
            if self.config.Submarine_Fleet:
                pass
            else:
                submarine.clear()
        else:
            self.config.SUBMARINE = 0

        return True
