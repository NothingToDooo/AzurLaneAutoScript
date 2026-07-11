import numpy as np

from module.base.button import Button
from module.base.utils import get_color
from module.logger import logger

from ..campaign_war_archives.campaign_base import CampaignBase as CampaignBase_

# Here manually type coordinates, because the ball appears in this event only.
BALL = Button(area=(589, 279, 685, 374), color=(), button=(589, 279, 685, 374))


class CampaignBase(CampaignBase_):
    STAGE_INCREASE = (
        "T1 > T2 > TS1 > T3",
        "T4 > T5 > TS2 > T6",
        "HT1 > HT2 > HTS1 > HT3",
        "HT4 > HT5 > HTS2 > HT6",
    )

    def campaign_set_chapter(self, name, mode="normal"):
        """按关卡名和 normal/hard 模式切换章节。"""
        chapter, stage = self.campaign_separate_name(name)

        if (
            self.campaign_set_chapter_main(chapter, mode)
            or self.campaign_set_chapter_event(chapter, mode)
            or self.campaign_set_chapter_sp(chapter, mode)
            or self.campaign_set_chapter_ball(chapter, stage)
        ):
            return

        logger.warning(f"Unknown campaign chapter: {chapter}{stage}")

    def campaign_set_chapter_main(self, chapter, mode="normal"):
        if not chapter.isdigit():
            return False

        self.ui_goto_campaign()
        self.campaign_ensure_mode("normal")
        self.campaign_ensure_chapter(chapter)
        if mode == "hard":
            self.campaign_ensure_mode("hard")
        return True

    def campaign_set_chapter_event(self, chapter, mode="normal"):
        del mode
        mode_by_chapter = {
            "a": "normal",
            "b": "normal",
            "c": "hard",
            "d": "hard",
            "ex_sp": "ex",
        }
        campaign_mode = mode_by_chapter.get(chapter)
        if campaign_mode is None:
            return False

        self.ui_goto_event()
        self.campaign_ensure_mode(campaign_mode)
        self.campaign_ensure_chapter(chapter)
        return True

    def campaign_set_chapter_sp(self, chapter, mode="normal"):
        del mode
        if chapter != "sp":
            return False

        self.ui_goto_sp()
        self.campaign_ensure_chapter(chapter)
        return True

    def campaign_set_chapter_ball(self, chapter, stage):
        if chapter not in {"t", "ts", "ht", "hts"}:
            return False

        self.ui_goto_event()
        self._campaign_ensure_ball_mode(chapter)
        self._campaign_ball_set(self._campaign_ball_status(chapter, stage))
        self.campaign_ensure_chapter(1)
        return True

    @staticmethod
    def _campaign_ball_status(chapter, stage):
        if chapter in {"t", "ht"} and stage in {"1", "2", "3"}:
            return "blue"
        if chapter in {"ts", "hts"} and stage == "1":
            return "blue"
        return "red"

    def _campaign_ensure_ball_mode(self, chapter):
        if chapter in {"t", "ts"}:
            self.campaign_ensure_mode("normal")
            return
        self.campaign_ensure_mode("hard")

    def _campaign_ball_get(self):
        """返回球色 blue、red；无法识别时返回 unknown。"""
        color = get_color(self.device.image, BALL.area)
        # Blue: (93, 127, 182), Red: (186, 116, 124)
        index = np.argmax(color)
        if index == 0:
            return "red"
        if index == 2:
            return "blue"
        logger.warning(f"Unknown campaign ball color: {color}")
        return "unknown"

    def _campaign_ball_set(self, status):
        """把球色切换为 blue 或 red。"""
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            current = self._campaign_ball_get()
            logger.attr("Campaign_ball", current)

            if current == status:
                break

            if self.is_in_stage():
                self.device.click(BALL)
                self.device.sleep(3)
                # 等待进入关卡。
                while 1:
                    self.device.screenshot()
                    if self.is_in_stage():
                        break
