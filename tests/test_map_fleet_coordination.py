import itertools
from typing import TYPE_CHECKING, Literal, cast, override

from module.map.fleet_navigation import FleetNavigationSnapshot
from module.map.map import Map
from module.map.map_grids import RoadGrids, SelectedGrids
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.map.fleet_navigation import FleetNavigationController
    from module.map.type_alias import FleetLocation, GridLocation


class _Config:
    fleet_2 = True
    fleet_boss = 2
    MAP_HAS_SIREN = True
    MAP_HAS_MOVABLE_ENEMY = True
    MAP_HAS_MOVABLE_NORMAL_ENEMY = False
    MAP_CLEAR_ALL_THIS_TIME = False
    EnemyPriority_EnemyScaleBalanceWeight = "default"


class _MapLayout:
    def __init__(self, grids: list[GridInfo]) -> None:
        self._grids = grids
        self._by_location = {grid.location: grid for grid in grids}

    def __iter__(self) -> Iterator[GridInfo]:
        return iter(self._grids)

    def __getitem__(self, location: GridLocation) -> GridInfo:
        return self._by_location[location]

    def select(self, **criteria: object) -> SelectedGrids[GridInfo]:
        return SelectedGrids(
            [
                grid
                for grid in self._grids
                if all(getattr(grid, field) == expected for field, expected in criteria.items())
            ]
        )


class _MapState:
    def __init__(self, grids: list[GridInfo]) -> None:
        self.layout = _MapLayout(grids)

    def __iter__(self) -> Iterator[GridInfo]:
        return iter(self.layout)

    def __getitem__(self, location: GridLocation) -> GridInfo:
        return self.layout[location]


class _Navigation:
    def __init__(self, campaign: _CoordinationCampaign) -> None:
        self._campaign = campaign
        self._fleet_1: FleetLocation = (0, 0)
        self._fleet_2: FleetLocation = (1, 0)
        self._current_index: Literal[1, 2] = 1

    @property
    def snapshot(self) -> FleetNavigationSnapshot:
        return FleetNavigationSnapshot(
            fleet_1=self._fleet_1,
            fleet_2=self._fleet_2,
            submarine=(),
            current_index=self._current_index,
            shown_index=self._current_index,
        )

    @property
    def current_index(self) -> Literal[1, 2]:
        return self._current_index

    @property
    def boss_index(self) -> Literal[1, 2]:
        return 2

    def seed_surface(self, *, fleet_1: FleetLocation, fleet_2: FleetLocation = ()) -> None:
        self._fleet_1 = fleet_1
        self._fleet_2 = fleet_2

    def record_fleet_2(self, location: GridLocation) -> None:
        self._fleet_2 = location

    def activate(self, index: int) -> bool:
        target = self._normalize_index(index)
        if target == self._current_index:
            return False
        self._campaign.events.append(("activate", target))
        self._current_index = target
        self.rebuild_paths()
        return True

    @staticmethod
    def _normalize_index(index: int | str) -> Literal[1, 2]:
        if index in {1, "1"}:
            return 1
        if index in {2, "2"}:
            return 2
        message = f"invalid fleet index: {index}"
        raise ValueError(message)

    def goto(
        self,
        location: GridInfo | str | GridLocation,
        expected: str = "",
        *,
        step_optimize: bool | None = None,
        turning_optimize: bool | None = None,
    ) -> None:
        del step_optimize, turning_optimize
        assert isinstance(location, GridInfo)
        assert location.location is not None
        self._campaign.events.append(("goto", self._current_index, location.location, expected))
        if self._current_index == 1:
            self._fleet_1 = location.location
        else:
            self._fleet_2 = location.location

    def rebuild_paths(self) -> None:
        self._campaign.project_paths(record=True)

    def is_at(self, grid: GridInfo, fleet: int | None = None) -> bool:
        index = self._current_index if fleet is None else fleet
        location = self._fleet_1 if index == 1 else self._fleet_2
        return location == grid.location

    def is_accessible(self, grid: GridInfo, fleet: int | str | None = None) -> bool:
        index = self._current_index if fleet is None else self._normalize_index(fleet)
        backup = self._current_index
        if index != backup:
            self._current_index = index
            self.rebuild_paths()
        try:
            return grid.is_accessible
        finally:
            if self._current_index != backup:
                self._current_index = backup
                self.rebuild_paths()

    def find_roadblocks(self, grid: GridInfo, fleet: int | None = None) -> SelectedGrids[GridInfo]:
        index = self._current_index if fleet is None else self._normalize_index(fleet)
        backup = self._current_index
        if index != backup:
            self._current_index = index
            self.rebuild_paths()
        try:
            if grid.is_accessible:
                return SelectedGrids([])
            enemies = self._campaign.map.layout.select(is_enemy=True)
            for repeat in range(1, enemies.count + 1):
                for selection in itertools.combinations(enemies, repeat):
                    try:
                        for blocker in selection:
                            blocker.is_enemy = False
                        self.rebuild_paths()
                        accessible = grid.is_accessible
                    finally:
                        for blocker in selection:
                            blocker.is_enemy = True
                        self.rebuild_paths()
                    if accessible:
                        return SelectedGrids(list(selection))
            return SelectedGrids([])
        finally:
            if self._current_index != backup:
                self._current_index = backup
                self.rebuild_paths()


class _CoordinationCampaign(Map):
    config: _Config
    map: _MapState

    def __init__(self, grids: list[GridInfo]) -> None:
        self.config = _Config()
        self.map = _MapState(grids)
        self.battle_count = 0
        self.events: list[tuple[object, ...]] = []
        self.path_projections: list[tuple[int, bool | None]] = []
        self.rescue_target: GridInfo | None = None
        self.rescue_blocker: GridInfo | None = None
        self._base_costs = {grid.location: (grid.cost_1, grid.cost_2) for grid in grids}
        self.navigation = cast("FleetNavigationController", _Navigation(self))
        self.project_paths(record=False)

    def project_paths(self, *, record: bool) -> None:
        blocker_present = self.rescue_blocker.is_enemy if self.rescue_blocker is not None else None
        for grid in self.map.layout:
            cost_1, cost_2 = self._base_costs[grid.location]
            if grid is self.rescue_target and blocker_present is False:
                cost_2 = 1
            grid.cost_1 = cost_1
            grid.cost_2 = cost_2
            grid.cost = cost_1 if self.navigation.current_index == 1 else cost_2
        if record:
            self.path_projections.append((self.navigation.current_index, blocker_present))

    @override
    def clear_chosen_enemy(self, grid: GridInfo, expected: str = "") -> bool:
        assert grid.location is not None
        current_index = self.navigation.current_index
        self.events.append(("clear", current_index, grid.location, expected))
        if current_index == 1:
            self.navigation.seed_surface(fleet_1=grid.location, fleet_2=self.navigation.snapshot.fleet_2)
        else:
            self.navigation.record_fleet_2(grid.location)
        grid.is_enemy = False
        grid.is_siren = False
        grid.is_boss = False
        return True

    @override
    def ensure_edge_insight(
        self,
        *,
        reverse: bool = False,
        preset: GridLocation | None = None,
        swipe_limit: GridLocation = (3, 2),
        skip_first_update: bool = True,
    ) -> list[GridLocation]:
        del reverse, preset, swipe_limit, skip_first_update
        self.events.append(("ensure_edge_insight", self.navigation.current_index))
        return []


def _grid(
    location: tuple[int, int],
    *,
    cost_1: int = 1,
    cost_2: int = 1,
) -> GridInfo:
    grid = GridInfo()
    grid.location = location
    grid.cost = cost_1
    grid.cost_1 = cost_1
    grid.cost_2 = cost_2
    grid.weight = 1
    grid.is_enemy = False
    grid.is_siren = False
    grid.is_caught_by_siren = False
    grid.is_cleared = False
    grid.is_mystery = False
    grid.is_fleet = False
    return grid


def test_step_on_uses_fleet_2_path_and_move_then_restores_fleet_1() -> None:
    fleet_1 = _grid((0, 0))
    fleet_2 = _grid((1, 0))
    destination = _grid((2, 0), cost_1=9999, cost_2=1)
    campaign = _CoordinationCampaign([fleet_1, fleet_2, destination])

    applied = campaign.fleet_2_step_on(SelectedGrids([destination]), ())

    assert not applied
    assert campaign.path_projections[:2] == [(2, None), (1, None)]
    assert campaign.events == [
        ("activate", 2),
        ("goto", 2, (2, 0), ""),
        ("activate", 1),
    ]
    assert campaign.navigation.snapshot.fleet_2 == (2, 0)
    assert campaign.navigation.current_index == 1


def test_step_on_uses_fleet_1_to_clear_a_blocked_fleet_2_route() -> None:
    fleet_1 = _grid((0, 0))
    fleet_2 = _grid((1, 0))
    destination = _grid((2, 0), cost_2=9999)
    blocker = _grid((3, 0), cost_1=1, cost_2=9999)
    blocker.is_enemy = True
    campaign = _CoordinationCampaign([fleet_1, fleet_2, destination, blocker])
    road = RoadGrids([[blocker]])

    applied = campaign.fleet_2_step_on(SelectedGrids([destination]), (road,))

    assert applied
    assert campaign.path_projections == [(2, None), (1, None)]
    assert campaign.events == [("clear", 1, (3, 0), "")]
    assert campaign.navigation.current_index == 1


def test_break_siren_caught_clears_with_fleet_2_then_restores_fleet_1() -> None:
    fleet_1 = _grid((0, 0))
    caught = _grid((1, 0))
    caught.is_siren = True
    caught.is_caught_by_siren = True
    campaign = _CoordinationCampaign([fleet_1, caught])

    applied = campaign.fleet_2_break_siren_caught()

    assert applied
    assert campaign.events == [
        ("activate", 2),
        ("ensure_edge_insight", 2),
        ("clear", 2, (1, 0), ""),
        ("activate", 1),
    ]
    assert not caught.is_caught_by_siren
    assert campaign.navigation.current_index == 1


def test_rescue_finds_the_fleet_2_blocker_but_clears_it_with_fleet_1() -> None:
    fleet_1 = _grid((0, 0))
    fleet_2 = _grid((1, 0))
    blocker = _grid((2, 0), cost_1=1, cost_2=1)
    blocker.is_enemy = True
    target = _grid((3, 0), cost_1=9999, cost_2=9999)
    campaign = _CoordinationCampaign([fleet_1, fleet_2, blocker, target])
    campaign.rescue_target = target
    campaign.rescue_blocker = blocker

    applied = campaign.fleet_2_rescue(target)

    assert applied
    assert campaign.path_projections == [
        (2, True),
        (2, False),
        (2, True),
        (1, True),
    ]
    assert campaign.events == [("clear", 1, (2, 0), "")]
    assert campaign.navigation.current_index == 1


def test_protect_selects_by_fleet_2_cost_but_clears_with_active_fleet_1() -> None:
    fleet_1 = _grid((0, 0))
    fleet_2 = _grid((1, 0))
    near_fleet_2 = _grid((2, 0), cost_1=5, cost_2=1)
    near_fleet_2.is_siren = True
    near_fleet_1 = _grid((3, 0), cost_1=1, cost_2=2)
    near_fleet_1.is_siren = True
    campaign = _CoordinationCampaign([fleet_1, fleet_2, near_fleet_2, near_fleet_1])

    applied = campaign.fleet_2_protect()

    assert applied
    assert campaign.events == [("clear", 1, (2, 0), "siren")]
    assert campaign.navigation.current_index == 1
