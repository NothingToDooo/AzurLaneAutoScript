from dataclasses import dataclass

from module.map.map import GridSelection, Map
from module.map.map_grids import SelectedGrids


@dataclass(slots=True, eq=False)
class _Grid:
    name: str
    enemy_scale: int = 1
    enemy_genre: str = "Light"
    is_nearby: bool = True
    is_accessible: bool = True
    weight: int = 0
    cost: int = 0

    def __str__(self) -> str:
        return self.name


def _names(grids):
    return [grid.name for grid in grids]


def test_select_grids_applies_basic_filters_and_ignore() -> None:
    kept = _Grid("kept", is_nearby=True, is_accessible=True)
    far = _Grid("far", is_nearby=False, is_accessible=True)
    blocked = _Grid("blocked", is_nearby=True, is_accessible=False)
    ignored = _Grid("ignored", is_nearby=True, is_accessible=True)
    grids = SelectedGrids([kept, far, blocked, ignored])

    result = Map.select_grids(grids, GridSelection(nearby=True, ignore=SelectedGrids([ignored])))

    assert _names(result) == ["kept"]


def test_select_grids_scale_tuple_collects_all_requested_scales() -> None:
    grids = SelectedGrids(
        [
            _Grid("scale-1", enemy_scale=1, weight=2),
            _Grid("scale-2", enemy_scale=2, weight=1),
            _Grid("scale-3", enemy_scale=3, weight=3),
        ]
    )

    result = Map.select_grids(grids, GridSelection(scale=(2, 1), sort=("weight",)))

    assert _names(result) == ["scale-2", "scale-1"]


def test_select_grids_scale_list_stops_after_first_available_scale() -> None:
    grids = SelectedGrids(
        [
            _Grid("scale-1", enemy_scale=1, weight=1),
            _Grid("scale-2", enemy_scale=2, weight=2),
        ]
    )

    result = Map.select_grids(grids, GridSelection(scale=[2, 1], sort=("weight",)))

    assert _names(result) == ["scale-2"]


def test_select_grids_genre_normalizes_lowercase_and_keeps_list_priority() -> None:
    grids = SelectedGrids(
        [
            _Grid("light", enemy_genre="Light", weight=1),
            _Grid("main", enemy_genre="Main", weight=2),
        ]
    )

    result = Map.select_grids(grids, GridSelection(genre=["main", "light"], sort=("weight",)))

    assert _names(result) == ["main"]


def test_select_grids_strongest_and_weakest_pick_scale_priority() -> None:
    grids = SelectedGrids(
        [
            _Grid("small", enemy_scale=1),
            _Grid("middle", enemy_scale=2),
            _Grid("large", enemy_scale=3),
        ]
    )

    assert _names(Map.select_grids(grids, GridSelection(strongest=True))) == ["large"]
    assert _names(Map.select_grids(grids, GridSelection(weakest=True))) == ["small"]
