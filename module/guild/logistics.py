import re

import numpy as np

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.filter import Filter
from module.base.timer import Timer
from module.base.utils import area_offset, color_mapping, get_color, rgb2gray
from module.combat.assets import GET_ITEMS_1
from module.exception import GameBugError
from module.guild.assets import (
    GUILD_LOGISTICS_ENSURE_CHECK,
    GUILD_MISSION,
    GUILD_MISSION_NEW,
    GUILD_MISSION_SELECT,
    GUILD_SUPPLY,
    OCR_GUILD_EXCHANGE_LIMIT,
)
from module.guild.base import GuildBase
from module.logger import logger
from module.ocr.ocr import Digit
from module.statistics.item import ItemGrid

EXCHANGE_GRIDS = ButtonGrid(
    origin=(470, 470), delta=(198.5, 0), button_shape=(83, 83), grid_shape=(3, 1), name="EXCHANGE_GRIDS"
)
EXCHANGE_BUTTONS = ButtonGrid(
    origin=(440, 609), delta=(198.5, 0), button_shape=(144, 31), grid_shape=(3, 1), name="EXCHANGE_BUTTONS"
)
EXCHANGE_FILTER = Filter(regex=re.compile("^(.*?)$"), attr=("name",))


class ExchangeLimitOcr(Digit):
    def pre_process(self, image):
        """
        Args:
            image (np.ndarray): Shape (height, width, channel)

        Returns:
            np.ndarray: Shape (width, height)
        """
        return 255 - color_mapping(rgb2gray(image), max_multiply=2.5)


GUILD_EXCHANGE_LIMIT = ExchangeLimitOcr(OCR_GUILD_EXCHANGE_LIMIT, threshold=64)


class GuildLogistics(GuildBase):
    _guild_logistics_mission_finished = False

    @cached_property
    def exchange_items(self):
        item_grid = ItemGrid(EXCHANGE_GRIDS, {}, template_area=(40, 21, 89, 70), amount_area=(60, 71, 91, 92))
        item_grid.load_template_folder("./assets/stats_basic")
        return item_grid

    def _is_in_guild_logistics(self):
        """
        通过 GUILD_LOGISTICS_ENSURE_CHECK 颜色采样判断当前是否在后勤页。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        # 赤色阵营 (181, 97, 99)，蓝色阵营 (148, 178, 255)。
        return self.image_color_count(
            GUILD_LOGISTICS_ENSURE_CHECK, color=(181, 97, 99), threshold=221, count=400
        ) or self.image_color_count(GUILD_LOGISTICS_ENSURE_CHECK, color=(148, 178, 255), threshold=221, count=400)

    def _guild_logistics_ensure(self, skip_first_screenshot=True):
        """
        Ensure guild logistics is loaded
        After entering guild logistics, background loaded first, then St.Louis / Leipzig, then guild logistics

        Args:
            skip_first_screenshot (bool):
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._is_in_guild_logistics():
                break

    def _guild_logistics_mission_available(self):
        """
        通过 GUILD_MISSION 区域颜色判断任务按钮状态。

        领取和接受任务时都会调用。

        Returns:
            bool: 任务按钮是否可点击。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        r, g, b = get_color(self.device.image, GUILD_MISSION.area)
        if g > max(r, b) - 10:
            # 任务完成后右下角会出现绿色勾。
            logger.info("Guild mission has finished this week")
            self._guild_logistics_mission_finished = True
            return False
        if self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=180, count=400):
            # 未完成任务的接受/领取按钮计数大约在 240 到 322。
            logger.info("Guild mission button active")
            return True
        if not self.image_color_count(GUILD_MISSION, color=(255, 255, 255), threshold=180, count=50):
            # 没有公会任务计数。
            logger.info("No guild mission found, mission of this week may not started")
            return False
            # if self.image_color_count(GUILD_MISSION_CHOOSE, color=(255, 255, 255), threshold=221, count=100):
            #     # 公会会长可以选择公会任务。
            #     logger.info('Guild mission choose found')
            #     return True
            # else:
            #     logger.info('Guild mission choose not found')
            #     return False
        logger.info("Guild mission button inactive")
        return False

    def _guild_logistics_supply_available(self):
        """
        通过 GUILD_SUPPLY 区域颜色判断补给按钮是否可用。

        Returns:
            bool: 补给按钮是否可点击。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        color = get_color(self.device.image, GUILD_SUPPLY.area)
        # 可点击按钮是白字，不可点击按钮是灰字。
        if np.max(color) > np.mean(color) + 25:
            # 成员点击领取补给；会长点击购买并领取补给。
            logger.info("Guild supply button active")
            return True
        logger.info("Guild supply button inactive")
        return False

    def _handle_guild_fleet_mission_start(self):
        """
        选择新的每周舰队任务。

        当前账号必须是公会会长或军官。

        Returns:
            bool: 是否发生点击。
        """
        if not self.config.GuildLogistics_SelectNewMission:
            return False

        if self.appear_then_click(GUILD_MISSION_NEW, offset=(20, 20), interval=2):
            return True
        # 公会会长选择公会任务。
        # 固定选择“塞壬歼灭 III，击败 300 个敌人”。
        # 这个任务补给最多，也最容易让成员完成。
        return self.appear_then_click(GUILD_MISSION_SELECT, offset=(20, 20), interval=2)

    def _guild_logistics_collect(self, skip_first_screenshot=True):
        """
        Execute collect/accept screen transitions within
        logistics

        Args:
            skip_first_screenshot (bool):

        Returns:
            bool: If all guild logistics are check, no need to check them today.

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        logger.hr("Guild logistics")
        logger.attr("Guild master/official", self.config.GuildLogistics_SelectNewMission)
        confirm_timer = Timer(1.5, count=3).start()
        exchange_interval = Timer(1.5, count=3)
        click_interval = Timer(0.5, count=1)
        supply_checked = False
        mission_checked = False
        exchange_checked = False
        exchange_count = 0

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Handle all popups
            if self.handle_popup_confirm("GUILD_LOGISTICS"):
                confirm_timer.reset()
                exchange_interval.reset()
                continue
            if self.appear_then_click(GET_ITEMS_1, interval=2):
                confirm_timer.reset()
                exchange_interval.reset()
                continue
            if self._handle_guild_fleet_mission_start():
                confirm_timer.reset()
                continue

            if self._is_in_guild_logistics():
                # Supply
                if not supply_checked and self._guild_logistics_supply_available():
                    if click_interval.reached():
                        self.device.click(GUILD_SUPPLY)
                        click_interval.reset()
                    confirm_timer.reset()
                    continue
                supply_checked = True
                # Mission
                if not mission_checked and self._guild_logistics_mission_available():
                    if click_interval.reached():
                        self.device.click(GUILD_MISSION)
                        click_interval.reset()
                    confirm_timer.reset()
                    continue
                mission_checked = True
                # Exchange
                if not exchange_checked and exchange_interval.reached():
                    if self._guild_exchange():
                        confirm_timer.reset()
                        exchange_interval.reset()
                        exchange_count += 1
                        continue
                    exchange_checked = True
                # End
                if not self.info_bar_count() and confirm_timer.reached():
                    break
                # if supply_checked and mission_checked and exchange_checked:
                #     break
                if exchange_count >= 5:
                    # If you run AL across days, then do guild exchange.
                    # There will show an error, said time is not up.
                    # Restart the game can't fix the problem.
                    # To fix this, you have to enter guild logistics once, then restart.
                    # If exchange for 5 times, this bug is considered to be triggered.
                    logger.warning("Unable to do guild exchange, probably because the timer in game was bugged")
                    raise GameBugError("Triggered guild logistics refresh bug")

            else:
                confirm_timer.reset()

        logger.info(
            f"supply_checked: {supply_checked}, mission_checked: {mission_checked}, "
            f"exchange_checked: {exchange_checked}, mission_finished: {self._guild_logistics_mission_finished}"
        )
        # Azur Lane receives new guild missions now
        # No longer consider `self._guild_logistics_mission_finished` as a check
        return all([supply_checked, mission_checked, exchange_checked])

    def _guild_exchange_scan(self):
        """
        Image scan of available options.
        Not exchangeable items are tagged enough=False.

        Returns:
            list[Item]:

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        # 扫描可选择的兑换物品。
        items = self.exchange_items.predict(self.device.image, name=True, amount=False)

        # 遍历 EXCHANGE_GRIDS，检测右下角红色文本。
        # 红色文本表示玩家缺少该物品库存。
        for item, button in zip(items, EXCHANGE_GRIDS.buttons, strict=False):
            area = area_offset((35, 64, 83, 83), button.area[0:2])
            if self.image_color_count(area, color=(255, 93, 90), threshold=221, count=20):
                item.enough = False
            else:
                item.enough = True

        text = [str(item.name) if item.enough else str(item.name) + " (not enough)" for item in items]
        logger.info(f"Exchange items: {', '.join(text)}")
        return items

    def _guild_exchange(self):
        """
        根据筛选器执行可用的公会兑换。

        兑换次数由剩余次数限制决定；完全无法兑换时外层流程会提前结束。

        Returns:
            bool: 是否发生点击。

        Pages:
            in: GUILD_LOGISTICS
            out: GUILD_LOGISTICS
        """
        if not GUILD_EXCHANGE_LIMIT.ocr(self.device.image) > 0:
            return False

        items = self._guild_exchange_scan()
        EXCHANGE_FILTER.load(self.config.GuildLogistics_ExchangeFilter)
        selected = EXCHANGE_FILTER.apply(items, func=lambda item: item.enough)
        logger.attr("Exchange_sort", " > ".join([str(item.name) for item in selected]))

        if len(selected):
            button = EXCHANGE_BUTTONS.buttons[items.index(selected[0])]
            # 点击后交给 self._guild_logistics_collect 重试确认。
            self.device.click(button)
            return True
        logger.warning("No guild exchange items satisfy current filter, or not having enough resources")
        return False

    def guild_logistics(self):
        """
        Execute all actions in logistics

        Returns:
            bool: If all guild logistics are check, no need to check them today.

        Pages:
            in: page_guild
            out: page_guild, GUILD_LOGISTICS
        """
        logger.hr("Guild logistics", level=1)
        self.guild_side_navbar_ensure(bottom=3)
        self._guild_logistics_ensure()

        result = self._guild_logistics_collect()
        logger.info(f"Guild logistics run success: {result}")
        return result
