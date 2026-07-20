from typing import TYPE_CHECKING, Protocol

from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.map.map_grids import RoadGrids, SelectedGrids

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.application import CancellationSource
    from module.content.cell import CellId
    from module.content.mechanic_rules import RoadGroup, RoadPath
    from module.map_detection.grid_info import GridInfo


class _FleetCoordinationMap(Protocol):
    def __getitem__(self, item: tuple[int, int], /) -> GridInfo: ...


class _FleetCoordinationSource(Protocol):
    @property
    def map(self) -> _FleetCoordinationMap: ...

    def fleet_2_push_forward(self) -> bool: ...

    def fleet_2_break_siren_caught(self) -> bool: ...

    def fleet_2_protect(self) -> bool: ...

    def fleet_2_rescue(self, grid: GridInfo, /) -> bool: ...

    def fleet_2_step_on(
        self,
        grids: SelectedGrids[GridInfo],
        roadblocks: Iterable[RoadGrids[GridInfo]],
        /,
    ) -> bool: ...


class Mumu12FleetCoordinationDriver:
    """隔离当前地图运行中会协调多支舰队的复合战术原语。"""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: _FleetCoordinationSource) -> None:
        self._runtime = runtime

    def push_forward(self, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        return bool(self._runtime.fleet_2_push_forward())

    def break_siren_caught(self, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        return bool(self._runtime.fleet_2_break_siren_caught())

    def protect(self, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        return bool(self._runtime.fleet_2_protect())

    def rescue(self, target: CellId, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        return bool(self._runtime.fleet_2_rescue(self._grid(target)))

    def step_on(
        self,
        candidates: tuple[CellId, ...],
        roadblocks: tuple[RoadGroup, ...],
        cancellation: CancellationSource,
    ) -> bool:
        selected = SelectedGrids([self._grid(cell) for cell in candidates])
        roads = tuple(self._road_group(road.paths) for road in roadblocks)
        cancellation.raise_if_requested()
        return bool(self._runtime.fleet_2_step_on(selected, roads))

    def _grid(self, cell: CellId) -> GridInfo:
        try:
            return self._runtime.map[(cell.x, cell.y)]
        except KeyError:
            message = f"battle program references cell outside the active map: {cell}"
            raise BattleProgramMumu12AdapterError(message) from None

    def _road_group(self, paths: Iterable[RoadPath]) -> RoadGrids[GridInfo]:
        return RoadGrids([[self._grid(cell) for cell in path.cells] for path in paths])
