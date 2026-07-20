from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, assert_never, cast

from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError, FleetIndex
from module.adapters.campaign_program_capabilities import CampaignProgramCapabilityReader
from module.content import battle_program as program_model
from module.content.battle_policy import EnemyFilterEntry, parse_enemy_filter
from module.content.cell import CellId
from module.content.errors import ContentValidationError
from module.content.mechanic_rules import FleetRole
from module.gameplay.campaign import EnemyPriorityMode

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.application import CancellationSource


class RuntimeProgramState(Protocol):
    """不能从静态 profile 推断的当前地图运行事实。"""

    def use_single_fleet_override(self, cancellation: CancellationSource) -> bool | None: ...

    def use_support_fleet(self, cancellation: CancellationSource) -> bool: ...


class _ProgramConfig(Protocol):
    MAP_CLEAR_ALL_THIS_TIME: bool
    MAP_HAS_MOVABLE_ENEMY: bool
    MAP_HAS_MOVABLE_NORMAL_ENEMY: bool
    POOR_MAP_DATA: bool
    fleet_2: int
    fleet_boss: int


class _SelectionProgramConfig(Protocol):
    EnemyPriority_EnemyScaleBalanceWeight: str
    MAP_CLEAR_ALL_THIS_TIME: bool
    MAP_HAS_MOVABLE_NORMAL_ENEMY: bool


class _ProgramDefinition(Protocol):
    @property
    def enemy_filter(self) -> str: ...


class _ProgramGrid(Protocol):
    @property
    def location(self) -> tuple[int, int] | None: ...

    @property
    def weight(self) -> float: ...

    @property
    def cost_1(self) -> float: ...

    @property
    def cost_2(self) -> float: ...

    @property
    def is_enemy(self) -> bool: ...

    @property
    def is_siren(self) -> bool: ...

    @property
    def is_boss(self) -> bool: ...

    @property
    def is_fortress(self) -> bool: ...

    @property
    def is_mystery(self) -> bool: ...

    @property
    def may_ammo(self) -> bool: ...

    @property
    def enemy_scale(self) -> int: ...

    @property
    def enemy_genre(self) -> str | None: ...


class _ProgramMap(Protocol):
    def __iter__(self) -> Iterator[_ProgramGrid]: ...


class Mumu12ProgramReadSource(Protocol):
    """从当前引擎读取 BattleProgram 所需事实的最小表面。"""

    @property
    def config(self) -> _ProgramConfig: ...

    @property
    def definition(self) -> _ProgramDefinition: ...

    @property
    def map(self) -> _ProgramMap: ...

    @property
    def map_is_clear_mode(self) -> bool: ...

    @property
    def battle_count(self) -> int: ...

    @property
    def fleet_step(self) -> int: ...

    @property
    def mystery_count(self) -> int: ...

    @property
    def fleet_boss_index(self) -> int: ...

    @property
    def fleet_current_index(self) -> int: ...

    @property
    def fleet_1_location(self) -> tuple[int, int] | tuple[()] | None: ...

    @property
    def fleet_2_location(self) -> tuple[int, int] | tuple[()] | None: ...


class BattleProgramReadModel(Protocol):
    def mode(self, cancellation: CancellationSource) -> program_model.BattleProgramMode: ...

    def battle_count(self, cancellation: CancellationSource) -> int: ...

    def status(self, cancellation: CancellationSource) -> ProgramStatusSnapshot: ...

    def battlefield(self, cancellation: CancellationSource) -> ProgramBattlefieldView: ...

    def selection_context(self, cancellation: CancellationSource) -> ProgramBattleSelectionContext: ...

    def initial_flags(self, cancellation: CancellationSource) -> frozenset[program_model.ProgramFlag]: ...

    def read_metric(
        self,
        metric: program_model.ProgramMetric,
        cancellation: CancellationSource,
    ) -> int: ...

    def read_cell_property(
        self,
        cell: CellId,
        cell_property: program_model.CellProperty,
        cancellation: CancellationSource,
    ) -> program_model.CellPropertyValue: ...

    def is_fleet_at(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool: ...

    def has_map_presence(
        self,
        presence: program_model.MapPresence,
        cancellation: CancellationSource,
    ) -> bool: ...

    def is_boss_at(self, cell: CellId, cancellation: CancellationSource) -> bool: ...

    def is_boss_accessible(
        self,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool: ...

    def is_cell_accessible_for_fleet(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool: ...

    def has_candidate_enemy(
        self,
        candidates: tuple[CellId, ...],
        excluded_genres: tuple[str, ...],
        cancellation: CancellationSource,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProgramStatusSnapshot:
    flags: frozenset[program_model.ProgramFlag]
    battle_count: int
    fleet_step: int
    mystery_count: int
    fleet_boss_index: FleetIndex
    configured_boss_fleet: int
    fleet_current_index: FleetIndex
    fleet_1_location: CellId | None
    fleet_2_location: CellId | None

    def metric(self, metric: program_model.ProgramMetric) -> int:
        if metric is program_model.ProgramMetric.BATTLE_COUNT:
            return self.battle_count
        if metric is program_model.ProgramMetric.FLEET_STEP:
            return self.fleet_step
        if metric is program_model.ProgramMetric.MYSTERY_COUNT:
            return self.mystery_count
        if metric is program_model.ProgramMetric.FLEET_BOSS_INDEX:
            return self.fleet_boss_index
        if metric is program_model.ProgramMetric.CONFIGURED_BOSS_FLEET:
            return self.configured_boss_fleet
        assert_never(metric)

    def fleet_index(self, fleet: FleetRole) -> FleetIndex:
        if fleet is FleetRole.ACTIVE:
            return self.fleet_current_index
        if fleet is FleetRole.FLEET_1:
            return 1
        if fleet is FleetRole.FLEET_2:
            return 2
        if fleet is FleetRole.FLEET_BOSS:
            return self.fleet_boss_index
        if fleet is FleetRole.NON_BOSS:
            return 1 if self.fleet_boss_index == 2 else 2
        assert_never(fleet)

    def fleet_location(self, fleet: FleetRole) -> CellId | None:
        return self.fleet_location_for(self.fleet_index(fleet))

    def fleet_location_for(self, fleet: FleetIndex) -> CellId | None:
        return self.fleet_1_location if fleet == 1 else self.fleet_2_location


@dataclass(frozen=True, slots=True)
class ProgramBattleSelectionContext:
    executor_fleet: FleetIndex
    enemy_priority: EnemyPriorityMode
    clear_all: bool
    movable_normal_enemy: bool
    default_enemy_filter: tuple[EnemyFilterEntry, ...]

    def __post_init__(self) -> None:
        if type(self.executor_fleet) is not int or self.executor_fleet not in (1, 2):
            message = f"unsupported selection executor fleet: {self.executor_fleet}"
            raise BattleProgramMumu12AdapterError(message)
        if not isinstance(self.enemy_priority, EnemyPriorityMode):
            message = "selection enemy priority must be an EnemyPriorityMode"
            raise TypeError(message)
        if type(self.clear_all) is not bool or type(self.movable_normal_enemy) is not bool:
            message = "selection mode flags must be booleans"
            raise TypeError(message)
        if not self.default_enemy_filter or any(
            not isinstance(entry, EnemyFilterEntry) for entry in self.default_enemy_filter
        ):
            message = "selection default enemy filter must contain EnemyFilterEntry values"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ProgramCellFacts:
    cell: CellId
    weight: float
    cost_1: float
    cost_2: float
    is_enemy: bool
    is_siren: bool
    is_boss: bool
    is_fortress: bool
    is_mystery: bool
    may_ammo: bool
    enemy_scale: int
    enemy_genre: str

    def cost_for(self, fleet_index: FleetIndex) -> float:
        if fleet_index == 1:
            return self.cost_1
        if fleet_index == 2:
            return self.cost_2
        message = f"unsupported fleet index: {fleet_index}"
        raise BattleProgramMumu12AdapterError(message)

    def accessible_for(self, fleet_index: FleetIndex) -> bool:
        return self.cost_for(fleet_index) < 9999


@dataclass(frozen=True, slots=True)
class ProgramBattlefieldView:
    cells: tuple[ProgramCellFacts, ...]

    def cell(self, cell: CellId) -> ProgramCellFacts:
        for facts in self.cells:
            if facts.cell == cell:
                return facts
        message = f"battle program references cell outside the active map: {cell}"
        raise BattleProgramMumu12AdapterError(message)

    def has_presence(self, presence: program_model.MapPresence) -> bool:
        if presence is program_model.MapPresence.BOSS:
            return any(cell.is_boss for cell in self.cells)
        if presence is program_model.MapPresence.SIREN:
            return any(cell.is_siren for cell in self.cells)
        if presence is program_model.MapPresence.ENEMY:
            return any(cell.is_enemy for cell in self.cells)
        if presence is program_model.MapPresence.NON_BOSS_TARGET:
            return any(not cell.is_boss and (cell.is_enemy or cell.is_siren or cell.is_fortress) for cell in self.cells)
        assert_never(presence)

    def has_candidate_enemy(
        self,
        candidates: tuple[CellId, ...],
        excluded_genres: tuple[str, ...],
    ) -> bool:
        return any(facts.is_enemy and facts.enemy_genre not in excluded_genres for facts in map(self.cell, candidates))


class Mumu12BattleProgramReadModel:
    """每次查询都从当前单运行实例投影新的不可变事实。"""

    __slots__ = ("_program_capabilities", "_program_state", "_source")

    def __init__(
        self,
        source: Mumu12ProgramReadSource,
        program_state: RuntimeProgramState,
        program_capabilities: CampaignProgramCapabilityReader,
    ) -> None:
        if not isinstance(program_capabilities, CampaignProgramCapabilityReader):
            message = "MuMu12 battle program read model requires a program capability reader"
            raise TypeError(message)
        self._source = source
        self._program_state = program_state
        self._program_capabilities = program_capabilities

    @staticmethod
    def _integer(value: object, field: str) -> int:
        if type(value) is not int:
            message = f"runtime program field {field} must be an integer"
            raise BattleProgramMumu12AdapterError(message)
        return value

    @staticmethod
    def _fleet_index(value: object, field: str) -> FleetIndex:
        index = Mumu12BattleProgramReadModel._integer(value, field)
        if index == 1:
            return 1
        if index == 2:
            return 2
        message = f"runtime program field {field} must be fleet 1 or 2"
        raise BattleProgramMumu12AdapterError(message)

    @staticmethod
    def _location(value: object, field: str) -> CellId | None:
        if value in (None, ()):
            return None
        if not isinstance(value, tuple) or len(value) != 2:
            message = f"runtime program field {field} must be a map location"
            raise BattleProgramMumu12AdapterError(message)
        x, y = value
        if type(x) is not int or type(y) is not int:
            message = f"runtime program field {field} must contain integer coordinates"
            raise BattleProgramMumu12AdapterError(message)
        return CellId(x, y)

    def mode(self, cancellation: CancellationSource) -> program_model.BattleProgramMode:
        cancellation.raise_if_requested()
        if self._source.config.MAP_CLEAR_ALL_THIS_TIME:
            return program_model.BattleProgramMode.CLEAR_ALL
        if self._source.config.POOR_MAP_DATA:
            return program_model.BattleProgramMode.POOR_MAP_DATA
        return program_model.BattleProgramMode.NORMAL

    def battle_count(self, cancellation: CancellationSource) -> int:
        cancellation.raise_if_requested()
        return self._integer(self._source.battle_count, "battle_count")

    def status(self, cancellation: CancellationSource) -> ProgramStatusSnapshot:
        cancellation.raise_if_requested()
        source = self._source
        single_fleet_override = self._program_state.use_single_fleet_override(cancellation)
        if single_fleet_override is not None and type(single_fleet_override) is not bool:
            message = "runtime program state use_single_fleet_override() must return bool or None"
            raise BattleProgramMumu12AdapterError(message)
        use_single_fleet = not bool(source.config.fleet_2) if single_fleet_override is None else single_fleet_override
        flags = {
            flag
            for enabled, flag in (
                (source.map_is_clear_mode, program_model.ProgramFlag.CLEAR_MODE),
                (source.config.MAP_CLEAR_ALL_THIS_TIME, program_model.ProgramFlag.CLEAR_ALL),
                (source.config.POOR_MAP_DATA, program_model.ProgramFlag.POOR_MAP_DATA),
                (use_single_fleet, program_model.ProgramFlag.USE_SINGLE_FLEET),
                (source.config.MAP_HAS_MOVABLE_ENEMY, program_model.ProgramFlag.MOVABLE_ENEMY),
                (
                    source.config.MAP_HAS_MOVABLE_NORMAL_ENEMY,
                    program_model.ProgramFlag.MOVABLE_NORMAL_ENEMY,
                ),
            )
            if enabled
        }
        cancellation.raise_if_requested()
        if self._program_capabilities.map_has_mob_move(cancellation):
            flags.add(program_model.ProgramFlag.MAP_HAS_MOB_MOVE)
        cancellation.raise_if_requested()
        use_support_fleet = self._program_state.use_support_fleet(cancellation)
        if type(use_support_fleet) is not bool:
            message = "runtime program state use_support_fleet() must return bool"
            raise BattleProgramMumu12AdapterError(message)
        if use_support_fleet:
            flags.add(program_model.ProgramFlag.USE_SUPPORT_FLEET)
        return ProgramStatusSnapshot(
            frozenset(flags),
            self._integer(source.battle_count, "battle_count"),
            self._integer(source.fleet_step, "fleet_step"),
            self._integer(source.mystery_count, "mystery_count"),
            self._fleet_index(source.fleet_boss_index, "fleet_boss_index"),
            self._integer(source.config.fleet_boss, "configured_boss_fleet"),
            self._fleet_index(source.fleet_current_index, "fleet_current_index"),
            self._location(source.fleet_1_location, "fleet_1_location"),
            self._location(source.fleet_2_location, "fleet_2_location"),
        )

    @staticmethod
    def _cell_facts(grid: _ProgramGrid) -> ProgramCellFacts:
        location = Mumu12BattleProgramReadModel._location(grid.location, "grid.location")
        if location is None:
            message = "runtime program grid must have a map location"
            raise BattleProgramMumu12AdapterError(message)
        enemy_scale = Mumu12BattleProgramReadModel._integer(grid.enemy_scale, f"{location}.enemy_scale")
        enemy_genre = grid.enemy_genre
        if enemy_genre is None:
            enemy_genre = ""
        elif not isinstance(enemy_genre, str):
            message = f"{location}.enemy_genre is not a string"
            raise BattleProgramMumu12AdapterError(message)
        return ProgramCellFacts(
            cell=location,
            weight=grid.weight,
            cost_1=grid.cost_1,
            cost_2=grid.cost_2,
            is_enemy=bool(grid.is_enemy),
            is_siren=bool(grid.is_siren),
            is_boss=bool(grid.is_boss),
            is_fortress=bool(grid.is_fortress),
            is_mystery=bool(grid.is_mystery),
            may_ammo=bool(grid.may_ammo),
            enemy_scale=enemy_scale,
            enemy_genre=enemy_genre,
        )

    def battlefield(self, cancellation: CancellationSource) -> ProgramBattlefieldView:
        cancellation.raise_if_requested()
        return ProgramBattlefieldView(tuple(self._cell_facts(grid) for grid in self._source.map))

    def selection_context(self, cancellation: CancellationSource) -> ProgramBattleSelectionContext:
        cancellation.raise_if_requested()
        source = self._source
        selection_config = cast("_SelectionProgramConfig", source.config)
        try:
            enemy_priority = EnemyPriorityMode(selection_config.EnemyPriority_EnemyScaleBalanceWeight)
        except ValueError as error:
            message = f"unsupported runtime enemy priority: {selection_config.EnemyPriority_EnemyScaleBalanceWeight!r}"
            raise BattleProgramMumu12AdapterError(message) from error
        try:
            default_enemy_filter = parse_enemy_filter(source.definition.enemy_filter)
        except ContentValidationError as error:
            message = f"invalid runtime enemy filter: {source.definition.enemy_filter!r}"
            raise BattleProgramMumu12AdapterError(message) from error
        clear_all = selection_config.MAP_CLEAR_ALL_THIS_TIME
        movable_normal_enemy = selection_config.MAP_HAS_MOVABLE_NORMAL_ENEMY
        if type(clear_all) is not bool or type(movable_normal_enemy) is not bool:
            message = "runtime selection mode flags must be booleans"
            raise BattleProgramMumu12AdapterError(message)
        cancellation.raise_if_requested()
        return ProgramBattleSelectionContext(
            executor_fleet=self._fleet_index(source.fleet_current_index, "fleet_current_index"),
            enemy_priority=enemy_priority,
            clear_all=clear_all,
            movable_normal_enemy=movable_normal_enemy,
            default_enemy_filter=default_enemy_filter,
        )

    def initial_flags(self, cancellation: CancellationSource) -> frozenset[program_model.ProgramFlag]:
        return self.status(cancellation).flags

    def read_metric(
        self,
        metric: program_model.ProgramMetric,
        cancellation: CancellationSource,
    ) -> int:
        return self.status(cancellation).metric(metric)

    def read_cell_property(
        self,
        cell: CellId,
        cell_property: program_model.CellProperty,
        cancellation: CancellationSource,
    ) -> program_model.CellPropertyValue:
        facts = self.battlefield(cancellation).cell(cell)
        if cell_property is program_model.CellProperty.ACCESSIBLE:
            status = self.status(cancellation)
            return facts.accessible_for(status.fleet_current_index)
        if cell_property is program_model.CellProperty.ENEMY_SCALE:
            return facts.enemy_scale
        if cell_property is program_model.CellProperty.ENEMY_GENRE:
            return facts.enemy_genre
        if cell_property is program_model.CellProperty.IS_MYSTERY:
            return facts.is_mystery
        assert_never(cell_property)

    def is_fleet_at(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        return self.status(cancellation).fleet_location(fleet) == cell

    def has_map_presence(
        self,
        presence: program_model.MapPresence,
        cancellation: CancellationSource,
    ) -> bool:
        return self.battlefield(cancellation).has_presence(presence)

    def is_boss_at(self, cell: CellId, cancellation: CancellationSource) -> bool:
        return self.battlefield(cancellation).cell(cell).is_boss

    def is_boss_accessible(
        self,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        status = self.status(cancellation)
        fleet_index = status.fleet_index(fleet)
        return any(cell.is_boss and cell.accessible_for(fleet_index) for cell in self.battlefield(cancellation).cells)

    def is_cell_accessible_for_fleet(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        status = self.status(cancellation)
        facts = self.battlefield(cancellation).cell(cell)
        return facts.accessible_for(status.fleet_index(fleet))

    def has_candidate_enemy(
        self,
        candidates: tuple[CellId, ...],
        excluded_genres: tuple[str, ...],
        cancellation: CancellationSource,
    ) -> bool:
        return self.battlefield(cancellation).has_candidate_enemy(candidates, excluded_genres)
