import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import area_offset, color_similarity_2d
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3
from module.guild.assets import GUILD_REPORT_AVAILABLE, GUILD_REPORT_CLAIM, GUILD_REPORT_CLAIMED, GUILD_REPORT_CLOSE
from module.guild.base import GuildBase
from module.logger import logger
from module.map_detection.utils import Points
from module.ui.assets import GUILD_CHECK


class GuildLobby(GuildBase):
    def guild_lobby_get_report(self):
        """按报告区域红点位置返回报告图标按钮。"""
        image = color_similarity_2d(self.image_crop(GUILD_REPORT_AVAILABLE, copy=False), color=(255, 8, 8))
        points = np.array(np.where(image > 221)).T[:, ::-1]
        if len(points):
            points = Points(points).group(threshold=40) + GUILD_REPORT_AVAILABLE.area[:2]
            # 红点位于图标右下方，向左上偏移到报告图标中心。
            area = area_offset((-51, -45, -13, 0), offset=points[0])
            return Button(area=area, color=(255, 255, 255), button=area, name="GUILD_REPORT")
        return None

    def _guild_lobby_collect(self, skip_first_screenshot=True):
        """在任意页面尝试领取排队中的报告奖励；不在大厅时超时并留待下次。"""
        confirm_timer = Timer(1.5, count=3).start()
        click_timer = Timer(3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            self._guild_lobby_open_report(click_timer)
            if self._guild_lobby_handle_report_rewards(confirm_timer):
                continue

            if self._guild_lobby_collect_finished(confirm_timer):
                break

    def _guild_lobby_open_report(self, click_timer):
        if not click_timer.reached():
            return False
        if not self.appear(GUILD_CHECK, offset=(20, 20)):
            return False

        button = self.guild_lobby_get_report()
        if button is None:
            return False

        self.device.click(button)
        click_timer.reset()
        return True

    def _guild_lobby_handle_report_rewards(self, confirm_timer):
        if self.appear_then_click(GUILD_REPORT_CLAIM, threshold=30, interval=3):
            confirm_timer.reset()
            return True

        for button in (GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3):
            if self.appear_then_click(button, offset=(30, 30), interval=2):
                confirm_timer.reset()
                return True

        if not self.appear(GUILD_REPORT_CLAIMED, threshold=30, interval=3):
            return False

        self.device.click(GUILD_REPORT_CLOSE)
        confirm_timer.reset()
        return True

    def _guild_lobby_collect_finished(self, confirm_timer):
        if self.appear(GUILD_CHECK, offset=(20, 20)):
            return confirm_timer.reached()

        confirm_timer.reset()
        return False

    def guild_lobby(self):
        """在公会大厅领取报告奖励。"""
        logger.hr("Guild lobby", level=1)
        self._guild_lobby_collect()
        logger.info("Guild lobby collect finished")
