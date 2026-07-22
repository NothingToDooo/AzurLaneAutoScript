from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.adapters.battle_program_read_mumu12 import (
    ProgramBattlefieldView,
    ProgramBattleSelectionContext,
    ProgramCellFacts,
)
from module.adapters.battle_program_roadblock_mumu12 import Mumu12RoadblockPlanner
from module.content.battle_policy import EnemyFilterEntry
from module.content.cell import CellId
from module.content.mechanic_rules import (
    RoadblockAction,
    RoadblockMode,
    RoadblockSelection,
    RoadGroup,
    RoadPath,
)
from module.gameplay.campaign import EnemyPriorityMode
from module.map.map_grids import SelectedGrids
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.adapters.battle_program_mumu12_contracts import FleetIndex
    from module.application import CancellationSource


A1 = CellId(0, 0)
B1 = CellId(1, 0)
C1 = CellId(2, 0)
D1 = CellId(3, 0)
E1 = CellId(4, 0)
F1 = CellId(5, 0)


@dataclass(slots=True)
class _Cancellation:
    requested: bool = False
    checks: int = 0

    def raise_if_requested(self) -> None:
        self.checks += 1
        if self.requested:
            message = "cancelled"
            raise RuntimeError(message)


class _Map:
    def __init__(self, grids: tuple[GridInfo, ...]) -> None:
        self._by_location = {grid.location: grid for grid in grids}

    def __getitem__(self, item: tuple[int, int]) -> GridInfo:
        return self._by_location[item]


class _Navigation:
    def __init__(self, blockers: tuple[GridInfo, ...]) -> None:
        self.blockers = blockers
        self.find_calls: list[tuple[tuple[int, int] | None, int | None]] = []

    def find_roadblocks(
        self,
        grid: GridInfo,
        fleet: int | None = None,
    ) -> SelectedGrids[GridInfo]:
        self.find_calls.append((grid.location, fleet))
        return SelectedGrids(self.blockers)


class _Runtime:
    def __init__(self, grids: tuple[GridInfo, ...], blockers: tuple[GridInfo, ...] = ()) -> None:
        self.map = _Map(grids)
        self.navigation = _Navigation(blockers)


class _Reads:
    def __init__(
        self,
        grids: tuple[GridInfo, ...],
        *,
        enemy_priority: EnemyPriorityMode = EnemyPriorityMode.DEFAULT,
        clear_all: bool = False,
    ) -> None:
        self._grids = grids
        self._enemy_priority = enemy_priority
        self._clear_all = clear_all
        self.calls = 0
        self.context_calls = 0

    def battlefield(self, cancellation: CancellationSource) -> ProgramBattlefieldView:
        cancellation.raise_if_requested()
        self.calls += 1
        return ProgramBattlefieldView(tuple(_facts(grid) for grid in self._grids))

    def selection_context(self, cancellation: CancellationSource) -> ProgramBattleSelectionContext:
        cancellation.raise_if_requested()
        self.context_calls += 1
        return ProgramBattleSelectionContext(
            executor_fleet=1,
            enemy_priority=self._enemy_priority,
            clear_all=self._clear_all,
            movable_normal_enemy=False,
            default_enemy_filter=(EnemyFilterEntry(1, "E"),),
        )


def _grid(
    cell: CellId,
    **attributes: bool | float,
) -> GridInfo:
    grid = GridInfo()
    grid.location = (cell.x, cell.y)
    grid.cost_1 = 1
    grid.cost_2 = 1
    for name, value in attributes.items():
        setattr(grid, name, value)
    return grid


def _facts(grid: GridInfo) -> ProgramCellFacts:
    if grid.location is None:
        message = "test grid requires a location"
        raise AssertionError(message)
    return ProgramCellFacts(
        cell=CellId(*grid.location),
        weight=grid.weight,
        cost_1=grid.cost_1,
        cost_2=grid.cost_2,
        is_enemy=grid.is_enemy,
        is_siren=grid.is_siren,
        is_boss=grid.is_boss,
        is_fortress=grid.is_fortress,
        is_mystery=grid.is_mystery,
        may_ammo=grid.may_ammo,
        enemy_scale=grid.enemy_scale,
        enemy_genre=grid.enemy_genre or "",
    )


def _action(
    mode: RoadblockMode,
    paths: tuple[tuple[CellId, ...], ...],
    selection: RoadblockSelection = RoadblockSelection.DEFAULT,
) -> RoadblockAction:
    return RoadblockAction(
        battle=0,
        mode=mode,
        roads=(RoadGroup(tuple(RoadPath(path) for path in paths)),),
        selection=selection,
    )


def _planner(
    grids: tuple[GridInfo, ...],
    blockers: tuple[GridInfo, ...] = (),
    *,
    enemy_priority: EnemyPriorityMode = EnemyPriorityMode.DEFAULT,
    clear_all: bool = False,
) -> tuple[Mumu12RoadblockPlanner, _Runtime, _Reads]:
    runtime = _Runtime(grids, blockers)
    reads = _Reads(grids, enemy_priority=enemy_priority, clear_all=clear_all)
    return Mumu12RoadblockPlanner(runtime, reads), runtime, reads


def test_find_blockers_uses_explicit_path_fleet_and_returns_cell_ids() -> None:
    grids = (_grid(A1), _grid(B1, is_enemy=True), _grid(C1, is_enemy=True))
    planner, runtime, _reads = _planner(grids, (grids[1], grids[2], grids[1]))

    blockers = planner.find_blockers(A1, 2, _Cancellation())

    assert blockers == (B1, C1)
    assert runtime.navigation.find_calls == [((0, 0), 2)]


def test_find_blockers_honors_cancellation_before_runtime_io() -> None:
    grids = (_grid(A1),)
    planner, runtime, _reads = _planner(grids)

    with pytest.raises(RuntimeError, match="cancelled"):
        planner.find_blockers(A1, 1, _Cancellation(requested=True))

    assert runtime.navigation.find_calls == []


def test_find_blockers_rejects_target_outside_active_map() -> None:
    planner, runtime, _reads = _planner((_grid(A1),))

    with pytest.raises(BattleProgramMumu12AdapterError, match="outside the active map: B1"):
        planner.find_blockers(B1, 1, _Cancellation())

    assert runtime.navigation.find_calls == []


def test_select_target_rejects_road_cell_outside_active_map() -> None:
    planner, _runtime, reads = _planner((_grid(A1, is_enemy=True),))
    action = _action(RoadblockMode.CLEAR, ((B1,),))

    with pytest.raises(BattleProgramMumu12AdapterError, match="outside the active map: B1"):
        planner.select_target(action, 1, _Cancellation())

    assert reads.calls == 0
    assert reads.context_calls == 0


def test_select_target_honors_cancellation_before_planning() -> None:
    planner, _runtime, reads = _planner((_grid(A1, is_enemy=True),))
    action = _action(RoadblockMode.CLEAR, ((A1,),))

    with pytest.raises(RuntimeError, match="cancelled"):
        planner.select_target(action, 1, _Cancellation(requested=True))

    assert reads.calls == 0
    assert reads.context_calls == 0


def test_clear_selects_only_fully_blocked_paths() -> None:
    grids = (
        _grid(A1, is_enemy=True, weight=2),
        _grid(B1, is_enemy=True, weight=1),
        _grid(C1, is_enemy=True, weight=0),
        _grid(D1),
    )
    planner, _runtime, _reads = _planner(grids)
    action = _action(RoadblockMode.CLEAR, ((A1, B1), (C1, D1)))

    assert planner.select_target(action, 1, _Cancellation()) == B1


def test_clear_potential_selects_paths_with_exactly_one_open_cell() -> None:
    grids = (
        _grid(A1, is_enemy=True, weight=2),
        _grid(B1, is_enemy=True, weight=1),
        _grid(C1),
        _grid(D1, is_enemy=True, weight=0),
        _grid(E1),
        _grid(F1),
    )
    planner, _runtime, _reads = _planner(grids)
    action = _action(RoadblockMode.CLEAR_POTENTIAL, ((A1, B1, C1), (D1, E1, F1)))

    assert planner.select_target(action, 1, _Cancellation()) == B1


def test_clear_first_skips_paths_already_occupied_or_cleared() -> None:
    grids = (
        _grid(A1, is_enemy=True, weight=2),
        _grid(B1),
        _grid(C1, is_enemy=True, weight=0),
        _grid(D1, is_fleet=True),
        _grid(E1, is_enemy=True, weight=0),
        _grid(F1, is_cleared=True),
    )
    planner, _runtime, _reads = _planner(grids)
    action = _action(RoadblockMode.CLEAR_FIRST, ((A1, B1), (C1, D1), (E1, F1)))

    assert planner.select_target(action, 1, _Cancellation()) == A1


def test_clear_for_faster_selects_only_enemy_references() -> None:
    grids = (
        _grid(A1, weight=0),
        _grid(B1, is_enemy=True, weight=2),
        _grid(C1, is_enemy=True, weight=1),
    )
    planner, _runtime, _reads = _planner(grids)
    action = _action(RoadblockMode.CLEAR_FOR_FASTER, ((A1, B1, C1),))

    assert planner.select_target(action, 1, _Cancellation()) == C1


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        (RoadblockSelection.DEFAULT, B1),
        (RoadblockSelection.WEAKEST, A1),
        (RoadblockSelection.STRONGEST, B1),
    ],
)
def test_select_target_applies_declared_enemy_scale_selection(
    selection: RoadblockSelection,
    expected: CellId,
) -> None:
    grids = (
        _grid(A1, is_enemy=True, enemy_scale=1, weight=10),
        _grid(B1, is_enemy=True, enemy_scale=3, weight=1),
    )
    planner, _runtime, _reads = _planner(grids)
    action = _action(RoadblockMode.CLEAR, ((A1,), (B1,)), selection)

    assert planner.select_target(action, 1, _Cancellation()) == expected


@pytest.mark.parametrize(("executor_fleet", "expected"), [(1, A1), (2, B1)])
def test_select_target_uses_executor_fleet_accessibility_and_cost(
    executor_fleet: FleetIndex,
    expected: CellId,
) -> None:
    grids = (
        _grid(A1, is_enemy=True, weight=1, cost_1=2, cost_2=9999),
        _grid(B1, is_enemy=True, weight=1, cost_1=5, cost_2=1),
    )
    planner, _runtime, _reads = _planner(grids)
    action = _action(RoadblockMode.CLEAR, ((A1,), (B1,)))

    assert planner.select_target(action, executor_fleet, _Cancellation()) == expected


def test_select_target_returns_none_when_executor_cannot_reach_a_candidate() -> None:
    grids = (_grid(A1, is_enemy=True, cost_1=9999),)
    planner, _runtime, _reads = _planner(grids)
    action = _action(RoadblockMode.CLEAR, ((A1,),))

    assert planner.select_target(action, 1, _Cancellation()) is None


@pytest.mark.parametrize("mode", [RoadblockMode.CLEAR, RoadblockMode.CLEAR_POTENTIAL])
@pytest.mark.parametrize(
    "policy",
    [
        (EnemyPriorityMode.LARGE_ENEMY_FIRST, False),
        (EnemyPriorityMode.DEFAULT, True),
    ],
)
def test_global_strongest_policy_applies_to_configured_priority_modes(
    mode: RoadblockMode,
    policy: tuple[EnemyPriorityMode, bool],
) -> None:
    enemy_priority, clear_all = policy
    grids = (
        _grid(A1, is_enemy=True, enemy_scale=1, weight=1),
        _grid(B1, is_enemy=True, enemy_scale=3, weight=2),
        _grid(C1),
        _grid(D1),
    )
    paths = ((A1,), (B1,)) if mode is RoadblockMode.CLEAR else ((A1, C1), (B1, D1))
    planner, _runtime, _reads = _planner(
        grids,
        enemy_priority=enemy_priority,
        clear_all=clear_all,
    )

    assert planner.select_target(_action(mode, paths), 1, _Cancellation()) == B1


def test_explicit_selection_overrides_global_enemy_priority_and_clear_all() -> None:
    grids = (
        _grid(A1, is_enemy=True, enemy_scale=1, weight=10),
        _grid(B1, is_enemy=True, enemy_scale=3, weight=1),
    )
    planner, _runtime, reads = _planner(
        grids,
        enemy_priority=EnemyPriorityMode.LARGE_ENEMY_FIRST,
        clear_all=True,
    )
    action = _action(RoadblockMode.CLEAR, ((A1,), (B1,)), RoadblockSelection.WEAKEST)

    assert planner.select_target(action, 1, _Cancellation()) == A1
    assert reads.context_calls == 0


def test_small_enemy_priority_takes_precedence_over_clear_all() -> None:
    grids = (
        _grid(A1, is_enemy=True, enemy_scale=1, weight=10),
        _grid(B1, is_enemy=True, enemy_scale=3, weight=1),
    )
    planner, _runtime, _reads = _planner(
        grids,
        enemy_priority=EnemyPriorityMode.SMALL_ENEMY_FIRST,
        clear_all=True,
    )

    assert (
        planner.select_target(
            _action(RoadblockMode.CLEAR, ((A1,), (B1,))),
            1,
            _Cancellation(),
        )
        == A1
    )


@pytest.mark.parametrize("mode", [RoadblockMode.CLEAR_FIRST, RoadblockMode.CLEAR_FOR_FASTER])
def test_global_enemy_priority_and_clear_all_do_not_change_other_modes(mode: RoadblockMode) -> None:
    grids = (
        _grid(A1, is_enemy=True, enemy_scale=1, weight=1),
        _grid(B1, is_enemy=True, enemy_scale=3, weight=2),
    )
    planner, _runtime, reads = _planner(
        grids,
        enemy_priority=EnemyPriorityMode.LARGE_ENEMY_FIRST,
        clear_all=True,
    )

    assert (
        planner.select_target(
            _action(mode, ((A1,), (B1,))),
            1,
            _Cancellation(),
        )
        == A1
    )
    assert reads.context_calls == 0
