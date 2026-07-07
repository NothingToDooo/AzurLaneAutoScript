from campaign.event_20200521_cn.a1 import Config as ConfigBase
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


class Config(ConfigBase):
    pass


class Campaign(CampaignBase):
    MAP = MAP
