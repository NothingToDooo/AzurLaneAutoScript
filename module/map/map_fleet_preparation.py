from dataclasses import dataclass
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray


@dataclass(slots=True)
class FleetOperatorAssets:
    choose: Button
    advice: Button
    bar: Button
    clear: Button
    in_use: Button
    hard_satisfied: Button


class FleetOperator:
    FLEET_BAR_SHAPE_Y = 33
    FLEET_BAR_MARGIN_Y = 9
    FLEET_BAR_ACTIVE_STD = 45  # 已激活：67，未激活：12。
    FLEET_IN_USE_STD = 27  # 使用中 52，未使用为 (3, 6)。

    OFFSET = (-20, -80, 20, 5)

    def __init__(self, assets: FleetOperatorAssets, main: InfoHandler) -> None:
        self._choose = assets.choose
        self._advice = assets.advice
        self._bar = assets.bar
        self._clear = assets.clear
        self._in_use = assets.in_use
        self._hard_satisfied = assets.hard_satisfied
        self.main = main

        if main.appear(assets.clear, offset=FleetOperator.OFFSET):
            assets.choose.load_offset(assets.clear)
            assets.bar.load_offset(assets.clear)
            assets.in_use.load_offset(assets.clear)
            assets.hard_satisfied.load_offset(assets.clear)

    @property
    def clear_button(self) -> Button:
        return self._clear

    def __str__(self) -> str:
        return str(self._choose)[:-7]

    def parse_fleet_bar(self, image: ImageArray) -> list[int]:
        """返回下拉菜单中已选的舰队编号列表，编号范围为 1～6。"""
        width, height = image_size(image)
        result = []
        for index, y in enumerate(range(0, height, self.FLEET_BAR_SHAPE_Y + self.FLEET_BAR_MARGIN_Y)):
            area = (0, y, width, y + self.FLEET_BAR_SHAPE_Y)
            mean = get_color(image, area)
            if np.std(mean, ddof=1) > self.FLEET_BAR_ACTIVE_STD:
                result.append(index + 1)
        logger.info(f"Current selected: {result}")
        return result

    def get_button(self, index: int) -> Button:
        """把 1～6 的舰队编号映射为下拉菜单按钮。"""
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

    def allow(self) -> bool:
        return self.main.appear(self._clear, offset=FleetOperator.OFFSET)

    def is_hard(self) -> bool:
        return self.main.appear(self._advice, offset=FleetOperator.OFFSET)

    def is_hard_satisfied(self) -> bool | None:
        """以浅橙色限制线判断困难图是否达标；非困难模式返回 None。"""
        if not self.is_hard():
            return None

        area = self._hard_satisfied.button
        image = color_similarity_2d(self.main.image_crop(area, copy=False), color=(249, 199, 0))
        height = cv2.reduce(image, 1, cv2.REDUCE_AVG).flatten()
        parameters = {"height": 180, "distance": 5}
        peaks, _ = signal.find_peaks(height, **parameters)
        lines = len(peaks)
        return lines > 0

    def raise_hard_not_satisfied(self) -> None:
        if self.is_hard_satisfied() is False:
            stage = self.main.config.Campaign_Name
            logger.critical(
                f'Stage "{stage}" is a hard mode, please prepare your fleet "{self!s}" in game before running Alas'
            )
            raise RequestHumanTakeover

    def clear(self, *, skip_first_screenshot: bool = True) -> None:
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
                if not self.in_use():
                    break

                if click_timer.reached():
                    main.device.click(self._clear)
                    click_timer.reset()

    def recommend(self, *, skip_first_screenshot: bool = True) -> None:
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            if self.in_use():
                break

            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def open(self, *, skip_first_screenshot: bool = True) -> None:
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            if self.bar_opened():
                break

            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def close(self, *, skip_first_screenshot: bool = True) -> None:
        main = self.main
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            if not self.bar_opened():
                break

            if click_timer.reached():
                main.device.click(self._choose)
                click_timer.reset()

    def click(self, index: int, *, skip_first_screenshot: bool = True) -> None:
        """选择 1～6 号舰队并关闭下拉菜单。"""
        main = self.main
        button = self.get_button(index)
        click_timer = Timer(3, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            if not self.bar_opened():
                if self.in_use():
                    break
                self.open()

            if click_timer.reached():
                main.device.click(button)
                click_timer.reset()

    def selected(self) -> list[int]:
        """返回当前选择的舰队编号列表，编号范围为 1～6。"""
        return self.parse_fleet_bar(self.main.image_crop(self._bar.button, copy=False))

    def in_use(self) -> bool:
        # 裁剪 FLEET_*_IN_USE 以避开 info_bar，也能避免额外处理 info_bar。
        image = self.main.image_crop(self._in_use.button, copy=False)

        # 针对英仙座皮肤的特殊修正，它的颜色过于平坦。
        # https://github.com/LmeSzinc/AzurLaneAutoScript/issues/5678
        # 没有舰船时颜色为 (71, 70, 63)。
        color = cv2.mean(image)[:3]
        if color_similar(color, (224, 154, 114), threshold=30):
            return True

        gray = rgb2gray(image)
        return bool(np.std(gray.flatten(), ddof=1) > self.FLEET_IN_USE_STD)

    def bar_opened(self) -> bool:
        # 检查列表区域最右列的亮度。
        luma = rgb2gray(self.main.image_crop(self._bar.button, copy=False))[:, -1]
        # FLEET_PREPARATION is about 146~155
        return np.sum(luma > 168) / luma.size > 0.5

    def ensure_to_be(self, index: int) -> None:
        """确保选中 1～6 号中的指定舰队。"""
        self.open()
        if index in self.selected():
            self.close()
        else:
            self.click(index)


class FleetPreparation(InfoHandler):
    map_fleet_checked = False
    map_is_hard_mode = False

    def _load_fleet_asset_offsets(self) -> None:
        if self.appear(map_assets.FLEET_1_CLEAR, offset=FleetOperator.OFFSET):
            AUTO_SEARCH_SET_MOB.load_offset(map_assets.FLEET_1_CLEAR)
            AUTO_SEARCH_SET_BOSS.load_offset(map_assets.FLEET_1_CLEAR)
            AUTO_SEARCH_SET_ALL.load_offset(map_assets.FLEET_1_CLEAR)
            AUTO_SEARCH_SET_STANDBY.load_offset(map_assets.FLEET_1_CLEAR)
        if self.appear(map_assets.SUBMARINE_CLEAR, offset=FleetOperator.OFFSET):
            AUTO_SEARCH_SET_SUB_AUTO.load_offset(map_assets.SUBMARINE_CLEAR)
            AUTO_SEARCH_SET_SUB_STANDBY.load_offset(map_assets.SUBMARINE_CLEAR)

    @staticmethod
    def _fleet_2_in_use_button() -> Button:
        y = map_assets.FLEET_1_CLEAR.button[1] - map_assets.FLEET_1_CLEAR.area[1]
        if y < -10:
            logger.info("FLEET_1_CLEAR moves up, load W15 assets")
            return map_assets.FLEET_2_IN_USE_W15
        return map_assets.FLEET_2_IN_USE

    def _fleet_operators(self) -> tuple[FleetOperator, FleetOperator, FleetOperator]:
        fleet_1 = FleetOperator(
            assets=FleetOperatorAssets(
                choose=map_assets.FLEET_1_CHOOSE,
                advice=map_assets.FLEET_1_ADVICE,
                bar=map_assets.FLEET_1_BAR,
                clear=map_assets.FLEET_1_CLEAR,
                in_use=map_assets.FLEET_1_IN_USE,
                hard_satisfied=map_assets.FLEET_1_HARD_SATIESFIED,
            ),
            main=self,
        )
        fleet_2 = FleetOperator(
            assets=FleetOperatorAssets(
                choose=map_assets.FLEET_2_CHOOSE,
                advice=map_assets.FLEET_2_ADVICE,
                bar=map_assets.FLEET_2_BAR,
                clear=map_assets.FLEET_2_CLEAR,
                in_use=self._fleet_2_in_use_button(),
                hard_satisfied=map_assets.FLEET_2_HARD_SATIESFIED,
            ),
            main=self,
        )
        submarine = FleetOperator(
            assets=FleetOperatorAssets(
                choose=map_assets.SUBMARINE_CHOOSE,
                advice=map_assets.SUBMARINE_ADVICE,
                bar=map_assets.SUBMARINE_BAR,
                clear=map_assets.SUBMARINE_CLEAR,
                in_use=map_assets.SUBMARINE_IN_USE,
                hard_satisfied=map_assets.SUBMARINE_HARD_SATIESFIED,
            ),
            main=self,
        )
        return fleet_1, fleet_2, submarine

    def _check_fleet_hard_satisfied(
        self, fleet_1: FleetOperator, fleet_2: FleetOperator, submarine: FleetOperator
    ) -> bool:
        h1, h2, h3 = fleet_1.is_hard_satisfied(), fleet_2.is_hard_satisfied(), submarine.is_hard_satisfied()
        logger.info(f"Hard satisfied: Fleet_1: {h1}, Fleet_2: {h2}, Submarine: {h3}")
        if self.config.Fleet_Fleet1:
            fleet_1.raise_hard_not_satisfied()
        if self.config.Fleet_Fleet2:
            fleet_2.raise_hard_not_satisfied()
        if self.config.Submarine_Fleet:
            submarine.raise_hard_not_satisfied()
        return bool(h1 or h2 or h3)

    def _handle_hard_mode_fleet_preparation(self, submarine: FleetOperator) -> None:
        logger.info("Hard Campaign. No fleet preparation")
        # 如果用户未设置潜艇舰队，清空潜艇。
        if submarine.allow():
            if not self.config.Submarine_Fleet:
                submarine.clear()
        else:
            self.config.submarine = 0

    def _prepare_submarine_fleet(self, fleet_2: FleetOperator, submarine: FleetOperator) -> bool:
        # 缓存 submarine.allow()，避免设置 fleet_2 后结果不一致。
        # 展开的 fleet_2 可能覆盖潜艇按钮。
        map_allow_submarine = submarine.allow()
        logger.attr("map_allow_submarine", map_allow_submarine)
        if not map_allow_submarine:
            return False
        if self.config.Submarine_Fleet:
            if fleet_2.allow():
                self.device.click(fleet_2.clear_button)
                # 不需要重新截图，因为潜艇检查不需要 fleet_2 部分。
            submarine.ensure_to_be(self.config.Submarine_Fleet)
            return True
        # 用简单点击同时清空 submarine 和 fleet2。
        # 这样更快，因为不需要等待点击动画消失。
        # 后续 clear() 调用可以保证点击成功。
        op = False
        if fleet_2.allow():
            self.device.click(fleet_2.clear_button)
            op = True
        if submarine.allow():
            self.device.click(submarine.clear_button)
            op = True
        if op:
            self.device.screenshot()
        return True

    def _prepare_surface_fleets(self, fleet_1: FleetOperator, fleet_2: FleetOperator) -> None:
        if self.config.Fleet_Fleet2:
            # 强制重新设置一次。
            # AL 不再把编号较小的舰队当作第一舰队，因此舰队可能被反转。
            fleet_2.clear()
            fleet_1.ensure_to_be(self.config.Fleet_Fleet1)
            fleet_2.ensure_to_be(self.config.Fleet_Fleet2)
            return
        if fleet_2.allow():
            fleet_2.clear()
        fleet_1.ensure_to_be(self.config.Fleet_Fleet1)

    def _finalize_submarine_fleet(self, submarine: FleetOperator, *, map_allow_submarine: bool) -> None:
        # 再次检查潜艇是否为空。
        if map_allow_submarine:
            if not self.config.Submarine_Fleet:
                submarine.clear()
        else:
            self.config.submarine = 0

    def fleet_preparation(self) -> bool:
        logger.info(f"Using fleet: {[self.config.Fleet_Fleet1, self.config.Fleet_Fleet2, self.config.Submarine_Fleet]}")
        if self.map_fleet_checked:
            return False

        self._load_fleet_asset_offsets()
        fleet_1, fleet_2, submarine = self._fleet_operators()

        # 困难模式跳过舰队准备。
        self.map_is_hard_mode = self._check_fleet_hard_satisfied(fleet_1, fleet_2, submarine)
        if self.map_is_hard_mode:
            self._handle_hard_mode_fleet_preparation(submarine)
            return False

        map_allow_submarine = self._prepare_submarine_fleet(fleet_2, submarine)

        self._prepare_surface_fleets(fleet_1, fleet_2)
        self._finalize_submarine_fleet(submarine, map_allow_submarine=map_allow_submarine)

        return True
