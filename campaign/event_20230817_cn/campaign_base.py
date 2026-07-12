from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.base.utils import crop, rgb2gray
from module.campaign.assets import (
    EVENT_20230817_STORY,
    TEMPLATE_EVENT_20230817_STORY_E1,
    TEMPLATE_EVENT_20230817_STORY_E2,
)
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.logger import logger
from module.ui.page import page_event

if TYPE_CHECKING:
    from module.base.button import Button


class CampaignBase(CampaignBase_):
    def handle_chapter_additional(self) -> bool:
        """该活动以剧情作为关卡入口，需先清完剧情才能解锁关卡。"""
        if self.get_story_button():
            self.event_20230817_story()
            return True
        logger.info("No event_20230817_story")
        return False

    def get_story_button(self) -> Button | None:
        """识别活动剧情按钮（约 26ms），未检测到时返回 None。"""
        # Story before A1, E0-1 ~ E0-3
        if self.appear(EVENT_20230817_STORY, offset=(20, 100)):
            return EVENT_20230817_STORY

        # Smaller image to run faster
        area = (73, 135, 1223, 583)
        image = rgb2gray(crop(self.device.image, area=area, copy=False))

        # E1-1 ~ E1-2
        sim, button = TEMPLATE_EVENT_20230817_STORY_E1.match_result(image)
        if sim > 0.85:
            return button.move(area[:2])

        # E21-1 ~ E2-7
        sim, button = TEMPLATE_EVENT_20230817_STORY_E2.match_result(image)
        if sim > 0.85:
            return button.move(area[:2])

        return None

    def event_20230817_story(self, *, skip_first_screenshot: bool = True) -> None:
        logger.hr("event_20230817_story", level=2)
        confirm = Timer(1, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_page_appear(page_event):
                if confirm.reached():
                    break
            else:
                confirm.reset()

            if self.handle_story_skip():
                continue
            if self.handle_get_items():
                continue

            button = self.get_story_button()
            if button:
                self.device.click(button)

    def is_stage_page_has_entrance(self) -> bool:
        if self.get_story_button():
            return True
        return super().is_stage_page_has_entrance()
