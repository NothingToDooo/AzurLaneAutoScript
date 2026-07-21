from typing import TYPE_CHECKING, Protocol, assert_never

from module.adapters.battle_program_mumu12_contracts import (
    BattleProgramMumu12AdapterError,
    FleetIndex,
)
from module.content.cell import CellId
from module.content.mechanic_rules import RoadblockAction, RoadblockMode, RoadblockSelection
from module.gameplay.campaign import EnemyPriorityMode
from module.map.map_grids import RoadGrids

if TYPE_CHECKING:
    from module.adapters.battle_program_read_mumu12 import (
        ProgramBattlefieldView,
        ProgramBattleSelectionContext,
        ProgramCellFacts,
    )
    from module.application import CancellationSource
    from module.map.map_grids import SelectedGrids
    from module.map_detection.grid_info import GridInfo


class _RoadblockMap(Protocol):
    def __getitem__(self, item: tuple[int, int], /) -> GridInfo: ...


class _RoadblockNavigation(Protocol):
    def find_roadblocks(
        self,
        grid: GridInfo,
        fleet: int | None = None,
    ) -> SelectedGrids[GridInfo]: ...


class Mumu12RoadblockRuntime(Protocol):
    @property
    def map(self) -> _RoadblockMap: ...

    @property
    def navigation(self) -> _RoadblockNavigation: ...


class _RoadblockReadModel(Protocol):
    def battlefield(self, cancellation: CancellationSource) -> ProgramBattlefieldView: ...

    def selection_context(self, cancellation: CancellationSource) -> ProgramBattleSelectionContext: ...


class Mumu12RoadblockPlanner:
    """把当前地图路障计算投影成只含 CellId 的确定性计划。"""

    __slots__ = ("_reads", "_runtime")

    def __init__(self, runtime: Mumu12RoadblockRuntime, reads: _RoadblockReadModel) -> None:
        self._runtime = runtime
        self._reads = reads

    def find_blockers(
        self,
        target: CellId,
        path_fleet: FleetIndex,
        cancellation: CancellationSource,
    ) -> tuple[CellId, ...]:
        """查找指定舰队通往目标格的最小阻挡集合。"""

        cancellation.raise_if_requested()
        target_grid = self._grid(target)
        cancellation.raise_if_requested()
        blockers = self._runtime.navigation.find_roadblocks(target_grid, fleet=path_fleet)

        cells: list[CellId] = []
        seen: set[CellId] = set()
        for blocker in blockers:
            cancellation.raise_if_requested()
            cell = self._cell(blocker)
            self._grid(cell)
            if cell not in seen:
                cells.append(cell)
                seen.add(cell)
        cancellation.raise_if_requested()
        return tuple(cells)

    def select_target(
        self,
        action: RoadblockAction,
        executor_fleet: FleetIndex,
        cancellation: CancellationSource,
    ) -> CellId | None:
        """选择应由执行舰队清理的格子，不执行移动或战斗。"""

        cancellation.raise_if_requested()
        candidate_cells = self._candidate_cells(action, cancellation)
        battlefield = self._reads.battlefield(cancellation)
        candidates = tuple(
            facts
            for cell in candidate_cells
            if (facts := battlefield.cell(cell)).is_enemy and facts.accessible_for(executor_fleet)
        )
        candidates = self._apply_selection(candidates, self._effective_selection(action, cancellation))
        cancellation.raise_if_requested()
        if not candidates:
            return None
        chosen = min(
            candidates,
            key=lambda facts: (
                facts.weight,
                facts.cost_for(executor_fleet),
                facts.cell,
            ),
        )
        return chosen.cell

    def _candidate_cells(
        self,
        action: RoadblockAction,
        cancellation: CancellationSource,
    ) -> tuple[CellId, ...]:
        candidates: list[GridInfo] = []
        for road in action.roads:
            cancellation.raise_if_requested()
            road_grids = RoadGrids([[self._grid(cell) for cell in path.cells] for path in road.paths])
            if action.mode is RoadblockMode.CLEAR:
                candidates.extend(road_grids.roadblocks())
            elif action.mode is RoadblockMode.CLEAR_POTENTIAL:
                candidates.extend(road_grids.potential_roadblocks())
            elif action.mode is RoadblockMode.CLEAR_FIRST:
                candidates.extend(road_grids.first_roadblocks())
            elif action.mode is RoadblockMode.CLEAR_FOR_FASTER:
                candidates.extend(self._grid(cell) for cell in road.referenced_cells)
            else:
                assert_never(action.mode)

        cells: list[CellId] = []
        seen: set[CellId] = set()
        for grid in candidates:
            cancellation.raise_if_requested()
            cell = self._cell(grid)
            if cell not in seen:
                cells.append(cell)
                seen.add(cell)
        return tuple(cells)

    def _effective_selection(
        self,
        action: RoadblockAction,
        cancellation: CancellationSource,
    ) -> RoadblockSelection:
        if action.selection is not RoadblockSelection.DEFAULT:
            return action.selection
        if action.mode not in (RoadblockMode.CLEAR, RoadblockMode.CLEAR_POTENTIAL):
            return RoadblockSelection.DEFAULT
        context = self._reads.selection_context(cancellation)
        if context.enemy_priority is EnemyPriorityMode.LARGE_ENEMY_FIRST:
            return RoadblockSelection.STRONGEST
        if context.enemy_priority is EnemyPriorityMode.SMALL_ENEMY_FIRST:
            return RoadblockSelection.WEAKEST
        if context.clear_all:
            return RoadblockSelection.STRONGEST
        return RoadblockSelection.DEFAULT

    @staticmethod
    def _apply_selection(
        candidates: tuple[ProgramCellFacts, ...],
        selection: RoadblockSelection,
    ) -> tuple[ProgramCellFacts, ...]:
        if selection is RoadblockSelection.DEFAULT:
            return candidates
        if selection is RoadblockSelection.WEAKEST:
            scale_order = (1, 2, 3, 0)
        elif selection is RoadblockSelection.STRONGEST:
            scale_order = (3, 2, 1, 0)
        else:
            assert_never(selection)

        for scale in scale_order:
            selected = tuple(candidate for candidate in candidates if candidate.enemy_scale == scale)
            if selected:
                return selected
        return candidates

    def _grid(self, cell: CellId) -> GridInfo:
        try:
            return self._runtime.map[(cell.x, cell.y)]
        except KeyError:
            message = f"battle program references cell outside the active map: {cell}"
            raise BattleProgramMumu12AdapterError(message) from None

    @staticmethod
    def _cell(grid: GridInfo) -> CellId:
        location = grid.location
        if (
            not isinstance(location, tuple)
            or len(location) != 2
            or type(location[0]) is not int
            or type(location[1]) is not int
            or location[0] < 0
            or location[1] < 0
        ):
            message = "roadblock runtime returned a grid without a valid map location"
            raise BattleProgramMumu12AdapterError(message)
        return CellId(*location)
