from module.base.button import Button
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.exception import CampaignNameError
from module.logger import logger

ANIMATION_PINK = Button(
    area=(1186, 446, 1272, 493), color=(255, 153, 172), button=(1186, 446, 1272, 493), name="ANIMATION_PINK"
)
ANIMATION_ORANGE = Button(
    area=(1186, 446, 1272, 493), color=(255, 177, 123), button=(1186, 446, 1272, 493), name="ANIMATION_ORANGE"
)
ANIMATION_BLUE = Button(
    area=(1186, 446, 1272, 493), color=(176, 192, 251), button=(1186, 446, 1272, 493), name="ANIMATION_BLUE"
)


class CampaignBase(CampaignBase_):
    """偶像大师联动图分章：第 1 章 SP1～SP4，第 2 章 VSP。"""

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        """将 vsp/sp 映射为 (ex_sp, 1)，extra* 映射为 (ex_ex, 1)，并兼容连字符、SP 与尾号分解。"""
        if name in {"vsp", "sp"}:
            return "ex_sp", "1"
        if name.startswith("extra"):
            return "ex_ex", "1"
        if "-" in name:
            chapter, stage = name.split("-", maxsplit=1)
            return chapter, stage
        if name.startswith("sp"):
            return "sp", name[-1]
        if name[-1].isdigit():
            return name[:-1], name[-1]

        return CampaignBase_.campaign_separate_name(name)

    @staticmethod
    def campaign_get_chapter_index(name):
        """将整数或章节名转换为章节序号。"""
        if isinstance(name, int):
            return name
        if name.isdigit():
            return int(name)
        if name in ["a", "c", "as", "cs", "sp"]:
            return 1
        if name in ["b", "d", "bs", "ds", "ex_ex", "ex_sp"]:
            return 2
        raise CampaignNameError

    def campaign_set_chapter(self, name, mode="normal"):
        """按关卡名和 normal/hard 模式切换章节。"""
        chapter, _ = self.campaign_separate_name(name)

        if chapter.isdigit():
            self.ui_goto_campaign()
            self.campaign_ensure_mode("normal")
            self.campaign_ensure_chapter(chapter)
            if mode == "hard":
                self.campaign_ensure_mode("hard")
                self.campaign_ensure_chapter(chapter)

        elif chapter in ["a", "b", "c", "d", "ex_sp", "as", "bs", "cs", "ds"]:
            self.ui_goto_event()
            if chapter in ["a", "b", "as", "bs"]:
                self.campaign_ensure_mode("normal")
            elif chapter in ["c", "d", "cs", "ds"]:
                self.campaign_ensure_mode("hard")
            elif chapter == "ex_sp":
                # 活动差异：EX_SP 不切换 EX 模式。
                pass
            self.campaign_ensure_chapter(chapter)

        elif chapter == "sp":
            # 活动差异：SP 从活动入口进入。
            self.ui_goto_event()
            self.campaign_ensure_chapter(chapter)

        else:
            logger.warning(f"Unknown campaign chapter: {name}")

    def campaign_get_entrance(self, name):
        if name == "sp":
            name = "vsp"
        return super().campaign_get_entrance(name)

    def is_event_animation(self):
        """返回活动战斗后动画是否出现。"""
        for button in [ANIMATION_PINK, ANIMATION_ORANGE, ANIMATION_BLUE]:
            if self.appear(button):
                logger.info("Idol Master animation, waiting")
                return True

        return False

    def campaign_match_multi(self, *args, **kwargs):
        # Lower campaign match threshold to 0.8, in order to detect 50% clear SP3
        kwargs["similarity"] = 0.8
        return super().campaign_match_multi(*args, **kwargs)
