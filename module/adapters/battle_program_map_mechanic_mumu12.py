from typing import TYPE_CHECKING, Protocol

from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.exception import MapEnemyMoved
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.content.cell import CellId
    from module.map_detection.grid_info import GridInfo


class _MapMechanicLayout(Protocol):
    def __getitem__(self, item: tuple[int, int], /) -> GridInfo: ...

    def select(self, **criteria: object) -> SelectedGrids[GridInfo]: ...


class _MapMechanicMap(Protocol):
    @property
    def layout(self) -> _MapMechanicLayout: ...


class _MapMechanicNavigation(Protocol):
    def rebuild_paths(self) -> None: ...


class Mumu12MapMechanicRuntime(Protocol):
    @property
    def map(self) -> _MapMechanicMap: ...

    def clear_mechanism(self, grids: SelectedGrids[GridInfo] | None = None) -> bool: ...

    def full_scan(self) -> None: ...

    @property
    def navigation(self) -> _MapMechanicNavigation: ...

    def clear_bouncing_enemy(self) -> bool: ...


class Mumu12MapMechanicDriver:
    """执行会改变游戏地图、并要求刷新本地投影的关卡机制。"""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: Mumu12MapMechanicRuntime) -> None:
        self._runtime = runtime

    def trigger_mechanisms(
        self,
        cells: tuple[CellId, ...],
        cancellation: CancellationSource,
    ) -> bool:
        selected = SelectedGrids([self._grid(cell) for cell in cells]) if cells else None
        limit = len(cells) if cells else self._runtime.map.layout.select(is_mechanism_trigger=True).count
        applied = False
        for _ in range(limit):
            cancellation.raise_if_requested()
            try:
                changed = bool(self._runtime.clear_mechanism(selected))
            except MapEnemyMoved:
                applied = True
                # 游戏内动作已经提交，必须先把本地地图推进到一致状态，再响应取消。
                self._runtime.full_scan()
                self._runtime.navigation.rebuild_paths()
                cancellation.raise_if_requested()
                continue
            return applied or changed
        return applied

    def clear_bouncing_enemy(self, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        applied = bool(self._runtime.clear_bouncing_enemy())
        cancellation.raise_if_requested()
        return applied

    def _grid(self, cell: CellId) -> GridInfo:
        try:
            return self._runtime.map.layout[(cell.x, cell.y)]
        except KeyError:
            message = f"battle program references cell outside the active map: {cell}"
            raise BattleProgramMumu12AdapterError(message) from None
