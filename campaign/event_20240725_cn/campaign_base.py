from module.campaign.campaign_base import CampaignBase as CampaignBase_


class CampaignBase(CampaignBase_):
    def campaign_ensure_mode(self, mode: str = "normal") -> None:
        if mode == "hard":
            self.config.override(Campaign_Mode="hard")

        self.campaign_ensure_mode_20241219(mode)
