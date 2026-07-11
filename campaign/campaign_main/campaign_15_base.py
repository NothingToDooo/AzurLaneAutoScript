from typing import TYPE_CHECKING, ClassVar, Literal

from module.base.timer import Timer
from module.handler.assets import STRATEGY_OPENED
from module.handler.strategy import MOB_MOVE_OFFSET
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.map.utils import location_ensure
from module.map_detection.grid_info import GridInfo

from .campaign_support_fleet import CampaignBase as CampaignBase_

if TYPE_CHECKING:
    from module.base.type_alias import Point
    from module.map.type_alias import GridLocation, GridMode
    from module.map.utils import HasLocation
    from module.map_detection.grid import Grid


class Config:
    # Ambushes can be avoid by having more DDs.
    MAP_WALK_TURNING_OPTIMIZE = False
    MAP_HAS_MYSTERY = False
    MAP_ENEMY_TEMPLATE = ("Light", "Main", "Carrier", "CarrierSpecial")
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS: ClassVar[dict[str, object]] = {
        "height": (80, 255 - 33),
        "width": (0.9, 10),
        "prominence": 10,
        "distance": 35,
    }
    HOMO_CANNY_THRESHOLD = (50, 100)
    MAP_SWIPE_MULTIPLY = (0.993, 1.011)
    MAP_SWIPE_MULTIPLY_MINITOUCH = (0.960, 0.978)


class W15GridInfo(GridInfo):
    def merge(self, info: GridInfo, mode: GridMode = "normal") -> bool:
        # 将 Boss 视作 Siren。
        if info.is_boss and not self.is_land and self.may_siren:
            self.is_siren = True
            self.enemy_scale = 0
            self.enemy_genre = ""
            return True

        return super().merge(info, mode=mode)


class CampaignBase(CampaignBase_):
    ENEMY_FILTER = "1L > 1M > 1E > 2L > 3L > 2M > 2E > 1C > 2C > 3M > 3E > 3C"

    map_has_mob_move = True

    def strategy_set_execute(
        self,
        formation: Literal["line_ahead", "double_line", "diamond"] | None = None,
        *,
        sub_view: bool | None = None,
        sub_hunt: bool | None = None,
    ) -> None:
        super().strategy_set_execute(
            formation=formation,
            sub_view=sub_view,
            sub_hunt=sub_hunt,
        )
        logger.attr("Map has mob move", self.strategy_has_mob_move())

    def mob_movable(
        self,
        location: HasLocation | str | Point,
        target: HasLocation | str | Point,
    ) -> bool:
        """仅当起点和终点均在地图内、曼哈顿距离为 1、起点是敌方舰队且终点是海面格时可移动。"""
        location = location_ensure(location)
        target = location_ensure(target)
        movable = True

        try:
            logger.info(f"location: {self.map[location]}, target: {self.map[target]}")
        except KeyError:
            logger.exception("Given coordinates are outside the map.")
            raise

        if abs(location[0] - target[0]) + abs(location[1] - target[1]) != 1:
            logger.error(f"{self.map[target]} is not adjacent from {self.map[location]}.")
            movable = False

        if not self.map[location].is_enemy:
            logger.error(f"{self.map[location]} is not a mob fleet.")
            movable = False

        if not self.map[target].is_sea:
            logger.error(f"{self.map[target]} is not a sea grid.")
            movable = False

        if not movable:
            logger.error(f"Cannot move from {self.map[location]} to {self.map[target]}.")

        return movable

    def _mob_move_grids(self, location: GridLocation, target: GridLocation) -> tuple[Grid, Grid]:
        view_target = SelectedGrids([self.map[location], self.map[target]]).sort_by_camera_distance(self.camera)[1]
        self.in_sight(view_target)
        origin_grid = self.convert_global_to_local(location)
        target_grid = self.convert_global_to_local(target)
        return origin_grid, target_grid

    def _select_mob_move_origin(self, origin_grid: Grid) -> None:
        logger.info("Select mob to move")
        skip_first_screenshot = True
        interval = Timer(2, count=4)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_in_strategy_mob_move():
                self.view.update(image=self.device.image)
            if origin_grid.predict_mob_move_icon():
                break
            if interval.reached() and self.is_in_strategy_mob_move():
                self.device.click(origin_grid)
                interval.reset()
                continue

    def _select_mob_move_target(self, target_grid: Grid) -> None:
        logger.info("Select target grid")
        skip_first_screenshot = True
        interval = Timer(2, count=4)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(STRATEGY_OPENED, offset=MOB_MOVE_OFFSET):
                break
            if interval.reached() and self.is_in_strategy_mob_move():
                self.device.click(target_grid)
                interval.reset()
                continue
            if self.handle_popup_confirm("MOB_MOVE"):
                continue

    def _mob_move(self, location: HasLocation | str | Point, target: HasLocation | str | Point) -> None:
        """在 MOB_MOVE_CANCEL 页面选择起点和终点，结束于 STRATEGY_OPENED 页面。"""
        location = location_ensure(location)
        target = location_ensure(target)
        origin_grid, target_grid = self._mob_move_grids(location, target)
        self._select_mob_move_origin(origin_grid)
        self._select_mob_move_target(target_grid)

    def _mob_move_info_change(self, location: HasLocation | str | Point, target: HasLocation | str | Point) -> None:
        location = location_ensure(location)
        target = location_ensure(target)
        self.map[target].enemy_scale = self.map[location].enemy_scale
        self.map[location].enemy_scale = 0
        self.map[target].enemy_genre = self.map[location].enemy_genre
        self.map[location].enemy_genre = None
        self.map[target].is_boss = self.map[location].is_boss
        self.map[location].is_boss = False
        self.map[target].is_enemy = True
        self.map[target].may_enemy = True
        self.map[location].is_enemy = False

    def mob_move(self, location: HasLocation | str | Point, target: HasLocation | str | Point) -> bool:
        """从 IN_MAP 打开策略页、移动敌方舰队并返回 IN_MAP；无效或次数耗尽时返回 False。"""
        if not self.mob_movable(location, target):
            return False

        self.strategy_open()
        if not self.strategy_has_mob_move():
            logger.warning("No remain mob move trials, will abandon moving")
            self.strategy_close()
            return False
        self.strategy_mob_move_enter()
        self._mob_move(location, target)
        self.strategy_close(skip_first_screenshot=False)

        self._mob_move_info_change(location, target)
        self.find_path_initial()
        self.map.show()
        return True
