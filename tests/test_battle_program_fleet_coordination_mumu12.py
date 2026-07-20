from typing import TYPE_CHECKING

import pytest

from module.adapters.battle_program_fleet_coordination_mumu12 import Mumu12FleetCoordinationDriver
from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.content.cell import CellId
from module.content.mechanic_rules import RoadGroup, RoadPath
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.map.map_grids import RoadGrids, SelectedGrids


A1 = CellId(0, 0)
B1 = CellId(1, 0)
C1 = CellId(2, 0)


class _Cancellation:
    @staticmethod
    def raise_if_requested() -> None:
        pass


class _Map:
    def __init__(self, grids: tuple[GridInfo, ...]) -> None:
        self.grids = {grid.location: grid for grid in grids}

    def __getitem__(self, location: tuple[int, int]) -> GridInfo:
        return self.grids[location]


class _Runtime:
    def __init__(self, grids: tuple[GridInfo, ...]) -> None:
        self.map = _Map(grids)
        self.events: list[object] = []

    def fleet_2_push_forward(self) -> bool:
        self.events.append("push_forward")
        return True

    def fleet_2_break_siren_caught(self) -> bool:
        self.events.append("break_siren_caught")
        return True

    def fleet_2_protect(self) -> bool:
        self.events.append("protect")
        return True

    def fleet_2_rescue(self, grid: GridInfo) -> bool:
        self.events.append(("rescue", grid.location))
        return True

    def fleet_2_step_on(
        self,
        grids: SelectedGrids[GridInfo],
        roadblocks: Iterable[RoadGrids[GridInfo]],
    ) -> bool:
        self.events.append(
            (
                "step_on",
                tuple(grids.location),
                tuple(tuple(path.location) for road in roadblocks for path in road.grids),
            )
        )
        return True


def _grid(cell: CellId) -> GridInfo:
    grid = GridInfo()
    grid.location = (cell.x, cell.y)
    return grid


def test_delegates_coordination_primitives_to_the_map_runtime() -> None:
    runtime = _Runtime((_grid(A1),))
    driver = Mumu12FleetCoordinationDriver(runtime)
    cancellation = _Cancellation()

    assert driver.push_forward(cancellation)
    assert driver.break_siren_caught(cancellation)
    assert driver.protect(cancellation)
    assert driver.rescue(A1, cancellation)
    assert runtime.events == [
        "push_forward",
        "break_siren_caught",
        "protect",
        ("rescue", (0, 0)),
    ]


def test_step_on_resolves_cells_and_road_paths_before_delegation() -> None:
    runtime = _Runtime((_grid(A1), _grid(B1), _grid(C1)))
    driver = Mumu12FleetCoordinationDriver(runtime)

    applied = driver.step_on(
        (A1, B1),
        (RoadGroup((RoadPath((B1, C1)),)),),
        _Cancellation(),
    )

    assert applied
    assert runtime.events == [
        (
            "step_on",
            ((0, 0), (1, 0)),
            (((1, 0), (2, 0)),),
        )
    ]


def test_rescue_rejects_a_cell_outside_the_active_map() -> None:
    driver = Mumu12FleetCoordinationDriver(_Runtime((_grid(A1),)))

    with pytest.raises(BattleProgramMumu12AdapterError, match="outside the active map"):
        driver.rescue(B1, _Cancellation())
