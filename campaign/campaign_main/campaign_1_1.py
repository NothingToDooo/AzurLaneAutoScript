from typing import ClassVar

from module.campaign.campaign_base import CampaignBase
from module.map.map_base import CampaignMap

MAP = CampaignMap()
MAP.shape = "G1"
MAP.camera_data = ["D1"]
MAP.camera_data_spawn_point = ["D1"]
MAP.map_data = """
    SP -- -- -- -- ME MB
"""
MAP.spawn_data = [
    {"battle": 0, "enemy": 1},
    {"battle": 1, "boss": 1},
]
(
    A1,
    B1,
    C1,
    D1,
    E1,
    F1,
    G1,
) = MAP.flatten()


class Config:
    fleet_2 = 0
    submarine = 0
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS: ClassVar[dict[str, object]] = {
        "height": (120, 255 - 49),
        "width": (1.5, 10),
        "prominence": 10,
        "distance": 35,
    }
    EDGE_LINES_FIND_PEAKS_PARAMETERS: ClassVar[dict[str, object]] = {
        "height": (255 - 49, 255),
        "prominence": 10,
        "distance": 50,
        "wlen": 1000,
    }
    HOMO_CANNY_THRESHOLD = (75, 100)
    HOMO_EDGE_COLOR_RANGE = (0, 49)
    INTERNAL_LINES_HOUGHLINES_THRESHOLD = 40
    EDGE_LINES_HOUGHLINES_THRESHOLD = 40
    HOMO_EDGE_HOUGHLINES_THRESHOLD = 80


class Campaign(CampaignBase):
    MAP = MAP

    def battle_0(self):
        return self.battle_default()

    def battle_1(self):
        return self.clear_boss()

    def handle_boss_appear_refocus(self, preset=(-3, 0)):
        return super().handle_boss_appear_refocus(preset)
