from campaign.event_20200423_cn.a1 import Config as Config
from module.campaign.campaign_base import CampaignBase
from module.map.map_base import CampaignMap

MAP = CampaignMap()
MAP.map_data = """
    -- -- -- -- -- -- --
    -- -- -- ++ ++ ++ --
    -- -- -- -- -- -- --
    -- -- ++ -- -- -- --
    -- -- -- -- -- -- --
    SP -- -- -- -- ++ --
    SP SP -- -- -- ++ --
"""


class Campaign(CampaignBase):
    MAP = MAP
