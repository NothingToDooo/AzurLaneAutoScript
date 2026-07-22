from typing import TYPE_CHECKING, cast

import pytest

from module.map.fleet_navigation import FleetNavigationController, FleetNavigationRules, FleetNavigationServices
from module.map.map_base import CampaignMap

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.map.fleet_navigation import FleetMovementUi, FleetSwitchUi, SubmarineMovementUi
    from module.map.fleet_turn import FleetTurnController
    from module.map.map_pathfinder import CampaignPathfinder
    from module.map.type_alias import FleetLocation, GridLocation
    from module.map_detection.grid_info import GridInfo


def _controller(map_: CampaignMap) -> FleetNavigationController:
    navigation = FleetNavigationController(
        FleetNavigationRules(fleet_2_enabled=True),
        FleetNavigationServices(
            map=map_,
            turn_controller=cast("FleetTurnController", object()),
            switch_ui=cast("FleetSwitchUi", object()),
            movement_ui=cast("FleetMovementUi", object()),
            submarine_ui=cast("SubmarineMovementUi", object()),
        ),
    )
    navigation.seed_surface(fleet_1=(5, 0), fleet_2=(6, 0))
    return navigation


def _map() -> CampaignMap:
    map_ = CampaignMap("roadblock-test")
    map_.layout.initialize("G1")
    map_.topology.rebuild()
    return map_


class _RoadblockPathfinder:
    def __init__(
        self,
        target: GridInfo,
        enemy: GridInfo,
        *,
        reachable_without_enemy: bool,
        fail_on_calls: set[int],
    ) -> None:
        self._target = target
        self._enemy = enemy
        self._reachable_without_enemy = reachable_without_enemy
        self._fail_on_calls = fail_on_calls
        self.path_calls = 0
        self.projections: list[tuple[int, bool]] = []

    def project_fleets(
        self,
        locations: Mapping[int, FleetLocation],
        current: GridLocation,
        *,
        has_ambush: bool,
    ) -> None:
        del has_ambush
        self.path_calls += 1
        index = 2 if locations.get(2) == current else 1
        self.projections.append((index, self._enemy.is_enemy))
        if self.path_calls in self._fail_on_calls:
            message = f"path failure {self.path_calls}"
            raise RuntimeError(message)
        accessible = index == 2 and not self._enemy.is_enemy and self._reachable_without_enemy
        self._target.cost = 1 if accessible else 9999


class _RoadblockHarness:
    def __init__(self, *, reachable_without_enemy: bool = True, fail_on_calls: set[int] | None = None) -> None:
        self.map = _map()
        self.enemy = self.map[(0, 0)]
        self.enemy.is_enemy = True
        self.target = self.map[(1, 0)]
        self.target.cost = 9999
        self.pathfinder = _RoadblockPathfinder(
            self.target,
            self.enemy,
            reachable_without_enemy=reachable_without_enemy,
            fail_on_calls=set() if fail_on_calls is None else set(fail_on_calls),
        )
        self.map.pathfinder = cast("CampaignPathfinder", self.pathfinder)
        self.navigation = _controller(self.map)


class _CombinationPathfinder:
    def __init__(
        self,
        target: GridInfo,
        enemies: list[GridInfo],
        required_roadblocks: tuple[frozenset[int], ...],
    ) -> None:
        self._target = target
        self._enemies = enemies
        self._required_roadblocks = required_roadblocks
        self.candidate_projections: list[tuple[int, ...]] = []
        self.restored_projections = 0

    def project_fleets(
        self,
        locations: Mapping[int, FleetLocation],
        current: GridLocation,
        *,
        has_ambush: bool,
    ) -> None:
        del locations, current, has_ambush
        disabled = tuple(index for index, enemy in enumerate(self._enemies) if not enemy.is_enemy)
        if disabled:
            self.candidate_projections.append(disabled)
        else:
            self.restored_projections += 1
        disabled_set = frozenset(disabled)
        accessible = any(required <= disabled_set for required in self._required_roadblocks)
        self._target.cost = 1 if accessible else 9999


class _CombinationHarness:
    def __init__(self, required_roadblocks: tuple[frozenset[int], ...]) -> None:
        self.map = _map()
        self.enemies = [self.map[(index, 0)] for index in range(3)]
        for enemy in self.enemies:
            enemy.is_enemy = True
        self.target = self.map[(3, 0)]
        self.target.cost = 9999
        self.pathfinder = _CombinationPathfinder(self.target, self.enemies, required_roadblocks)
        self.map.pathfinder = cast("CampaignPathfinder", self.pathfinder)
        self.navigation = _controller(self.map)


def test_roadblock_probe_restores_fleet_enemy_and_path_projection_when_found() -> None:
    harness = _RoadblockHarness()

    roadblocks = harness.navigation.find_roadblocks(harness.target, fleet=2)

    assert roadblocks.location == [(0, 0)]
    assert harness.navigation.current_index == 1
    assert harness.enemy.is_enemy
    assert not harness.target.is_accessible
    assert harness.pathfinder.projections == [(2, True), (2, False), (2, True), (1, True)]


def test_roadblock_probe_restores_projection_when_search_is_exhausted() -> None:
    harness = _RoadblockHarness(reachable_without_enemy=False)

    roadblocks = harness.navigation.find_roadblocks(harness.target, fleet=2)

    assert not roadblocks
    assert harness.navigation.current_index == 1
    assert harness.enemy.is_enemy
    assert not harness.target.is_accessible
    assert harness.pathfinder.projections[-1] == (1, True)


def test_roadblock_probe_tries_each_unique_combination_once() -> None:
    harness = _CombinationHarness((frozenset({0, 1, 2}),))

    roadblocks = harness.navigation.find_roadblocks(harness.target)

    assert roadblocks.location == [(0, 0), (1, 0), (2, 0)]
    assert harness.pathfinder.candidate_projections == [
        (0,),
        (1,),
        (2,),
        (0, 1),
        (0, 2),
        (1, 2),
        (0, 1, 2),
    ]
    assert len(harness.pathfinder.candidate_projections) == len(set(harness.pathfinder.candidate_projections))


def test_roadblock_probe_returns_the_first_minimal_blocking_set() -> None:
    harness = _CombinationHarness((frozenset({0, 2}),))

    roadblocks = harness.navigation.find_roadblocks(harness.target)

    assert roadblocks.location == [(0, 0), (2, 0)]
    assert harness.pathfinder.candidate_projections == [(0,), (1,), (2,), (0, 1), (0, 2)]
    assert all(len(candidate) <= 2 for candidate in harness.pathfinder.candidate_projections)


def test_roadblock_probe_restores_every_enemy_after_exhausting_combinations() -> None:
    harness = _CombinationHarness(())

    roadblocks = harness.navigation.find_roadblocks(harness.target)

    assert not roadblocks
    assert all(enemy.is_enemy for enemy in harness.enemies)
    assert not harness.target.is_accessible
    assert harness.pathfinder.restored_projections == 7
    assert len(harness.pathfinder.candidate_projections) == 7


def test_roadblock_probe_restores_projection_after_path_failure() -> None:
    harness = _RoadblockHarness(fail_on_calls={2})

    with pytest.raises(RuntimeError, match="path failure 2"):
        harness.navigation.find_roadblocks(harness.target, fleet=2)

    assert harness.navigation.current_index == 1
    assert harness.enemy.is_enemy
    assert harness.pathfinder.projections[-2:] == [(2, True), (1, True)]


def test_accessibility_probe_restores_projection_when_alternate_path_fails() -> None:
    harness = _RoadblockHarness(fail_on_calls={1})

    with pytest.raises(RuntimeError, match="path failure 1"):
        harness.navigation.is_accessible(harness.target, fleet=2)

    assert harness.navigation.current_index == 1
    assert harness.enemy.is_enemy
    assert harness.pathfinder.projections == [(2, True), (1, True)]
