from module.campaign.campaign_base import CampaignBase
from module.map.map_base import CampaignMap

MAP = CampaignMap()
MAP.map_data = """
    -- ++ ++ MB MB ++ ++ ++
    ME ++ ME -- -- ME ME --
    -- -- __ -- ME __ -- --
    ME -- ME -- -- -- ME --
    -- -- ++ ME -- ME ++ ME
    ME -- -- SP SP -- -- --
    ++ ++ -- -- -- -- ME ++
"""
MAP.camera_data = ["D3", "D5"]
MAP.spawn_data = [
    {"battle": 0, "enemy": 3},
    {"battle": 1, "enemy": 1},
    {"battle": 2, "enemy": 1},
    {"battle": 3, "enemy": 1},
    {"battle": 4, "boss": 1},
]


class Config:
    submarine = 0
    fleet_boss = 1

    MAP_HAS_AMBUSH = False


class Campaign(CampaignBase):
    MAP = MAP

    def battle_0(self):
        return self.battle_default()

    def battle_4(self):
        return self.brute_clear_boss()
