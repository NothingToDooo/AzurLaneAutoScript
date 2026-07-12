from typing import TYPE_CHECKING

from module.ui.page import page_event

from ..campaign_war_archives.campaign_base import CampaignBase as CampaignBase_

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap


class CampaignBase(CampaignBase_):
    def handle_exp_info(self) -> bool:
        # Random background of hits EXP_INFO_B
        if self.ui_page_appear(page_event):
            return False
        return super().handle_exp_info()

    def map_data_init(self, map_: CampaignMap | None) -> None:
        super().map_data_init(map_)
        self.config.override(EnemyPriority_EnemyScaleBalanceWeight="default_mode")
