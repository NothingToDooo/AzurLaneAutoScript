import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

import numpy as np

from module.base.failure import cleanup_scope
from module.base.timer import Timer
from module.base.utils import location2node
from module.exception import MapEnemyMoved, MapWalkError
from module.logger import logger
from module.map.fleet_turn import FleetTurnEvent
from module.map.map_grids import SelectedGrids
from module.map.map_scanner import MovableEnemySnapshot
from module.map.utils import location_ensure

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.map.fleet_turn import FleetTurnController
    from module.map.map_base import CampaignMap
    from module.map.type_alias import FleetLocation, GridLocation
    from module.map_detection.grid import Grid
    from module.map_detection.grid_info import GridInfo

WALK_OUT_OF_STEP_MESSAGE = "walk_out_of_step"


class NavigationTimer(Protocol):
    def start(self) -> NavigationTimer: ...

    def started(self) -> bool: ...

    def reached(self) -> bool: ...

    def reset(self) -> NavigationTimer: ...


@dataclass(frozen=True, slots=True)
class NavigationCombatOutcome:
    grid: Grid
    battle_count: int
    arrived: bool
    needs_retry: bool = False


class FleetSwitchUi(Protocol):
    def navigation_screenshot(self) -> None: ...

    def navigation_handle_switch_interruption(self) -> bool: ...

    def navigation_detect_shown_fleet(self) -> int: ...

    def navigation_click_switch(self) -> bool: ...

    def navigation_sleep_after_switch(self) -> None: ...

    def navigation_focus_after_activation(self, location: GridLocation) -> None: ...

    def navigation_refresh_after_activation(self, shown_index: int) -> None: ...


class FleetMovementUi(Protocol):
    def navigation_withdraw_if_needed(self) -> None: ...

    def navigation_click_target(self, location: GridLocation, sight: tuple[int, int, int, int]) -> Grid: ...

    def navigation_refresh_target(self, grid: Grid, *, portal: bool) -> Grid: ...

    def navigation_handle_fleet_lock(self, walk_timeout: NavigationTimer) -> None: ...

    def navigation_handle_combat(
        self,
        expected: str,
        location: GridLocation,
    ) -> NavigationCombatOutcome | None: ...

    def navigation_handle_ambush(self, grid: Grid) -> bool: ...

    def navigation_handle_mystery(self, grid: Grid) -> str | None: ...

    def navigation_handle_cat_attack(self) -> bool: ...

    def navigation_handle_guild_popup(self) -> bool: ...

    def navigation_handle_walk_out_of_step(self) -> bool: ...

    def navigation_handle_story(self, expected: str) -> bool: ...

    def navigation_is_in_map(self) -> bool: ...

    def navigation_recover_walk(self, *, skip_first_update: bool) -> None: ...

    def navigation_click_grid(self, grid: Grid) -> None: ...

    def navigation_predict(self) -> None: ...

    def navigation_handle_carrier_spawn(self) -> None: ...

    def navigation_scan_movable(self, snapshot: MovableEnemySnapshot, *, enemy_cleared: bool) -> None: ...

    def navigation_after_arrival(self, location: GridLocation) -> None: ...

    def navigation_set_camera(self, location: GridLocation) -> None: ...


class SubmarineMovementUi(Protocol):
    def navigation_click_submarine_target(
        self,
        location: GridLocation,
        sight: tuple[int, int, int, int],
    ) -> Grid: ...

    def navigation_refresh_submarine_target(self, grid: Grid) -> None: ...

    def navigation_submarine_open(self) -> None: ...

    def navigation_submarine_confirm(self) -> None: ...

    def navigation_submarine_cancel(self) -> None: ...

    def navigation_submarine_finish(self) -> None: ...


@dataclass(frozen=True, slots=True)
class FleetNavigationServices:
    map: CampaignMap
    turn_controller: FleetTurnController
    switch_ui: FleetSwitchUi
    movement_ui: FleetMovementUi
    submarine_ui: SubmarineMovementUi
    timer_factory: Callable[[float, int], NavigationTimer] = Timer


@dataclass(frozen=True, slots=True)
class FleetNavigationRules:
    fleet_2_enabled: bool = False
    boss_fleet_index: Literal[1, 2] = 1
    fleets_reversed: bool = False
    fleet_step_enabled: bool = False
    fleet_1_step: int = 0
    fleet_2_step: int = 0
    portal: bool = False
    maze: bool = False
    ambush: bool = False
    movable_enemy: bool = False
    decoy_enemy: bool = False
    walk_use_current_fleet: bool = False
    submarine_mode: str = ""
    land_based: bool = False
    fortress: bool = False
    call_submarine_at_boss: bool = False
    submarine_distance_to_boss: str = "to_boss_position"
    walk_sight: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class FleetNavigationSnapshot:
    fleet_1: FleetLocation
    fleet_2: FleetLocation
    submarine: FleetLocation
    current_index: Literal[1, 2]
    shown_index: Literal[1, 2]


@dataclass(slots=True)
class _GotoState:
    location: GridLocation
    expected: str
    grid: Grid
    portal_destination: GridLocation | None
    may_submarine_icon: bool
    extra: float
    arrive_timer: NavigationTimer
    arrive_unexpected_timer: NavigationTimer
    ambushed_retry: NavigationTimer
    walk_timeout: NavigationTimer
    movable_snapshot: MovableEnemySnapshot
    result: str = "nothing"
    result_mystery: str = ""
    battle_count: int | None = None
    arrived: bool = False


@dataclass(frozen=True, slots=True)
class _GotoRequest:
    location: GridLocation
    expected: str
    portal_destination: GridLocation | None
    may_submarine_icon: bool
    movable_snapshot: MovableEnemySnapshot


class FleetNavigationController:
    """唯一持有舰队位置和激活状态，并编排地图移动、阻路探测与潜艇导航。"""

    def __init__(
        self,
        rules: FleetNavigationRules,
        services: FleetNavigationServices,
    ) -> None:
        self._rules = rules
        self._map = services.map
        self._turn_controller = services.turn_controller
        self._switch_ui = services.switch_ui
        self._movement_ui = services.movement_ui
        self._submarine_ui = services.submarine_ui
        self._timer_factory = services.timer_factory
        self._fleet_1: FleetLocation = ()
        self._fleet_2: FleetLocation = ()
        self._submarine: FleetLocation = ()
        self._current_index: Literal[1, 2] = 1
        self._shown_index: Literal[1, 2] = 1

    @property
    def snapshot(self) -> FleetNavigationSnapshot:
        return FleetNavigationSnapshot(
            fleet_1=self._fleet_1,
            fleet_2=self._fleet_2,
            submarine=self._submarine,
            current_index=self._current_index,
            shown_index=self._shown_index,
        )

    @property
    def current_index(self) -> Literal[1, 2]:
        return self._current_index

    @property
    def shown_index(self) -> Literal[1, 2]:
        return self._shown_index

    @property
    def current_location(self) -> GridLocation:
        location = self._fleet_2 if self._current_index == 2 else self._fleet_1
        return self._require_location(location)

    @property
    def boss_index(self) -> Literal[1, 2]:
        if self._rules.boss_fleet_index == 2 and self._rules.fleet_2_enabled:
            return 2
        return 1

    @property
    def fleet_step(self) -> int:
        if not self._rules.fleet_step_enabled:
            return 0
        if self._current_index == 2:
            return self._rules.fleet_1_step if self._rules.fleets_reversed else self._rules.fleet_2_step
        return self._rules.fleet_2_step if self._rules.fleets_reversed else self._rules.fleet_1_step

    @staticmethod
    def _require_location(location: FleetLocation | None) -> GridLocation:
        if location is None or len(location) != 2:
            message = "舰队缺少地图位置"
            raise RuntimeError(message)
        return location

    def seed_surface(self, *, fleet_1: FleetLocation, fleet_2: FleetLocation = ()) -> None:
        self._fleet_1 = fleet_1
        self._fleet_2 = fleet_2

    def seed_submarine(self, location: FleetLocation) -> None:
        self._submarine = location

    def record_fleet_2(self, location: GridLocation) -> None:
        self._fleet_2 = location

    def observe_active(self) -> bool:
        """从当前画面同步显示舰队，返回逻辑舰队是否发生变化。"""
        previous = self._current_index
        self._record_shown(self._switch_ui.navigation_detect_shown_fleet())
        return self._current_index != previous

    def activate_boss(self) -> bool:
        return self.activate(self.boss_index)

    def activate(self, index: int) -> bool:
        target = self._fleet_index(index)
        if target == 2 and not self._rules.fleet_2_enabled:
            return False

        logger.info(f"Fleet set to {target}")
        timeout = self._timer_factory(5, 10).start()
        switched = False
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self._switch_ui.navigation_screenshot()

            if timeout.reached():
                logger.warning("Fleet set timeout, assume current fleet is correct")
                break
            ready, clicked = self._activation_frame(target, timeout)
            switched = switched or clicked
            if ready:
                break

        active_location = self._fleet_2 if self._current_index == 2 else self._fleet_1
        if switched and active_location:
            self._switch_ui.navigation_focus_after_activation(self._require_location(active_location))
            self.rebuild_paths()
            self._map.pathfinder.show_cost()
            self.show()
            self._switch_ui.navigation_refresh_after_activation(self._shown_index)
        return switched

    def _activation_frame(self, target: Literal[1, 2], timeout: NavigationTimer) -> tuple[bool, bool]:
        if self._switch_ui.navigation_handle_switch_interruption():
            timeout.reset()
            return False, False
        self._record_shown(self._switch_ui.navigation_detect_shown_fleet())
        logger.info(f"Fleet: {self._shown_index}, fleet_current_index: {self._current_index}")
        if self._current_index == target:
            return True, False
        if not self._switch_ui.navigation_click_switch():
            logger.warning("SWITCH_OVER not found")
            return False, False
        self._switch_ui.navigation_sleep_after_switch()
        timeout.reset()
        return False, True

    def _record_shown(self, shown: int) -> None:
        shown_index = self._fleet_index(shown)
        self._shown_index = shown_index
        if self._rules.fleets_reversed:
            self._current_index = 2 if shown_index == 1 else 1
        else:
            self._current_index = shown_index

    @property
    def _walk_sight(self) -> tuple[int, int, int, int]:
        if self._rules.walk_sight is not None:
            return self._rules.walk_sight
        sight = self._map.layout.camera_sight
        return sight[0], 0, sight[2], sight[3]

    def goto(
        self,
        location: GridInfo | str | GridLocation,
        expected: str = "",
        *,
        step_optimize: bool | None = None,
        turning_optimize: bool | None = None,
    ) -> None:
        location = location_ensure(location)
        step = self._step_optimize(value=step_optimize)
        turning = self._turning_optimize(value=turning_optimize)
        if not step and not turning:
            self._travel_direct(location, expected=expected)
            return

        nodes = self._map.pathfinder.route(location, step=self.fleet_step if step else 0, turning_optimize=turning)
        for node in nodes:
            self._wait_maze(node)
            node_expected = expected if node == nodes[-1] else ""
            try:
                self._travel_direct(node, expected=node_expected)
            except MapWalkError:
                self._retry_after_walk_error(node, expected=node_expected)

    def _step_optimize(self, *, value: bool | None) -> bool:
        if value is not None:
            return value
        return self._rules.portal or self._rules.maze or self._rules.fleet_step_enabled

    def _turning_optimize(self, *, value: bool | None) -> bool:
        return self._rules.ambush if value is None else value

    def _wait_maze(self, node: GridLocation) -> None:
        if not self._turn_controller.maze_active_on(node):
            return
        logger.info(f"Maze is active on {location2node(node)}, bouncing to wait")
        for _ in range(10):
            nearby = self._map[node].maze_nearby
            if nearby is None:
                message = "激活的迷宫格缺少相邻格子"
                raise RuntimeError(message)
            grids = nearby.delete(self._map.layout.select(is_fleet=True))
            non_enemy_grids = grids.select(is_enemy=False)
            if non_enemy_grids:
                grids = non_enemy_grids
            self._travel_direct(grids.sort("cost")[0], expected="")

    def _retry_after_walk_error(self, node: GridLocation, *, expected: str) -> None:
        logger.warning("Map walk error.")
        self._movement_ui.navigation_predict()
        self._movement_ui.navigation_recover_walk(skip_first_update=True)
        for retry_node in self._map.pathfinder.route(node, step=1, turning_optimize=False):
            self._travel_direct(retry_node, expected=expected)

    def _travel_direct(self, location: GridInfo | str | GridLocation, *, expected: str) -> None:
        location = location_ensure(location)
        movable_snapshot = MovableEnemySnapshot.capture(self._map)
        self._movement_ui.navigation_withdraw_if_needed()
        portal_destination = self._map.topology.portal_destination(location)
        covered = self._map.layout.covered_by(self._map[location], offsets=[(0, -1)])
        may_submarine_icon = bool(covered and self._submarine == covered[0].location)
        request = _GotoRequest(location, expected, portal_destination, may_submarine_icon, movable_snapshot)

        while True:
            self.activate(self._current_index)
            grid = self._movement_ui.navigation_click_target(location, self._walk_sight)
            state = self._new_goto_state(request, grid)
            self._wait_arrival(state)
            if not state.arrived:
                continue
            if self._map[state.location].may_ammo:
                self._movement_ui.navigation_click_grid(state.grid)
            break

        self._finish_arrival(state)
        self._movement_ui.navigation_after_arrival(state.location)

    def _new_goto_state(self, request: _GotoRequest, grid: Grid) -> _GotoState:
        extra = 0.0
        if self._rules.submarine_mode in {"hunt_only", "hunt_and_boss"}:
            extra += 4.5
        destination = self._map[request.location]
        if self._rules.land_based and destination.is_mechanism_trigger:
            extra += destination.mechanism_wait
        movement_wait = self._turn_controller.movement_wait
        return _GotoState(
            location=request.location,
            expected=request.expected,
            grid=grid,
            portal_destination=request.portal_destination,
            may_submarine_icon=request.may_submarine_icon,
            extra=extra,
            arrive_timer=self._timer_factory(0.5 + movement_wait + extra, 2),
            arrive_unexpected_timer=self._timer_factory(1.5 + movement_wait + extra, 6),
            ambushed_retry=self._timer_factory(0.5 + movement_wait + extra, 2),
            walk_timeout=self._timer_factory(20, 0).start(),
            movable_snapshot=request.movable_snapshot,
        )

    def _wait_arrival(self, state: _GotoState) -> None:
        while True:
            state.grid = self._movement_ui.navigation_refresh_target(
                state.grid,
                portal=state.portal_destination is not None,
            )
            self._movement_ui.navigation_handle_fleet_lock(state.walk_timeout)
            self._handle_combat(state)
            self._handle_ambush(state)
            self._handle_mystery(state)

            if self._movement_ui.navigation_handle_cat_attack():
                state.arrive_timer.reset()
                state.arrive_unexpected_timer.reset()
                state.walk_timeout.reset()
                continue
            if self._movement_ui.navigation_handle_guild_popup():
                state.walk_timeout.reset()
                continue
            if self._movement_ui.navigation_handle_walk_out_of_step():
                raise MapWalkError(WALK_OUT_OF_STEP_MESSAGE)
            if self._confirm_arrival(state):
                return
            if state.expected == "story" and self._movement_ui.navigation_handle_story(state.expected):
                state.result = "story"
                continue
            if self._retry_needed(state):
                return

    def _handle_combat(self, state: _GotoState) -> None:
        outcome = self._movement_ui.navigation_handle_combat(state.expected, state.location)
        if outcome is None:
            return
        state.grid = outcome.grid
        state.arrived = outcome.arrived
        state.result = "combat"
        state.battle_count = outcome.battle_count
        state.arrive_timer = self._timer_factory(0.5 + state.extra, 2)
        state.arrive_unexpected_timer = self._timer_factory(1.5 + state.extra, 6)
        state.walk_timeout.reset()
        if outcome.needs_retry:
            state.ambushed_retry.start()

    def _handle_ambush(self, state: _GotoState) -> None:
        if not self._movement_ui.navigation_handle_ambush(state.grid):
            return
        state.walk_timeout.reset()
        if not (state.grid.predict_fleet() and state.grid.predict_current_fleet()):
            state.ambushed_retry.start()

    def _handle_mystery(self, state: _GotoState) -> None:
        kind = self._movement_ui.navigation_handle_mystery(state.grid)
        if kind is None:
            return
        state.result = "mystery"
        state.result_mystery = kind

    def _arrival_prediction(self, state: _GotoState) -> tuple[str, bool]:
        if not self._movement_ui.navigation_is_in_map():
            return "", False
        if not state.may_submarine_icon and state.grid.predict_fleet():
            return "(is_fleet)", True
        if state.may_submarine_icon and state.grid.predict_current_fleet():
            return "(may_submarine_icon, is_current_fleet)", True
        if (
            self._rules.walk_use_current_fleet
            and state.expected != "combat_boss"
            and not ("combat" in state.expected and state.grid.may_boss)
            and (state.grid.predict_fleet() or state.grid.predict_current_fleet())
        ):
            return "(MAP_WALK_USE_CURRENT_FLEET, is_current_fleet)", True
        if state.walk_timeout.reached() and state.grid.predict_current_fleet():
            return "(walk_timeout, is_current_fleet)", True
        return "", False

    def _confirm_arrival(self, state: _GotoState) -> bool:
        prediction, arrived = self._arrival_prediction(state)
        if not arrived:
            if state.arrive_timer.started():
                state.arrive_timer.reset()
            if state.arrive_unexpected_timer.started():
                state.arrive_unexpected_timer.reset()
            return False
        if not state.arrive_timer.started():
            logger.info(f"Arrive {location2node(state.location)} {prediction}".strip())
        state.arrive_timer.start()
        state.arrive_unexpected_timer.start()
        if state.result == "nothing" and not state.arrive_timer.reached():
            return False
        if state.expected and state.result not in state.expected and not state.arrive_unexpected_timer.reached():
            return False
        if state.expected and state.result not in state.expected:
            logger.warning("Arrive with unexpected result")
        if state.portal_destination is not None:
            state.location = state.portal_destination
            self._movement_ui.navigation_set_camera(state.location)
        logger.info(
            f"Arrive {location2node(state.location)} confirm. Result: {state.result}. Expected: {state.expected}"
        )
        state.arrived = True
        return True

    def _retry_needed(self, state: _GotoState) -> bool:
        if state.ambushed_retry.started() and state.ambushed_retry.reached():
            return True
        if not state.walk_timeout.reached():
            return False
        logger.warning("Walk timeout. Retrying.")
        self._movement_ui.navigation_predict()
        self._movement_ui.navigation_recover_walk(skip_first_update=False)
        return True

    def _finish_arrival(self, state: _GotoState) -> None:
        self._map[self.current_location].is_fleet = False
        self._map[state.location].wipe_out()
        self._map[state.location].is_fleet = True
        if self._current_index == 2:
            self._fleet_2 = state.location
        else:
            self._fleet_1 = state.location

        if state.result_mystery == "get_carrier":
            self._movement_ui.navigation_handle_carrier_spawn()
        if state.result == "combat":
            if state.battle_count is None:
                message = "combat navigation result is missing battle count"
                raise RuntimeError(message)
            self._turn_controller.battle_resolved(state.battle_count)
            self._movement_ui.navigation_predict()
        turn_event = self._turn_controller.fleet_arrived()
        if turn_event is FleetTurnEvent.ENEMY_MOVED:
            if state.result != "combat":
                self._movement_ui.navigation_predict()
            self._movement_ui.navigation_scan_movable(
                state.movable_snapshot,
                enemy_cleared=state.result == "combat",
            )
            self.rebuild_paths()
            raise MapEnemyMoved
        if turn_event is FleetTurnEvent.MAZE_CHANGED:
            self.rebuild_paths()
            raise MapEnemyMoved
        self.rebuild_paths()
        if self._rules.decoy_enemy and state.result == "nothing" and state.expected == "combat":
            raise MapEnemyMoved

    def rebuild_paths(self) -> None:
        if self._fleet_1:
            self._map[self._fleet_1].is_fleet = True
        if self._fleet_2:
            self._map[self._fleet_2].is_fleet = True
        locations: dict[int, FleetLocation] = {1: self._fleet_1}
        if self._fleet_2:
            locations[2] = self._fleet_2
        if self._rules.fortress and not self._map.layout.select(is_fortress=True):
            self._map.layout.select(is_mechanism_block=True).set(is_mechanism_block=False)
        self._map.pathfinder.project_fleets(
            locations,
            current=self.current_location,
            has_ambush=self._rules.ambush,
        )

    def show(self) -> None:
        fleets = []
        for index, location in ((1, self._fleet_1), (2, self._fleet_2)):
            if not location:
                continue
            text = f"Fleet_{index}: {location2node(location)}"
            fleets.append(f"[{text}]" if self._current_index == index else text)
        logger.info(" ".join(fleets))

    def is_at(self, grid: GridInfo, fleet: int | None = None) -> bool:
        index = self._current_index if fleet is None else self._fleet_index(fleet)
        location = self._fleet_1 if index == 1 else self._fleet_2
        return location == grid.location

    def is_accessible(self, grid: GridInfo, fleet: int | str | None = None) -> bool:
        index = self._normalize_fleet(fleet)
        if index == self._current_index:
            return grid.is_accessible
        backup = self._current_index
        with cleanup_scope(
            lambda: self._restore_projection(backup),
            message="accessibility probe and fleet projection restore both failed",
        ):
            self._current_index = index
            self.rebuild_paths()
            return grid.is_accessible

    def find_roadblocks(self, grid: GridInfo, fleet: int | None = None) -> SelectedGrids[GridInfo]:
        index = self._current_index if fleet is None else self._fleet_index(fleet)
        if index == self._current_index:
            return self._find_current_roadblocks(grid)
        backup = self._current_index
        with cleanup_scope(
            lambda: self._restore_projection(backup),
            message="roadblock probe and fleet projection restore both failed",
        ):
            self._current_index = index
            self.rebuild_paths()
            return self._find_current_roadblocks(grid)

    def _normalize_fleet(self, fleet: int | str | None) -> Literal[1, 2]:
        if fleet is None:
            return self._current_index
        if fleet == "boss":
            return self.boss_index
        if isinstance(fleet, str):
            if fleet.isdigit():
                return self._fleet_index(int(fleet))
            message = f"fleet index must be 1, 2, or boss, got {fleet!r}"
            raise ValueError(message)
        return self._fleet_index(fleet)

    @staticmethod
    def _fleet_index(value: int) -> Literal[1, 2]:
        if value == 1:
            return 1
        if value == 2:
            return 2
        message = f"fleet index must be 1 or 2, got {value}"
        raise ValueError(message)

    def _find_current_roadblocks(self, grid: GridInfo) -> SelectedGrids[GridInfo]:
        if grid.is_accessible:
            return SelectedGrids([])
        enemies = self._map.layout.select(is_enemy=True)
        logger.info(f"Potential enemy roadblocks: {enemies}")
        for repeat in range(1, enemies.count + 1):
            for selection in itertools.combinations(enemies, repeat):
                with cleanup_scope(
                    lambda roadblocks=selection: self._restore_roadblocks(roadblocks),
                    message="roadblock probe and map projection restore both failed",
                ):
                    for block in selection:
                        block.is_enemy = False
                    self.rebuild_paths()
                    accessible = grid.is_accessible
                if accessible:
                    roadblocks = SelectedGrids(list(selection))
                    logger.info(f"Enemy roadblock: {roadblocks}")
                    return roadblocks
        logger.warning("Enemy roadblock try exhausted.")
        return SelectedGrids([])

    def _restore_projection(self, index: Literal[1, 2]) -> None:
        self._current_index = index
        self.rebuild_paths()

    def _restore_roadblocks(self, roadblocks: tuple[GridInfo, ...]) -> None:
        for block in roadblocks:
            block.is_enemy = True
        self.rebuild_paths()

    def move_submarine(self, location: GridInfo | str | GridLocation) -> bool:
        location = location_ensure(location)
        self._submarine_ui.navigation_submarine_open()
        moved = self._move_submarine_direct(location)
        if moved:
            self._submarine_ui.navigation_submarine_confirm()
            self._submarine = location
        else:
            self._submarine_ui.navigation_submarine_cancel()
        self._submarine_ui.navigation_submarine_finish()
        return moved

    def _move_submarine_direct(self, location: GridLocation) -> bool:
        moved = True
        while True:
            grid = self._submarine_ui.navigation_click_submarine_target(location, self._walk_sight)
            arrive_timer = self._timer_factory(0.1, 0)
            walk_timeout = self._timer_factory(2, 6).start()
            while True:
                self._submarine_ui.navigation_refresh_submarine_target(grid)
                arrived = grid.predict_submarine_move()
                if grid.predict_submarine() or (walk_timeout.reached() and grid.predict_fleet()):
                    arrived = True
                    moved = False
                if arrived:
                    if not arrive_timer.started():
                        logger.info(f"Arrive {location2node(location)}")
                    arrive_timer.start()
                    if not arrive_timer.reached():
                        continue
                    logger.info(f"Submarine arrive {location2node(location)} confirm.")
                    return moved
                if walk_timeout.reached():
                    logger.warning("Walk timeout. Retrying.")
                    self._movement_ui.navigation_predict()
                    self._movement_ui.navigation_recover_walk(skip_first_update=False)
                    break

    def move_submarine_near(self, boss: GridInfo | str | GridLocation) -> bool:
        if not (self._rules.call_submarine_at_boss and self._map.layout.select(is_submarine_spawn_point=True)):
            return False
        if self._rules.submarine_distance_to_boss == "use_open_ocean_support":
            logger.info("Going to use Open Ocean Support, skip moving submarines")
            return False

        boss_location = location_ensure(boss)
        logger.info(f"Move submarine near {location2node(boss_location)}")
        submarine = self._require_location(self._submarine)
        self._map.pathfinder.project(submarine, has_ambush=False, has_enemy=False)
        self._map.pathfinder.show_cost()
        distances = {"to_boss_position": 0, "1_grid_to_boss": 1, "2_grid_to_boss": 2}
        distance = distances.get(self._rules.submarine_distance_to_boss, 0)
        logger.attr("Distance to boss", distance)
        if np.sum(np.abs(np.subtract(submarine, boss_location))) <= distance:
            logger.info("Boss is already in hunting zone")
            self.rebuild_paths()
            return False
        near = self._nearest_submarine_target(boss_location, distance)
        self.rebuild_paths()
        logger.info(f"Move submarine to {location2node(near)}")
        return self.move_submarine(near)

    def _nearest_submarine_target(self, boss: GridLocation, distance: int) -> GridLocation:
        candidates = self._map.layout.select(is_land=False).filter(
            lambda grid: (
                sum(abs(coordinate - target) for coordinate, target in zip(location_ensure(grid), boss, strict=True))
                <= distance
            )
        )
        if candidates:
            return location_ensure(candidates.sort("cost")[0])
        if distance > 0:
            logger.info(f"Unable to find a grid near boss in distance {distance}, fallback to {distance - 1}")
            return self._nearest_submarine_target(boss, distance - 1)
        logger.warning(f"Unable to find a grid near boss in distance {distance}, return boss position")
        return boss
