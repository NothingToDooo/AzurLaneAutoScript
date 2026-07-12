from typing import TYPE_CHECKING

from module.campaign.campaign_base import CampaignBase as CampaignBase_

if TYPE_CHECKING:
    from module.base.button import Button


class CampaignBase(CampaignBase_):
    def campaign_ensure_mode(self, mode: str = "normal") -> None:
        if mode == "hard":
            self.config.override(Campaign_Mode="hard")

        self.campaign_ensure_mode_20241219(mode)

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        """将 tp 特殊映射为 (ex_sp, 1)，其余按通用规则分解。"""
        if name == "tp":
            return "ex_sp", "1"
        return CampaignBase_.campaign_separate_name(name)

    def campaign_get_entrance(self, name: str) -> Button:
        if name == "sp":
            name = "tp"
        return super().campaign_get_entrance(name)
