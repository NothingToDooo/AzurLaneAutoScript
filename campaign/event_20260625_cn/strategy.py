from module.campaign.campaign_base import CampaignBase


class EarlyBossStrategy(CampaignBase):
    def battle_4(self):
        return self.clear_boss()
