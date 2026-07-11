from module.base.button import Button
from module.campaign.assets import (
    EVENT_20201126_DETAIL,
    EVENT_20201126_DETAIL_CHECK,
    EVENT_20201126_DETAIL_WHITE,
    EVENT_20201126_ENTRANCE,
    EVENT_20201126_PT_ICON,
)
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.exception import CampaignNameError
from module.logger import logger
from module.ui.page import page_campaign_menu, page_event, page_main_white

EVENT_ANIMATION = Button(
    area=(49, 229, 119, 400), color=(118, 215, 240), button=(49, 229, 119, 400), name="EVENT_ANIMATION"
)


class CampaignBase(CampaignBase_):
    """DOA 联动图分章：第 1 章 SP1～SP4，第 2 章 VSP，第 3 章 EX；模式切换无意义。"""

    def ui_goto_event(self):
        if self.appear(EVENT_20201126_PT_ICON, offset=(40, 20)) and self.ui_page_appear(page_event):
            logger.info("Already at EVENT_20201126")
            return True
        self.ui_ensure(page_campaign_menu)
        if self.is_event_entrance_available():
            self.ui_goto_main()
            if self.ui_page_appear(page_main_white):
                self.ui_click(EVENT_20201126_DETAIL_WHITE, check_button=EVENT_20201126_DETAIL_CHECK)
            else:
                self.ui_click(EVENT_20201126_DETAIL, check_button=EVENT_20201126_DETAIL_CHECK)
            self.ui_click(
                EVENT_20201126_ENTRANCE,
                check_button=EVENT_20201126_PT_ICON,
                appear_button=EVENT_20201126_DETAIL_CHECK,
                offset=(40, 20),
            )
            return True
        return False

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        """将 vsp、sp 特殊映射为 (ex_sp, 1)，其余按通用规则分解。"""
        if name in {"vsp", "sp"}:
            return "ex_sp", "1"
        return CampaignBase_.campaign_separate_name(name)

    @staticmethod
    def campaign_get_chapter_index(name):
        """将整数或章节名转换为章节序号。"""
        if isinstance(name, int):
            return name
        if name.isdigit():
            return int(name)
        if name in ["a", "c", "sp"]:
            return 1
        if name in ["b", "d", "ex_sp"]:
            return 2
        if name == "ex_ex":
            return 3
        raise CampaignNameError

    def campaign_set_chapter_event(self, chapter, mode="normal"):
        del mode
        self.ui_goto_event()
        self.campaign_ensure_chapter(chapter)
        return True

    def campaign_get_entrance(self, name):
        if name == "sp":
            name = "vsp"
        return super().campaign_get_entrance(name)

    def is_event_animation(self):
        """返回活动战斗后动画是否出现。"""
        appear = self.appear(EVENT_ANIMATION)
        if appear:
            logger.info("DOA animation, waiting")
        return appear
