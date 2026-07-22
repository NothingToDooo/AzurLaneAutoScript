from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from module.adapters.battle_program_map_mutation_mumu12 import Mumu12MapMutationDriver
from module.adapters.battle_program_mumu12_contracts import (
    BattleProgramMumu12AdapterError,
    MapMutationDriver,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.application import CancellationSource


class _RequestedCancellationError(Exception):
    pass


class _Cancellation:
    def __init__(self, *, requested: bool = False) -> None:
        self.requested = requested

    def raise_if_requested(self) -> None:
        if self.requested:
            raise _RequestedCancellationError


@dataclass
class _Grid:
    may_siren: bool = False
    weight: float = 10.0


class _Map:
    def __init__(self, *, columns: int, rows: int) -> None:
        self.grids = {(x, y): _Grid() for y in range(rows) for x in range(columns)}

    def __iter__(self) -> Iterator[_Grid]:
        return iter(self.grids.values())

    def __getitem__(self, location: tuple[int, int]) -> _Grid:
        return self.grids[location]


@dataclass(frozen=True)
class _Shape:
    columns: int
    rows: int


@dataclass(frozen=True)
class _MapDefinition:
    shape: _Shape


@dataclass(frozen=True)
class _Definition:
    map: _MapDefinition


class _Runtime:
    def __init__(self, *, columns: int = 3, rows: int = 2) -> None:
        self.definition = _Definition(_MapDefinition(_Shape(columns, rows)))
        self.map = _Map(columns=columns, rows=rows)


def _driver(runtime: _Runtime) -> MapMutationDriver:
    return Mumu12MapMutationDriver(runtime)


def _cancellation(*, requested: bool = False) -> CancellationSource:
    return _Cancellation(requested=requested)


def test_marks_every_runtime_grid_as_a_siren_candidate() -> None:
    runtime = _Runtime()

    _driver(runtime).mark_all_siren_candidates(_cancellation())

    assert all(grid.may_siren for grid in runtime.map)


def test_cancellation_prevents_siren_candidate_mutation() -> None:
    runtime = _Runtime()

    with pytest.raises(_RequestedCancellationError):
        _driver(runtime).mark_all_siren_candidates(_cancellation(requested=True))

    assert all(not grid.may_siren for grid in runtime.map)


def test_sets_weights_in_row_major_map_coordinates() -> None:
    runtime = _Runtime()

    _driver(runtime).set_map_weights(((1, 2, 3), (4, 5, 6)), _cancellation())

    assert [runtime.map[(x, y)].weight for y in range(2) for x in range(3)] == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize(
    "rows",
    [
        ((1, 2, 3),),
        ((1, 2, 3), (4, 5)),
    ],
)
def test_invalid_weight_dimensions_do_not_partially_mutate(
    rows: tuple[tuple[int, ...], ...],
) -> None:
    runtime = _Runtime()

    with pytest.raises(BattleProgramMumu12AdapterError, match="map weight matrix must be 2x3"):
        _driver(runtime).set_map_weights(rows, _cancellation())

    assert [grid.weight for grid in runtime.map] == [10.0] * 6


def test_cancellation_prevents_weight_mutation_after_validation() -> None:
    runtime = _Runtime()

    with pytest.raises(_RequestedCancellationError):
        _driver(runtime).set_map_weights(((1, 2, 3), (4, 5, 6)), _cancellation(requested=True))

    assert [grid.weight for grid in runtime.map] == [10.0] * 6


def test_missing_runtime_grid_does_not_partially_mutate_weights() -> None:
    runtime = _Runtime()
    del runtime.map.grids[(1, 1)]

    with pytest.raises(KeyError):
        _driver(runtime).set_map_weights(((1, 2, 3), (4, 5, 6)), _cancellation())

    assert [grid.weight for grid in runtime.map] == [10.0] * 5
