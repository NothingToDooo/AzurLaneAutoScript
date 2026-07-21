import pytest

from module.map import fleet as fleet_module
from module.map.fleet import Fleet
from module.map.map_spawn_gap import MapSpawnGapSnapshot, MapSpawnProgress

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


class _Config:
    MAP_HAS_MOVABLE_NORMAL_ENEMY = False
    MAP_ENEMY_TEMPLATE = True
    MAP_HAS_WALL = False
    MAP_HAS_PORTAL = False
    MAP_HAS_AMBUSH = False
    MOVABLE_ENEMY_FLEET_STEP = 2


class _Map:
    def __init__(self) -> None:
        self.grids: dict[_Location, _Grid] = {}
        self.select_results: dict[tuple[tuple[str, object], ...], _Selected] = {}
        self.manual_map_covered = _Selected([])
        self.covered_result = _Selected([])
        self.missing = {"siren": 0, "enemy": 0}
        self.find_path_initial_calls: list[tuple[object, object]] = []
        self.grid_connection_calls: list[dict[str, object]] = []

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

    def grid_connection_initial(self, **kwargs: object) -> None:
        self.grid_connection_calls.append(kwargs)

    def __getitem__(self, location: _Location) -> _Grid:
        return self.grids[location]


class _Fleet(Fleet):
    config: _Config
    map: _Map
    fleet_1_location: _Location
    fleet_2_location: _MaybeLocation
    movable_before: _Selected
    movable_before_normal: _Selected

    def __init__(self) -> None:
        self.config = _Config()
        self.map = _Map()
        self.battle_count = 0
        self.mystery_count = 0
        self.siren_count = 0
        self.carrier_count = 0
        self.fleet_current_index = 1
        self.fleet_1_location = (0, 0)
        self.fleet_2_location = ()
        self.map.add_grid(self.fleet_1_location)
        self._spawn_gap_predictor = _SpawnGapPredictor(self.map)
        self.movable_before = _Selected([])
        self.movable_before_normal = _Selected([])


class _SpawnGapPredictor(fleet_module.MapSpawnGapPredictor):
    def __init__(self, map_: _Map) -> None:
        self._test_map = map_

    def estimate(self, progress: MapSpawnProgress) -> MapSpawnGapSnapshot:
        del progress
        return MapSpawnGapSnapshot(possible={}, missing=self._test_map.missing)


@pytest.fixture(autouse=True)
def _patch_selected_grids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fleet_module, "SelectedGrids", _Selected)


def test_track_movable_marks_matched_enemy_as_movable(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet()
    before = fleet.map.add_grid((1, 0))
    after = fleet.map.add_grid((2, 0))
    fleet.movable_before = _Selected([before])
    fleet.map.set_select({"is_siren": True}, _Selected([after]))
    fleet.map.set_select({"may_siren": True}, _Selected([before, after]))
    monkeypatch.setattr(fleet_module, "match_movable", lambda **_kwargs: ([(1, 0)], [(2, 0)]))

    fleet.track_movable()

    assert after.is_movable is True


def test_track_movable_wipes_wrong_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet()
    wrong = fleet.map.add_grid((3, 0), may_siren=False)
    fleet.map.set_select({"is_siren": True}, _Selected([wrong]))
    fleet.map.set_select({"may_siren": True}, _Selected([]))
    monkeypatch.setattr(fleet_module, "match_movable", lambda **_kwargs: ([], []))

    fleet.track_movable()

    assert wrong.wiped is True


def test_track_movable_predicts_missing_siren(monkeypatch: pytest.MonkeyPatch) -> None:
    fleet = _Fleet()
    lost = fleet.map.add_grid((4, 0))
    predicted = fleet.map.add_grid((5, 0))
    fleet.movable_before = _Selected([lost])
    fleet.map.missing = {"siren": 1, "enemy": 0}
    fleet.map.covered_result = _Selected([predicted])
    fleet.map.set_select({"is_siren": True}, _Selected([]))
    fleet.map.set_select({"may_siren": True}, _Selected([lost, predicted]))
    fleet.map.set_select({"cost": 0}, _Selected([predicted]))
    monkeypatch.setattr(fleet_module, "match_movable", lambda **_kwargs: ([], []))

    fleet.track_movable()

    assert predicted.is_siren is True
    assert predicted.is_enemy is True
    assert predicted.is_movable is True
    assert fleet.map.find_path_initial_calls[-1] == (fleet.fleet_current, False)
