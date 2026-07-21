from typing import TYPE_CHECKING, Protocol

from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.base.decorator import del_cached_property
from module.base.failure import cleanup_scope, raise_cleanup_errors
from module.base.timer import Timer
from module.handler.assets import AIR_STRIKE_CONFIRM, STRATEGY_OPENED
from module.handler.strategy import AIR_STRIKE_OFFSET, MOB_MOVE_OFFSET
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource
    from module.base.button import Button
    from module.base.type_alias import ImageArray, Point
    from module.content.cell import CellId
    from module.device.control import ButtonTarget
    from module.map_detection.grid import Grid
    from module.map_detection.grid_info import GridInfo


class _StrategyMap(Protocol):
    def __getitem__(self, item: tuple[int, int], /) -> GridInfo: ...


class _StrategyDevice(Protocol):
    @property
    def image(self) -> ImageArray: ...

    def screenshot(self) -> ImageArray: ...

    def click(self, button: ButtonTarget, /) -> None: ...


class _StrategyView(Protocol):
    def update(self, image: ImageArray) -> None: ...


class Mumu12StrategyRuntime(Protocol):
    @property
    def map(self) -> _StrategyMap: ...

    @property
    def camera(self) -> Point: ...

    @property
    def device(self) -> _StrategyDevice: ...

    @property
    def view(self) -> _StrategyView: ...

    def strategy_open(self) -> None: ...

    def strategy_close(self, *, skip_first_screenshot: bool = True) -> None: ...

    def strategy_has_air_strike(self) -> bool: ...

    def strategy_air_strike_enter(self) -> None: ...

    def strategy_air_strike_cancel(self) -> None: ...

    def strategy_has_mob_move(self) -> bool: ...

    def strategy_mob_move_enter(self) -> None: ...

    def strategy_mob_move_cancel(self) -> None: ...

    def is_in_strategy_air_strike(self) -> bool: ...

    def is_in_strategy_mob_move(self) -> bool: ...

    def in_sight(self, grid: GridInfo, /) -> None: ...

    def convert_global_to_local(self, grid: GridInfo, /) -> Grid: ...

    def appear(self, button: Button, *, offset: tuple[int, int]) -> bool: ...

    def handle_popup_confirm(self, name: str, /) -> bool: ...

    def find_path_initial(self) -> None: ...


class Mumu12StrategyActionDriver:
    """封装策略页识别、设备交互及确认后的地图状态迁移。"""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: Mumu12StrategyRuntime) -> None:
        self._runtime = runtime

    def air_strike(self, target: CellId, cancellation: CancellationSource) -> bool:
        grid = self._grid(target)
        if grid.is_land:
            return False
        cancellation.raise_if_requested()
        self._runtime.strategy_open()
        target_mode = False
        committed = False

        def cleanup() -> None:
            cancel = self._runtime.strategy_air_strike_cancel if target_mode and not committed else None
            self._cleanup_strategy(cancel)

        with cleanup_scope(cleanup, message="air strike failed and strategy cleanup also failed"):
            if not self._runtime.strategy_has_air_strike():
                cancellation.raise_if_requested()
                return False
            cancellation.raise_if_requested()
            target_mode = True
            self._runtime.strategy_air_strike_enter()
            cancellation.raise_if_requested()
            self._runtime.in_sight(grid)
            attack_grid = self._runtime.convert_global_to_local(grid)
            self._select_air_strike_target(attack_grid, cancellation)
            self._confirm_air_strike(cancellation)
            committed = True
            cancellation.raise_if_requested()
            return True

    def move_enemy(
        self,
        source: CellId,
        target: CellId,
        cancellation: CancellationSource,
    ) -> bool:
        source_grid = self._grid(source)
        target_grid = self._grid(target)
        distance = abs(source.x - target.x) + abs(source.y - target.y)
        if distance != 1 or not source_grid.is_enemy or not target_grid.is_sea:
            return False
        view_target = SelectedGrids([source_grid, target_grid]).sort_by_camera_distance(self._runtime.camera)[1]
        cancellation.raise_if_requested()
        self._runtime.in_sight(view_target)
        origin_visual = self._runtime.convert_global_to_local(source_grid)
        target_visual = self._runtime.convert_global_to_local(target_grid)
        cancellation.raise_if_requested()
        self._runtime.strategy_open()
        target_mode = False
        committed = False

        def cleanup() -> None:
            cancel = self._runtime.strategy_mob_move_cancel if target_mode and not committed else None
            self._cleanup_strategy(cancel)

        with cleanup_scope(cleanup, message="enemy move failed and strategy cleanup also failed"):
            if not self._runtime.strategy_has_mob_move():
                cancellation.raise_if_requested()
                return False
            cancellation.raise_if_requested()
            target_mode = True
            self._runtime.strategy_mob_move_enter()
            self._select_mob_move_origin(origin_visual, cancellation)
            self._select_mob_move_target(target_visual, cancellation)
            committed = True
            self._commit_enemy_move(source_grid, target_grid)
            cancellation.raise_if_requested()
            return True

    def _cleanup_strategy(self, cancel_target: Callable[[], None] | None) -> None:
        errors: list[BaseException] = []
        if cancel_target is not None:
            try:
                cancel_target()
            except BaseException as error:  # ruff:ignore[blind-except] - 清理链必须保留取消及退出类失败。
                errors.append(error)
        try:
            self._runtime.strategy_close(skip_first_screenshot=False)
        except BaseException as error:  # ruff:ignore[blind-except] - 清理链必须保留取消及退出类失败。
            errors.append(error)
        raise_cleanup_errors(errors, message="strategy target cancellation or close failed")

    def _commit_enemy_move(self, source_grid: GridInfo, target_grid: GridInfo) -> None:
        target_grid.enemy_scale = source_grid.enemy_scale
        source_grid.enemy_scale = 0
        target_grid.enemy_genre = source_grid.enemy_genre
        source_grid.enemy_genre = None
        target_grid.is_boss = source_grid.is_boss
        source_grid.is_boss = False
        target_grid.is_enemy = True
        target_grid.may_enemy = True
        source_grid.is_enemy = False
        self._runtime.find_path_initial()

    def _select_air_strike_target(self, grid: Grid, cancellation: CancellationSource) -> None:
        interval = Timer(5, count=10)
        for index in range(180):
            cancellation.raise_if_requested()
            if index:
                self._runtime.device.screenshot()
            if grid.predict_air_strike_icon():
                return
            if self._runtime.is_in_strategy_air_strike():
                self._runtime.view.update(image=self._runtime.device.image)
                del_cached_property(grid, "image_trans")
            if interval.reached() and self._runtime.is_in_strategy_air_strike():
                cancellation.raise_if_requested()
                self._runtime.device.click(grid)
                interval.reset()
        message = "air strike target did not become selectable"
        raise BattleProgramMumu12AdapterError(message)

    def _confirm_air_strike(self, cancellation: CancellationSource) -> None:
        interval = Timer(3, count=6)
        for index in range(180):
            cancellation.raise_if_requested()
            if index:
                self._runtime.device.screenshot()
            if self._runtime.appear(STRATEGY_OPENED, offset=AIR_STRIKE_OFFSET):
                return
            if interval.reached() and self._runtime.is_in_strategy_air_strike():
                cancellation.raise_if_requested()
                self._runtime.device.click(AIR_STRIKE_CONFIRM)
                interval.reset()
        message = "air strike did not return to the strategy page"
        raise BattleProgramMumu12AdapterError(message)

    def _select_mob_move_origin(self, grid: Grid, cancellation: CancellationSource) -> None:
        interval = Timer(2, count=4)
        for index in range(180):
            cancellation.raise_if_requested()
            if index:
                self._runtime.device.screenshot()
            if self._runtime.is_in_strategy_mob_move():
                self._runtime.view.update(image=self._runtime.device.image)
            if grid.predict_mob_move_icon():
                return
            if interval.reached() and self._runtime.is_in_strategy_mob_move():
                cancellation.raise_if_requested()
                self._runtime.device.click(grid)
                interval.reset()
        message = "movable enemy did not become selectable"
        raise BattleProgramMumu12AdapterError(message)

    def _select_mob_move_target(self, grid: Grid, cancellation: CancellationSource) -> None:
        interval = Timer(2, count=4)
        for index in range(180):
            cancellation.raise_if_requested()
            if index:
                self._runtime.device.screenshot()
            if self._runtime.appear(STRATEGY_OPENED, offset=MOB_MOVE_OFFSET):
                return
            if interval.reached() and self._runtime.is_in_strategy_mob_move():
                cancellation.raise_if_requested()
                self._runtime.device.click(grid)
                interval.reset()
                continue
            if self._runtime.handle_popup_confirm("MOB_MOVE"):
                continue
        message = "movable enemy target was not confirmed"
        raise BattleProgramMumu12AdapterError(message)

    def _grid(self, cell: CellId) -> GridInfo:
        try:
            return self._runtime.map[(cell.x, cell.y)]
        except KeyError:
            message = f"battle program references cell outside the active map: {cell}"
            raise BattleProgramMumu12AdapterError(message) from None
