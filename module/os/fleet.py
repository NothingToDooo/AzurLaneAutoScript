import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast, override

import numpy as np

from module.base.button import Button
from module.base.filter import Filter
from module.base.timer import Timer
from module.base.utils import point_limit
from module.exception import MapWalkError
from module.handler.assets import MAINTENANCE_ANNOUNCE
from module.handler.mystery_item import MysteryKind, MysteryResult
from module.logger import logger
from module.map.fleet import Fleet
from module.map.fleet_navigation_ui import CampaignFleetMovementUi
from module.map.map_grids import SelectedGrids
from module.map.utils import location_ensure
from module.map_detection.utils import area2corner, corner2inner
from module.ocr.ocr import Ocr
from module.os.assets import FLEET_EMP_DEBUFF, MAP_EXIT, MAP_GOTO_GLOBE, STRONGHOLD_PERCENTAGE, TEMPLATE_EMPTY_HP
from module.os.camera import OSCamera
from module.os.map_base import OSCampaignMap
from module.os_ash.ash import OSAsh
from module.os_combat import assets as os_combat_assets
from module.os_combat.combat import Combat
from module.os_handler.assets import AUTO_SEARCH_REWARD, CLICK_SAFE_AREA, IN_MAP, PORT_ENTER
from module.os_shop.assets import PORT_SUPPLY_CHECK
from module.ui.assets import BACK_ARROW

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Unpack

    from module.base.type_alias import ImageArray, NumericArray, Point
    from module.config.config import AzurLaneConfig
    from module.device.device import Device
    from module.map.map_base import CampaignMap
    from module.map.type_alias import GridLocation
    from module.map_detection.grid import Grid
    from module.os.radar import RadarGrid, RadarSelection

FLEET_FILTER = Filter(regex=re.compile(r"fleet-?(\d)"), attr=("fleet",), preset=("callsubmarine",))
WALK_OUT_OF_STEP_MESSAGE = "walk_out_of_step"


@dataclass(slots=True)
class _WalkStableContext:
    confirm_timer: Timer
    stuck_timer: Timer
    walk_out_of_step: bool
    record: NumericArray | GridLocation | None = None
    enemy_searching_appear: bool = False
    clicked_story: bool = False
    result: set[str] = field(default_factory=set)


def limit_walk(location: Point, step: int = 3) -> GridLocation:
    values = tuple(location)
    x, y = int(values[0]), int(values[1])
    if abs(x) > 0:
        x = min(abs(x), step - abs(y)) * x // abs(x)
    return int(x), int(y)


def offset_location(location: GridLocation, offset: Point) -> GridLocation:
    values = tuple(offset)
    return location[0] + int(values[0]), location[1] + int(values[1])


class BossFleet:
    def __init__(self, fleet_index: int) -> None:
        self.fleet_index = fleet_index
        self.fleet = str(fleet_index)
        self.standby_loca = (0, 0)

    def __str__(self) -> str:
        return f"Fleet-{self.fleet}"

    __repr__ = __str__

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)

    __hash__ = None


class PercentageOcr(Ocr[str]):
    def pre_process(self, image: ImageArray) -> ImageArray:
        image = super().pre_process(image)
        return np.pad(image, ((2, 2), (0, 0)), mode="constant", constant_values=255)


FLEET_LOW_RESOLVE = Button(
    area=(294, 76, 339, 121), color=(255, 44, 33), button=(294, 76, 339, 121), name="FLEET_LOW_RESOLVE"
)


class OSFleetMovementUi(CampaignFleetMovementUi):
    """在通用到达提交后刷新大世界雷达与信标攻击状态。"""

    @override
    def navigation_after_arrival(self, location: GridLocation) -> None:
        runtime = cast("OSFleet", self._runtime)
        runtime.predict_radar()
        runtime.map.show()

        if runtime.handle_ash_beacon_attack():
            # 信标攻击后镜头会重新聚焦当前舰队。
            runtime.camera = location
            runtime.update()


class OSFleet(OSCamera, Combat, Fleet, OSAsh):
    @override
    def _build_navigation_movement_ui(self) -> OSFleetMovementUi:
        return OSFleetMovementUi(self, self._map_observer)

    @override
    def _navigation_walk_sight(self) -> tuple[int, int, int, int]:
        return (-4, -1, 3, 2)

    @override
    def _active_hp_fleet_index(self) -> int:
        return self.fleet_selector.get() or 1

    def map_data_init(self, map_: CampaignMap | None = None) -> None:
        map_ = OSCampaignMap()
        map_.layout.initialize(self.zone.shape)
        super().map_data_init(map_)

    def map_control_init(self) -> None:
        """初始化大世界地图控制，并移除战略、回合等不存在的状态。"""
        self.update()
        self.hp_reset()
        self.hp_get()
        self.lv_reset()
        self.lv_get()
        self.ensure_edge_insight(preset=self.map.in_map_swipe_preset_data, swipe_limit=(6, 5))

    _os_map_event_handled = False

    def ambush_color_initial(self) -> None:
        self._os_map_event_handled = False

    def handle_ambush(self) -> bool:
        """把地图事件视为伏击，使航行流程重试。"""
        if self.handle_map_get_items():
            self._os_map_event_handled = True
            self.device.sleep(0.3)
            self.device.screenshot()
            return True
        if self.handle_map_event():
            self.ensure_no_map_event()
            self._os_map_event_handled = True
            return True
        return False

    def handle_mystery(self, button: Grid | None = None) -> MysteryResult | None:
        """处理伏击后，舰队已到达时按神秘事件处理，否则仍按伏击处理。"""
        if button is None:
            return None
        if self._os_map_event_handled and button.predict_fleet() and button.predict_current_fleet():
            return MysteryResult(MysteryKind.GET_ITEM, counts_toward_mystery=True)
        return None

    @staticmethod
    def _get_goto_expected(grid: RadarGrid) -> str:
        if grid.is_enemy:
            return "combat"
        if grid.is_resource or grid.is_meowfficer or grid.is_exclamation:
            return "mystery"
        return ""

    @override
    def hp_retreat_triggered(self) -> bool:
        return False

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
    ) -> None:
        self.need_repair: list[bool] = [False] * 6
        super().__init__(config, device=device)

    def hp_get(self) -> list[float]:
        """计算当前血量，并识别舰船阵亡后需要维修的扳手标记。"""
        super().hp_get()
        ship_icon = self._hp_grid().crop((0, -67, 67, 0))
        need_repair = [TEMPLATE_EMPTY_HP.match(self.image_crop(button, copy=False)) for button in ship_icon.buttons]
        self.need_repair = need_repair
        logger.attr("Repair icon", need_repair)

        if any(need_repair):
            fleet_index = self._active_hp_fleet_index()
            for index, repair in enumerate(need_repair):
                if repair:
                    self._hp_has_ship[fleet_index][index] = True
                    self._hp[fleet_index][index] = 0

            logger.attr(
                "HP",
                " ".join(
                    [
                        str(int(data * 100)).rjust(3) + "%" if use else "____"
                        for data, use in zip(self.hp, self.hp_has_ship, strict=True)
                    ]
                ),
            )

        return self.hp

    @override
    def lv_get(self, *, after_battle: bool = False) -> None:
        del after_battle

    def fleet_low_resolve_appear(self) -> bool:
        return self.image_color_count(FLEET_LOW_RESOLVE, color=FLEET_LOW_RESOLVE.color, threshold=221, count=250)

    def wait_until_camera_stable(self, *, skip_first_screenshot: bool = True) -> None:
        """在 homography 检测模式下等待镜头定位稳定。"""
        logger.hr("Wait until camera stable")
        record = None
        confirm_timer = Timer(0.6, count=2).start()
        for _ in self.loop(skip_first=skip_first_screenshot):
            self.update_os()
            current = self._homography_loca(self.view)
            logger.attr("homo_loca", current)
            if record is None or (current is not None and np.linalg.norm(np.subtract(current, record)) < 3):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

            record = current

        logger.info("Camera stabled")

    @staticmethod
    def _walk_stable_reset(context: _WalkStableContext) -> None:
        context.confirm_timer.reset()
        context.stuck_timer.reset()

    def _walk_stable_abyssal_expected_end(self) -> bool:
        # OSCombat.combat_status() 会禁用普通掉落处理，这里补充地图事件处理。
        if self.handle_map_event():
            return False
        return self.is_in_map()

    def _handle_walk_stable_map_event(self, context: _WalkStableContext) -> bool:
        event = self.handle_map_event()
        if not event:
            return False
        self._walk_stable_reset(context)
        context.result.add("event")
        if event == "story_skip":
            context.clicked_story = True
        elif event == "map_get_items" and context.clicked_story:
            logger.info("Got items from story")
            self.device.click_record_clear()
            context.clicked_story = False
        else:
            context.clicked_story = False
        return True

    def _handle_walk_stable_basic_blockers(self, context: _WalkStableContext) -> bool:
        if self.handle_retirement():
            self._walk_stable_reset(context)
            return True
        if self.handle_walk_out_of_step():
            if context.walk_out_of_step:
                raise MapWalkError(WALK_OUT_OF_STEP_MESSAGE)
            return True
        if self.handle_popup_confirm("WALK_UNTIL_STABLE"):
            self._walk_stable_reset(context)
            return True
        return False

    def _handle_walk_stable_accident_clicks(self, context: _WalkStableContext) -> bool:
        if self.is_in_globe():
            self.os_globe_goto_map()
        elif self.is_in_storage():
            self.storage_quit()
        elif self.is_in_os_mission():
            self.os_mission_quit()
        elif self.handle_os_game_tips():
            pass
        elif self.is_in_map_order():
            self.order_quit()
        else:
            return False
        self._walk_stable_reset(context)
        return True

    def _handle_walk_stable_combat(self, context: _WalkStableContext) -> bool:
        if not self.combat_appear():
            return False
        self.combat(
            expected_end=self._walk_stable_abyssal_expected_end,
            fleet_index=self._active_hp_fleet_index(),
        )
        self._walk_stable_reset(context)
        context.result.add("event")
        return True

    def _handle_walk_stable_akashi(self, context: _WalkStableContext) -> bool:
        if not self.appear(PORT_SUPPLY_CHECK, offset=(20, 20)):
            return False
        self.interval_clear(PORT_SUPPLY_CHECK)
        self.handle_akashi_supply_buy(CLICK_SAFE_AREA)
        self._walk_stable_reset(context)
        context.result.add("akashi")
        return True

    def _handle_walk_stable_reward_popup(self, context: _WalkStableContext) -> bool:
        if not self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
            return False
        self._walk_stable_reset(context)
        return True

    def _handle_walk_stable_enemy_searching(self, context: _WalkStableContext) -> bool:
        if not context.enemy_searching_appear and self.enemy_searching_appear():
            context.enemy_searching_appear = True
            self._walk_stable_reset(context)
            return True
        if not context.enemy_searching_appear:
            return False
        self.handle_enemy_flashing()
        self.device.sleep(0.3)
        logger.info("Enemy searching appeared.")
        context.enemy_searching_appear = False
        self._walk_stable_reset(context)
        context.result.add("search")
        return False

    def _handle_walk_stable_interruption(self, context: _WalkStableContext) -> bool:
        handlers = (
            self._handle_walk_stable_map_event,
            self._handle_walk_stable_basic_blockers,
            self._handle_walk_stable_accident_clicks,
            self._handle_walk_stable_combat,
            self._handle_walk_stable_akashi,
            self._handle_walk_stable_reward_popup,
            self._handle_walk_stable_enemy_searching,
        )
        return any(handler(context) for handler in handlers)

    def _handle_walk_stable_arrival(self, context: _WalkStableContext) -> bool:
        # 解锁动画会使屏幕变黑，因此必须同时确认地图模板颜色。
        if not self.match_template_color(IN_MAP, offset=(200, 5)):
            self._walk_stable_reset(context)
            return False
        self.update_os()
        current = self._homography_loca(self.view)
        logger.attr("homo_loca", current)
        # 已知最大定位偏差为 4.48 像素，这里用 5.5 作为稳定阈值。
        if context.record is None or (
            current is not None and np.linalg.norm(np.subtract(current, context.record)) < 5.5
        ):
            if context.confirm_timer.reached():
                return True
        else:
            if context.stuck_timer.reached():
                logger.warning("homo_loca stuck at current view, try reset.")
                if self.fleet_reset_view():
                    context.stuck_timer.reset()
            context.confirm_timer.reset()
        context.record = current
        return False

    def wait_until_walk_stable(
        self,
        confirm_timer: Timer | None = None,
        *,
        skip_first_screenshot: bool = False,
        walk_out_of_step: bool = True,
    ) -> str:
        """在 homography 模式等待航行稳定。

        返回途中事件名或其组合；没有事件时返回空字符串，无法到达时抛出 MapWalkError。
        walk_out_of_step 控制是否捕获步数不同步，深渊海域应设为 False。
        """
        logger.hr("Wait until walk stable")
        self.device.screenshot_interval_set(0.35)
        if confirm_timer is None:
            confirm_timer = Timer(0.8, count=2)
        stuck_timer = Timer(20, count=5).start()
        confirm_timer.reset()
        context = _WalkStableContext(
            confirm_timer=confirm_timer,
            stuck_timer=stuck_timer,
            walk_out_of_step=walk_out_of_step,
        )

        for _ in self.loop(skip_first=skip_first_screenshot):
            if self._handle_walk_stable_interruption(context):
                continue
            if self.is_in_map():
                self.enemy_searching_color_initial()

            if self._handle_walk_stable_arrival(context):
                break

        result = "_".join(context.result)
        logger.info(f"Walk stabled, result: {result}")
        self.device.screenshot_interval_set()
        return result

    def fleet_reset_view(self) -> bool:
        current_fleet = self.fleet_selector.get()
        if not current_fleet:
            logger.warning("Failed to get OpSi fleet")
            return False
        self.fleet_selector.open()
        self.fleet_selector.click(current_fleet)
        return True

    def port_goto(self, *, allow_port_arrive: bool = True) -> bool:
        """按雷达位置驶向港口，规避移动时镜头自动跟随对常规 goto 的干扰。

        点击陆地、港口中心或舰队自身而无法到达时抛出 MapWalkError。
        """
        confirm_timer = Timer(3, count=6).start()
        while 1:
            grid = self.radar.port_predict(self.device.image)
            logger.info(f"Port route at {grid}")
            if grid is None:
                self.device.screenshot()
                continue

            radar_arrive = np.linalg.norm(grid) == 0
            port_arrive = self.appear(PORT_ENTER, offset=(20, 20))
            if allow_port_arrive and port_arrive:
                logger.info("Arrive port (port_arrive)")
                break
            if allow_port_arrive and (not port_arrive and radar_arrive):
                if confirm_timer.reached():
                    logger.warning("Arrive port on radar but port entrance not appear")
                    raise MapWalkError
                logger.info("Arrive port on radar but port entrance not appear, confirming")
                self.device.screenshot()
                continue
            if not allow_port_arrive and radar_arrive:
                logger.info("Arrive port (radar_arrive)")
                break
            confirm_timer.reset()

            self.update_os()
            self.predict()

            grid = point_limit(grid, area=(-4, -2, 3, 2))
            grid = self.convert_radar_to_local(grid)
            self.device.click(grid)

            self.wait_until_walk_stable()
        return True

    def fleet_set(self, index: int | None = None, *, skip_first_screenshot: bool = True) -> bool:
        """切换到目标舰队编号，返回是否实际发生切换。"""
        _ = skip_first_screenshot
        if index is None:
            index = 1
        logger.hr(f"Fleet set to {index}")
        if self.fleet_selector.ensure_to_be(index):
            self.wait_until_camera_stable()
            return True
        return False

    def parse_fleet_filter(self) -> list[BossFleet | str]:
        """返回 BossFleet 与指令字符串组成的顺序列表。"""
        FLEET_FILTER.load(self.config.OpsiFleetFilter_Filter)
        fleets = FLEET_FILTER.apply([BossFleet(f) for f in [1, 2, 3, 4]])

        standby_list = [(-1, -1), (0, -1), (1, -1)]
        index = 0
        for fleet in fleets:
            if isinstance(fleet, BossFleet) and index < len(standby_list):
                fleet.standby_loca = standby_list[index]
                index += 1

        return [fleet for fleet in fleets if isinstance(fleet, (BossFleet, str))]

    # relative_goto、question_goto 和 boss_goto 先让 update_os() 复用当前截图定位，点击后才刷新截图等待到达。
    def relative_goto(
        self,
        *,
        has_fleet_step: bool = False,
        near_by: bool = False,
        relative_position: Point = (0, 0),
        index: int = 0,
        **kwargs: Unpack[RadarSelection],
    ) -> None:
        logger.hr("Relative goto")
        logger.info(f"Relative goto, {kwargs}")

        self.update_os()
        self.predict()
        self.predict_radar()

        grids = self.radar.select(**kwargs)
        if near_by:
            grids = grids.sort_by_camera_distance((0, 0))
        if grids:
            grid = offset_location(location_ensure(grids[index]), relative_position)

            grid = point_limit(grid, area=(-4, -2, 3, 2))
            if has_fleet_step:
                grid = limit_walk(grid)
            grid = self.convert_radar_to_local(grid)
            self.device.click(grid)
        else:
            logger.info("No position to goto, stop")

        self.wait_until_walk_stable(confirm_timer=Timer(1.5, count=4), walk_out_of_step=False)

    def go_month_boss_room(self, *, is_normal: bool = True) -> None:
        logger.hr("Goto room entrance")
        logger.info(f"Goto room entrance, is_normal={is_normal}")
        while 1:
            if self.appear(MAP_EXIT, offset=(20, 20)):
                break

            # 入口下方两格。
            self.relative_goto(has_fleet_step=True, near_by=True, relative_position=(3, -2), is_port=True)

            self.update_os()
            self.predict()
            self.predict_radar()
            grid = self.radar.select(is_port=True).first_or_none()
            if grid is not None and grid.location == (-3, 2):
                logger.info("At room entrance")
                break

        logger.hr("Enter room entrance")
        while 1:
            if self.appear(MAP_EXIT, offset=(20, 20)):
                logger.info("Entered boss room")
                break

            if is_normal:
                self.relative_goto(has_fleet_step=True, near_by=True, is_exclamation=True)
            elif self.radar.select(is_exclamation=True).count:
                logger.warning("Trying to enter month boss hard mode but is_exclamation exists")
                self.relative_goto(has_fleet_step=True, near_by=True, is_exclamation=True)
            else:
                self.relative_goto(has_fleet_step=True, near_by=True, is_question=True)

    def question_goto(self, *, has_fleet_step: bool = False) -> None:
        logger.hr("Question goto")
        while 1:
            # 游戏可能延迟弹出上一个已清理海域的自动搜索奖励。
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                self.device.screenshot()
                continue

            self.update_os()
            self.predict()
            self.predict_radar()

            fleets = self.view.select(is_current_fleet=True)
            if fleets.count == 0:
                logger.warning("Current fleet not found on local view, reset camera view to current fleet.")
                if self.fleet_reset_view():
                    self.wait_until_camera_stable()
                    continue
            grids = self.radar.select(is_question=True)
            if grids:
                grid = location_ensure(grids[0])
                grid = point_limit(grid, area=(-4, -2, 3, 2))
                if has_fleet_step:
                    grid = limit_walk(grid)
                grid = self.convert_radar_to_local(grid)
                self.device.click(grid)
            else:
                logger.info("No question mark to goto, stop")
                break

            self.wait_until_walk_stable(confirm_timer=Timer(1.5, count=4), walk_out_of_step=False)

    def month_boss_goto_additional(
        self,
        location: Point = (0, 0),
        *,
        has_fleet_step: bool = False,
    ) -> None:
        self.update_os()
        self.predict()
        self.predict_radar()

        grids = self.radar.select(is_question=True)
        if grids:
            grid = offset_location(location_ensure(grids[0]), location)
            # 根据问号相对位置推算首领区域入口。
            grid = np.add(grid, (1, -6))
            grid = point_limit(grid, area=(-4, -2, 3, 2))
            if has_fleet_step:
                grid = limit_walk(grid)
            if grid == (0, 0):
                logger.info(f"Arrive destination: boss {location}")
            grid = self.convert_radar_to_local(grid)
            self.device.click(grid)
        else:
            logger.info("No boss to goto, stop")
        self.wait_until_walk_stable(confirm_timer=Timer(1.5, count=4), walk_out_of_step=False)

    def boss_goto(
        self,
        location: Point = (0, 0),
        *,
        has_fleet_step: bool = False,
        is_month: bool = False,
    ) -> None:
        logger.hr("BOSS goto")

        if is_month:
            self.month_boss_goto_additional(location=location, has_fleet_step=has_fleet_step)

        while 1:
            self.update_os()
            self.predict()
            self.predict_radar()

            grids = self.radar.select(is_enemy=True)
            if grids:
                grid = offset_location(location_ensure(grids[0]), location)
                grid = point_limit(grid, area=(-4, -2, 3, 2))
                if has_fleet_step:
                    grid = limit_walk(grid)
                if grid == (0, 0):
                    logger.info(f"Arrive destination: boss {location}")
                    break
                grid = self.convert_radar_to_local(grid)
                self.device.click(grid)
            else:
                logger.info("No boss to goto, stop")
                break

            self.wait_until_walk_stable(confirm_timer=Timer(4, count=6), walk_out_of_step=False)

    def get_boss_leave_button(self) -> Button | None:
        for grid in self.view:
            if grid.predict_current_fleet():
                return None

        grids = [grid for grid in self.view if grid.predict_caught_by_siren()]
        if len(grids) == 1:
            center = grids[0]
        elif len(grids) > 1:
            logger.warning(f"Found multiple fleets in boss ({grids}), use the center one")
            center = SelectedGrids(grids).sort_by_camera_distance(self.view.center_loca)[0]
        else:
            logger.warning("No fleet in boss, use camera center instead")
            center = self.view[self.view.center_loca]

        logger.info(f"Fleet in boss: {center}")
        # 中心格右侧相邻格的左半部分用于点击离开首领。
        area = corner2inner(center.grid2screen(area2corner((1, 0.25, 1.5, 0.75))))
        return Button(area=area, color=(), button=area, name="BOSS_LEAVE")

    def boss_leave(self) -> None:
        """从地图或战斗页离开首领区域，结束于区域地图。"""
        logger.hr("BOSS leave")
        self.update_os()
        self.predict()

        click_timer = Timer(3)
        pause_interval = Timer(0.5, count=1)
        for _ in self.loop():
            if self._boss_leave_finished():
                break
            if self._boss_leave_handle_reentry(pause_interval):
                continue
            if self._boss_leave_handle_quit(pause_interval):
                continue

            if self.is_in_map() and click_timer.reached():
                button = self.get_boss_leave_button()
                if button is not None:
                    self.device.click(button)
                    click_timer.reset()
                    continue
                logger.info("Fleet left boss, current fleet found")
                break

    def _boss_leave_finished(self) -> bool:
        if not self.is_in_map():
            return False
        self.predict_radar()
        if self.radar.select(is_enemy=True):
            logger.info("Fleet left boss, boss found")
            return True
        return False

    def _boss_leave_handle_reentry(self, pause_interval: Timer) -> bool:
        if not pause_interval.reached():
            return False
        if self._boss_leave_back_from_preparation(pause_interval):
            return True
        pause = self.is_combat_executing()
        if pause:
            self.device.click(pause)
            self._boss_leave_reset_pause(pause_interval)
            return True
        return False

    def _boss_leave_back_from_preparation(self, pause_interval: Timer) -> bool:
        if self.appear(os_combat_assets.BATTLE_PREPARATION):
            logger.info(f"{os_combat_assets.BATTLE_PREPARATION} -> {BACK_ARROW}")
            self.device.click(BACK_ARROW)
            pause_interval.reset()
            return True
        if self.appear(os_combat_assets.SIREN_PREPARATION, offset=(20, 20)):
            logger.info(f"{os_combat_assets.SIREN_PREPARATION} -> {BACK_ARROW}")
            self.device.click(BACK_ARROW)
            pause_interval.reset()
            return True
        return False

    def _boss_leave_handle_quit(self, pause_interval: Timer) -> bool:
        if self.handle_combat_quit() or self.handle_combat_quit_reconfirm():
            self._boss_leave_reset_pause(pause_interval)
            return True
        return False

    def _boss_leave_reset_pause(self, pause_interval: Timer) -> None:
        self.interval_reset(MAINTENANCE_ANNOUNCE)
        pause_interval.reset()

    def boss_clear(self, *, has_fleet_step: bool = True, is_month: bool = False) -> bool:
        """让各舰队轮流攻击首领。

        成功时进入危险或安全海域；失败时留在当前的深渊或月度首领海域，并返回是否清理成功。
        """
        logger.hr("BOSS clear", level=1)

        fleets = self.parse_fleet_filter()
        for fleet in fleets:
            logger.hr(f"Turn: {fleet}", level=2)
            if not isinstance(fleet, BossFleet):
                self._boss_clear_call_submarine(fleet)
                continue

            self._boss_clear_set_fleet(fleet, fleets)
            if self._boss_clear_skip_low_resolve(fleet, has_fleet_step=has_fleet_step, is_month=is_month):
                continue

            self._boss_clear_ensure_month_boss(is_month=is_month)
            self.boss_goto(location=(0, 0), has_fleet_step=has_fleet_step, is_month=is_month)

            if self._boss_clear_finished():
                return True
            if self._boss_clear_standby(fleet, has_fleet_step=has_fleet_step):
                break

        logger.critical("Unable to clear boss, fleets exhausted")
        return False

    def _boss_clear_call_submarine(self, fleet: BossFleet | str) -> bool:
        if isinstance(fleet, BossFleet):
            return False
        self.os_order_execute(recon_scan=False, submarine_call=True)
        return True

    def _boss_clear_set_fleet(self, fleet: BossFleet, fleets: Sequence[BossFleet | str]) -> None:
        if self.fleet_set(fleet.fleet_index):
            return

        # 当前舰队无法切换时，先切到其他舰队再切回来以重新聚焦镜头。
        others = [item for item in fleets if isinstance(item, BossFleet) and item != fleet]
        if others:
            other: BossFleet = others[0]
            self.fleet_set(other.fleet_index)
            self.fleet_set(fleet.fleet_index)
            return
        logger.warning(f"No other fleets from {fleets}, skip refocus")

    def _boss_clear_skip_low_resolve(
        self,
        fleet: BossFleet,
        *,
        has_fleet_step: bool,
        is_month: bool,
    ) -> bool:
        self.handle_os_map_fleet_lock(enable=False)
        if not self.fleet_low_resolve_appear():
            return False
        logger.warning("Skip using current fleet because of the low resolve debuff")
        self.boss_goto(location=fleet.standby_loca, has_fleet_step=has_fleet_step, is_month=is_month)
        return True

    def _boss_clear_ensure_month_boss(self, *, is_month: bool) -> None:
        if not is_month:
            return
        while not self.radar.select(is_enemy=True):
            self.relative_goto(has_fleet_step=True, is_question=True, relative_position=(1, -6), index=0)
            try:
                self.relative_goto(has_fleet_step=True, is_question=True, index=1)
            except IndexError:
                self.relative_goto(has_fleet_step=True, is_question=True, relative_position=(1, -7), index=0)

    def _boss_clear_finished(self) -> bool:
        self.predict_radar()
        if self.radar.select(is_question=True):
            logger.info("BOSS clear")
            self.map_exit()
            return True
        return False

    def _boss_clear_standby(self, fleet: BossFleet, *, has_fleet_step: bool) -> bool:
        self.boss_leave()
        if fleet.standby_loca == (0, 0):
            return True
        self.boss_goto(location=fleet.standby_loca, has_fleet_step=has_fleet_step)
        return False

    def run_abyssal(self) -> bool:
        """处理双重确认并攻击深渊首领；成功后进入危险或安全海域，失败时仍在深渊海域。"""
        self.handle_os_map_fleet_lock(enable=False)

        def is_at_front(grid: RadarGrid) -> bool:
            # 首领通常位于雷达坐标 (0, -2)。
            x, y = grid.location
            return (abs(x) <= abs(y)) and (y < 0)

        while 1:
            self.device.screenshot()
            self.question_goto(has_fleet_step=True)

            if self.radar.select(is_enemy=True).filter(is_at_front):
                logger.info("Found boss at front")
                break
            logger.info("No boss at front, retry question_goto")
            continue

        return self.boss_clear(has_fleet_step=True)

    def get_stronghold_percentage(self) -> str:
        """返回要塞清理进度字符串，通常为 100、80、60、40、20 或 0。"""
        ocr = PercentageOcr(STRONGHOLD_PERCENTAGE, letter=(255, 255, 255), threshold=128, name="STRONGHOLD_PERCENTAGE")
        result = ocr.ocr_single(self.device.image)
        result = result.rstrip("7Kk")
        for starter in ["100", "80", "60", "40", "20", "0"]:
            if result.startswith(starter):
                result = starter
                logger.attr("STRONGHOLD_PERCENTAGE", result)
                return result

        logger.warning(f"Unexpected STRONGHOLD_PERCENTAGE: {result}")
        return result

    def get_second_fleet(self) -> int:
        """返回用于解锁双舰队机关的第二舰队编号。"""
        current = self.fleet_selector.get()
        second = 2 if current == 1 else 1
        logger.attr("Second_fleet", second)
        return second

    @staticmethod
    def fleet_walk_limit(outside: Point, step: int = 3) -> GridLocation:
        vector = np.asarray(outside, dtype=float)
        if np.linalg.norm(vector) <= 3:
            values = tuple(vector)
            return int(values[0]), int(values[1])
        if step == 1:
            grids = np.array(
                [
                    (0, -1),
                    (0, 1),
                    (-1, 0),
                    (1, 0),
                ]
            )
        else:
            grids = np.array(
                [
                    (0, -3),
                    (0, 3),
                    (-3, 0),
                    (3, 0),
                    (2, -2),
                    (2, 2),
                    (-2, 2),
                    (2, 2),
                ]
            )
        degree = np.sum(grids * vector, axis=1) / np.linalg.norm(grids, axis=1) / np.linalg.norm(vector)
        location = grids[np.argmax(degree)]
        return int(location[0]), int(location[1])

    _nearest_object_click_timer = Timer(2)

    def click_nearest_object(self) -> bool:
        if not self._nearest_object_click_timer.reached():
            return False
        if not self.appear(MAP_GOTO_GLOBE, offset=(200, 20)):
            return False
        if self.appear(PORT_ENTER, offset=(20, 20)):
            return False

        self.update_os()
        self.view.predict()
        self.radar.predict(self.device.image)
        self.radar.show()
        nearest = self.radar.nearest_object()
        if nearest is None:
            self._nearest_object_click_timer.reset()
            return False

        step = 1 if self.appear(FLEET_EMP_DEBUFF, offset=(50, 20)) else 3
        nearest = self.fleet_walk_limit(nearest.location, step=step)
        try:
            nearest = self.convert_radar_to_local(nearest)
        except KeyError:
            logger.info("Radar grid not on local map")
            self._nearest_object_click_timer.reset()
            return False
        self.device.click(nearest)
        self._nearest_object_click_timer.reset()
        return True
