from typing import TYPE_CHECKING, override

from module.map.fleet import Fleet
from module.map_detection.grid import Grid
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.base.type_alias import Point

_Location = tuple[int, int]
_MaybeLocation = _Location | tuple[()]


class _Config:
    POOR_MAP_DATA = False
    fleet_2 = False


class _Grid(GridInfo):
    def __init__(
        self,
        location: _Location,
        *,
        is_current_fleet: bool = False,
        is_spawn_point: bool = True,
    ) -> None:
        self.location = location
        self.is_current_fleet = is_current_fleet
        self.is_spawn_point = is_spawn_point

    def __repr__(self) -> str:
        return f"_Grid({self.location})"


class _LocalGrid(Grid):
    def __init__(self, *, current: bool) -> None:
        self.current = current

    @override
    def predict_current_fleet(self) -> bool:
        return self.current


class _Selected(list[_Grid]):  # ruff:ignore[subclass-builtin] - 测试替身须复现生产 list 协议。
    @property
    def count(self) -> int:
        return len(self)

    def delete(self, other: _Selected) -> _Selected:
        other_locations = {grid.location for grid in other}
        return _Selected([grid for grid in self if grid.location not in other_locations])

    def sort_by_camera_distance(self, _camera: object) -> _Selected:
        return self


class _Map:
    def __init__(self) -> None:
        self.select_results: dict[tuple[tuple[str, object], ...], _Selected] = {}
        self.cover_results: dict[_Location, _Selected] = {}

    def set_select(self, kwargs: dict[str, object], grids: _Selected) -> None:
        self.select_results[tuple(sorted(kwargs.items()))] = grids

    def select(self, **kwargs: object) -> _Selected:
        return self.select_results.get(tuple(sorted(kwargs.items())), _Selected([]))

    def grid_covered(self, grid: _Grid, **_kwargs: object) -> _Selected:
        return self.cover_results.get(grid.location, _Selected([]))


class _Fleet(Fleet):
    config: _Config
    map: _Map
    camera: _Location
    fleet_1_location: _MaybeLocation
    fleet_2_location: _MaybeLocation

    def __init__(self) -> None:
        self.config = _Config()
        self.map = _Map()
        self.camera = (0, 0)
        self.fleet_current_index = 1
        self.fleet_1_location = ()
        self.fleet_2_location = ()
        self.calls: list[tuple[object, ...]] = []
        self.local_current_results: dict[_Location, bool] = {}

    def find_all_fleets(self) -> None:
        self.calls.append(("find_all_fleets",))

    def show_fleet(self) -> None:
        self.calls.append(("show_fleet", self.fleet_1_location, self.fleet_2_location))

    @override
    def in_sight(
        self,
        location: GridInfo | str | Point,
        sight: tuple[int, int, int, int] | None = None,
    ) -> None:
        assert isinstance(location, _Grid)
        self.calls.append(("in_sight", location.location, sight))

    @override
    def convert_global_to_local(self, location: GridInfo | str | Point) -> _LocalGrid:
        assert isinstance(location, _Grid)
        self.calls.append(("convert_global_to_local", location.location))
        return _LocalGrid(current=self.local_current_results.get(location.location, False))


def test_find_current_fleet_uses_single_detected_fleet_without_second_fleet() -> None:
    fleet = _Fleet()
    detected = _Grid((1, 1))
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([detected]))

    result = fleet.find_current_fleet()

    assert result == (1, 1)
    assert fleet.fleet_1_location == (1, 1)
    assert fleet.fleet_2_location == ()


def test_find_current_fleet_predicts_missing_second_fleet_from_spawn_points() -> None:
    fleet = _Fleet()
    fleet.config.fleet_2 = True
    detected = _Grid((1, 1), is_current_fleet=False)
    another = _Grid((2, 2))
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([detected]))
    fleet.map.set_select({"is_spawn_point": True}, _Selected([detected, another]))

    result = fleet.find_current_fleet()

    assert result == (2, 2)
    assert fleet.fleet_1_location == (2, 2)
    assert fleet.fleet_2_location == (1, 1)


def test_find_current_fleet_uses_current_marker_when_two_fleets_detected() -> None:
    fleet = _Fleet()
    first = _Grid((1, 1))
    second = _Grid((2, 2), is_current_fleet=True)
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([first, second]))
    fleet.map.set_select({"is_current_fleet": True}, _Selected([second]))

    result = fleet.find_current_fleet()

    assert result == (2, 2)
    assert fleet.fleet_1_location == (2, 2)
    assert fleet.fleet_2_location == (1, 1)


def test_find_current_fleet_predicts_current_when_marker_missing() -> None:
    fleet = _Fleet()
    first = _Grid((1, 1))
    second = _Grid((2, 2))
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([first, second]))
    fleet.map.set_select({"is_current_fleet": True}, _Selected([]))
    fleet.local_current_results[(2, 2)] = True

    result = fleet.find_current_fleet()

    assert result == (2, 2)
    assert fleet.fleet_1_location == (2, 2)
    assert fleet.fleet_2_location == (1, 1)


def test_find_current_fleet_falls_back_to_full_scan_when_no_fleet_detected() -> None:
    fleet = _Fleet()
    current = _Grid((3, 3), is_current_fleet=True)
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([]))
    fleet.map.set_select({"is_current_fleet": True}, _Selected([current]))

    result = fleet.find_current_fleet()

    assert result == (3, 3)
    assert fleet.fleet_1_location == (3, 3)
    assert ("find_all_fleets",) in fleet.calls
