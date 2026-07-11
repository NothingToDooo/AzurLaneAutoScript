from typing import TYPE_CHECKING

from module.base.mask import Mask
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.logger import logger
from module.map.assets import FLEET_SUPPORT_EMPTY
from module.map_detection.utils_assets import ASSETS

if TYPE_CHECKING:
    from module.base.type_alias import Area, Point
    from module.map.map_base import CampaignMap

MASK_MAP_UI_SUPPORT = Mask(file="./assets/mask/MASK_MAP_UI_SUPPORT.png")


class CampaignBase(CampaignBase_):
    use_support_fleet = True

    def fleet_preparation(self) -> bool:
        if self.appear(FLEET_SUPPORT_EMPTY, offset=(5, 5)):
            self.use_support_fleet = False
        logger.attr("use_support_fleet", self.use_support_fleet)
        return super().fleet_preparation()

    def _map_swipe(self, vector: Point, box: Area = (239, 159, 1175, 628)) -> bool:
        # Left border to 239, avoid swiping on support fleet
        return super()._map_swipe(vector, box=box)

    def map_data_init(self, map_: CampaignMap | None) -> None:
        super().map_data_init(map_)
        if self.use_support_fleet:
            # Patch ui_mask, get rid of supporting fleet
            _ = ASSETS.ui_mask
            ASSETS.ui_mask = MASK_MAP_UI_SUPPORT.image
