from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.logger import logger


class Config:
    HOMO_EDGE_COLOR_RANGE = (0, 12)
    HOMO_EDGE_HOUGHLINES_THRESHOLD = 210
    MAP_SWIPE_MULTIPLY = (1.006, 1.025)
    MAP_SWIPE_MULTIPLY_MINITOUCH = (0.973, 0.991)

    # 该配置会导致错误，因此禁用。
    MAP_SWIPE_PREDICT_WITH_SEA_GRIDS = False
    # Ambushes can be avoid by having more DDs.
    MAP_WALK_TURNING_OPTIMIZE = False


class CampaignBase(CampaignBase_):
    ENEMY_FILTER = "1T > 1L > 1E > 1M > 2T > 2L > 2E > 2M > 3T > 3L > 3E > 3M"

    def __init__(self, *args, **kwargs):
        self.picked_light_house = []
        self.picked_flare = []
        super().__init__(*args, **kwargs)

    def map_data_init(self, map_):
        super().map_data_init(map_)
        self.picked_light_house = []
        self.picked_flare = []

    def handle_mystery_items(self, button=None):
        """
        处理照明弹获得弹窗，但不把它算作常规 mystery。
        """
        super().handle_mystery_items(button=button)
        return False

    def pick_up_flare(self, grid):
        """标记并尝试拾取对应设施，始终返回 False。"""
        grid.is_flare = True
        if grid in self.picked_flare:
            logger.info(f"Flares {grid} already picked up")
        elif grid.is_accessible:
            logger.info(f"Pick up flares on {grid}")
            # get_items shows after flares picked up.
            self.goto(grid)
            self.picked_flare.append(grid)
        else:
            logger.info(f"Flares {grid} not accessible, will check in next battle")

        return False

    def pick_up_light_house(self, grid):
        """标记并尝试拾取对应设施，始终返回 False。"""
        if grid in self.picked_light_house:
            logger.info(f"Light house {grid} already picked up")
        elif grid.is_accessible:
            logger.info(f"Pick up light house on {grid}")
            self.goto(grid)
            self.picked_light_house.append(grid)
            self.ensure_no_info_bar()
        else:
            logger.info(f"Light house {grid} not accessible, will check in next battle")

        return False
