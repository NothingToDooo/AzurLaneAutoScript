from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.exception import CampaignNameError
from module.logger import logger


class CampaignBase(CampaignBase_):
    def campaign_set_chapter(self, name: str, mode: str = "normal") -> None:
        """按关卡名和 normal/hard 模式切换章节。"""
        chapter, _ = self.campaign_separate_name(name)

        if chapter.isdigit():
            self.ui_goto_campaign()
            self.campaign_ensure_mode("normal")
            self.campaign_ensure_chapter(chapter)
            if mode == "hard":
                self.campaign_ensure_mode("hard")
                self.campaign_ensure_chapter(chapter)

        elif chapter in "abcd" or chapter == "ex_sp" or chapter in ["as", "cs"]:
            self.ui_goto_event()
            if chapter in "ab" or chapter == "as":
                self.campaign_ensure_mode("normal")
            elif chapter in "cd" or chapter == "cs":
                self.campaign_ensure_mode("hard")
            elif chapter == "ex_sp":
                self.campaign_ensure_mode("ex")
            self.campaign_ensure_chapter(chapter)

        elif chapter == "sp":
            self.ui_goto_sp()
            self.campaign_ensure_chapter(chapter)

        else:
            logger.warning(f"Unknown campaign chapter: {name}")

    @staticmethod
    def campaign_get_chapter_index(name: str | int) -> int:
        """将整数或章节名转换为章节序号。"""
        if isinstance(name, int):
            return name
        if name.isdigit():
            return int(name)
        if name in ["a", "c", "sp", "ex_sp", "as", "cs"]:
            return 1
        if name in ["b", "d", "ex_ex"]:
            return 2
        raise CampaignNameError
