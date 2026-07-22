from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.content.cell import CellId
    from module.content.mechanic_rules import EncounterExpectation, MapItemKind, RoadblockAction, RoadGroup


type FleetIndex = Literal[1, 2]


class BattleProgramMumu12AdapterError(RuntimeError):
    """声明式战斗程序与 MuMu12 运行能力之间的固定适配错误。"""


class StrategyActionDriver(Protocol):
    """BattleProgram 所需的高层策略页动作，不暴露设备或识别细节。"""

    def air_strike(self, target: CellId, cancellation: CancellationSource) -> bool: ...

    def move_enemy(
        self,
        source: CellId,
        target: CellId,
        cancellation: CancellationSource,
    ) -> bool: ...


class FleetActionDriver(Protocol):
    """只执行已经解析到具体舰队编号的单舰队动作。"""

    def activate(self, fleet: FleetIndex, cancellation: CancellationSource) -> bool: ...

    def clear_target(
        self,
        fleet: FleetIndex,
        target: CellId,
        expected: EncounterExpectation,
        cancellation: CancellationSource,
    ) -> bool: ...

    def move(
        self,
        fleet: FleetIndex,
        destination: CellId,
        expected: EncounterExpectation,
        cancellation: CancellationSource,
    ) -> bool: ...

    def pickup_ammo(
        self,
        fleet: FleetIndex,
        target: CellId,
        cancellation: CancellationSource,
    ) -> bool: ...

    def pickup_map_item(
        self,
        fleet: FleetIndex,
        cell: CellId,
        kind: MapItemKind,
        cancellation: CancellationSource,
    ) -> bool: ...

    def clear_mystery(
        self,
        fleet: FleetIndex,
        cell: CellId,
        cancellation: CancellationSource,
    ) -> None: ...


class FleetCoordinationDriver(Protocol):
    """执行固有的多舰队战术过程，不冒充单舰队命令。"""

    def push_forward(self, cancellation: CancellationSource) -> bool: ...

    def break_siren_caught(self, cancellation: CancellationSource) -> bool: ...

    def protect(self, cancellation: CancellationSource) -> bool: ...

    def rescue(self, target: CellId, cancellation: CancellationSource) -> bool: ...

    def step_on(
        self,
        candidates: tuple[CellId, ...],
        roadblocks: tuple[RoadGroup, ...],
        cancellation: CancellationSource,
    ) -> bool: ...


class MapMutationDriver(Protocol):
    """只变更运行地图数据，不负责 UI 操作或路障处理。"""

    def mark_all_siren_candidates(self, cancellation: CancellationSource) -> None: ...

    def set_map_weights(
        self,
        rows: tuple[tuple[int, ...], ...],
        cancellation: CancellationSource,
    ) -> None: ...


class MapMechanicDriver(Protocol):
    """执行不可回滚的地图机制，并在返回前闭合本地投影。"""

    def trigger_mechanisms(
        self,
        cells: tuple[CellId, ...],
        cancellation: CancellationSource,
    ) -> bool: ...

    def clear_bouncing_enemy(self, cancellation: CancellationSource) -> bool: ...


class RoadblockPlanner(Protocol):
    """把路障推演投影为 CellId，不执行舰队或设备动作。"""

    def find_blockers(
        self,
        target: CellId,
        path_fleet: FleetIndex,
        cancellation: CancellationSource,
    ) -> tuple[CellId, ...]: ...

    def select_target(
        self,
        action: RoadblockAction,
        executor_fleet: FleetIndex,
        cancellation: CancellationSource,
    ) -> CellId | None: ...
