from typing import TYPE_CHECKING

from module.logger import logger

from ..campaign_war_archives.campaign_base import CampaignBase as CampaignBase_

if TYPE_CHECKING:
    from module.base.button import Button


class CampaignBase(CampaignBase_):
    def campaign_set_chapter_sp(self, chapter: str, mode: str = "normal") -> bool:
        del mode
        # SP 活动入口仍显示 event UI。
        logger.info("Set chapter SP")
        if chapter in ["sp", "sp_sp"]:
            self.ui_goto_sp()
            self.campaign_ensure_chapter(chapter)
            return True
        return False

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        if name in ["esp", "sp"]:
            return "sp_sp", "2"
        if name == "ex":
            return "sp_ex", "3"
        return CampaignBase_.campaign_separate_name(name)

    def campaign_get_entrance(self, name: str) -> Button:
        if name == "sp":
            name = "esp"
        return super().campaign_get_entrance(name)

    @staticmethod
    def campaign_get_chapter_index(name: str | int) -> int:
        if name == "sp_sp":
            return 2
        if name == "sp_ex":
            return 3
        return CampaignBase_.campaign_get_chapter_index(name)
