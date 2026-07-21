from typing import TYPE_CHECKING, cast, override

import pytest

from module.map.fleet import Fleet
from module.map.map_grids import SelectedGrids
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap


class _RoadblockLayout:
    def __init__(self, enemies: list[GridInfo]) -> None:
        self.enemies = enemies

    def select(self, **criteria: object) -> SelectedGrids[GridInfo]:
        if criteria != {"is_enemy": True}:
            message = f"unexpected map selection: {criteria}"
            raise AssertionError(message)
        return SelectedGrids([enemy for enemy in self.enemies if enemy.is_enemy])


class _RoadblockMap:
    def __init__(self, enemies: list[GridInfo]) -> None:
        self.layout = _RoadblockLayout(enemies)


class _RoadblockFleet(Fleet):
    def __init__(self, *, reachable_without_enemy: bool = True, fail_on_calls: set[int] | None = None) -> None:
        enemy = GridInfo()
        enemy.location = (0, 0)
        enemy.is_enemy = True
        self.enemy = enemy
        self.target = GridInfo()
        self.target.location = (1, 0)
        self.target.cost = 9999
        self.map = cast("CampaignMap", _RoadblockMap([enemy]))
        self.fleet_current_index = 1
        self.reachable_without_enemy = reachable_without_enemy
        self.fail_on_calls = set() if fail_on_calls is None else set(fail_on_calls)
        self.path_calls = 0
        self.projections: list[tuple[int, bool]] = []

    @override
    def find_path_initial(self) -> None:
        self.path_calls += 1
        self.projections.append((self.fleet_current_index, self.enemy.is_enemy))
        if self.path_calls in self.fail_on_calls:
            message = f"path failure {self.path_calls}"
            raise RuntimeError(message)
        accessible = self.fleet_current_index == 2 and not self.enemy.is_enemy and self.reachable_without_enemy
        self.target.cost = 1 if accessible else 9999


class _CombinationRoadblockFleet(Fleet):
    def __init__(self, required_roadblocks: tuple[frozenset[int], ...]) -> None:
        self.enemies: list[GridInfo] = []
        for index in range(3):
            enemy = GridInfo()
            enemy.location = (index, 0)
            enemy.is_enemy = True
            self.enemies.append(enemy)
        self.target = GridInfo()
        self.target.location = (3, 0)
        self.target.cost = 9999
        self.map = cast("CampaignMap", _RoadblockMap(self.enemies))
        self.fleet_current_index = 1
        self.required_roadblocks = required_roadblocks
        self.candidate_projections: list[tuple[int, ...]] = []
        self.restored_projections = 0

    @override
    def find_path_initial(self) -> None:
        disabled = tuple(index for index, enemy in enumerate(self.enemies) if not enemy.is_enemy)
        if disabled:
            self.candidate_projections.append(disabled)
        else:
            self.restored_projections += 1
        disabled_set = frozenset(disabled)
        accessible = any(required <= disabled_set for required in self.required_roadblocks)
        self.target.cost = 1 if accessible else 9999


def test_brute_roadblock_probe_restores_fleet_enemy_and_path_projection_when_found() -> None:
    fleet = _RoadblockFleet()

    roadblocks = fleet.brute_find_roadblocks(fleet.target, fleet=2)

    assert roadblocks.location == [(0, 0)]
    assert fleet.fleet_current_index == 1
    assert fleet.enemy.is_enemy
    assert not fleet.target.is_accessible
    assert fleet.projections == [(2, True), (2, False), (2, True), (1, True)]


def test_brute_roadblock_probe_restores_projection_when_search_is_exhausted() -> None:
    fleet = _RoadblockFleet(reachable_without_enemy=False)

    roadblocks = fleet.brute_find_roadblocks(fleet.target, fleet=2)

    assert not roadblocks
    assert fleet.fleet_current_index == 1
    assert fleet.enemy.is_enemy
    assert not fleet.target.is_accessible
    assert fleet.projections[-1] == (1, True)


def test_brute_roadblock_probe_tries_each_unique_combination_once() -> None:
    fleet = _CombinationRoadblockFleet((frozenset({0, 1, 2}),))

    roadblocks = fleet.brute_find_roadblocks(fleet.target)

    assert roadblocks.location == [(0, 0), (1, 0), (2, 0)]
    assert fleet.candidate_projections == [
        (0,),
        (1,),
        (2,),
        (0, 1),
        (0, 2),
        (1, 2),
        (0, 1, 2),
    ]
    assert len(fleet.candidate_projections) == len(set(fleet.candidate_projections))


def test_brute_roadblock_probe_returns_the_first_minimal_blocking_set() -> None:
    fleet = _CombinationRoadblockFleet((frozenset({0, 2}),))

    roadblocks = fleet.brute_find_roadblocks(fleet.target)

    assert roadblocks.location == [(0, 0), (2, 0)]
    assert fleet.candidate_projections == [(0,), (1,), (2,), (0, 1), (0, 2)]
    assert all(len(candidate) <= 2 for candidate in fleet.candidate_projections)


def test_brute_roadblock_probe_restores_every_enemy_after_exhausting_combinations() -> None:
    fleet = _CombinationRoadblockFleet(())

    roadblocks = fleet.brute_find_roadblocks(fleet.target)

    assert not roadblocks
    assert all(enemy.is_enemy for enemy in fleet.enemies)
    assert not fleet.target.is_accessible
    assert fleet.restored_projections == 7
    assert len(fleet.candidate_projections) == 7


def test_brute_roadblock_probe_restores_projection_after_path_failure() -> None:
    fleet = _RoadblockFleet(fail_on_calls={2})

    with pytest.raises(RuntimeError, match="path failure 2"):
        fleet.brute_find_roadblocks(fleet.target, fleet=2)

    assert fleet.fleet_current_index == 1
    assert fleet.enemy.is_enemy
    assert fleet.projections[-2:] == [(2, True), (1, True)]


def test_accessibility_probe_restores_projection_when_alternate_path_fails() -> None:
    fleet = _RoadblockFleet(fail_on_calls={1})

    with pytest.raises(RuntimeError, match="path failure 1"):
        fleet.check_accessibility(fleet.target, fleet=2)

    assert fleet.fleet_current_index == 1
    assert fleet.enemy.is_enemy
    assert fleet.projections == [(2, True), (1, True)]
