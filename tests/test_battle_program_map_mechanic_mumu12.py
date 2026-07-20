from typing import TYPE_CHECKING

import pytest

from module.adapters.battle_program_map_mechanic_mumu12 import Mumu12MapMechanicDriver
from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.content.cell import CellId
from module.exception import MapEnemyMoved
from module.map.map_grids import SelectedGrids
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.application import CancellationSource


A1 = CellId(0, 0)
B1 = CellId(1, 0)


class _RequestedCancellationError(Exception):
    pass


class _Cancellation:
    def __init__(self, events: list[object], *, requested: bool = False) -> None:
        self.events = events
        self.requested = requested

    def raise_if_requested(self) -> None:
        self.events.append("cancellation")
        if self.requested:
            raise _RequestedCancellationError


class _Map:
    def __init__(self, grids: list[GridInfo]) -> None:
        self.grids = {grid.location: grid for grid in grids}

    def __getitem__(self, location: tuple[int, int]) -> GridInfo:
        return self.grids[location]

    def select(self, **criteria: object) -> SelectedGrids[GridInfo]:
        selected = self.grids.values()
        for name, value in criteria.items():
            selected = [grid for grid in selected if getattr(grid, name) == value]
        return SelectedGrids(selected)


class _Runtime:
    def __init__(self, grids: list[GridInfo]) -> None:
        self.events: list[object] = []
        self.map = _Map(grids)
        self.cancellation: _Cancellation | None = None
        self.full_scan_error: BaseException | None = None
        self.find_path_error: BaseException | None = None
        self.bouncing_error: BaseException | None = None
        self.bouncing_result = False

    def clear_mechanism(self, grids: SelectedGrids[GridInfo] | None = None) -> bool:
        candidates = (
            self.map.select(is_mechanism_trigger=True) if grids is None else grids.select(is_mechanism_trigger=True)
        )
        self.events.append(("clear_mechanism", candidates.location))
        if not candidates:
            return False
        candidates[0].is_mechanism_trigger = False
        if self.cancellation is not None:
            self.cancellation.requested = True
        raise MapEnemyMoved

    def full_scan(self) -> None:
        self.events.append("full_scan")
        if self.full_scan_error is not None:
            raise self.full_scan_error

    def find_path_initial(self) -> None:
        self.events.append("find_path_initial")
        if self.find_path_error is not None:
            raise self.find_path_error

    def clear_bouncing_enemy(self) -> bool:
        self.events.append("clear_bouncing_enemy")
        if self.cancellation is not None:
            self.cancellation.requested = True
        if self.bouncing_error is not None:
            raise self.bouncing_error
        return self.bouncing_result


def _grid(cell: CellId, *, mechanism: bool = False) -> GridInfo:
    grid = GridInfo()
    grid.location = (cell.x, cell.y)
    grid.is_mechanism_trigger = mechanism
    return grid


def _driver(runtime: _Runtime) -> Mumu12MapMechanicDriver:
    return Mumu12MapMechanicDriver(runtime)


def _cancellation(runtime: _Runtime, *, requested: bool = False) -> CancellationSource:
    return _Cancellation(runtime.events, requested=requested)


def test_triggers_each_requested_mechanism_and_refreshes_its_projection() -> None:
    runtime = _Runtime([_grid(A1, mechanism=True), _grid(B1, mechanism=True)])

    applied = _driver(runtime).trigger_mechanisms((A1, B1), _cancellation(runtime))

    assert applied
    assert runtime.events == [
        "cancellation",
        ("clear_mechanism", [(0, 0), (1, 0)]),
        "full_scan",
        "find_path_initial",
        "cancellation",
        "cancellation",
        ("clear_mechanism", [(1, 0)]),
        "full_scan",
        "find_path_initial",
        "cancellation",
    ]


def test_cancellation_after_mechanism_commit_waits_for_projection_refresh() -> None:
    runtime = _Runtime([_grid(A1, mechanism=True)])
    cancellation = _Cancellation(runtime.events)
    runtime.cancellation = cancellation

    with pytest.raises(_RequestedCancellationError):
        _driver(runtime).trigger_mechanisms(
            (A1,),
            cancellation,
        )

    assert runtime.events == [
        "cancellation",
        ("clear_mechanism", [(0, 0)]),
        "full_scan",
        "find_path_initial",
        "cancellation",
    ]


@pytest.mark.parametrize("failure_stage", ["full_scan", "find_path_initial"])
def test_mechanism_refresh_failure_is_not_reported_as_success(failure_stage: str) -> None:
    runtime = _Runtime([_grid(A1, mechanism=True)])
    error = RuntimeError(f"{failure_stage} failed")
    if failure_stage == "full_scan":
        runtime.full_scan_error = error
    else:
        runtime.find_path_error = error

    with pytest.raises(RuntimeError, match=f"{failure_stage} failed") as raised:
        _driver(runtime).trigger_mechanisms((A1,), _cancellation(runtime))

    assert raised.value is error
    assert runtime.events[:3] == [
        "cancellation",
        ("clear_mechanism", [(0, 0)]),
        "full_scan",
    ]
    if failure_stage == "full_scan":
        assert runtime.events == [
            "cancellation",
            ("clear_mechanism", [(0, 0)]),
            "full_scan",
        ]
    else:
        assert runtime.events == [
            "cancellation",
            ("clear_mechanism", [(0, 0)]),
            "full_scan",
            "find_path_initial",
        ]


def test_all_requested_cells_are_resolved_before_mechanism_io() -> None:
    runtime = _Runtime([_grid(A1, mechanism=True)])

    with pytest.raises(BattleProgramMumu12AdapterError, match="outside the active map"):
        _driver(runtime).trigger_mechanisms((A1, B1), _cancellation(runtime))

    assert runtime.events == []
    assert runtime.map[(0, 0)].is_mechanism_trigger


def test_pre_requested_cancellation_prevents_mechanism_io() -> None:
    runtime = _Runtime([_grid(A1, mechanism=True)])

    with pytest.raises(_RequestedCancellationError):
        _driver(runtime).trigger_mechanisms(
            (A1,),
            _cancellation(runtime, requested=True),
        )

    assert runtime.events == ["cancellation"]
    assert runtime.map[(0, 0)].is_mechanism_trigger


def test_clear_bouncing_enemy_checks_cancellation_around_the_closed_action() -> None:
    runtime = _Runtime([])
    runtime.bouncing_result = True

    assert _driver(runtime).clear_bouncing_enemy(_cancellation(runtime))
    assert runtime.events == ["cancellation", "clear_bouncing_enemy", "cancellation"]


def test_clear_bouncing_enemy_does_not_hide_failure() -> None:
    runtime = _Runtime([])
    error = RuntimeError("bouncing refresh failed")
    runtime.bouncing_error = error

    with pytest.raises(RuntimeError, match="bouncing refresh failed") as raised:
        _driver(runtime).clear_bouncing_enemy(_cancellation(runtime))

    assert raised.value is error
    assert runtime.events == ["cancellation", "clear_bouncing_enemy"]


def test_clear_bouncing_enemy_observes_cancellation_only_after_runtime_closes_action() -> None:
    runtime = _Runtime([])
    runtime.bouncing_result = True
    cancellation = _Cancellation(runtime.events)
    runtime.cancellation = cancellation

    with pytest.raises(_RequestedCancellationError):
        _driver(runtime).clear_bouncing_enemy(cancellation)

    assert runtime.events == ["cancellation", "clear_bouncing_enemy", "cancellation"]
