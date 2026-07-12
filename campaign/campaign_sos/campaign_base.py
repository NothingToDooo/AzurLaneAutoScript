from typing import TYPE_CHECKING

from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.exception import CampaignNameError
from module.template.assets import TEMPLATE_STAGE_SOS

if TYPE_CHECKING:
    from module.base.button import Button


class ConfigBase:
    MAP_HAS_CLEAR_PERCENTAGE = False


class CampaignBase(CampaignBase_):
    ENEMY_FILTER = "1T > 1L > 1E > 1M > 2T > 2L > 2E > 2M > 3T > 3L > 3E > 3M"

    def campaign_get_entrance(self, name: str) -> Button:
        """SOS 关卡无游戏内名称；对玩家称作 X-5/X-sos 的关卡，以潜艇图标作为入口。"""
        if "-5" not in name:
            return super().campaign_get_entrance(name)

        sim, button = TEMPLATE_STAGE_SOS.match_result(self.device.image)
        if sim < 0.85:
            raise CampaignNameError

        return button.crop((-12, -12, 44, 32), image=self.device.image, name=name)
