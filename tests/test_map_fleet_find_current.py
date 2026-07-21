from typing import TYPE_CHECKING, cast, overload, override

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    InSightNext,
    build_campaign_map_observer,
)
from module.map.fleet import Fleet
from module.map.fleet_locator import (
    STANDARD_CAMPAIGN_FLEET_LOCATOR,
    SurfaceFleetLocationRequest,
    SurfaceFleetLocations,
)
from module.map_detection.grid import Grid
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from module.base.type_alias import Point
    from module.map.fleet_locator import FleetLocationContext
    from module.map.map_observer import InSightRequest, MapViewportRuntime

_Location = tuple[int, int]


class _Grid(GridInfo):
    def __init__(
        self,
        location: _Location,
        *,
        is_current_fleet: bool = False,
        is_spawn_point: bool = True,
        is_submarine_spawn_point: bool = False,
    ) -> None:
        self.location = location
        self.is_current_fleet = is_current_fleet
        self.is_spawn_point = is_spawn_point
        self.is_submarine = False
        self.is_submarine_spawn_point = is_submarine_spawn_point
        self.is_enemy = False
        self.is_fleet = False
        self.is_siren = False
        self.is_boss = False
        self.is_land = False

    def __repr__(self) -> str:
        return f"_Grid({self.location})"


class _LocalGrid(Grid):
    def __init__(
        self,
        location: _Location,
        calls: list[tuple[object, ...]],
        *,
        current: bool,
        fleet: bool,
        submarine: bool,
    ) -> None:
        self.location = location
        self.calls = calls
        self.current = current
        self.fleet = fleet
        self.submarine = submarine

    @override
    def predict_fleet(self) -> bool:
        self.calls.append(("predict_fleet", self.location))
        return self.fleet

    @override
    def predict_current_fleet(self) -> bool:
        self.calls.append(("predict_current_fleet", self.location))
        return self.current

    @override
    def predict_submarine(self) -> bool:
        self.calls.append(("predict_submarine", self.location))
        return self.submarine


class _Selected:
    def __init__(self, grids: Iterable[_Grid]) -> None:
        self._grids = list(grids)

    def __iter__(self) -> Iterator[_Grid]:
        return iter(self._grids)

    def __bool__(self) -> bool:
        return bool(self._grids)

    def __len__(self) -> int:
        return len(self._grids)

    def __repr__(self) -> str:
        return repr(self._grids)

    @property
    def grids(self) -> list[_Grid]:
        return list(self._grids)

    @property
    def count(self) -> int:
        return len(self._grids)

    def delete(self, other: Iterable[_Grid]) -> _Selected:
        other_locations = {grid.location for grid in other}
        return _Selected([grid for grid in self if grid.location not in other_locations])

    def sort_by_camera_distance(self, _camera: object) -> _Selected:
        return self

    def filter(self, predicate: Callable[[_Grid], bool]) -> _Selected:
        return _Selected([grid for grid in self if predicate(grid)])

    @overload
    def __getitem__(self, item: int) -> _Grid: ...

    @overload
    def __getitem__(self, item: slice) -> _Selected: ...

    def __getitem__(self, item: int | slice) -> _Grid | _Selected:
        if isinstance(item, slice):
            return _Selected(self._grids[item])
        return self._grids[item]


class _Map:
    def __init__(self) -> None:
        self.select_results: dict[tuple[tuple[str, object], ...], _Selected] = {}
        self.cover_results: dict[_Location, _Selected] = {}
        self.shape = (6, 6)

    def set_select(self, kwargs: dict[str, object], grids: _Selected) -> None:
        self.select_results[tuple(sorted(kwargs.items()))] = grids

    def select(self, **kwargs: object) -> _Selected:
        return self.select_results.get(tuple(sorted(kwargs.items())), _Selected([]))

    def grid_covered(self, grid: _Grid, **_kwargs: object) -> _Selected:
        return self.cover_results.get(grid.location, _Selected([]))


class _Fleet(Fleet):
    map: _Map
    camera: _Location

    def __init__(self) -> None:
        self.map = _Map()
        self.camera = (0, 0)
        self.calls: list[tuple[object, ...]] = []
        self.local_current_results: dict[_Location, bool] = {}
        self.local_fleet_results: dict[_Location, bool] = {}
        self.local_submarine_results: dict[_Location, bool] = {}

        def in_sight(
            runtime: MapViewportRuntime,
            request: InSightRequest,
            next_handler: InSightNext,
        ) -> None:
            del next_handler
            assert runtime is self
            self.calls.append(("in_sight", request.location, request.sight))

        self._map_observer = build_campaign_map_observer(
            (CampaignMapObserverExecutor(CampaignMapObserverContributor(in_sight=in_sight)),)
        )

    @override
    def convert_global_to_local(self, location: GridInfo | str | Point) -> _LocalGrid:
        assert isinstance(location, _Grid)
        grid_location = location.location
        assert grid_location is not None
        self.calls.append(("convert_global_to_local", grid_location))
        return _LocalGrid(
            grid_location,
            self.calls,
            current=self.local_current_results.get(grid_location, False),
            fleet=self.local_fleet_results.get(grid_location, True),
            submarine=self.local_submarine_results.get(grid_location, False),
        )


def _locate_surface(
    fleet: _Fleet,
    *,
    fleet_2_enabled: bool = False,
) -> SurfaceFleetLocations:
    return STANDARD_CAMPAIGN_FLEET_LOCATOR.locate_surface(
        cast("FleetLocationContext", fleet),
        SurfaceFleetLocationRequest(
            previous=SurfaceFleetLocations(fleet_1=(), fleet_2=()),
            fleet_2_enabled=fleet_2_enabled,
            poor_map_data=False,
        ),
    )


def test_locate_surface_uses_single_detected_fleet_without_second_fleet() -> None:
    fleet = _Fleet()
    detected = _Grid((1, 1))
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([detected]))

    result = _locate_surface(fleet)

    assert result == SurfaceFleetLocations(fleet_1=(1, 1), fleet_2=())


def test_locate_surface_predicts_missing_second_fleet_from_spawn_points() -> None:
    fleet = _Fleet()
    detected = _Grid((1, 1), is_current_fleet=False)
    another = _Grid((2, 2))
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([detected]))
    fleet.map.set_select({"is_spawn_point": True}, _Selected([detected, another]))

    result = _locate_surface(fleet, fleet_2_enabled=True)

    assert result == SurfaceFleetLocations(fleet_1=(2, 2), fleet_2=(1, 1))


def test_locate_surface_uses_current_marker_when_two_fleets_detected() -> None:
    fleet = _Fleet()
    first = _Grid((1, 1))
    second = _Grid((2, 2), is_current_fleet=True)
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([first, second]))
    fleet.map.set_select({"is_current_fleet": True}, _Selected([second]))

    result = _locate_surface(fleet)

    assert result == SurfaceFleetLocations(fleet_1=(2, 2), fleet_2=(1, 1))


def test_locate_surface_observes_current_marker_when_map_marker_is_missing() -> None:
    fleet = _Fleet()
    first = _Grid((1, 1))
    second = _Grid((2, 2))
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([first, second]))
    fleet.map.set_select({"is_current_fleet": True}, _Selected([]))
    fleet.local_current_results[(2, 2)] = True

    result = _locate_surface(fleet)

    assert result == SurfaceFleetLocations(fleet_1=(2, 2), fleet_2=(1, 1))
    assert fleet.calls == [
        ("in_sight", (1, 1), (-1, 0, 1, 2)),
        ("convert_global_to_local", (1, 1)),
        ("predict_current_fleet", (1, 1)),
        ("in_sight", (2, 2), (-1, 0, 1, 2)),
        ("convert_global_to_local", (2, 2)),
        ("predict_current_fleet", (2, 2)),
    ]


def test_locate_surface_uses_current_marker_when_no_fleet_is_detected() -> None:
    fleet = _Fleet()
    current = _Grid((3, 3), is_current_fleet=True)
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([]))
    fleet.map.set_select({"is_current_fleet": True}, _Selected([current]))

    result = _locate_surface(fleet)

    assert result == SurfaceFleetLocations(fleet_1=(3, 3), fleet_2=())


def test_locate_surface_observes_every_spawn_point_when_detection_is_missing() -> None:
    fleet = _Fleet()
    first = _Grid((1, 1))
    second = _Grid((2, 2))
    fleet.map.set_select({"is_fleet": True, "is_spawn_point": True}, _Selected([]))
    fleet.map.set_select({"is_current_fleet": True}, _Selected([]))
    fleet.map.set_select({"is_spawn_point": True}, _Selected([first, second]))
    fleet.local_fleet_results = {(1, 1): True, (2, 2): True}
    fleet.local_current_results = {(1, 1): False, (2, 2): True}

    result = _locate_surface(fleet, fleet_2_enabled=True)

    assert result == SurfaceFleetLocations(fleet_1=(2, 2), fleet_2=(1, 1))
    assert ("predict_fleet", (1, 1)) in fleet.calls
    assert ("predict_fleet", (2, 2)) in fleet.calls


def test_locate_submarine_infers_spawn_point_hidden_by_an_enemy() -> None:
    fleet = _Fleet()
    first = _Grid((1, 1), is_submarine_spawn_point=True)
    second = _Grid((2, 1), is_submarine_spawn_point=True)
    blocker = _Grid((1, 2), is_spawn_point=False)
    blocker.is_enemy = True
    fleet.map.set_select({"is_submarine_spawn_point": True}, _Selected([first, second]))
    fleet.map.set_select({"is_submarine": True}, _Selected([]))
    fleet.map.cover_results[(1, 1)] = _Selected([blocker])
    fleet.map.cover_results[(2, 1)] = _Selected([])
    fleet.map.cover_results[(1, 2)] = _Selected([first])

    result = STANDARD_CAMPAIGN_FLEET_LOCATOR.locate_submarine(
        cast("FleetLocationContext", fleet),
        enabled=True,
    )

    assert result == (1, 1)
