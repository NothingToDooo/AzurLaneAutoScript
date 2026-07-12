from typing import TYPE_CHECKING, Literal

from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ui.assets import WAR_ARCHIVES_CHECK
from module.ui.page import page_archives
from module.ui.scroll import Scroll
from module.ui.switch import Switch
from module.war_archives.assets import (
    WAR_ARCHIVES_CAMPAIGN_CHECK,
    WAR_ARCHIVES_EX_ON,
    WAR_ARCHIVES_SP_ON,
)
from module.war_archives.assets import (
    WAR_ARCHIVES_SCROLL as WAR_ARCHIVES_SCROLL_AREA,
)
from module.war_archives.dictionary import dic_archives_template

if TYPE_CHECKING:
    from module.base.button import Button

WAR_ARCHIVES_SWITCH = Switch("War_Archives_switch", is_selector=True)
WAR_ARCHIVES_SWITCH.add_state("ex", WAR_ARCHIVES_EX_ON)
WAR_ARCHIVES_SWITCH.add_state("sp", WAR_ARCHIVES_SP_ON)
WAR_ARCHIVES_SCROLL = Scroll(WAR_ARCHIVES_SCROLL_AREA, color=(247, 211, 66), name="WAR_ARCHIVES_SCROLL")


class CampaignBase(CampaignBase_):
    first_run = True
    ENEMY_FILTER = "1T > 1L > 1E > 1M > 2T > 2L > 2E > 2M > 3T > 3L > 3E > 3M"

    def _get_archives_entrance(self, name: str) -> Button | None:
        """按活动目录名取得模板并识别对应档案入口。"""
        template = dic_archives_template[name]

        sim, button = template.match_result(self.device.image)
        if sim < 0.85:
            return None

        return button.crop((-12, -12, 44, 32), image=self.device.image, name=name)

    def _archives_loading_complete(self) -> bool:
        for war_archive_folder in dic_archives_template:
            template = dic_archives_template[war_archive_folder]
            loading_result = template.match(self.device.image)
            if loading_result:
                return True

        return False

    def _discard_archives_scroll_record(self) -> None:
        while self.device.click_record and self.device.click_record[-1] == "WAR_ARCHIVES_SCROLL":
            self.device.click_record.pop()

    def _ensure_archives_search_page(self) -> bool:
        recovered = False
        while not self.appear(WAR_ARCHIVES_CHECK):
            self.ui_ensure(destination=page_archives)
            recovered = True
        return recovered

    def _wait_archives_loaded(self) -> None:
        while not self._archives_loading_complete():
            self.device.screenshot()

    def _advance_archives_scroll(self) -> bool:
        if not WAR_ARCHIVES_SCROLL.appear(main=self):
            return False
        if WAR_ARCHIVES_SCROLL.at_bottom(main=self):
            WAR_ARCHIVES_SCROLL.set_top(main=self)
        else:
            WAR_ARCHIVES_SCROLL.next_page(main=self, page=0.66)
        return True

    def _search_archives_entrance(self, name: str, *, skip_first_screenshot: bool = True) -> Button | None:
        """滚动搜索档案入口，最多尝试 20 次后放弃。"""
        loading_checked = False
        for _ in range(20):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            self._discard_archives_scroll_record()

            # 拖动可能意外退出；每轮搜索前先恢复档案列表页。
            if self._ensure_archives_search_page():
                loading_checked = False

            # 游戏会保留上次滚动位置；先匹配入口，命中时可跳过较慢的加载检查。
            entrance = self._get_archives_entrance(name)
            if entrance is not None:
                return entrance

            if not loading_checked:
                # 档案列表不在顶部时，加载检查可能耗时 1～2 秒。
                self._wait_archives_loaded()
                loading_checked = True

                entrance = self._get_archives_entrance(name)
                if entrance is not None:
                    return entrance

            if self._advance_archives_scroll():
                continue
            break

        logger.warning("Failed to find archives entrance")
        return None

    def ui_goto_archives_campaign(self, mode: Literal["ex", "sp"] = "ex") -> bool:
        """切换档案模式并进入目标活动地图。"""
        # 首次运行无论当前位置都从档案页重新进入；后续若仍在目标地图且未触发奖励或停止条件则直接复用。
        result = True
        if self.first_run or not self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
            result = self.ui_ensure(destination=page_archives)

            WAR_ARCHIVES_SWITCH.set(mode, main=self)

            entrance = self._search_archives_entrance(self.config.Campaign_Event)
            if entrance is not None:
                self.ui_click(
                    entrance,
                    appear_button=WAR_ARCHIVES_CHECK,
                    check_button=WAR_ARCHIVES_CAMPAIGN_CHECK,
                    skip_first_screenshot=True,
                )
            else:
                logger.critical(
                    "Respective server may not yet support the chosen War Archives campaign, "
                    "check back in the next app update"
                )
                raise RequestHumanTakeover

        if self.first_run:
            self.first_run = False

        return result

    def ui_goto_event(self) -> bool:
        return self.ui_goto_archives_campaign(mode="ex")

    def ui_goto_sp(self) -> bool:
        return self.ui_goto_archives_campaign(mode="sp")
