from dataclasses import dataclass, field
from enum import StrEnum

from module.content.cell import CellId
from module.content.errors import ContentValidationError


def _validate_battle(battle: int) -> None:
    if type(battle) is not int or battle < 0:
        message = "mechanic battle must be a non-negative integer"
        raise ContentValidationError(message)


def _cells(values: tuple[CellId, ...], *, field_name: str, allow_empty: bool = False) -> tuple[CellId, ...]:
    normalized = tuple(values)
    if not allow_empty and not normalized:
        message = f"{field_name} must not be empty"
        raise ContentValidationError(message)
    if any(not isinstance(cell, CellId) for cell in normalized):
        message = f"{field_name} must contain CellId values"
        raise TypeError(message)
    if len(set(normalized)) != len(normalized):
        message = f"{field_name} must not contain duplicate cells"
        raise ContentValidationError(message)
    return normalized


class FleetRole(StrEnum):
    ACTIVE = "active"
    FLEET_1 = "fleet_1"
    FLEET_2 = "fleet_2"
    FLEET_BOSS = "fleet_boss"
    NON_BOSS = "non_boss"


class EncounterExpectation(StrEnum):
    ANY = "any"
    ENEMY = "enemy"
    SIREN = "siren"
    FORTRESS = "fortress"
    BOSS = "boss"
    MYSTERY = "mystery"
    STORY = "story"


class CandidateSortKey(StrEnum):
    WEIGHT = "weight"
    COST = "cost"


@dataclass(frozen=True, slots=True)
class RoadPath:
    cells: tuple[CellId, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _cells(self.cells, field_name="road path cells"))


@dataclass(frozen=True, slots=True)
class RoadGroup:
    paths: tuple[RoadPath, ...]

    def __post_init__(self) -> None:
        paths = tuple(self.paths)
        if not paths:
            message = "road group paths must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(path, RoadPath) for path in paths):
            message = "road group paths must contain RoadPath values"
            raise TypeError(message)
        if len(set(paths)) != len(paths):
            message = "road group paths must not contain duplicates"
            raise ContentValidationError(message)
        object.__setattr__(self, "paths", paths)

    @property
    def referenced_cells(self) -> frozenset[CellId]:
        return frozenset(cell for path in self.paths for cell in path.cells)


class RoadblockMode(StrEnum):
    CLEAR = "clear"
    CLEAR_POTENTIAL = "clear_potential"
    CLEAR_FIRST = "clear_first"
    CLEAR_FOR_FASTER = "clear_for_faster"


class RoadblockSelection(StrEnum):
    DEFAULT = "default"
    WEAKEST = "weakest"
    STRONGEST = "strongest"


@dataclass(frozen=True, slots=True)
class RoadblockAction:
    battle: int
    mode: RoadblockMode
    roads: tuple[RoadGroup, ...]
    selection: RoadblockSelection = RoadblockSelection.DEFAULT

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        if not isinstance(self.mode, RoadblockMode):
            message = "roadblock mode must be a RoadblockMode"
            raise TypeError(message)
        if not isinstance(self.selection, RoadblockSelection):
            message = "roadblock selection must be a RoadblockSelection"
            raise TypeError(message)
        roads = tuple(self.roads)
        if not roads:
            message = "roadblock action roads must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(road, RoadGroup) for road in roads):
            message = "roadblock action roads must contain RoadGroup values"
            raise TypeError(message)
        object.__setattr__(self, "roads", roads)

    @property
    def referenced_cells(self) -> frozenset[CellId]:
        return frozenset(cell for road in self.roads for cell in road.referenced_cells)


@dataclass(frozen=True, slots=True)
class RoadblockRules:
    actions: tuple[RoadblockAction, ...] = ()

    def __post_init__(self) -> None:
        actions = tuple(self.actions)
        if any(not isinstance(action, RoadblockAction) for action in actions):
            message = "roadblock rules must contain RoadblockAction values"
            raise TypeError(message)
        object.__setattr__(self, "actions", actions)


@dataclass(frozen=True, slots=True)
class PushFleetForward:
    battle: int
    fleet: FleetRole = FleetRole.FLEET_2

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet_2(self.fleet, operation="push forward")


@dataclass(frozen=True, slots=True)
class BreakSirenCaught:
    battle: int
    fleet: FleetRole = FleetRole.FLEET_2

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet_2(self.fleet, operation="break siren caught")


@dataclass(frozen=True, slots=True)
class ProtectFleet:
    battle: int
    fleet: FleetRole = FleetRole.FLEET_2

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet_2(self.fleet, operation="protect fleet")


@dataclass(frozen=True, slots=True)
class RescueFleet:
    battle: int
    target: CellId
    fleet: FleetRole = FleetRole.FLEET_2

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet_2(self.fleet, operation="rescue fleet")
        _validate_cell(self.target, field_name="rescue target")


@dataclass(frozen=True, slots=True)
class StepFleetOn:
    battle: int
    candidates: tuple[CellId, ...]
    roadblocks: tuple[RoadGroup, ...] = ()
    fleet: FleetRole = FleetRole.FLEET_2

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet_2(self.fleet, operation="step fleet on")
        object.__setattr__(self, "candidates", _cells(self.candidates, field_name="step-on candidates"))
        roadblocks = tuple(self.roadblocks)
        if any(not isinstance(road, RoadGroup) for road in roadblocks):
            message = "step-on roadblocks must contain RoadGroup values"
            raise TypeError(message)
        object.__setattr__(self, "roadblocks", roadblocks)


@dataclass(frozen=True, slots=True)
class MoveFleet:
    battle: int
    destination: CellId
    fleet: FleetRole
    expected: EncounterExpectation = EncounterExpectation.ANY

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)
        _validate_cell(self.destination, field_name="fleet destination")
        if not isinstance(self.expected, EncounterExpectation):
            message = "fleet move expectation must be an EncounterExpectation"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MoveFleetToBestCandidate:
    battle: int
    candidates: tuple[CellId, ...]
    fleet: FleetRole
    sort: tuple[CandidateSortKey, ...] = (
        CandidateSortKey.WEIGHT,
        CandidateSortKey.COST,
    )
    expected: EncounterExpectation = EncounterExpectation.ANY

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)
        object.__setattr__(
            self,
            "candidates",
            _cells(self.candidates, field_name="best fleet-move candidates"),
        )
        sort = tuple(self.sort)
        if not sort:
            message = "best fleet-move sort must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(key, CandidateSortKey) for key in sort):
            message = "best fleet-move sort must contain CandidateSortKey values"
            raise TypeError(message)
        if len(set(sort)) != len(sort):
            message = "best fleet-move sort must not contain duplicate keys"
            raise ContentValidationError(message)
        if not isinstance(self.expected, EncounterExpectation):
            message = "best fleet-move expectation must be an EncounterExpectation"
            raise TypeError(message)
        object.__setattr__(self, "sort", sort)


@dataclass(frozen=True, slots=True)
class EnsureFleetAt:
    battle: int
    target: CellId
    fleet: FleetRole = FleetRole.ACTIVE

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)
        _validate_cell(self.target, field_name="fleet location target")


@dataclass(frozen=True, slots=True)
class EnsureFleet:
    battle: int
    fleet: FleetRole

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)


@dataclass(frozen=True, slots=True)
class FleetClearTarget:
    battle: int
    target: CellId
    fleet: FleetRole
    expected: EncounterExpectation

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)
        _validate_cell(self.target, field_name="fleet clear target")
        if not isinstance(self.expected, EncounterExpectation):
            message = "fleet clear expectation must be an EncounterExpectation"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class FleetClearSelectedTarget:
    """由指定舰队清理有序候选中首个符合预期且可达的目标。"""

    battle: int
    candidates: tuple[CellId, ...]
    fleet: FleetRole
    expected: EncounterExpectation

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)
        object.__setattr__(
            self,
            "candidates",
            _cells(self.candidates, field_name="fleet clear selected candidates"),
        )
        if not isinstance(self.expected, EncounterExpectation):
            message = "fleet clear selected expectation must be an EncounterExpectation"
            raise TypeError(message)


type FleetCoordinationAction = (
    BreakSirenCaught
    | PushFleetForward
    | ProtectFleet
    | RescueFleet
    | StepFleetOn
    | MoveFleet
    | EnsureFleet
    | EnsureFleetAt
    | FleetClearTarget
    | FleetClearSelectedTarget
)


@dataclass(frozen=True, slots=True)
class FleetCoordinationRules:
    actions: tuple[FleetCoordinationAction, ...] = ()

    def __post_init__(self) -> None:
        actions = tuple(self.actions)
        action_types = (
            BreakSirenCaught
            | PushFleetForward
            | ProtectFleet
            | RescueFleet
            | StepFleetOn
            | MoveFleet
            | EnsureFleet
            | EnsureFleetAt
            | FleetClearTarget
            | FleetClearSelectedTarget
        )
        if any(not isinstance(action, action_types) for action in actions):
            message = "fleet coordination rules contain an invalid action"
            raise TypeError(message)
        object.__setattr__(self, "actions", actions)


@dataclass(frozen=True, slots=True)
class PickupAmmo:
    battle: int
    fleet: FleetRole = FleetRole.ACTIVE

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)


class MapItemKind(StrEnum):
    FLARE = "flare"
    LIGHT_HOUSE = "light_house"


@dataclass(frozen=True, slots=True)
class PickupMapItem:
    battle: int
    kind: MapItemKind
    cell: CellId
    fleet: FleetRole = FleetRole.ACTIVE

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)
        if not isinstance(self.kind, MapItemKind):
            message = "map item kind must be a MapItemKind"
            raise TypeError(message)
        _validate_cell(self.cell, field_name="map item cell")


type PickupAction = PickupAmmo | PickupMapItem


@dataclass(frozen=True, slots=True)
class PickupRules:
    actions: tuple[PickupAction, ...] = ()

    def __post_init__(self) -> None:
        actions = tuple(self.actions)
        if any(not isinstance(action, PickupAmmo | PickupMapItem) for action in actions):
            message = "pickup rules contain an invalid action"
            raise TypeError(message)
        object.__setattr__(self, "actions", actions)


@dataclass(frozen=True, slots=True)
class ClearAllMystery:
    battle: int
    nearby: bool = True
    ignored: tuple[CellId, ...] = ()

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        if type(self.nearby) is not bool:
            message = "clear mystery nearby must be a boolean"
            raise TypeError(message)
        object.__setattr__(self, "ignored", _cells(self.ignored, field_name="ignored mystery cells", allow_empty=True))


@dataclass(frozen=True, slots=True)
class ClearChosenMystery:
    battle: int
    cell: CellId
    fleet: FleetRole = FleetRole.ACTIVE

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_fleet(self.fleet)
        _validate_cell(self.cell, field_name="chosen mystery cell")


@dataclass(frozen=True, slots=True)
class ClearMechanism:
    battle: int
    cells: tuple[CellId, ...] = ()

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        object.__setattr__(self, "cells", _cells(self.cells, field_name="mechanism cells", allow_empty=True))


@dataclass(frozen=True, slots=True)
class ClearMapItems:
    battle: int
    cells: tuple[CellId, ...]

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        object.__setattr__(self, "cells", _cells(self.cells, field_name="map item cells"))


@dataclass(frozen=True, slots=True)
class AirStrike:
    battle: int
    target: CellId

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_cell(self.target, field_name="air strike target")


type MapInteractionAction = ClearAllMystery | ClearChosenMystery | ClearMechanism | ClearMapItems | AirStrike


@dataclass(frozen=True, slots=True)
class MapInteractionRules:
    actions: tuple[MapInteractionAction, ...] = ()

    def __post_init__(self) -> None:
        actions = tuple(self.actions)
        action_types = ClearAllMystery | ClearChosenMystery | ClearMechanism | ClearMapItems | AirStrike
        if any(not isinstance(action, action_types) for action in actions):
            message = "map interaction rules contain an invalid action"
            raise TypeError(message)
        object.__setattr__(self, "actions", actions)


class MechanicOperation(StrEnum):
    """确实无参数的关卡机制操作。"""

    CLEAR_BOUNCING_ENEMY = "clear_bouncing_enemy"
    FIND_ROADBLOCKS = "find_roadblocks"
    CHECK_ACCESSIBILITY = "check_accessibility"


@dataclass(frozen=True, slots=True)
class MoveEnemy:
    battle: int
    source: CellId
    target: CellId

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        _validate_cell(self.source, field_name="moving enemy source")
        _validate_cell(self.target, field_name="moving enemy target")


@dataclass(frozen=True, slots=True)
class MechanicProcedure:
    battle: int
    operations: tuple[MechanicOperation, ...]

    def __post_init__(self) -> None:
        _validate_battle(self.battle)
        operations = tuple(self.operations)
        if not operations:
            message = "mechanic procedure operations must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(operation, MechanicOperation) for operation in operations):
            message = "mechanic procedure contains an invalid operation"
            raise TypeError(message)
        if len(set(operations)) != len(operations):
            message = "mechanic procedure operations must be unique"
            raise ContentValidationError(message)
        object.__setattr__(self, "operations", operations)


type BattleMechanicAction = (
    RoadblockAction | FleetCoordinationAction | PickupAction | MapInteractionAction | MoveEnemy | MechanicProcedure
)


@dataclass(frozen=True, slots=True)
class EnemyMovementRules:
    moves: tuple[MoveEnemy, ...] = ()

    def __post_init__(self) -> None:
        moves = tuple(self.moves)
        if any(not isinstance(move, MoveEnemy) for move in moves):
            message = "enemy movement rules contain an invalid move"
            raise TypeError(message)
        object.__setattr__(self, "moves", moves)


@dataclass(frozen=True, slots=True)
class MovingEnemyRules:
    turns: tuple[int, ...] = ()
    normal_turns: tuple[int, ...] = ()
    wait_until_clear: bool = False
    initial_enemy_cells: tuple[CellId, ...] = ()
    initial_siren_cells: tuple[CellId, ...] = ()

    def __post_init__(self) -> None:
        turns = tuple(self.turns)
        normal_turns = tuple(self.normal_turns)
        if any(type(turn) is not int or turn <= 0 for turn in turns):
            message = "moving enemy turns must be positive integers"
            raise ContentValidationError(message)
        if tuple(sorted(set(turns))) != turns:
            message = "moving enemy turns must be unique and increasing"
            raise ContentValidationError(message)
        if any(type(turn) is not int or turn <= 0 for turn in normal_turns):
            message = "moving normal enemy turns must be positive integers"
            raise ContentValidationError(message)
        if tuple(sorted(set(normal_turns))) != normal_turns:
            message = "moving normal enemy turns must be unique and increasing"
            raise ContentValidationError(message)
        if type(self.wait_until_clear) is not bool:
            message = "moving enemy wait_until_clear must be a boolean"
            raise TypeError(message)
        enemy_cells = _cells(self.initial_enemy_cells, field_name="initial moving enemy cells", allow_empty=True)
        siren_cells = _cells(self.initial_siren_cells, field_name="initial moving siren cells", allow_empty=True)
        if set(enemy_cells) & set(siren_cells):
            message = "moving enemy and siren cells must not overlap"
            raise ContentValidationError(message)
        object.__setattr__(self, "turns", turns)
        object.__setattr__(self, "normal_turns", normal_turns)
        object.__setattr__(self, "initial_enemy_cells", enemy_cells)
        object.__setattr__(self, "initial_siren_cells", siren_cells)


@dataclass(frozen=True, slots=True)
class WallEdge:
    source: CellId
    target: CellId

    def __post_init__(self) -> None:
        _validate_cell(self.source, field_name="wall source")
        _validate_cell(self.target, field_name="wall target")
        if abs(self.source.x - self.target.x) + abs(self.source.y - self.target.y) != 1:
            message = "wall endpoints must be adjacent cells"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class MapStructureRules:
    walls: tuple[WallEdge, ...] = ()
    maze_groups: tuple[tuple[CellId, ...], ...] = ()
    fortress_enemy_cells: tuple[CellId, ...] = ()
    fortress_block_cells: tuple[CellId, ...] = ()
    bouncing_enemy_routes: tuple[tuple[CellId, ...], ...] = ()

    def __post_init__(self) -> None:
        walls = tuple(self.walls)
        if any(not isinstance(wall, WallEdge) for wall in walls):
            message = "map structure walls contain an invalid edge"
            raise TypeError(message)
        maze_groups = tuple(_cells(group, field_name="maze group cells") for group in self.maze_groups)
        bouncing_routes = tuple(
            _cells(route, field_name="bouncing enemy route cells") for route in self.bouncing_enemy_routes
        )
        object.__setattr__(self, "walls", walls)
        object.__setattr__(self, "maze_groups", maze_groups)
        object.__setattr__(
            self,
            "fortress_enemy_cells",
            _cells(self.fortress_enemy_cells, field_name="fortress enemy cells", allow_empty=True),
        )
        object.__setattr__(
            self,
            "fortress_block_cells",
            _cells(self.fortress_block_cells, field_name="fortress block cells", allow_empty=True),
        )
        object.__setattr__(self, "bouncing_enemy_routes", bouncing_routes)

    @property
    def referenced_cells(self) -> frozenset[CellId]:
        cells = {cell for wall in self.walls for cell in (wall.source, wall.target)}
        cells.update(cell for group in self.maze_groups for cell in group)
        cells.update(self.fortress_enemy_cells)
        cells.update(self.fortress_block_cells)
        cells.update(cell for route in self.bouncing_enemy_routes for cell in route)
        return frozenset(cells)


@dataclass(frozen=True, slots=True)
class StageMechanicRules:
    roadblocks: RoadblockRules = field(default_factory=RoadblockRules)
    fleet_coordination: FleetCoordinationRules = field(default_factory=FleetCoordinationRules)
    pickups: PickupRules = field(default_factory=PickupRules)
    map_interactions: MapInteractionRules = field(default_factory=MapInteractionRules)
    moving_enemies: MovingEnemyRules = field(default_factory=MovingEnemyRules)
    procedures: tuple[MechanicProcedure, ...] = ()
    enemy_movement: EnemyMovementRules = field(default_factory=EnemyMovementRules)
    map_structures: MapStructureRules = field(default_factory=MapStructureRules)

    def __post_init__(self) -> None:
        expected = (
            (self.roadblocks, RoadblockRules, "roadblocks"),
            (self.fleet_coordination, FleetCoordinationRules, "fleet_coordination"),
            (self.pickups, PickupRules, "pickups"),
            (self.map_interactions, MapInteractionRules, "map_interactions"),
            (self.moving_enemies, MovingEnemyRules, "moving_enemies"),
        )
        for value, expected_type, field_name in expected:
            if not isinstance(value, expected_type):
                message = f"stage mechanic {field_name} has an invalid type"
                raise TypeError(message)
        procedures = tuple(self.procedures)
        if any(not isinstance(procedure, MechanicProcedure) for procedure in procedures):
            message = "stage mechanic procedures contain an invalid value"
            raise TypeError(message)
        object.__setattr__(self, "procedures", procedures)
        if not isinstance(self.enemy_movement, EnemyMovementRules):
            message = "stage mechanic enemy_movement has an invalid type"
            raise TypeError(message)
        if not isinstance(self.map_structures, MapStructureRules):
            message = "stage mechanic map_structures has an invalid type"
            raise TypeError(message)

    @property
    def referenced_battles(self) -> frozenset[int]:
        actions = (
            *self.roadblocks.actions,
            *self.fleet_coordination.actions,
            *self.pickups.actions,
            *self.map_interactions.actions,
        )
        battles = {action.battle for action in actions}
        battles.update(procedure.battle for procedure in self.procedures)
        battles.update(move.battle for move in self.enemy_movement.moves)
        return frozenset(battles)

    @property
    def referenced_cells(self) -> frozenset[CellId]:
        cells: set[CellId] = set()
        for action in self.roadblocks.actions:
            cells.update(action.referenced_cells)
        for action in self.fleet_coordination.actions:
            cells.update(_fleet_action_cells(action))
        for action in self.pickups.actions:
            if isinstance(action, PickupMapItem):
                cells.add(action.cell)
        for action in self.map_interactions.actions:
            cells.update(_map_interaction_cells(action))
        cells.update(self.moving_enemies.initial_enemy_cells)
        cells.update(self.moving_enemies.initial_siren_cells)
        for move in self.enemy_movement.moves:
            cells.update((move.source, move.target))
        cells.update(self.map_structures.referenced_cells)
        return frozenset(cells)


def _validate_fleet(fleet: FleetRole) -> None:
    if not isinstance(fleet, FleetRole):
        message = "fleet must be a FleetRole"
        raise TypeError(message)


def _validate_fleet_2(fleet: FleetRole, *, operation: str) -> None:
    _validate_fleet(fleet)
    if fleet is not FleetRole.FLEET_2:
        message = f"{operation} only supports fleet_2"
        raise ContentValidationError(message)


def _validate_cell(cell: CellId, *, field_name: str) -> None:
    if not isinstance(cell, CellId):
        message = f"{field_name} must be a CellId"
        raise TypeError(message)


def _fleet_action_cells(action: FleetCoordinationAction) -> frozenset[CellId]:
    if isinstance(action, RescueFleet):
        return frozenset({action.target})
    if isinstance(action, StepFleetOn):
        road_cells = {cell for road in action.roadblocks for cell in road.referenced_cells}
        return frozenset((*action.candidates, *road_cells))
    if isinstance(action, MoveFleet):
        return frozenset({action.destination})
    if isinstance(action, EnsureFleetAt):
        return frozenset({action.target})
    if isinstance(action, FleetClearTarget | FleetClearSelectedTarget):
        cells = action.candidates if isinstance(action, FleetClearSelectedTarget) else (action.target,)
        return frozenset(cells)
    return frozenset()


def _map_interaction_cells(action: MapInteractionAction) -> frozenset[CellId]:
    if isinstance(action, ClearAllMystery):
        return frozenset(action.ignored)
    if isinstance(action, ClearChosenMystery):
        return frozenset({action.cell})
    if isinstance(action, ClearMechanism):
        return frozenset(action.cells)
    if isinstance(action, ClearMapItems):
        return frozenset(action.cells)
    if isinstance(action, AirStrike):
        return frozenset({action.target})
    return frozenset()
