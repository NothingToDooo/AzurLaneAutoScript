from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.logger import logger


class CampaignBase(CampaignBase_):
    def campaign_set_chapter_sp(self, chapter, mode="normal"):
        # SP 活动入口仍显示 event UI。
        logger.info("Set chapter SP")
        if chapter in ["sp", "sp_sp"]:
            self.ui_goto_event()
            self.campaign_ensure_chapter(chapter)
            return True
        return False

    @staticmethod
    def campaign_separate_name(name):
        if name in ["esp", "sp"]:
            return "sp_sp", "2"
        if name == "ex":
            return "sp_ex", "3"
        return CampaignBase_.campaign_separate_name(name)

    def campaign_get_entrance(self, name):
        if name == "sp":
            name = "esp"
        return super().campaign_get_entrance(name)

    @staticmethod
    def campaign_get_chapter_index(name):
        if name == "sp_sp":
            return 2
        if name == "sp_ex":
            return 3
        return CampaignBase_.campaign_get_chapter_index(name)
