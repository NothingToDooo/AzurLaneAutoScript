from module.base.button import Button
from module.campaign.assets import (
    EVENT_20260417_DETAIL,
    EVENT_20260417_DETAIL_CHECK,
    EVENT_20260417_DETAIL_WHITE,
    EVENT_20260417_ENTRANCE,
    EVENT_20260417_PT_ICON,
)
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.logger import logger
from module.ui.page import page_campaign_menu, page_event, page_main_white

EVENT_ANIMATION = Button(
    area=(49, 229, 119, 400), color=(118, 215, 240), button=(49, 229, 119, 400), name="EVENT_ANIMATION"
)


class CampaignBase(CampaignBase_):
    def ui_goto_event(self) -> bool:
        if self.appear(EVENT_20260417_PT_ICON, offset=(40, 20)) and self.ui_page_appear(page_event):
            logger.info("Already at EVENT_20260417")
            return True
        self.ui_ensure(page_campaign_menu)
        if self.is_event_entrance_available():
            self.ui_goto_main()
            if self.ui_page_appear(page_main_white):
                self.ui_click(EVENT_20260417_DETAIL_WHITE, check_button=EVENT_20260417_DETAIL_CHECK)
            else:
                self.ui_click(EVENT_20260417_DETAIL, check_button=EVENT_20260417_DETAIL_CHECK)
            self.ui_click(
                EVENT_20260417_ENTRANCE,
                check_button=EVENT_20260417_PT_ICON,
                appear_button=EVENT_20260417_DETAIL_CHECK,
                offset=(40, 20),
            )
            return True
        return False

    @staticmethod
    def campaign_ocr_result_process(result: str) -> str:
        result = CampaignBase_.campaign_ocr_result_process(result)
        if result in ["ysp", "usp", "vsp"]:
            result = "sp"
        return result

    def is_event_animation(self) -> bool:
        """返回活动战斗后动画是否出现。"""
        appear = self.appear(EVENT_ANIMATION)
        if appear:
            logger.info("DOA animation, waiting")
        return appear

    def event_animation_end(self) -> bool:
        if not self.appear(EVENT_ANIMATION):
            return False
        for _ in self.loop():
            if self.is_event_animation():
                continue
            break
        return True
