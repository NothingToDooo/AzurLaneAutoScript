import copy
from typing import TYPE_CHECKING

import numpy as np

from module.base.timer import Timer
from module.base.utils import area_offset
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_1_RYZA
from module.device.control_options import SwipeVectorOptions
from module.exception import CampaignEnd, GameNotRunningError, MapDetectionError
from module.handler.assets import AUTO_SEARCH_MENU_CONTINUE, GAME_TIPS, GET_MISSION
from module.logger import logger
from module.map.assets import MAP_PREPARATION
from module.map.map_base import CampaignMap, location2node
from module.map.map_observer import InSightRequest
from module.map.map_operation import MapOperation
from module.map.map_swipe import STANDARD_MAP_SWIPE_SERVICE, MapSwipeRequest, MapSwipeService
from module.map.utils import location_ensure, random_direction
from module.map_detection.grid import Grid
from module.map_detection.utils import area2corner, trapezoid2area
from module.map_detection.view import CAMERA_OUTSIDE_MAP_MESSAGE, View
from module.os.assets import GLOBE_GOTO_MAP
from module.os_handler.assets import AUTO_SEARCH_REWARD, GET_ADAPTABILITY
from module.os_handler.assets import MISSION_CHECK as OPSI_MISSION_CHECK
from module.os_shop.assets import PORT_SUPPLY_CHECK
from module.ui.assets import BACK_ARROW

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from module.base.button import Button, MatchOffset
    from module.base.type_alias import Area, NumericArray, Point
    from module.map.map_grids import SelectedGrids
    from module.map.map_spawn_gap import MapSpawnGapPredictor
    from module.map.type_alias import GridLocation
    from module.map_detection.grid_info import GridInfo

type RecoveryOverlay = tuple[Button, MatchOffset, Button, str]

_EARLY_CLICK_RECOVERY_OVERLAYS = (
    (GET_ITEMS_1, 5, GET_ITEMS_1, "Perspective error caused by get_items"),
    (GET_ITEMS_1_RYZA, (-20, -100, 20, 20), GET_ITEMS_1_RYZA, "Perspective error caused by GET_ITEMS_1_RYZA"),
    (GET_ADAPTABILITY, (20, 20), GET_ADAPTABILITY, "Perspective error caused by GET_ADAPTABILITY"),
    (GET_MISSION, (20, 20), GET_MISSION, "Perspective error caused by GET_MISSION"),
)
_LATE_CLICK_RECOVERY_OVERLAYS = (
    (PORT_SUPPLY_CHECK, (20, 20), BACK_ARROW, "Perspective error caused by akashi shop"),
    (GAME_TIPS, (20, 20), GAME_TIPS, "Perspective error caused by game tips"),
)
IMAGE_NOT_IN_MAP_MESSAGE = "Image to detect is not in_map"
IMAGE_IN_STAGE_MESSAGE = "Image is in stage"
IMAGE_IN_MAP_PREPARATION_MESSAGE = "Image is in MAP_PREPARATION"
IMAGE_IN_AUTO_SEARCH_MENU_MESSAGE = "Image is in auto search menu"


class Camera(MapOperation):
    view: View
    map: CampaignMap
    camera: GridLocation = (0, 0)
    grid_class = Grid
    _prev_view: View | None = None
    _prev_swipe: Point | None = None
    _map_swipe_service: MapSwipeService = STANDARD_MAP_SWIPE_SERVICE
    map_spawn_gap_predictor: MapSpawnGapPredictor

    def _standard_map_swipe(self, vector: Point, *, box: Area) -> bool:
        """按浮点格子向量在 box 坐标区域内滑动，返回相机是否移动。"""
        vector = np.array(vector)
        name = "MAP_SWIPE_" + "_".join([str(round(x)) for x in vector])
        if np.any(np.abs(vector) > self.config.MAP_SWIPE_DROP):
            # 地图格子滑动倍率按 minitouch 固定。
            distance = self.view.swipe_base * self.config.MAP_SWIPE_MULTIPLY_MINITOUCH
            # 优化滑动路径。
            if self.config.MAP_SWIPE_OPTIMIZE:
                whitelist, blacklist = self.get_swipe_area_opt(vector)
            else:
                whitelist, blacklist = None, None

            vector = distance * vector
            vector = -vector
            self.device.swipe_vector(
                vector,
                SwipeVectorOptions(box=box, name=name, whitelist_area=whitelist, blacklist_area=blacklist),
            )
            self.update(wait_swipe=True)
            return True
        return False

    def _map_swipe(self, vector: Point, box: Area | None = None) -> bool:
        return self._map_swipe_service.swipe(
            self,
            MapSwipeRequest(vector=vector, explicit_box=box),
        )

    def map_swipe(self, vector: Point) -> bool:
        """按整数相对格子向量滑动；调用前必须已更新视图。"""
        logger.info(f"Map swipe: {vector}")
        self._prev_view = copy.copy(self.view)
        self._prev_swipe = vector
        vector = np.array(vector)
        vector = np.array([0.5, 0.5]) - self.view.center_offset + vector
        return self._map_swipe(vector)

    def focus_to_grid_center(self, tolerance: float | None = None) -> bool:
        """把镜头重置到格子中心；容差为 0～0.5，None 时使用配置值。"""
        if not tolerance:
            tolerance = self.config.MAP_GRID_CENTER_TOLERANCE
        if np.any(np.abs(self.view.center_offset - 0.5) > tolerance):
            logger.info("Re-focus to grid center.")
            return self.map_swipe((0, 0))

        return False

    def _view_init(self) -> None:
        if not hasattr(self, "view"):
            self.view = View(self.config, grid_class=self.grid_class)

    def _ensure_image_detectable(self) -> None:
        if (
            not self.is_in_map()
            and not self.is_in_strategy_submarine_move()
            and not self.is_in_strategy_mob_move()
            and not self.is_in_strategy_air_strike()
        ):
            logger.warning(IMAGE_NOT_IN_MAP_MESSAGE)
            raise MapDetectionError(IMAGE_NOT_IN_MAP_MESSAGE)

    def _update_view(self) -> bool:
        self._view_init()
        try:
            self._ensure_image_detectable()
            self.view.load(self.device.image)
        except MapDetectionError as e:
            return self._handle_update_view_error(e)

        return True

    def _handle_update_view_error(self, error: MapDetectionError) -> bool:
        if self._recover_perspective_error(error):
            return False
        if self._recover_camera_outside_map(error):
            return True

        # 最后检查游戏是否仍在运行。
        if not self.device.app_is_running():
            logger.error("Trying to update camera but game died")
            raise GameNotRunningError from error
        raise error

    def _recover_perspective_error(self, error: MapDetectionError) -> bool:
        for handler in (
            self._recover_info_bar,
            self._recover_early_click_overlays,
            self._recover_story,
        ):
            if handler():
                return True

        self._end_if_in_stage(error)
        self._end_if_map_preparation(error)
        self._end_if_auto_search_menu(error)

        for handler in (
            self._recover_globe_map,
            self._recover_auto_search_reward,
            self._recover_opsi_mission_check,
            self._recover_opsi_popup,
            self._recover_late_click_overlays,
        ):
            if handler():
                return True
        return False

    def _recover_info_bar(self) -> bool:
        if not self.info_bar_count():
            return False

        logger.warning("Perspective error caused by info bar")
        self.handle_info_bar()
        return True

    def _recover_early_click_overlays(self) -> bool:
        return self._recover_click_overlays(_EARLY_CLICK_RECOVERY_OVERLAYS)

    def _recover_late_click_overlays(self) -> bool:
        return self._recover_click_overlays(_LATE_CLICK_RECOVERY_OVERLAYS)

    def _recover_click_overlays(self, overlays: Sequence[RecoveryOverlay]) -> bool:
        for button, offset, click_button, message in overlays:
            if self.appear(button, offset=offset):
                logger.warning(message)
                self.device.click(click_button)
                return True
        return False

    def _recover_story(self) -> bool:
        if not self.handle_story_skip():
            return False

        logger.warning("Perspective error caused by story")
        self.ensure_no_story(skip_first_screenshot=False)
        return True

    def _end_if_in_stage(self, error: MapDetectionError) -> bool:
        if not self.is_in_stage():
            return False

        logger.warning(IMAGE_IN_STAGE_MESSAGE)
        raise CampaignEnd(IMAGE_IN_STAGE_MESSAGE) from error

    def _end_if_map_preparation(self, error: MapDetectionError) -> bool:
        if not self.appear(MAP_PREPARATION, offset=(20, 20)):
            return False

        logger.warning(IMAGE_IN_MAP_PREPARATION_MESSAGE)
        self.enter_map_cancel()
        raise CampaignEnd(IMAGE_IN_MAP_PREPARATION_MESSAGE) from error

    def _end_if_auto_search_menu(self, error: MapDetectionError) -> bool:
        if not self.appear(AUTO_SEARCH_MENU_CONTINUE, offset=self._auto_search_menu_offset):
            return False

        logger.warning(IMAGE_IN_AUTO_SEARCH_MENU_MESSAGE)
        self.ensure_auto_search_exit()
        raise CampaignEnd(IMAGE_IN_AUTO_SEARCH_MENU_MESSAGE) from error

    def _recover_globe_map(self) -> bool:
        if not self.appear(GLOBE_GOTO_MAP, offset=(20, 20)):
            return False

        logger.warning("Image is in OS globe map")
        self.ui_click(
            GLOBE_GOTO_MAP,
            check_button=self.is_in_map,
            offset=(20, 20),
            retry_wait=3,
            skip_first_screenshot=True,
        )
        return True

    def _recover_auto_search_reward(self) -> bool:
        if not self.appear(AUTO_SEARCH_REWARD, offset=(50, 50)):
            return False

        logger.warning("Perspective error caused by AUTO_SEARCH_REWARD")
        os_auto_search_quit = getattr(self, "os_auto_search_quit", None)
        if callable(os_auto_search_quit):
            os_auto_search_quit()
            return True

        logger.warning("Cannot find method os_auto_search_quit(), use ui_click() instead")
        self.ui_click(
            AUTO_SEARCH_REWARD,
            check_button=self.is_in_map,
            offset=(50, 50),
            retry_wait=3,
            skip_first_screenshot=True,
        )
        return True

    def _recover_opsi_mission_check(self) -> bool:
        if not self.appear(OPSI_MISSION_CHECK, offset=(20, 20)):
            return False

        logger.warning("Perspective error caused by OPSI_MISSION_CHECK")
        os_mission_quit = getattr(self, "os_mission_quit", None)
        if callable(os_mission_quit):
            os_mission_quit()
            return True

        logger.warning("Cannot find method os_mission_quit(), use ui_click() instead")
        self.ui_click(OPSI_MISSION_CHECK, check_button=self.is_in_map, offset=(200, 5), skip_first_screenshot=True)
        return True

    def _recover_opsi_popup(self) -> bool:
        if "opsi" not in self.config.task.command.lower() or not self.handle_popup_confirm("OPSI"):
            return False

        # 大型作战内始终确认弹窗，和 os_map_goto_globe() 的处理保持一致。
        logger.warning("Perspective error caused by popups")
        return True

    def _recover_camera_outside_map(self, error: MapDetectionError) -> bool:
        message = str(error)
        if CAMERA_OUTSIDE_MAP_MESSAGE not in message:
            return False

        logger.warning(message)
        x, y = message.split("=")[1].strip("() ").split(",")
        self._map_swipe((-int(x.strip()), -int(y.strip())))
        return True

    def _get_previous_center_offset(self, *, wait_swipe: bool) -> NumericArray | None:
        if not wait_swipe:
            return None

        prev_view = self._prev_view
        if prev_view is None:
            logger.warning("Camera.update(wait_swipe=True) but camera has no _prev_view")
            prev_center_offset = None
        else:
            prev_center_offset = prev_view.center_offset
        logger.attr("prev.center_offset", prev_center_offset)
        return prev_center_offset

    def _capture_update_screenshot(self, swipe_wait_timeout: Timer) -> None:
        # Camera.update() 没有 skip_first_screenshot。
        # 等待 swipe_wait_timeout 时不要额外限制截图间隔。
        if not swipe_wait_timeout.reached():
            self.device.screenshot_interval_clear()
        self.device.screenshot()

    def _is_grid_center(self) -> bool:
        return not np.any(np.abs(self.view.center_offset - 0.5) > self.config.MAP_GRID_CENTER_TOLERANCE)

    @staticmethod
    def _is_still_prev_view(center_offset: NumericArray, prev_center_offset: NumericArray | None) -> bool:
        if prev_center_offset is None:
            return False
        return np.linalg.norm(center_offset - prev_center_offset) < 0.001

    def _handle_wait_swipe_view(
        self,
        prev_center_offset: NumericArray | None,
        *,
        swiped: bool,
        error_confirm: Timer,
    ) -> tuple[bool, bool]:
        if self._is_still_prev_view(self.view.center_offset, prev_center_offset):
            swiped = False
        if self._is_grid_center():
            if swiped:
                return True, swiped
        else:
            swiped = True

        # 没有错误，重置检测错误确认计时。
        error_confirm.reset()
        return False, swiped

    def _update_view_data(self) -> bool:
        prev_swipe = np.asarray(self._prev_swipe if self._prev_swipe is not None else (0, 0))
        if self._prev_view is not None and np.linalg.norm(prev_swipe) > 0:
            if self.config.MAP_SWIPE_PREDICT:
                swipe = self._prev_view.predict_swipe(
                    self.view,
                    with_current_fleet=self.config.MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET,
                    with_sea_grids=self.config.MAP_SWIPE_PREDICT_WITH_SEA_GRIDS,
                )
                if swipe is not None:
                    prev_swipe = np.asarray(swipe)
                    self._prev_swipe = swipe
            self.camera = tuple(np.add(self.camera, prev_swipe))
            self._prev_view = None
            self._prev_swipe = None
            self.show_camera()

        if self.view.left_edge:
            x = 0 + self.view.center_loca[0]
        elif self.view.right_edge:
            x = self.map.layout.shape[0] - self.view.shape[0] + self.view.center_loca[0]
        else:
            x = self.camera[0]
        if self.view.upper_edge:
            y = self.map.layout.shape[1] - self.view.shape[1] + self.view.center_loca[1]
        elif self.view.lower_edge:
            y = 0 + self.view.center_loca[1]
        else:
            y = self.camera[1]

        if self.camera != (x, y):
            logger.attr_align("camera_corrected", f"{location2node(self.camera)} -> {location2node((x, y))}")
        self.camera = (x, y)
        self.show_camera()

        self.predict()
        return True

    def update(self, *, camera: bool = True, wait_swipe: bool = False, allow_error: bool = False) -> bool:
        """更新地图截图和相机视图。

        camera 控制是否更新相机与透视数据；wait_swipe 等待镜头回到格子中心；
        allow_error 遇到检测错误时退出本轮。
        """
        error_confirm = Timer(5, count=10).start()
        swipe_wait_timeout = Timer(0.35, count=1).start()
        swiped = True
        prev_center_offset = self._get_previous_center_offset(wait_swipe=wait_swipe)

        while 1:
            self._capture_update_screenshot(swipe_wait_timeout)

            if not camera:
                self.view.update(image=self.device.image)
                return True

            try:
                success = self._update_view()
            except MapDetectionError:
                if allow_error:
                    break
                if error_confirm.reached():
                    raise
                continue

            if not success:
                continue

            logger.attr("view.center_offset", self.view.center_offset)
            if wait_swipe and not swipe_wait_timeout.reached():
                should_stop, swiped = self._handle_wait_swipe_view(
                    prev_center_offset, swiped=swiped, error_confirm=error_confirm
                )
                if should_stop:
                    break
                continue
            break

        self._update_view_data()
        return True

    def predict(self) -> None:
        self.view.predict()
        self.view.show()

    def show_camera(self) -> None:
        logger.attr_align("Camera", location2node(self.camera))

    def ensure_edge_insight(
        self,
        *,
        reverse: bool = False,
        preset: GridLocation | None = None,
        swipe_limit: GridLocation = (3, 2),
        skip_first_update: bool = True,
    ) -> list[GridLocation]:
        """滑到两个边缘以定位相机；swipe_limit 限制各轴幅度，并返回滑动向量记录。"""
        logger.info("Ensure edge in sight.")
        record = []
        x_swipe, y_swipe = np.multiply(swipe_limit, random_direction(self.config.MAP_ENSURE_EDGE_INSIGHT_CORNER))

        while 1:
            if len(record) == 0:
                if not skip_first_update:
                    self.update()
                if preset is not None:
                    self.map_swipe(preset)
                    record.append(preset)

            x = 0 if self.view.left_edge or self.view.right_edge else x_swipe
            y = 0 if self.view.lower_edge or self.view.upper_edge else y_swipe

            if len(record) > 0:
                # 即使已看到两个边缘也再滑一次，避免镜头停在不稳定位置。
                self.map_swipe((x, y))

            record.append((x, y))

            if x == 0 and y == 0:
                break

        if reverse:
            logger.info("Reverse swipes.")
            for vector in record[::-1]:
                x, y = vector
                if x != 0 or y != 0:
                    self.map_swipe((-x, -y))

        return record

    def focus_to(self, location: GridInfo | str | Point, swipe_limit: GridLocation = (4, 3)) -> None:
        """聚焦到指定格子；swipe_limit 限制单次各轴滑动幅度。"""
        location = location_ensure(location)
        logger.info(f"Focus to: {location2node(location)}")

        while 1:
            vector = np.array(location) - self.camera
            swipe = tuple(np.min([np.abs(vector), swipe_limit], axis=0) * np.sign(vector))
            has_swiped = self.map_swipe(swipe)

            if not has_swiped:
                break

    def in_sight(self, location: GridInfo | str | Point, sight: tuple[int, int, int, int] | None = None) -> None:
        """确保格子位于相机视野矩形内；sight 形如 (-3, -1, 3, 2)。"""
        self._map_observer.viewport.in_sight(
            self,
            InSightRequest(location=location_ensure(location), sight=sight),
        )

    def _standard_in_sight(self, request: InSightRequest) -> None:
        """执行未被 profile 规则处理的标准视野算法。"""
        location = request.location
        logger.info(f"In sight: {location2node(location)}")
        sight = self.map.layout.camera_sight if request.sight is None else request.sight

        diff = np.array(location) - self.camera
        if diff[1] > sight[3]:
            y = diff[1] - sight[3]
        elif diff[1] < sight[1]:
            y = diff[1] - sight[1]
        else:
            y = 0
        if diff[0] > sight[2]:
            x = diff[0] - sight[2]
        elif diff[0] < sight[0]:
            x = diff[0] - sight[0]
        else:
            x = 0
        self.focus_to((self.camera[0] + x, self.camera[1] + y))

    def convert_global_to_local(self, location: GridInfo | str | Point) -> Grid:
        """把全局地图格转为当前视图格；越界时先聚焦再重算。"""
        location = location_ensure(location)

        local = np.array(location) - self.camera + self.view.center_loca
        logger.info(
            f"Global {location2node(location)} (camera={location2node(self.camera)}) "
            f"-> Local {location2node(local)} (center={location2node(self.view.center_loca)})"
        )
        if local in self.view:
            return self.view[local]
        logger.warning("Convert global to local Failed.")
        self.focus_to(location)
        local = np.array(location) - self.camera + self.view.center_loca
        return self.view[local]

    def convert_local_to_global(self, location: GridInfo | str | Point) -> GridInfo:
        """把当前视图格转为全局地图格；越界时校正相机再重算。"""
        location = location_ensure(location)

        global_ = np.array(location) + self.camera - self.view.center_loca
        logger.info(
            f"Global {location2node(global_)} (camera={location2node(self.camera)}) "
            f"<- Local {location2node(location)} (center={location2node(self.view.center_loca)})"
        )

        if global_ in self.map:
            return self.map[global_]
        logger.warning("Convert local to global Failed.")
        self.ensure_edge_insight(reverse=True)
        global_ = np.array(location) + self.camera - self.view.center_loca
        return self.map[global_]

    def full_scan_find_boss(self) -> bool:
        logger.info("Full scan find boss.")
        self.map.reset_fleet()

        queue = self.map.layout.select(may_boss=True)
        while len(queue) > 0:
            queue = queue.sort_by_camera_distance(self.camera)
            self.in_sight(queue[0])
            self.predict()
            queue = queue[1:]

            boss = self.map.layout.select(is_boss=True)
            boss = boss.add(self.map.layout.select(may_boss=True, is_enemy=True))
            if boss:
                logger.info(f"Boss found: {boss}")
                self.map.show()
                return True

        logger.warning("No boss found.")
        return False

    def get_swipe_area_opt(self, map_vector: Point) -> tuple[list[Area], list[Area]]:
        """返回滑动终点随机化使用的白名单、黑名单区域列表。"""
        map_vector = np.array(map_vector)

        def local_to_area(local_grid: Iterable[Grid], pad: int = 0) -> list[Area]:
            result = []
            for local in local_grid:
                # 预测滑动后的格子位置，让手势在那里结束以免被识别为点击。
                area = area_offset((0, 0, 1, 1), offset=-map_vector)
                corner = local.grid2screen(area2corner(area))
                area = trapezoid2area(corner, pad=pad)
                result.append(area)
            return result

        def globe_to_local(globe_grids: SelectedGrids[GridInfo]) -> list[Grid]:
            result = []
            for globe in globe_grids:
                location = tuple(np.array(globe.location) - self.camera + self.view.center_loca)
                if location in self.view:
                    local = self.view[location]
                    result.append(local)
            return result

        whitelist = (
            self.map.layout.select(is_land=True)
            .add(self.map.layout.select(is_current_fleet=True))
            .sort_by_camera_distance(self.camera)
        )
        blacklist = (
            self.view.select(is_enemy=True)
            .add(self.view.select(is_siren=True))
            .add(self.view.select(is_boss=True))
            .add(self.view.select(is_mystery=True))
            .add(self.view.select(is_fleet=True, is_current_fleet=False))
        )

        whitelist = local_to_area(globe_to_local(whitelist), pad=25)
        blacklist = [grid.outer for grid in blacklist] + local_to_area(blacklist, pad=-5)

        return whitelist, blacklist
