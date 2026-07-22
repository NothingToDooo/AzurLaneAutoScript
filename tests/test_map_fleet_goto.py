from typing import TYPE_CHECKING, cast

import pytest

from module.exception import MapEnemyMoved
from module.map.fleet_navigation import (
    FleetNavigationController,
    FleetNavigationRules,
    FleetNavigationServices,
    NavigationCombatOutcome,
)
from module.map.fleet_turn import FleetTurnEvent
from module.map.map_base import CampaignMap
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from module.map.fleet_navigation import NavigationTimer
    from module.map.fleet_turn import FleetTurnController
    from module.map.map_pathfinder import CampaignPathfinder
    from module.map.map_scanner import MovableEnemySnapshot
    from module.map.type_alias import FleetLocation, GridLocation
    from module.map_detection.grid import Grid


class _ImmediateTimer:
    def __init__(self, limit: float, _count: int = 0) -> None:
        self._limit = limit
        self._started = False

    def start(self) -> _ImmediateTimer:
        self._started = True
        return self

    def started(self) -> bool:
        return self._started

    def reached(self) -> bool:
        return self._limit < 5

    def reset(self) -> _ImmediateTimer:
        self._started = True
        return self


class _VisualGrid:
    may_boss = False

    @staticmethod
    def predict_fleet() -> bool:
        return True

    @staticmethod
    def predict_current_fleet() -> bool:
        return True


class _NavigationState:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.travels: list[tuple[GridLocation, str]] = []
        self.current_target: GridLocation | None = None
        self.walk_error_targets: set[GridLocation] = set()
        self.combat_targets: set[GridLocation] = set()
        self.predict_error: BaseException | None = None
        self.grid = _VisualGrid()


class _SwitchUi:
    @staticmethod
    def navigation_screenshot() -> None:
        pass

    @staticmethod
    def navigation_handle_switch_interruption() -> bool:
        return False

    @staticmethod
    def navigation_detect_shown_fleet() -> int:
        return 1

    @staticmethod
    def navigation_click_switch() -> bool:
        return False

    @staticmethod
    def navigation_sleep_after_switch() -> None:
        pass

    @staticmethod
    def navigation_focus_after_activation(location: GridLocation) -> None:
        del location

    @staticmethod
    def navigation_refresh_after_activation(shown_index: int) -> None:
        del shown_index


class _MovementUi:
    def __init__(self, state: _NavigationState) -> None:
        self._state = state

    @staticmethod
    def navigation_withdraw_if_needed() -> None:
        pass

    def navigation_click_target(self, location: GridLocation, sight: tuple[int, int, int, int]) -> Grid:
        del sight
        self._state.current_target = location
        return cast("Grid", self._state.grid)

    @staticmethod
    def navigation_refresh_target(grid: Grid, *, portal: bool) -> Grid:
        del portal
        return grid

    @staticmethod
    def navigation_handle_fleet_lock(walk_timeout: NavigationTimer) -> None:
        del walk_timeout

    def navigation_handle_combat(
        self,
        expected: str,
        location: GridLocation,
    ) -> NavigationCombatOutcome | None:
        self._state.travels.append((location, expected))
        if location not in self._state.combat_targets:
            return None
        self._state.combat_targets.remove(location)
        return NavigationCombatOutcome(
            grid=cast("Grid", self._state.grid),
            battle_count=1,
            arrived=True,
            needs_retry=False,
        )

    @staticmethod
    def navigation_handle_ambush(grid: Grid) -> bool:
        del grid
        return False

    @staticmethod
    def navigation_handle_mystery(grid: Grid) -> str | None:
        del grid
        return None

    @staticmethod
    def navigation_handle_cat_attack() -> bool:
        return False

    @staticmethod
    def navigation_handle_guild_popup() -> bool:
        return False

    def navigation_handle_walk_out_of_step(self) -> bool:
        target = self._state.current_target
        if target not in self._state.walk_error_targets:
            return False
        self._state.walk_error_targets.remove(target)
        return True

    @staticmethod
    def navigation_handle_story(expected: str) -> bool:
        del expected
        return False

    @staticmethod
    def navigation_is_in_map() -> bool:
        return True

    def navigation_recover_walk(self, *, skip_first_update: bool) -> None:
        self._state.events.append(("recover_walk", skip_first_update))

    @staticmethod
    def navigation_click_grid(grid: Grid) -> None:
        del grid

    def navigation_predict(self) -> None:
        self._state.events.append(("predict",))
        if self._state.predict_error is not None:
            raise self._state.predict_error

    def navigation_handle_carrier_spawn(self) -> None:
        self._state.events.append(("carrier_spawn",))

    def navigation_scan_movable(self, snapshot: MovableEnemySnapshot, *, enemy_cleared: bool) -> None:
        del snapshot
        self._state.events.append(("scan_movable", enemy_cleared))

    @staticmethod
    def navigation_after_arrival(location: GridLocation) -> None:
        del location

    @staticmethod
    def navigation_set_camera(location: GridLocation) -> None:
        del location


class _SubmarineUi:
    @staticmethod
    def navigation_click_submarine_target(
        location: GridLocation,
        sight: tuple[int, int, int, int],
    ) -> Grid:
        del location, sight
        return cast("Grid", _VisualGrid())

    @staticmethod
    def navigation_refresh_submarine_target(grid: Grid) -> None:
        del grid

    @staticmethod
    def navigation_submarine_open() -> None:
        pass

    @staticmethod
    def navigation_submarine_confirm() -> None:
        pass

    @staticmethod
    def navigation_submarine_cancel() -> None:
        pass

    @staticmethod
    def navigation_submarine_finish() -> None:
        pass


class _TurnController:
    movement_wait = 0.0

    def __init__(self, state: _NavigationState) -> None:
        self._state = state
        self.event = FleetTurnEvent.STABLE
        self.maze_nodes: set[GridLocation] = set()

    def battle_resolved(self, battle_count: int) -> None:
        self._state.events.append(("battle_resolved", battle_count))

    def fleet_arrived(self) -> FleetTurnEvent:
        self._state.events.append(("fleet_arrived",))
        return self.event

    def maze_active_on(self, location: GridLocation) -> bool:
        return location in self.maze_nodes


class _Pathfinder:
    def __init__(self, state: _NavigationState) -> None:
        self._state = state
        self.path_results: dict[tuple[GridLocation, int, bool], list[GridLocation]] = {}
        self.route_calls: list[tuple[GridLocation, int, bool]] = []

    def route(self, location: GridLocation, *, step: int, turning_optimize: bool) -> list[GridLocation]:
        call = (location, step, turning_optimize)
        self.route_calls.append(call)
        return self.path_results[call]

    def project_fleets(
        self,
        locations: Mapping[int, FleetLocation],
        current: GridLocation,
        *,
        has_ambush: bool,
    ) -> None:
        del locations, current, has_ambush
        self._state.events.append(("rebuild_paths",))

    @staticmethod
    def show_cost() -> None:
        pass


class _NavigationHarness:
    def __init__(self, rules: FleetNavigationRules | None = None) -> None:
        self.state = _NavigationState()
        self.turns = _TurnController(self.state)
        self.map = CampaignMap("fleet-goto-test")
        self.map.layout.initialize("G7")
        self.map.topology.rebuild()
        self.pathfinder = _Pathfinder(self.state)
        self.map.pathfinder = cast("CampaignPathfinder", self.pathfinder)
        self.navigation = FleetNavigationController(
            FleetNavigationRules() if rules is None else rules,
            FleetNavigationServices(
                map=self.map,
                turn_controller=cast("FleetTurnController", self.turns),
                switch_ui=_SwitchUi(),
                movement_ui=_MovementUi(self.state),
                submarine_ui=_SubmarineUi(),
                timer_factory=cast("Callable[[float, int], NavigationTimer]", _ImmediateTimer),
            ),
        )
        self.navigation.seed_surface(fleet_1=(0, 0))
        self.map[(0, 0)].is_fleet = True


def test_goto_walks_directly_without_optimizations() -> None:
    harness = _NavigationHarness()

    harness.navigation.goto((1, 2), expected="combat", step_optimize=False, turning_optimize=False)

    assert harness.state.travels == [((1, 2), "combat")]
    assert harness.pathfinder.route_calls == []


def test_goto_uses_fleet_step_when_portal_forces_step_optimization() -> None:
    harness = _NavigationHarness(
        FleetNavigationRules(
            portal=True,
            fleet_step_enabled=True,
            fleet_1_step=3,
            fleet_2_step=3,
        )
    )
    node = (2, 2)
    harness.pathfinder.path_results[((2, 3), 3, False)] = [node]

    harness.navigation.goto((2, 3), expected="combat")

    assert harness.pathfinder.route_calls == [((2, 3), 3, False)]
    assert harness.state.travels == [(node, "combat")]


def test_goto_passes_expected_only_to_final_path_node() -> None:
    harness = _NavigationHarness(FleetNavigationRules(ambush=True))
    first = (3, 3)
    final = (3, 4)
    harness.pathfinder.path_results[((3, 4), 0, True)] = [first, final]

    harness.navigation.goto((3, 4), expected="combat")

    assert harness.state.travels == [(first, ""), (final, "combat")]


def test_goto_waits_on_active_maze_before_walking_node() -> None:
    harness = _NavigationHarness(
        FleetNavigationRules(
            maze=True,
            fleet_step_enabled=True,
            fleet_1_step=3,
            fleet_2_step=3,
        )
    )
    maze = (1, 1)
    nearby = SelectedGrids([harness.map[(0, 1)], harness.map[(0, 2)]])
    harness.map[maze].maze_nearby = nearby
    harness.turns.maze_nodes = {maze}
    harness.pathfinder.path_results[((4, 5), 3, False)] = [maze]

    harness.navigation.goto((4, 5))

    assert len(harness.state.travels) == 11
    assert all(expected == "" for _location, expected in harness.state.travels)
    assert [location for location, _expected in harness.state.travels[:10]] == [(0, 1), (0, 2)] * 5
    assert harness.state.travels[-1] == (maze, "")


def test_goto_keeps_battle_prediction_before_turn_advance() -> None:
    harness = _NavigationHarness(FleetNavigationRules(movable_enemy=True))
    destination = (1, 0)
    prediction_error = RuntimeError("prediction failed")
    harness.state.combat_targets = {destination}
    harness.state.predict_error = prediction_error

    with pytest.raises(RuntimeError) as raised:
        harness.navigation.goto(destination, expected="combat", step_optimize=False, turning_optimize=False)

    assert raised.value is prediction_error
    assert harness.state.events == [("battle_resolved", 1), ("predict",)]


def test_goto_handles_enemy_turn_after_battle_prediction() -> None:
    harness = _NavigationHarness(FleetNavigationRules(movable_enemy=True))
    destination = (1, 0)
    harness.state.combat_targets = {destination}
    harness.turns.event = FleetTurnEvent.ENEMY_MOVED

    with pytest.raises(MapEnemyMoved):
        harness.navigation.goto(destination, expected="combat", step_optimize=False, turning_optimize=False)

    assert harness.state.events == [
        ("battle_resolved", 1),
        ("predict",),
        ("fleet_arrived",),
        ("scan_movable", True),
        ("rebuild_paths",),
    ]


def test_goto_retries_from_failed_node_after_walk_error() -> None:
    harness = _NavigationHarness(FleetNavigationRules(ambush=True))
    final = (5, 6)
    retry_a = (5, 5)
    retry_b = (4, 5)
    harness.state.walk_error_targets = {final}
    harness.pathfinder.path_results[((5, 6), 0, True)] = [final]
    harness.pathfinder.path_results[(final, 1, False)] = [retry_a, retry_b]

    harness.navigation.goto(final, expected="combat")

    assert harness.state.travels == [
        (final, "combat"),
        (retry_a, "combat"),
        (retry_b, "combat"),
    ]
    assert harness.state.events[:2] == [("predict",), ("recover_walk", True)]
