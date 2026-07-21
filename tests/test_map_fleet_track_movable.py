from typing import cast

import pytest

from module.map import map_scanner as scanner_module
from module.map.map_scanner import (
    MovableEnemyRules,
    MovableEnemySnapshot,
    MovableEnemyTracker,
    MovableScanRequest,
    MovableTrackerContext,
)
from module.map.map_spawn_gap import MapSpawnGapPredictor, MapSpawnGapSnapshot, MapSpawnProgress

_Location = tuple[int, int]
_MaybeLocation = _Location | tuple[()]


class _Grid:
    def __init__(self, location: _Location, *, may_siren: object = True) -> None:
        self.location = location
        self.may_siren = may_siren
        self.is_siren = False
        self.is_enemy = False
        self.is_movable = False
        self.is_sea = True
        self.is_fleet = False
        self.wiped = False

    def wipe_out(self) -> None:
        self.wiped = True

    def __repr__(self) -> str:
        return f"_Grid({self.location})"


class _Selected(list[_Grid]):  # ruff:ignore[subclass-builtin] - 测试替身须复现生产 list 协议。
    @property
    def location(self) -> list[_Location]:
        return [grid.location for grid in self]

    def delete(self, other: _Selected) -> _Selected:
        other_locations = set(other.location)
        return _Selected([grid for grid in self if grid.location not in other_locations])

    def add(self, other: _Selected) -> _Selected:
        grids = _Selected(self.copy())
        known = set(grids.location)
        for grid in other:
            if grid.location not in known:
                grids.append(grid)
                known.add(grid.location)
        return grids

    def intersect(self, other: _Selected) -> _Selected:
        other_locations = set(other.location)
        return _Selected([grid for grid in self if grid.location in other_locations])

    def select(self, **kwargs: object) -> _Selected:
        result = _Selected([])
        for grid in self:
            if all(getattr(grid, key) == value for key, value in kwargs.items()):
                result.append(grid)
        return result


class _Map:
    def __init__(self) -> None:
        self.grids: dict[_Location, _Grid] = {}
        self.select_results: dict[tuple[tuple[str, object], ...], _Selected] = {}
        self.manual_map_covered = _Selected([])
        self.covered_result = _Selected([])
        self.missing = {"siren": 0, "enemy": 0}
        self.find_path_initial_calls: list[tuple[object, object]] = []
        self.grid_connection_calls: list[dict[str, object]] = []
        self.find_path_failure: object | None = None

    def add_grid(self, location: _Location, *, may_siren: object = True) -> _Grid:
        grid = _Grid(location, may_siren=may_siren)
        self.grids[location] = grid
        return grid

    def set_select(self, kwargs: dict[str, object], grids: _Selected) -> None:
        self.select_results[tuple(sorted(kwargs.items()))] = grids

    def select(self, **kwargs: object) -> _Selected:
        return self.select_results.get(tuple(sorted(kwargs.items())), _Selected([]))

    def to_selected(self, locations: list[_Location]) -> _Selected:
        return _Selected([self.grids[location] for location in locations])

    def grid_covered(self, grid: _Grid, **_kwargs: object) -> _Selected:
        if self.covered_result:
            return self.covered_result
        return _Selected([grid])

    def find_path_initial(self, grid: object, *, has_ambush: object) -> None:
        self.find_path_initial_calls.append((grid, has_ambush))
        if grid is self.find_path_failure:
            msg = "path projection failed"
            raise RuntimeError(msg)

    def grid_connection_initial(self, **kwargs: object) -> None:
        self.grid_connection_calls.append(kwargs)

    def __getitem__(self, location: _Location) -> _Grid:
        return self.grids[location]


class _MovableRuntime:
    map: _Map
    fleet_1_location: _MaybeLocation
    fleet_2_location: _MaybeLocation

    def __init__(self) -> None:
        self.map = _Map()
        self.fleet_1_location = (0, 0)
        self.fleet_2_location = ()
        self.map.add_grid(self.fleet_1_location)
        self.map_spawn_gap_predictor = _SpawnGapPredictor(self.map)

    @property
    def fleet_current(self) -> _MaybeLocation:
        return self.fleet_1_location


class _SpawnGapPredictor(MapSpawnGapPredictor):
    def __init__(self, map_: _Map) -> None:
        self._test_map = map_

    def estimate(self, progress: MapSpawnProgress) -> MapSpawnGapSnapshot:
        del progress
        return MapSpawnGapSnapshot(possible={}, missing=self._test_map.missing)


@pytest.fixture(autouse=True)
def _patch_selected_grids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scanner_module, "SelectedGrids", _Selected)


def _request(
    *,
    sirens: tuple[_Location, ...] = (),
    missing: dict[str, int] | None = None,
    wall: bool = False,
    portal: bool = False,
) -> tuple[_MovableRuntime, MovableScanRequest]:
    runtime = _MovableRuntime()
    if missing is not None:
        runtime.map.missing = missing
    request = MovableScanRequest(
        snapshot=MovableEnemySnapshot(sirens=sirens),
        progress=MapSpawnProgress(mode="movable"),
        rules=MovableEnemyRules(
            siren=True,
            normal_enemy=False,
            enemy_template=True,
            wall=wall,
            portal=portal,
            ambush=False,
            siren_step=2,
        ),
    )
    return runtime, request


def _track(runtime: _MovableRuntime, request: MovableScanRequest) -> None:
    context = cast("MovableTrackerContext", runtime)
    MovableEnemyTracker().track(context, request, siren=True)


def test_track_movable_marks_matched_enemy_as_movable(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, request = _request(sirens=((1, 0),))
    before = runtime.map.add_grid((1, 0))
    after = runtime.map.add_grid((2, 0))
    runtime.map.set_select({"is_siren": True}, _Selected([after]))
    runtime.map.set_select({"may_siren": True}, _Selected([before, after]))
    monkeypatch.setattr(scanner_module, "match_movable", lambda **_kwargs: ([(1, 0)], [(2, 0)]))

    _track(runtime, request)

    assert after.is_movable is True


def test_track_movable_wipes_wrong_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, request = _request()
    wrong = runtime.map.add_grid((3, 0), may_siren=False)
    runtime.map.set_select({"is_siren": True}, _Selected([wrong]))
    runtime.map.set_select({"may_siren": True}, _Selected([]))
    monkeypatch.setattr(scanner_module, "match_movable", lambda **_kwargs: ([], []))

    _track(runtime, request)

    assert wrong.wiped is True


def test_track_movable_predicts_missing_siren(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, request = _request(sirens=((4, 0),), missing={"siren": 1, "enemy": 0})
    lost = runtime.map.add_grid((4, 0))
    predicted = runtime.map.add_grid((5, 0))
    runtime.map.covered_result = _Selected([predicted])
    runtime.map.set_select({"is_siren": True}, _Selected([]))
    runtime.map.set_select({"may_siren": True}, _Selected([lost, predicted]))
    runtime.map.set_select({"cost": 0}, _Selected([predicted]))
    monkeypatch.setattr(scanner_module, "match_movable", lambda **_kwargs: ([], []))

    _track(runtime, request)

    assert predicted.is_siren is True
    assert predicted.is_enemy is True
    assert predicted.is_movable is True
    assert runtime.map.find_path_initial_calls[-1] == (runtime.fleet_current, False)


def test_track_movable_restores_wall_and_fleet_path_after_projection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, request = _request(
        sirens=((6, 0),),
        missing={"siren": 1, "enemy": 0},
        wall=True,
        portal=True,
    )
    lost = runtime.map.add_grid((6, 0))
    runtime.map.set_select({"is_siren": True}, _Selected([]))
    runtime.map.set_select({"may_siren": True}, _Selected([lost]))
    runtime.map.find_path_failure = lost
    monkeypatch.setattr(scanner_module, "match_movable", lambda **_kwargs: ([], []))

    with pytest.raises(RuntimeError, match="path projection failed"):
        _track(runtime, request)

    assert runtime.map.grid_connection_calls == [
        {"wall": False, "portal": True},
        {"wall": True, "portal": True},
    ]
    assert runtime.map.find_path_initial_calls[-1] == (runtime.fleet_current, False)
