from dataclasses import dataclass

import pytest

from module.map.fleet_turn import FleetTurnController, FleetTurnEvent, FleetTurnRules


@dataclass(slots=True)
class _MazeGrid:
    is_maze: bool = False
    maze_round: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class _BouncingRoute:
    active: bool

    def select(self, **criteria: object) -> tuple[object, ...]:
        assert criteria == {"may_bouncing_enemy": True}
        return (object(),) if self.active else ()


class _Map:
    def __init__(self) -> None:
        self.spawn_data: list[dict[str, int]] = []
        self.siren_count = 0
        self.enemy_count = 0
        self.maze_round = 3
        self.bouncing_enemy_data: list[_BouncingRoute] = []
        self.grids: dict[tuple[int, int], _MazeGrid] = {}

    def select(self, **criteria: object) -> tuple[object, ...]:
        if criteria == {"is_siren": True}:
            return tuple(object() for _ in range(self.siren_count))
        if criteria == {"is_enemy": True}:
            return tuple(object() for _ in range(self.enemy_count))
        raise AssertionError(criteria)

    def __getitem__(self, location: tuple[int, int]) -> _MazeGrid:
        return self.grids[location]


def test_enemy_move_event_follows_battle_registration_and_arrival_order() -> None:
    rules = FleetTurnRules(movable_enemy=True, movable_enemy_turns=(2,), enemy_move_wait=0.7)
    map_ = _Map()
    map_.spawn_data = [{"siren": 1}]
    map_.siren_count = 1
    controller = FleetTurnController(rules, map_)

    controller.initialize(battle_count=0)

    assert controller.fleet_arrived() is FleetTurnEvent.STABLE
    assert controller.fleet_arrived() is FleetTurnEvent.ENEMY_MOVED


def test_battle_resolution_clears_movement_schedule_after_last_enemy() -> None:
    rules = FleetTurnRules(movable_enemy=True, movable_enemy_turns=(2,), enemy_move_wait=0.7)
    map_ = _Map()
    map_.spawn_data = [{"siren": 1}, {}]
    map_.siren_count = 1
    controller = FleetTurnController(rules, map_)
    controller.initialize(battle_count=0)
    assert controller.fleet_arrived() is FleetTurnEvent.STABLE

    map_.siren_count = 0
    controller.battle_resolved(battle_count=1)

    assert controller.fleet_arrived() is FleetTurnEvent.STABLE
    assert controller.fleet_arrived() is FleetTurnEvent.STABLE


def test_movable_normal_enemy_uses_its_own_turn_interval() -> None:
    rules = FleetTurnRules(
        movable_enemy=True,
        movable_normal_enemy=True,
        movable_enemy_turns=(3,),
        movable_normal_enemy_turns=(2,),
        enemy_move_wait=0.7,
    )
    map_ = _Map()
    map_.spawn_data = [{"enemy": 1}]
    map_.enemy_count = 1
    controller = FleetTurnController(rules, map_)
    controller.initialize(battle_count=0)

    assert controller.fleet_arrived() is FleetTurnEvent.STABLE
    assert controller.fleet_arrived() is FleetTurnEvent.ENEMY_MOVED


def test_maze_change_event_and_active_phase_follow_the_third_arrival() -> None:
    rules = FleetTurnRules(maze=True, enemy_move_wait=0.7)
    map_ = _Map()
    map_.grids[(1, 1)] = _MazeGrid(is_maze=True, maze_round=frozenset({0}))
    controller = FleetTurnController(rules, map_)
    controller.initialize(battle_count=0)

    assert controller.maze_active_on((1, 1))
    assert controller.fleet_arrived() is FleetTurnEvent.STABLE
    assert not controller.maze_active_on((1, 1))
    assert controller.fleet_arrived() is FleetTurnEvent.STABLE
    assert controller.fleet_arrived() is FleetTurnEvent.MAZE_CHANGED
    assert controller.maze_active_on((1, 1))


def test_enemy_move_takes_priority_when_maze_changes_on_the_same_arrival() -> None:
    rules = FleetTurnRules(
        movable_enemy=True,
        maze=True,
        movable_enemy_turns=(3,),
        enemy_move_wait=0.7,
    )
    map_ = _Map()
    map_.spawn_data = [{"siren": 1}]
    map_.siren_count = 1
    controller = FleetTurnController(rules, map_)
    controller.initialize(battle_count=0)

    assert controller.fleet_arrived() is FleetTurnEvent.STABLE
    assert controller.fleet_arrived() is FleetTurnEvent.STABLE
    assert controller.fleet_arrived() is FleetTurnEvent.ENEMY_MOVED


def test_movement_wait_combines_due_enemies_maze_and_active_bouncing_routes() -> None:
    rules = FleetTurnRules(
        movable_enemy=True,
        maze=True,
        bouncing_enemy=True,
        movable_enemy_turns=(3,),
        enemy_move_wait=0.7,
    )
    map_ = _Map()
    map_.spawn_data = [{"siren": 2}]
    map_.siren_count = 2
    map_.bouncing_enemy_data = [_BouncingRoute(active=True), _BouncingRoute(active=False)]
    controller = FleetTurnController(rules, map_)
    controller.initialize(battle_count=0)
    assert controller.fleet_arrived() is FleetTurnEvent.STABLE
    assert controller.fleet_arrived() is FleetTurnEvent.STABLE

    assert controller.movement_wait == pytest.approx(3.1)
