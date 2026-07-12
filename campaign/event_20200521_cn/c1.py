from typing import ClassVar

from module.campaign.campaign_base import CampaignBase
from module.map.map_base import CampaignMap

MAP = CampaignMap()
MAP.map_data = """
    -- -- ++ -- -- -- ++ ++
    -- -- -- -- -- -- -- --
    ++ -- -- ++ -- -- -- --
    ++ -- -- -- -- -- -- --
    -- -- -- -- -- -- -- --
    -- -- ++ ++ ++ -- -- ++
"""


class Config:
    submarine = 0
    fleet_boss = 1

    POOR_MAP_DATA = True
    MAP_HAS_AMBUSH = False
    MAP_HAS_FLEET_STEP = True
    MAP_HAS_MOVABLE_ENEMY = True
    MAP_HAS_SIREN = True
    MAP_HAS_DYNAMIC_RED_BORDER = False
    MAP_HAS_MAP_STORY = True
    MAP_SIREN_COUNT = 2

    TRUST_EDGE_LINES = False
    COINCIDENT_POINT_ENCOURAGE_DISTANCE = 1.5
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS: ClassVar[dict[str, object]] = {
        "height": (100, 255 - 16),
        "width": 1,
        "prominence": 10,
        "distance": 35,
    }
    EDGE_LINES_FIND_PEAKS_PARAMETERS: ClassVar[dict[str, object]] = {
        "height": (255 - 16, 255),
        "prominence": 2,
        "distance": 50,
        "wlen": 1000,
    }


class Campaign(CampaignBase):
    MAP = MAP
