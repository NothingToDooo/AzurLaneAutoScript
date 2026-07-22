from typing import TYPE_CHECKING, Protocol, assert_never

from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.content.mechanic_rules import EncounterExpectation, MapItemKind

if TYPE_CHECKING:
    from module.adapters.battle_program_mumu12_contracts import FleetIndex
    from module.application import CancellationSource
    from module.content.cell import CellId
    from module.map_detection.grid_info import GridInfo

_MOVE_ATTEMPT_LIMIT = 3


class _FleetActionMap(Protocol):
    def __getitem__(self, item: tuple[int, int], /) -> GridInfo: ...


class _FleetActionNavigationSnapshot(Protocol):
    @property
    def fleet_1(self) -> tuple[int, int] | tuple[()]: ...

    @property
    def fleet_2(self) -> tuple[int, int] | tuple[()]: ...

    @property
    def current_index(self) -> int: ...


class _FleetActionNavigation(Protocol):
    @property
    def snapshot(self) -> _FleetActionNavigationSnapshot: ...

    def activate(self, index: int) -> bool: ...

    def goto(self, grid: GridInfo, /, expected: str = "") -> None: ...


class Mumu12FleetActionRuntime(Protocol):
    @property
    def map(self) -> _FleetActionMap: ...

    @property
    def navigation(self) -> _FleetActionNavigation: ...

    def clear_chosen_enemy(self, grid: GridInfo, /, expected: str = "") -> bool: ...

    def pick_up_ammo(self, grid: GridInfo, /) -> bool: ...

    def ensure_no_info_bar(self) -> bool: ...

    def clear_chosen_mystery(self, grid: GridInfo, /) -> None: ...


class Mumu12FleetActionDriver:
    """在显式激活的 1/2 号舰队上执行单目标地图运行原语。"""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: Mumu12FleetActionRuntime) -> None:
        self._runtime = runtime

    def activate(self, fleet: FleetIndex, cancellation: CancellationSource) -> bool:
        self._validate_fleet(fleet)
        cancellation.raise_if_requested()
        if self._runtime.navigation.snapshot.current_index == fleet:
            return False
        self._runtime.navigation.activate(fleet)
        if self._runtime.navigation.snapshot.current_index != fleet:
            message = f"navigation.activate({fleet}) did not select the requested fleet"
            raise BattleProgramMumu12AdapterError(message)
        return True

    def clear_target(
        self,
        fleet: FleetIndex,
        target: CellId,
        expected: EncounterExpectation,
        cancellation: CancellationSource,
    ) -> bool:
        grid = self._grid(target)
        runtime_expected = self._clear_expected(expected)
        self.activate(fleet, cancellation)
        cancellation.raise_if_requested()
        return bool(self._runtime.clear_chosen_enemy(grid, expected=runtime_expected))

    def move(
        self,
        fleet: FleetIndex,
        destination: CellId,
        expected: EncounterExpectation,
        cancellation: CancellationSource,
    ) -> bool:
        grid = self._grid(destination)
        runtime_expected = self._move_expected(expected)
        self.activate(fleet, cancellation)
        origin = self._fleet_location(fleet)
        destination_location = (destination.x, destination.y)
        if origin == destination_location:
            return False

        for _ in range(_MOVE_ATTEMPT_LIMIT):
            cancellation.raise_if_requested()
            self._runtime.navigation.goto(grid, expected=runtime_expected)
            current = self._fleet_location(fleet)
            if current == destination_location:
                return True
            if current != origin:
                message = f"fleet_{fleet} moved to unexpected cell {current} while targeting {destination_location}"
                raise BattleProgramMumu12AdapterError(message)

        message = f"fleet_{fleet} did not reach {destination_location} after {_MOVE_ATTEMPT_LIMIT} attempts"
        raise BattleProgramMumu12AdapterError(message)

    def pickup_ammo(
        self,
        fleet: FleetIndex,
        target: CellId,
        cancellation: CancellationSource,
    ) -> bool:
        grid = self._grid(target)
        self.activate(fleet, cancellation)
        cancellation.raise_if_requested()
        return bool(self._runtime.pick_up_ammo(grid))

    def pickup_map_item(
        self,
        fleet: FleetIndex,
        cell: CellId,
        kind: MapItemKind,
        cancellation: CancellationSource,
    ) -> bool:
        grid = self._grid(cell)
        if kind is not MapItemKind.FLARE and kind is not MapItemKind.LIGHT_HOUSE:
            message = f"unsupported map item kind: {kind!r}"
            raise BattleProgramMumu12AdapterError(message)
        self.activate(fleet, cancellation)
        cancellation.raise_if_requested()
        if kind is MapItemKind.FLARE:
            grid.is_flare = True
        origin = self._fleet_location(fleet)
        self._runtime.navigation.goto(grid)
        if kind is MapItemKind.LIGHT_HOUSE:
            cancellation.raise_if_requested()
            self._runtime.ensure_no_info_bar()
        return self._fleet_location(fleet) != origin

    def clear_mystery(
        self,
        fleet: FleetIndex,
        cell: CellId,
        cancellation: CancellationSource,
    ) -> None:
        grid = self._grid(cell)
        self.activate(fleet, cancellation)
        cancellation.raise_if_requested()
        self._runtime.clear_chosen_mystery(grid)

    def _grid(self, cell: CellId) -> GridInfo:
        try:
            return self._runtime.map[(cell.x, cell.y)]
        except KeyError:
            message = f"battle program references cell outside the active map: {cell}"
            raise BattleProgramMumu12AdapterError(message) from None

    def _fleet_location(self, fleet: FleetIndex) -> tuple[int, int]:
        self._validate_fleet(fleet)
        snapshot = self._runtime.navigation.snapshot
        value = snapshot.fleet_1 if fleet == 1 else snapshot.fleet_2
        if len(value) != 2:
            message = f"fleet_{fleet} has no active map location"
            raise BattleProgramMumu12AdapterError(message)
        return value

    @staticmethod
    def _validate_fleet(fleet: object) -> None:
        if type(fleet) is not int or fleet not in (1, 2):
            message = f"unsupported fleet index: {fleet!r}"
            raise BattleProgramMumu12AdapterError(message)

    @staticmethod
    def _clear_expected(expected: EncounterExpectation) -> str:
        if expected in (EncounterExpectation.ANY, EncounterExpectation.ENEMY):
            return ""
        if expected is EncounterExpectation.SIREN:
            return "siren"
        if expected is EncounterExpectation.FORTRESS:
            return "fortress"
        if expected is EncounterExpectation.BOSS:
            return "boss"
        if expected is EncounterExpectation.MYSTERY:
            return "mystery"
        if expected is EncounterExpectation.STORY:
            return "story"
        assert_never(expected)

    @staticmethod
    def _move_expected(expected: EncounterExpectation) -> str:
        if expected is EncounterExpectation.ANY:
            runtime_expected = ""
        elif expected is EncounterExpectation.ENEMY:
            runtime_expected = "combat"
        elif expected is EncounterExpectation.SIREN:
            runtime_expected = "combat_siren"
        elif expected is EncounterExpectation.FORTRESS:
            runtime_expected = "combat_fortress"
        elif expected is EncounterExpectation.BOSS:
            runtime_expected = "combat_boss"
        elif expected is EncounterExpectation.MYSTERY:
            runtime_expected = "mystery"
        elif expected is EncounterExpectation.STORY:
            runtime_expected = "story"
        else:
            assert_never(expected)
        return runtime_expected
