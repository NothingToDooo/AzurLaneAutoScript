from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

from module.map.map import Map
from module.map.map_grids import SelectedGrids
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.map.fleet_navigation import FleetNavigationController


@dataclass(slots=True)
class _Grid(GridInfo):
    name: str
    weight: int
    cost: int
    may_boss: bool = True
    is_accessible: bool = True

    def __str__(self) -> str:
        return self.name


class _TrackedSelectedGrids(SelectedGrids[_Grid]):
    def __init__(self, grids: list[_Grid], sort_calls: list[tuple[str, ...]]) -> None:
        super().__init__(grids)
        self.sort_calls = sort_calls

    @override
    def sort(self, *args: str) -> _TrackedSelectedGrids:
        self.sort_calls.append(args)
        sorted_grids = super().sort(*args)
        return _TrackedSelectedGrids(sorted_grids.grids, self.sort_calls)


class _MapLayout:
    def __init__(self, grids: list[_Grid]) -> None:
        self.grids = grids
        self.sort_calls: list[tuple[str, ...]] = []

    def select(self, **kwargs: object) -> _TrackedSelectedGrids:
        grids = [grid for grid in self.grids if all(getattr(grid, key) == value for key, value in kwargs.items())]
        return _TrackedSelectedGrids(grids, self.sort_calls)


class _MapState:
    def __init__(self, grids: list[_Grid]) -> None:
        self.layout = _MapLayout(grids)


class _Navigation:
    def __init__(self, events: list[tuple[str, ...]]) -> None:
        self._events = events

    def activate_boss(self) -> bool:
        self._events.append(("activate_boss",))
        return True


class _Campaign(Map):
    map: _MapState

    def __init__(self, grids: list[_Grid], successful_grid: _Grid) -> None:
        self.map = _MapState(grids)
        self.successful_grid = successful_grid
        self.battle_count = 0
        self.attempts: list[tuple[str, str]] = []
        self.events: list[tuple[str, ...]] = []
        self.navigation = cast("FleetNavigationController", _Navigation(self.events))

    @override
    def clear_chosen_enemy(self, grid: GridInfo, expected: str = "") -> bool:
        assert isinstance(grid, _Grid)
        self.attempts.append((grid.name, expected))
        self.events.append(("clear", grid.name, expected))
        if grid is self.successful_grid:
            self.battle_count += 1
            return True
        return False


def test_clear_potential_boss_sorts_once_before_trying_candidates() -> None:
    correct = _Grid("correct", weight=2, cost=1)
    wrong = _Grid("wrong", weight=1, cost=5)
    campaign = _Campaign([correct, wrong], successful_grid=correct)

    assert campaign.clear_potential_boss() is True

    assert campaign.attempts == [("wrong", ""), ("correct", "")]
    assert campaign.events == [("activate_boss",), ("clear", "wrong", ""), ("clear", "correct", "")]
    assert campaign.battle_count == 1
    assert campaign.map.layout.sort_calls == [("weight", "cost")]


def test_clear_potential_boss_expects_boss_for_single_candidate() -> None:
    boss = _Grid("boss", weight=1, cost=1)
    campaign = _Campaign([boss], successful_grid=boss)

    assert campaign.clear_potential_boss() is True

    assert campaign.attempts == [("boss", "boss")]
    assert campaign.events == [("activate_boss",), ("clear", "boss", "boss")]
    assert campaign.battle_count == 1
