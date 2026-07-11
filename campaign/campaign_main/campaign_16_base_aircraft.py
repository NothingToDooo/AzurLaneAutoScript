from typing import TYPE_CHECKING, ClassVar

from module.base.decorator import del_cached_property
from module.base.timer import Timer
from module.base.utils import get_color, red_overlay_transparency
from module.handler.assets import AIR_STRIKE_CONFIRM, MAP_AIR_STRIKE, STRATEGY_OPENED
from module.handler.strategy import AIR_STRIKE_OFFSET
from module.logger import logger
from module.map.utils import location_ensure

from .campaign_15_base import CampaignBase as CampaignBase_

if TYPE_CHECKING:
    from module.base.type_alias import Point
    from module.map.type_alias import GridLocation
    from module.map.utils import HasLocation


class Config:
    MAP_WALK_TURNING_OPTIMIZE = False
    MAP_HAS_MYSTERY = False
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS: ClassVar[dict[str, object]] = {
        "height": (80, 255 - 33),
        "prominence": 10,
        "distance": 35,
    }
    # Handle fog on map, static homography parameters and lower canny threshold
    HOMO_STORAGE = ((8, 6), [(137.405, 104.804), (1046.044, 104.804), (-12.171, 652.093), (1166.717, 652.093)])
    HOMO_CANNY_THRESHOLD = (50, 80)


class CampaignBase(CampaignBase_):
    MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD = 0.35
    ENEMY_FILTER = "1L > 1M > 1E > 2L > 3L > 2M > 2E > 1C > 2C > 3M > 3E > 3C"

    def _air_strike_appear(self) -> bool:
        return bool(
            red_overlay_transparency(MAP_AIR_STRIKE.color, get_color(self.device.image, MAP_AIR_STRIKE.area))
            > self.MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD
        )

    def _air_strike(self, location: GridLocation) -> None:
        self.in_sight(location)
        attack_grid = self.convert_global_to_local(location)

        logger.info("Select grid to air strike")
        skip_first_screenshot = True
        interval = Timer(5, count=10)
        for _ in self.loop(skip_first=skip_first_screenshot):
            if self.is_in_strategy_air_strike():
                self.view.update(image=self.device.image)
                del_cached_property(attack_grid, "image_trans")
            if attack_grid.predict_air_strike_icon():
                break
            if interval.reached() and self.is_in_strategy_air_strike():
                self.device.click(attack_grid)
                interval.reset()
                continue

        logger.info("Confirm air strike")
        skip_first_screenshot = True
        interval = Timer(3, count=6)
        MAP_AIR_STRIKE.load_color(self.device.image)
        for _ in self.loop(skip_first=skip_first_screenshot):
            if self._air_strike_appear():
                interval.reset()
                continue
            if self.appear(STRATEGY_OPENED, offset=AIR_STRIKE_OFFSET):
                break
            if interval.reached() and self.is_in_strategy_air_strike():
                self.device.click(AIR_STRIKE_CONFIRM)
                interval.reset()
                continue

    def air_strike(self, location: HasLocation | str | Point) -> bool:
        """从地图打开策略页，对 X=(x, y) 空袭后返回地图。

        覆盖 [x-2, y-1, x+2, y]：上排 OOOOO，下排 OOXOO。
        """
        location = location_ensure(location)
        if self.map[location].is_land:
            logger.warning(f"Air strike location {location} is on land, will abandon attacking")
            return False
        self.strategy_open()
        if not self.strategy_has_air_strike():
            logger.warning("No remain air strike trials, will abandon attacking")
            self.strategy_close()
            return False
        self.strategy_air_strike_enter()
        self._air_strike(location)
        self.strategy_close(skip_first_screenshot=False)
        return True
