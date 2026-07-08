import numpy as np

from module.base.button import Button
from module.base.utils import get_color
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.exception import CampaignNameError
from module.logger import logger

# Here manually type coordinates, because the ball appears in event Dreamwaker's Butterfly only.
BALL = Button(area=(571, 283, 696, 387), color=(), button=(597, 274, 671, 343))


class CampaignBase(CampaignBase_):
    STAGE_INCREASE = (
        "TS1 > T1 > T2 > T3 > T4 > TS2 > T5 > T6",
        "HTS1 > HT1 > HT2 > HT3",
        "HT4 > HTS2 > HT5 > HT6",
    )

    def campaign_set_chapter(self, name, mode="normal"):
        """
        Args:
            name (str): 关卡名称，例如 '7-2'、'd3'、'sp3'。
            mode (str): 'normal' 或 'hard'。
        """
        chapter, stage = self.campaign_separate_name(name)

        if (
            self.campaign_set_chapter_main(chapter, mode)
            or self.campaign_set_chapter_event(chapter)
            or self.campaign_set_chapter_sp(chapter)
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

    def campaign_set_chapter_event(self, chapter):
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

    def campaign_set_chapter_sp(self, chapter):
        if chapter != "sp":
            return False

        self.ui_goto_sp()
        self.campaign_ensure_chapter(chapter)
        return True

    def campaign_set_chapter_ball(self, chapter, stage):
        if chapter not in {"t", "ts", "ht", "hts"}:
            return False

        self.ui_goto_event()
        self._campaign_ball_set(self._campaign_ball_status(stage))
        self._campaign_ensure_ball_mode(chapter)
        self.campaign_ensure_chapter(1)
        return True

    @staticmethod
    def _campaign_ball_status(stage):
        return "blue" if stage in {"1", "6"} else "red"

    def _campaign_ensure_ball_mode(self, chapter):
        if chapter in {"t", "ts"}:
            self.campaign_ensure_mode("normal")
            return
        self.campaign_ensure_mode("hard")

    @staticmethod
    def campaign_get_chapter_index(name):
        """
        Args:
            name (str, int):

        Returns:
            int
        """
        if isinstance(name, int):
            return name
        if name.isdigit():
            return int(name)
        if name in ["a", "c", "sp", "ex_sp", "ts", "t", "ht", "hts"]:
            return 1
        if name in ["b", "d", "ex_ex"]:
            return 2
        raise CampaignNameError

    def _campaign_ball_get(self):
        """
        Returns:
            str: 'blue' or 'red'.
        """
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
        """
        Args:
            status (str): 'blue' or 'red'.
        """
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
