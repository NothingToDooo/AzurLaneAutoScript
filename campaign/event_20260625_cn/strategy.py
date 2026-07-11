from module.campaign.campaign_base import CampaignBase


class EarlyBossStrategy(CampaignBase):
    def battle_4(self) -> bool:
        return self.clear_boss()
