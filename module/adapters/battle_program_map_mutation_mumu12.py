from typing import TYPE_CHECKING, Protocol

from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.application import CancellationSource


class _MutableMapGrid(Protocol):
    may_siren: bool
    weight: float


class _MutableMap(Protocol):
    def __iter__(self) -> Iterator[_MutableMapGrid]: ...

    def __getitem__(self, item: tuple[int, int], /) -> _MutableMapGrid: ...


class _MapShape(Protocol):
    @property
    def columns(self) -> int: ...

    @property
    def rows(self) -> int: ...


class _MapDefinition(Protocol):
    @property
    def shape(self) -> _MapShape: ...


class _StageDefinition(Protocol):
    @property
    def map(self) -> _MapDefinition: ...


class Mumu12MapMutationRuntime(Protocol):
    @property
    def definition(self) -> _StageDefinition: ...

    @property
    def map(self) -> _MutableMap: ...


class Mumu12MapMutationDriver:
    """封装不涉及设备交互的运行地图数据变更。"""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: Mumu12MapMutationRuntime) -> None:
        self._runtime = runtime

    def mark_all_siren_candidates(self, cancellation: CancellationSource) -> None:
        grids = tuple(self._runtime.map)
        cancellation.raise_if_requested()
        for grid in grids:
            grid.may_siren = True

    def set_map_weights(
        self,
        rows: tuple[tuple[int, ...], ...],
        cancellation: CancellationSource,
    ) -> None:
        shape = self._runtime.definition.map.shape
        self._validate_weight_shape(rows, expected_rows=shape.rows, expected_columns=shape.columns)
        assignments: tuple[tuple[_MutableMapGrid, int], ...] = tuple(
            (self._runtime.map[(x, y)], weight) for y, row in enumerate(rows) for x, weight in enumerate(row)
        )
        cancellation.raise_if_requested()
        for grid, weight in assignments:
            grid.weight = weight

    @staticmethod
    def _validate_weight_shape(
        rows: tuple[tuple[int, ...], ...],
        *,
        expected_rows: int,
        expected_columns: int,
    ) -> None:
        if len(rows) != expected_rows:
            message = f"map weight matrix must be {expected_rows}x{expected_columns}, got {len(rows)} rows"
            raise BattleProgramMumu12AdapterError(message)
        for index, row in enumerate(rows):
            if len(row) == expected_columns:
                continue
            message = (
                f"map weight matrix must be {expected_rows}x{expected_columns}, row {index} has {len(row)} columns"
            )
            raise BattleProgramMumu12AdapterError(message)
