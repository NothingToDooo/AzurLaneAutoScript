from module.campaign.assets import SWITCH_20241219_COMBAT, SWITCH_20241219_STORY
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.campaign.campaign_ui import ModeSwitch
from module.ui.ui import page_event

MODE_SWITCH_20240912 = ModeSwitch("Mode_switch_20240912", is_selector=True)
MODE_SWITCH_20240912.add_state("combat", SWITCH_20241219_COMBAT, offset=(444, 4))
MODE_SWITCH_20240912.add_state("story", SWITCH_20241219_STORY, offset=(444, 4))


class CampaignBase(CampaignBase_):
    def campaign_ensure_mode(self, mode: str = "normal") -> None:
        # event_20240912_cn has two mode switches at bottom
        # The classic one, MODE_SWITCH_* is at bottom-left,
        # and MODE_SWITCH_20240912 is at bottom-middle
        if mode == "story":
            MODE_SWITCH_20240912.set("story", main=self)
        elif mode in ["normal", "hard", "ex"]:
            # First switch to combat mode and then select Hard or Normal.
            MODE_SWITCH_20240912.set("combat", main=self)
            super().campaign_ensure_mode(mode)

    def campaign_set_chapter_20241219(self, chapter: str, stage: str, mode: str = "combat") -> bool:
        """
        国区活动同时使用传统章节入口和 MODE_SWITCH_20240912。
        """
        self.config.override(
            MAP_CHAPTER_SWITCH_20241219=False,
            MAP_HAS_MODE_SWITCH=False,
        )
        return super().campaign_set_chapter_20241219(chapter, stage, mode)

    def handle_exp_info(self) -> bool:
        # Random background of hits EXP_INFO_B
        if self.ui_page_appear(page_event):
            return False
        return super().handle_exp_info()
