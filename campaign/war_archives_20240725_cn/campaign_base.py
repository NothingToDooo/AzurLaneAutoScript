from ..campaign_war_archives.campaign_base import CampaignBase as CampaignBase_


class CampaignBase(CampaignBase_):
    def campaign_set_chapter_event(self, chapter: str, mode: str = "normal") -> bool:
        del mode
        self.ui_goto_sp()
        if chapter in ["a", "b", "as", "bs", "t", "ts", "tss"]:
            self.campaign_ensure_mode("normal")
        elif chapter in ["c", "d", "cs", "ds", "ht", "hts"]:
            self.campaign_ensure_mode("hard")
        elif chapter == "ex_sp":
            self.campaign_ensure_mode("ex")
        self.campaign_ensure_chapter(chapter)
        return True

    def campaign_ensure_mode(self, mode: str = "normal") -> None:
        if mode == "hard":
            self.config.override(Campaign_Mode="hard")

        # 该活动只有 T/HT 和 SP，复刻档案没有 SP，因此没有模式切换按钮。
