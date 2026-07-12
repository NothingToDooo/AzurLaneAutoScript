from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.exception import CampaignNameError
from module.logger import logger


class CampaignBase(CampaignBase_):
    """该联动活动分章：第 1 章 SP1～SP5，第 2 章 uSP，第 3 章 EX；模式切换无意义。"""

    @staticmethod
    def campaign_get_chapter_index(name: str | int) -> int:
        """将整数或章节名转换为章节序号。"""
        if isinstance(name, int):
            return name
        if name.isdigit():
            return int(name)
        if name in ["a", "c", "sp"]:
            return 1
        if name in ["b", "d", "ex_sp"]:
            return 2
        raise CampaignNameError

    def campaign_set_chapter(self, name: str, mode: str = "normal") -> None:
        """按关卡名和 normal/hard 模式切换章节。"""
        chapter, _stage = self.campaign_separate_name(name)

        if chapter.isdigit():
            self.ui_goto_campaign()
            self.campaign_ensure_mode("normal")
            self.campaign_ensure_chapter(chapter)
            if mode == "hard":
                self.campaign_ensure_mode("hard")
                self.campaign_ensure_chapter(chapter)

        elif chapter in "abcd" or chapter == "ex_sp":
            self.ui_goto_event()
            if chapter in "ab":
                self.campaign_ensure_mode("normal")
            elif chapter in "cd":
                self.campaign_ensure_mode("hard")
            elif chapter == "ex_sp":
                # EX_SP 不需要切换模式。
                pass
            self.campaign_ensure_chapter(chapter)

        elif chapter == "sp":
            self.ui_goto_event()
            self.campaign_ensure_chapter(chapter)

        else:
            logger.warning(f"Unknown campaign chapter: {name}")

    def is_event_animation(self) -> bool:
        appear = self.image_color_count((286, 342, 994, 422), color=(255, 255, 255), count=10000)
        if appear:
            logger.info("Live start!")

        return appear
