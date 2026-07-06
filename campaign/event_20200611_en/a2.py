from campaign.event_20200611_en.a1 import Config as Config
from module.campaign.campaign_base import CampaignBase
from module.map.map_base import CampaignMap

MAP = CampaignMap()
MAP.map_data = """
    -- -- -- -- -- -- -- -- ++
    -- -- -- ++ ++ -- -- -- ++
    ++ -- -- -- -- -- -- -- --
    ++ -- ++ -- -- -- -- -- --
    -- -- -- -- ++ ++ -- -- --
    -- -- -- -- ++ ++ -- -- --
"""
MAP.camera_data = ["D1", "D4", "F2", "F4"]


class Campaign(CampaignBase):
    MAP = MAP
