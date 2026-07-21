from typing import TYPE_CHECKING, cast

from module.map.fleet_navigation import (
    FleetNavigationController,
    FleetNavigationRules,
    FleetNavigationServices,
    NavigationCombatOutcome,
)
from module.map.fleet_turn import FleetTurnController, FleetTurnEvent, FleetTurnRules
from module.map.map_base import CampaignMap

if TYPE_CHECKING:
    from module.map.type_alias import GridLocation
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
    mechanism_wait = 0.0

    def __init__(self) -> None:
        self.fleet = True
        self.current_fleet = True
        self.submarine_move = False
        self.submarine = False

    def predict_fleet(self) -> bool:
        return self.fleet

    def predict_current_fleet(self) -> bool:
        return self.current_fleet

    def predict_submarine_move(self) -> bool:
        return self.submarine_move

    def predict_submarine(self) -> bool:
        return self.submarine


class _HostState:
    def __init__(self, shown: list[int] | None = None) -> None:
        self.events: list[object] = []
        self.shown = [1] if shown is None else shown
        self.current_shown = self.shown[-1]
        self.grid = _VisualGrid()
        self.current_target: GridLocation | None = None
        self.walk_error_targets: set[GridLocation] = set()
        self.combat_outcome: NavigationCombatOutcome | None = None
        self.predict_error: BaseException | None = None
        self.submarine_clicks = 0
        self.submarine_success_after_clicks: int | None = None


class _SwitchUi:
    def __init__(self, state: _HostState) -> None:
        self._state = state

    def navigation_screenshot(self) -> None:
        self._state.events.append("screenshot")

    def navigation_handle_switch_interruption(self) -> bool:
        _ = self._state
        return False

    def navigation_detect_shown_fleet(self) -> int:
        if self._state.shown:
            self._state.current_shown = self._state.shown.pop(0)
        shown = self._state.current_shown
        self._state.events.append(("detect", shown))
        return shown

    def navigation_click_switch(self) -> bool:
        self._state.events.append("switch")
        return True

    def navigation_sleep_after_switch(self) -> None:
        self._state.events.append("sleep")

    def navigation_focus_after_activation(self, location: GridLocation) -> None:
        self._state.events.append(("focused", location))

    def navigation_refresh_after_activation(self, shown_index: int) -> None:
        self._state.events.append(("activated", shown_index))


class _MovementUi:
    def __init__(self, state: _HostState) -> None:
        self._state = state

    def navigation_withdraw_if_needed(self) -> None:
        pass

    def navigation_click_target(self, location: GridLocation, sight: tuple[int, int, int, int]) -> Grid:
        self._state.current_target = location
        self._state.events.append(("click", location, sight))
        return cast("Grid", self._state.grid)

    def navigation_refresh_target(self, grid: Grid, *, portal: bool) -> Grid:
        self._state.events.append(("refresh", portal))
        return grid

    def navigation_handle_fleet_lock(self, walk_timeout: object) -> None:
        del walk_timeout
        _ = self._state

    def navigation_handle_combat(
        self,
        expected: str,
        location: GridLocation,
    ) -> NavigationCombatOutcome | None:
        del expected, location
        outcome = self._state.combat_outcome
        self._state.combat_outcome = None
        return outcome

    def navigation_handle_ambush(self, grid: Grid) -> bool:
        del grid
        _ = self._state
        return False

    def navigation_handle_mystery(self, grid: Grid) -> str | None:
        del grid
        _ = self._state
        return None

    def navigation_handle_cat_attack(self) -> bool:
        _ = self._state
        return False

    def navigation_handle_guild_popup(self) -> bool:
        _ = self._state
        return False

    def navigation_handle_walk_out_of_step(self) -> bool:
        target = self._state.current_target
        if target not in self._state.walk_error_targets:
            return False
        self._state.walk_error_targets.remove(target)
        return True

    def navigation_handle_story(self, expected: str) -> bool:
        del expected
        _ = self._state
        return False

    def navigation_is_in_map(self) -> bool:
        _ = self._state
        return True

    def navigation_recover_walk(self, *, skip_first_update: bool) -> None:
        self._state.events.append(("recover", skip_first_update))

    def navigation_click_grid(self, grid: Grid) -> None:
        del grid
        self._state.events.append("click_again")

    def navigation_predict(self) -> None:
        self._state.events.append("predict")
        if self._state.predict_error is not None:
            raise self._state.predict_error

    def navigation_handle_carrier_spawn(self) -> None:
        self._state.events.append("carrier")

    def navigation_scan_movable(self, snapshot: object, *, enemy_cleared: bool) -> None:
        del snapshot, enemy_cleared
        self._state.events.append("scan_movable")

    def navigation_after_arrival(self, location: GridLocation) -> None:
        self._state.events.append(("arrived", location))

    def navigation_set_camera(self, location: GridLocation) -> None:
        self._state.events.append(("camera", location))


class _SubmarineUi:
    def __init__(self, state: _HostState) -> None:
        self._state = state

    def navigation_click_submarine_target(
        self,
        location: GridLocation,
        sight: tuple[int, int, int, int],
    ) -> Grid:
        self._state.submarine_clicks += 1
        threshold = self._state.submarine_success_after_clicks
        self._state.grid.submarine_move = threshold is not None and self._state.submarine_clicks >= threshold
        self._state.events.append(("submarine_click", location, sight))
        return cast("Grid", self._state.grid)

    def navigation_refresh_submarine_target(self, grid: Grid) -> None:
        del grid
        self._state.events.append("submarine_refresh")

    def navigation_submarine_open(self) -> None:
        self._state.events.append("submarine_open")

    def navigation_submarine_confirm(self) -> None:
        self._state.events.append("submarine_confirm")

    def navigation_submarine_cancel(self) -> None:
        self._state.events.append("submarine_cancel")

    def navigation_submarine_finish(self) -> None:
        self._state.events.append("submarine_finish")


class _NavigationHost:
    def __init__(self, shown: list[int] | None = None) -> None:
        self._state = _HostState(shown)
        self.switch = _SwitchUi(self._state)
        self.movement = _MovementUi(self._state)
        self.submarine = _SubmarineUi(self._state)

    @property
    def events(self) -> list[object]:
        return self._state.events

    @property
    def state(self) -> _HostState:
        return self._state


class _TurnController:
    movement_wait = 0.0

    def __init__(self, events: list[object], event: FleetTurnEvent = FleetTurnEvent.STABLE) -> None:
        self._events = events
        self._event = event
        self.maze_nodes: set[GridLocation] = set()

    def battle_resolved(self, battle_count: int) -> None:
        self._events.append(("battle_resolved", battle_count))

    def fleet_arrived(self) -> FleetTurnEvent:
        self._events.append("fleet_arrived")
        return self._event

    def maze_active_on(self, location: GridLocation) -> bool:
        return location in self.maze_nodes


def _map(shape: str = "B1") -> CampaignMap:
    map_ = CampaignMap("navigation-test")
    map_.layout.initialize(shape)
    map_.topology.rebuild()
    return map_


def _controller(
    map_: CampaignMap,
    host: _NavigationHost,
    rules: FleetNavigationRules | None = None,
    turn: FleetTurnController | None = None,
) -> FleetNavigationController:
    turn = FleetTurnController(FleetTurnRules(), map_) if turn is None else turn
    return FleetNavigationController(
        FleetNavigationRules() if rules is None else rules,
        FleetNavigationServices(
            map=map_,
            turn_controller=turn,
            switch_ui=host.switch,
            movement_ui=host.movement,
            submarine_ui=host.submarine,
            timer_factory=_ImmediateTimer,
        ),
    )


def test_activation_commits_logical_state_only_after_ui_reports_the_target() -> None:
    map_ = _map()
    host = _NavigationHost(shown=[1, 2])
    navigation = _controller(map_, host, FleetNavigationRules(fleet_2_enabled=True))
    navigation.seed_surface(fleet_1=(0, 0), fleet_2=(1, 0))

    changed = navigation.activate(2)

    assert changed is True
    assert navigation.current_index == 2
    assert navigation.shown_index == 2
    assert host.events == [
        ("detect", 1),
        "switch",
        "sleep",
        "screenshot",
        ("detect", 2),
        ("focused", (1, 0)),
        ("activated", 2),
    ]


def test_reversed_fleet_mapping_uses_shown_fleet_one_as_logical_fleet_two() -> None:
    map_ = _map()
    host = _NavigationHost(shown=[1])
    navigation = _controller(
        map_,
        host,
        FleetNavigationRules(fleet_2_enabled=True, fleets_reversed=True),
    )
    navigation.seed_surface(fleet_1=(0, 0), fleet_2=(1, 0))

    changed = navigation.activate(2)

    assert changed is False
    assert navigation.current_index == 2
    assert navigation.shown_index == 1
    assert host.events == [("detect", 1)]


def test_observe_active_commits_a_passive_auto_search_switch() -> None:
    map_ = _map()
    host = _NavigationHost(shown=[2])
    navigation = _controller(map_, host, FleetNavigationRules(fleet_2_enabled=True))
    navigation.seed_surface(fleet_1=(0, 0), fleet_2=(1, 0))

    changed = navigation.observe_active()

    assert changed is True
    assert navigation.current_index == 2
    assert navigation.shown_index == 2
    assert host.events == [("detect", 2)]


def test_activation_before_fleet_location_scan_does_not_run_location_effects() -> None:
    map_ = _map()
    host = _NavigationHost(shown=[2, 1])
    navigation = _controller(map_, host, FleetNavigationRules(fleet_2_enabled=True))

    changed = navigation.activate(1)

    assert changed is True
    assert navigation.current_index == 1
    assert host.events == [
        ("detect", 2),
        "switch",
        "sleep",
        "screenshot",
        ("detect", 1),
    ]


def test_goto_commits_position_and_map_occupancy_after_visual_arrival() -> None:
    map_ = _map()
    map_[(0, 0)].is_fleet = True
    host = _NavigationHost(shown=[1])
    navigation = _controller(map_, host)
    navigation.seed_surface(fleet_1=(0, 0))

    navigation.goto((1, 0), step_optimize=False, turning_optimize=False)

    assert navigation.current_location == (1, 0)
    assert map_[(0, 0)].is_fleet is False
    assert map_[(1, 0)].is_fleet is True
    assert host.events == [
        ("detect", 1),
        ("click", (1, 0), (-3, 0, 3, 2)),
        ("refresh", False),
        ("arrived", (1, 0)),
    ]


def test_portal_arrival_commits_the_exit_and_updates_camera() -> None:
    map_ = _map("C1")
    map_.topology.configure(portals=(((1, 0), (2, 0)),))
    map_.topology.rebuild(portal=True)
    map_[(0, 0)].is_fleet = True
    host = _NavigationHost(shown=[1])
    navigation = _controller(map_, host)
    navigation.seed_surface(fleet_1=(0, 0))

    navigation.goto((1, 0), step_optimize=False, turning_optimize=False)

    assert navigation.current_location == (2, 0)
    assert map_[(0, 0)].is_fleet is False
    assert map_[(1, 0)].is_fleet is False
    assert map_[(2, 0)].is_fleet is True
    assert host.events == [
        ("detect", 1),
        ("click", (1, 0), (-3, 0, 3, 2)),
        ("refresh", True),
        ("camera", (2, 0)),
        ("arrived", (2, 0)),
    ]


def test_submarine_move_confirms_and_commits_the_new_location() -> None:
    map_ = _map()
    host = _NavigationHost()
    host.state.grid.fleet = False
    host.state.submarine_success_after_clicks = 1
    navigation = _controller(map_, host)
    navigation.seed_surface(fleet_1=(0, 0))
    navigation.seed_submarine((0, 0))

    moved = navigation.move_submarine((1, 0))

    assert moved is True
    assert navigation.snapshot.submarine == (1, 0)
    assert host.events == [
        "submarine_open",
        ("submarine_click", (1, 0), (-3, 0, 3, 2)),
        "submarine_refresh",
        "submarine_confirm",
        "submarine_finish",
    ]


def test_submarine_already_at_target_cancels_without_changing_location() -> None:
    map_ = _map()
    host = _NavigationHost()
    host.state.grid.submarine = True
    navigation = _controller(map_, host)
    navigation.seed_surface(fleet_1=(0, 0))
    navigation.seed_submarine((1, 0))

    moved = navigation.move_submarine((1, 0))

    assert moved is False
    assert navigation.snapshot.submarine == (1, 0)
    assert host.events[-2:] == ["submarine_cancel", "submarine_finish"]


def test_submarine_timeout_recovers_then_retries_the_target() -> None:
    map_ = _map()
    host = _NavigationHost()
    host.state.grid.fleet = False
    host.state.submarine_success_after_clicks = 2
    navigation = _controller(map_, host)
    navigation.seed_surface(fleet_1=(0, 0))
    navigation.seed_submarine((0, 0))

    moved = navigation.move_submarine((1, 0))

    assert moved is True
    assert navigation.snapshot.submarine == (1, 0)
    assert host.events.count(("submarine_click", (1, 0), (-3, 0, 3, 2))) == 2
    assert ("recover", False) in host.events
    assert host.events[-2:] == ["submarine_confirm", "submarine_finish"]


def test_rebuild_paths_projects_both_fleets_from_the_active_position() -> None:
    map_ = _map("C1")
    host = _NavigationHost(shown=[2])
    navigation = _controller(map_, host, FleetNavigationRules(fleet_2_enabled=True))
    navigation.seed_surface(fleet_1=(0, 0), fleet_2=(2, 0))
    navigation.observe_active()

    navigation.rebuild_paths()

    assert [grid.cost_1 for grid in map_] == [0, 1, 2]
    assert [grid.cost_2 for grid in map_] == [2, 1, 0]
    assert [grid.cost for grid in map_] == [2, 1, 0]
