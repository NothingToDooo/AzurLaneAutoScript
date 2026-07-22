import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from module.content.battle_policy import BattleStep, is_battle_step
from module.content.cell import CellId
from module.content.errors import ContentValidationError
from module.content.mechanic_rules import (
    AirStrike,
    BreakSirenCaught,
    ClearAllMystery,
    ClearChosenMystery,
    ClearMapItems,
    ClearMechanism,
    EncounterExpectation,
    EnsureFleet,
    EnsureFleetAt,
    FleetClearSelectedTarget,
    FleetClearTarget,
    FleetRole,
    MapItemKind,
    MechanicProcedure,
    MoveEnemy,
    MoveFleet,
    MoveFleetToBestCandidate,
    PickupAmmo,
    PickupMapItem,
    ProtectFleet,
    PushFleetForward,
    RescueFleet,
    RoadblockAction,
    StepFleetOn,
)


class BattleProgramMode(StrEnum):
    NORMAL = "normal"
    CLEAR_ALL = "clear_all"
    POOR_MAP_DATA = "poor_map_data"


class ProgramFlag(StrEnum):
    CLEAR_MODE = "clear_mode"
    CLEAR_ALL = "clear_all"
    POOR_MAP_DATA = "poor_map_data"
    MAP_HAS_MOB_MOVE = "map_has_mob_move"
    MOVABLE_NORMAL_ENEMY = "movable_normal_enemy"
    USE_SINGLE_FLEET = "use_single_fleet"
    USE_SUPPORT_FLEET = "use_support_fleet"
    MOVABLE_ENEMY = "movable_enemy"


_PROGRAM_MARKER_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")


class ProgramMarker(ABC):
    """仅在当前地图会话内持久化的类型化事实。"""

    __slots__ = ()

    @property
    @abstractmethod
    def value(self) -> str:
        """返回 checkpoint 与内容文档共用的稳定编码。"""

    @classmethod
    def parse(cls, value: str) -> ProgramMarker:
        if not isinstance(value, str) or not value:
            message = "program marker encoding must be a non-empty string"
            raise ContentValidationError(message)
        parts = value.split(":")
        try:
            match parts:
                case ["named", name]:
                    return NamedProgramMarker(name)
                case ["picked_map_item", kind, raw_x, raw_y]:
                    return PickedMapItem(MapItemKind(kind), CellId(int(raw_x), int(raw_y)))
                case ["visited_fixed_target", raw_x, raw_y]:
                    return VisitedFixedTarget(CellId(int(raw_x), int(raw_y)))
        except (TypeError, ValueError) as error:
            message = f"invalid program marker encoding: {value!r}"
            raise ContentValidationError(message) from error
        message = f"invalid program marker encoding: {value!r}"
        raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class NamedProgramMarker(ProgramMarker):
    """内容程序自定义的一次性 latch；名称只表达业务事实，不承载控制流。"""

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _PROGRAM_MARKER_PATTERN.fullmatch(self.name) is None:
            message = f"invalid named program marker: {self.name!r}"
            raise ContentValidationError(message)

    @property
    def value(self) -> str:
        return f"named:{self.name}"


@dataclass(frozen=True, slots=True)
class PickedMapItem(ProgramMarker):
    """某个地图物品已被拾取；事实按物品和格子去重，与执行舰队无关。"""

    kind: MapItemKind
    cell: CellId

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MapItemKind):
            message = "picked map item marker requires a MapItemKind"
            raise TypeError(message)
        if not isinstance(self.cell, CellId):
            message = "picked map item marker requires a CellId"
            raise TypeError(message)

    @property
    def value(self) -> str:
        return f"picked_map_item:{self.kind.value}:{self.cell.x}:{self.cell.y}"


@dataclass(frozen=True, slots=True)
class VisitedFixedTarget(ProgramMarker):
    """某个固定目标已在本次地图会话中尝试访问。"""

    cell: CellId

    def __post_init__(self) -> None:
        if not isinstance(self.cell, CellId):
            message = "visited fixed target marker requires a CellId"
            raise TypeError(message)

    @property
    def value(self) -> str:
        return f"visited_fixed_target:{self.cell.x}:{self.cell.y}"


class ProgramMetric(StrEnum):
    BATTLE_COUNT = "battle_count"
    FLEET_STEP = "fleet_step"
    MYSTERY_COUNT = "mystery_count"
    FLEET_BOSS_INDEX = "fleet_boss_index"
    CONFIGURED_BOSS_FLEET = "configured_boss_fleet"


class ComparisonOperator(StrEnum):
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"


class CellProperty(StrEnum):
    ACCESSIBLE = "accessible"
    ENEMY_SCALE = "enemy_scale"
    ENEMY_GENRE = "enemy_genre"
    IS_MYSTERY = "is_mystery"


class MapPresence(StrEnum):
    ENEMY = "enemy"
    NON_BOSS_TARGET = "non_boss_target"
    BOSS = "boss"
    SIREN = "siren"


@dataclass(frozen=True, slots=True)
class ProgramFlagCondition:
    flag: ProgramFlag
    value: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.flag, ProgramFlag):
            message = "program flag condition requires a ProgramFlag"
            raise TypeError(message)
        if type(self.value) is not bool:
            message = "program flag condition value must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ProgramMarkerCondition:
    marker: ProgramMarker
    value: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.marker, ProgramMarker):
            message = "program marker condition requires a ProgramMarker"
            raise TypeError(message)
        if type(self.value) is not bool:
            message = "program marker condition value must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MetricCondition:
    metric: ProgramMetric
    operator: ComparisonOperator
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.metric, ProgramMetric):
            message = "metric condition requires a ProgramMetric"
            raise TypeError(message)
        if not isinstance(self.operator, ComparisonOperator):
            message = "metric condition requires a ComparisonOperator"
            raise TypeError(message)
        if type(self.value) is not int:
            message = "metric condition value must be an integer"
            raise TypeError(message)


type CellPropertyValue = bool | int | str


@dataclass(frozen=True, slots=True)
class CellPropertyCondition:
    cell: CellId
    property: CellProperty
    operator: ComparisonOperator
    value: CellPropertyValue

    def __post_init__(self) -> None:
        if not isinstance(self.cell, CellId):
            message = "cell property condition requires a CellId"
            raise TypeError(message)
        if not isinstance(self.property, CellProperty):
            message = "cell property condition requires a CellProperty"
            raise TypeError(message)
        if not isinstance(self.operator, ComparisonOperator):
            message = "cell property condition requires a ComparisonOperator"
            raise TypeError(message)
        if not isinstance(self.value, bool | int | str):
            message = "cell property condition value must be boolean, integer, or string"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class FleetAtCondition:
    cell: CellId
    fleet: FleetRole = FleetRole.ACTIVE

    def __post_init__(self) -> None:
        if not isinstance(self.cell, CellId):
            message = "fleet-at condition requires a CellId"
            raise TypeError(message)
        if not isinstance(self.fleet, FleetRole):
            message = "fleet-at condition requires a FleetRole"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MapPresenceCondition:
    presence: MapPresence

    def __post_init__(self) -> None:
        if not isinstance(self.presence, MapPresence):
            message = "map presence condition requires a MapPresence"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class BossAtCondition:
    cell: CellId

    def __post_init__(self) -> None:
        if not isinstance(self.cell, CellId):
            message = "boss-at condition requires a CellId"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class BossAccessibleCondition:
    fleet: FleetRole = FleetRole.FLEET_BOSS

    def __post_init__(self) -> None:
        if not isinstance(self.fleet, FleetRole):
            message = "boss-accessible condition requires a FleetRole"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CellAccessibleForFleetCondition:
    cell: CellId
    fleet: FleetRole

    def __post_init__(self) -> None:
        if not isinstance(self.cell, CellId):
            message = "cell-accessible-for-fleet condition requires a CellId"
            raise TypeError(message)
        if not isinstance(self.fleet, FleetRole):
            message = "cell-accessible-for-fleet condition requires a FleetRole"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CandidateEnemyCondition:
    candidates: tuple[CellId, ...]
    excluded_genres: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        if not candidates or any(not isinstance(cell, CellId) for cell in candidates):
            message = "candidate enemy condition requires CellId candidates"
            raise ContentValidationError(message)
        if len(set(candidates)) != len(candidates):
            message = "candidate enemy condition must not contain duplicate cells"
            raise ContentValidationError(message)
        genres = tuple(self.excluded_genres)
        if any(not isinstance(genre, str) or not genre for genre in genres):
            message = "candidate enemy excluded genres must be non-empty strings"
            raise ContentValidationError(message)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "excluded_genres", genres)


type AtomicProgramCondition = (
    ProgramFlagCondition
    | ProgramMarkerCondition
    | MetricCondition
    | CellPropertyCondition
    | FleetAtCondition
    | MapPresenceCondition
    | BossAtCondition
    | BossAccessibleCondition
    | CellAccessibleForFleetCondition
    | CandidateEnemyCondition
)


@dataclass(frozen=True, slots=True)
class AllProgramConditions:
    conditions: tuple[ProgramCondition, ...]

    def __post_init__(self) -> None:
        conditions = tuple(self.conditions)
        if len(conditions) < 2 or any(not _is_condition(condition) for condition in conditions):
            message = "all-program condition requires at least two valid conditions"
            raise ContentValidationError(message)
        object.__setattr__(self, "conditions", conditions)


@dataclass(frozen=True, slots=True)
class AnyProgramCondition:
    conditions: tuple[ProgramCondition, ...]

    def __post_init__(self) -> None:
        conditions = tuple(self.conditions)
        if len(conditions) < 2 or any(not _is_condition(condition) for condition in conditions):
            message = "any-program condition requires at least two valid conditions"
            raise ContentValidationError(message)
        object.__setattr__(self, "conditions", conditions)


@dataclass(frozen=True, slots=True)
class NotProgramCondition:
    condition: ProgramCondition

    def __post_init__(self) -> None:
        if not _is_condition(self.condition):
            message = "not-program condition requires a valid condition"
            raise TypeError(message)


type ProgramCondition = AtomicProgramCondition | AllProgramConditions | AnyProgramCondition | NotProgramCondition


_ATOMIC_CONDITION_TYPES = (
    ProgramFlagCondition,
    ProgramMarkerCondition,
    MetricCondition,
    CellPropertyCondition,
    FleetAtCondition,
    MapPresenceCondition,
    BossAtCondition,
    BossAccessibleCondition,
    CellAccessibleForFleetCondition,
    CandidateEnemyCondition,
)
_CONDITION_TYPES = (*_ATOMIC_CONDITION_TYPES, AllProgramConditions, AnyProgramCondition, NotProgramCondition)


def _is_condition(value: object) -> bool:
    return isinstance(value, _CONDITION_TYPES)


type ProgramMechanicAction = (
    BreakSirenCaught
    | RoadblockAction
    | PushFleetForward
    | ProtectFleet
    | RescueFleet
    | StepFleetOn
    | MoveFleet
    | MoveFleetToBestCandidate
    | EnsureFleet
    | EnsureFleetAt
    | FleetClearTarget
    | FleetClearSelectedTarget
    | PickupAmmo
    | PickupMapItem
    | ClearAllMystery
    | ClearChosenMystery
    | ClearMechanism
    | ClearMapItems
    | AirStrike
    | MoveEnemy
    | MechanicProcedure
)


_MECHANIC_ACTION_TYPES = (
    BreakSirenCaught,
    RoadblockAction,
    PushFleetForward,
    ProtectFleet,
    RescueFleet,
    StepFleetOn,
    MoveFleet,
    MoveFleetToBestCandidate,
    EnsureFleet,
    EnsureFleetAt,
    FleetClearTarget,
    FleetClearSelectedTarget,
    PickupAmmo,
    PickupMapItem,
    ClearAllMystery,
    ClearChosenMystery,
    ClearMechanism,
    ClearMapItems,
    AirStrike,
    MoveEnemy,
    MechanicProcedure,
)


type BossApproachAction = MoveFleet | MoveFleetToBestCandidate


@dataclass(frozen=True, slots=True)
class BossApproachPlan:
    battle: int
    activation_modes: frozenset[BattleProgramMode]
    actions: tuple[BossApproachAction, ...]

    def __post_init__(self) -> None:
        if type(self.battle) is not int or self.battle < 0:
            message = "boss approach battle must be a non-negative integer"
            raise ContentValidationError(message)
        activation_modes = frozenset(self.activation_modes)
        if not activation_modes:
            message = "boss approach activation_modes must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(mode, BattleProgramMode) for mode in activation_modes):
            message = "boss approach activation_modes must contain BattleProgramMode values"
            raise TypeError(message)
        if BattleProgramMode.NORMAL in activation_modes:
            message = "boss approach cannot replace the normal stage policy"
            raise ContentValidationError(message)
        actions = tuple(self.actions)
        if not actions:
            message = "boss approach actions must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(action, MoveFleet | MoveFleetToBestCandidate) for action in actions):
            message = "boss approach actions must contain fleet-move actions"
            raise TypeError(message)
        if any(action.battle != self.battle for action in actions):
            message = "boss approach actions must belong to the plan battle"
            raise ContentValidationError(message)
        if any(action.fleet is not FleetRole.FLEET_BOSS for action in actions):
            message = "boss approach actions must target the boss fleet"
            raise ContentValidationError(message)
        object.__setattr__(self, "activation_modes", activation_modes)
        object.__setattr__(self, "actions", actions)

    @property
    def referenced_cells(self) -> frozenset[CellId]:
        cells: set[CellId] = set()
        for action in self.actions:
            if isinstance(action, MoveFleet):
                cells.add(action.destination)
            else:
                cells.update(action.candidates)
        return frozenset(cells)


@dataclass(frozen=True, slots=True)
class AttemptBattleAction:
    action: BattleStep

    def __post_init__(self) -> None:
        _validate_battle_action(self.action)


@dataclass(frozen=True, slots=True)
class ReturnBattleAction:
    action: BattleStep

    def __post_init__(self) -> None:
        _validate_battle_action(self.action)


@dataclass(frozen=True, slots=True)
class AttemptMechanicAction:
    action: ProgramMechanicAction
    expected_target: EncounterExpectation

    def __post_init__(self) -> None:
        _validate_mechanic_action(self.action)
        _validate_expected_target(self.expected_target)


@dataclass(frozen=True, slots=True)
class PerformMechanicAction:
    action: ProgramMechanicAction
    expected_target: EncounterExpectation | None = None

    def __post_init__(self) -> None:
        _validate_mechanic_action(self.action)
        if self.expected_target is not None:
            _validate_expected_target(self.expected_target)


@dataclass(frozen=True, slots=True)
class ReturnMechanicAction:
    action: ProgramMechanicAction
    expected_target: EncounterExpectation | None = None

    def __post_init__(self) -> None:
        _validate_mechanic_action(self.action)
        if self.expected_target is not None:
            _validate_expected_target(self.expected_target)


@dataclass(frozen=True, slots=True)
class MechanicActionBranch:
    action: ProgramMechanicAction
    when_applied: tuple[ProgramStatement, ...]
    when_not_applied: tuple[ProgramStatement, ...] = ()
    expected_target: EncounterExpectation | None = None

    def __post_init__(self) -> None:
        _validate_mechanic_action(self.action)
        if self.expected_target is not None:
            _validate_expected_target(self.expected_target)
        object.__setattr__(
            self,
            "when_applied",
            _validated_statements(self.when_applied, allow_empty=False),
        )
        object.__setattr__(
            self,
            "when_not_applied",
            _validated_statements(self.when_not_applied, allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class ProgramBranch:
    condition: ProgramCondition
    when_true: tuple[ProgramStatement, ...]
    when_false: tuple[ProgramStatement, ...] = ()

    def __post_init__(self) -> None:
        if not _is_condition(self.condition):
            message = "program branch requires a ProgramCondition"
            raise TypeError(message)
        when_true = _validated_statements(self.when_true, allow_empty=False)
        when_false = _validated_statements(self.when_false, allow_empty=True)
        object.__setattr__(self, "when_true", when_true)
        object.__setattr__(self, "when_false", when_false)


@dataclass(frozen=True, slots=True)
class SetProgramFlag:
    flag: ProgramFlag
    value: bool

    def __post_init__(self) -> None:
        if not isinstance(self.flag, ProgramFlag):
            message = "set-program-flag requires a ProgramFlag"
            raise TypeError(message)
        if type(self.value) is not bool:
            message = "set-program-flag value must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class SetProgramFlagFromCondition:
    flag: ProgramFlag
    condition: ProgramCondition

    def __post_init__(self) -> None:
        if not isinstance(self.flag, ProgramFlag):
            message = "conditional program flag requires a ProgramFlag"
            raise TypeError(message)
        if not _is_condition(self.condition):
            message = "conditional program flag requires a ProgramCondition"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class SetProgramMarker:
    marker: ProgramMarker
    value: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.marker, ProgramMarker):
            message = "set-program-marker requires a ProgramMarker"
            raise TypeError(message)
        if type(self.value) is not bool:
            message = "set-program-marker value must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class SetProgramMarkerFromCondition:
    marker: ProgramMarker
    condition: ProgramCondition

    def __post_init__(self) -> None:
        if not isinstance(self.marker, ProgramMarker):
            message = "conditional program marker requires a ProgramMarker"
            raise TypeError(message)
        if not _is_condition(self.condition):
            message = "conditional program marker requires a ProgramCondition"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MarkAllSirenCandidates:
    pass


@dataclass(frozen=True, slots=True)
class SetMapWeights:
    rows: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        rows = tuple(tuple(row) for row in self.rows)
        if not rows or any(not row for row in rows):
            message = "map weights must contain non-empty rows"
            raise ContentValidationError(message)
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            message = "map weight rows must have equal width"
            raise ContentValidationError(message)
        if any(type(weight) is not int or weight <= 0 for row in rows for weight in row):
            message = "map weights must contain positive integers"
            raise ContentValidationError(message)
        object.__setattr__(self, "rows", rows)


@dataclass(frozen=True, slots=True)
class ReturnProgramContinue:
    pass


@dataclass(frozen=True, slots=True)
class ReturnProgramNoTarget:
    pass


@dataclass(frozen=True, slots=True)
class EndCampaign:
    pass


class BattleProgramDelegation(StrEnum):
    STAGE_POLICY = "stage_policy"
    DEFAULT_MODE = "default_mode"


@dataclass(frozen=True, slots=True)
class DelegateBattle:
    target: BattleProgramDelegation

    def __post_init__(self) -> None:
        if not isinstance(self.target, BattleProgramDelegation):
            message = "battle delegation requires a BattleProgramDelegation"
            raise TypeError(message)


type ProgramStatement = (
    AttemptBattleAction
    | ReturnBattleAction
    | AttemptMechanicAction
    | PerformMechanicAction
    | ReturnMechanicAction
    | MechanicActionBranch
    | ProgramBranch
    | SetProgramFlag
    | SetProgramFlagFromCondition
    | SetProgramMarker
    | SetProgramMarkerFromCondition
    | MarkAllSirenCandidates
    | SetMapWeights
    | ReturnProgramContinue
    | ReturnProgramNoTarget
    | EndCampaign
    | DelegateBattle
)


_STATEMENT_TYPES = (
    AttemptBattleAction,
    ReturnBattleAction,
    AttemptMechanicAction,
    PerformMechanicAction,
    ReturnMechanicAction,
    MechanicActionBranch,
    ProgramBranch,
    SetProgramFlag,
    SetProgramFlagFromCondition,
    SetProgramMarker,
    SetProgramMarkerFromCondition,
    MarkAllSirenCandidates,
    SetMapWeights,
    ReturnProgramContinue,
    ReturnProgramNoTarget,
    EndCampaign,
    DelegateBattle,
)


@dataclass(frozen=True, slots=True)
class BattleProgram:
    battle: int
    activation_modes: frozenset[BattleProgramMode]
    statements: tuple[ProgramStatement, ...]

    def __post_init__(self) -> None:
        if type(self.battle) is not int or self.battle < 0:
            message = "battle program battle must be a non-negative integer"
            raise ContentValidationError(message)
        activation_modes = frozenset(self.activation_modes)
        if not activation_modes:
            message = "battle program activation_modes must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(mode, BattleProgramMode) for mode in activation_modes):
            message = "battle program activation_modes must contain BattleProgramMode values"
            raise TypeError(message)
        statements = _validated_statements(self.statements, allow_empty=False)
        referenced_battles = {
            action_battle for statement in statements for action_battle in _statement_battles(statement)
        }
        if referenced_battles - {self.battle}:
            message = "battle program actions must belong to the program battle"
            raise ContentValidationError(message)
        object.__setattr__(self, "activation_modes", activation_modes)
        object.__setattr__(self, "statements", statements)

    @property
    def referenced_cells(self) -> frozenset[CellId]:
        cells: set[CellId] = set()
        for statement in self.statements:
            cells.update(_statement_cells(statement))
        return frozenset(cells)


class ProgramBattleTarget(StrEnum):
    ENEMY = "enemy"
    SIREN = "siren"
    BOSS = "boss"


@dataclass(frozen=True, slots=True)
class ProgramBattleSettled:
    target: ProgramBattleTarget
    advances_wave: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.target, ProgramBattleTarget):
            message = "settled program result requires a ProgramBattleTarget"
            raise TypeError(message)
        if type(self.advances_wave) is not bool:
            message = "settled program result advances_wave must be a bool"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ProgramNoTarget:
    pass


@dataclass(frozen=True, slots=True)
class ProgramContinue:
    pass


@dataclass(frozen=True, slots=True)
class ProgramFailed:
    evidence: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            message = "failed program result requires non-empty evidence"
            raise ContentValidationError(message)


type BattleProgramResult = ProgramBattleSettled | ProgramNoTarget | ProgramContinue | ProgramFailed


@dataclass(frozen=True, slots=True)
class ProgramCampaignEnded:
    pass


@dataclass(frozen=True, slots=True)
class ProgramDelegated:
    target: BattleProgramDelegation

    def __post_init__(self) -> None:
        if not isinstance(self.target, BattleProgramDelegation):
            message = "delegated program result requires a BattleProgramDelegation"
            raise TypeError(message)


type CompleteBattleProgramResult = BattleProgramResult | ProgramCampaignEnded | ProgramDelegated


def _validated_statements(
    statements: tuple[ProgramStatement, ...],
    *,
    allow_empty: bool,
) -> tuple[ProgramStatement, ...]:
    normalized = tuple(statements)
    if not allow_empty and not normalized:
        message = "battle program statements must not be empty"
        raise ContentValidationError(message)
    if any(not isinstance(statement, _STATEMENT_TYPES) for statement in normalized):
        message = "battle program contains an invalid statement"
        raise TypeError(message)
    return normalized


def _validate_battle_action(action: BattleStep) -> None:
    if not is_battle_step(action):
        message = "program battle action must be a BattleStep"
        raise TypeError(message)


def _validate_mechanic_action(action: ProgramMechanicAction) -> None:
    if not isinstance(action, _MECHANIC_ACTION_TYPES):
        message = "program mechanic action has an invalid type"
        raise TypeError(message)


def _validate_expected_target(expected: EncounterExpectation) -> None:
    if not isinstance(expected, EncounterExpectation):
        message = "program action expectation must be an EncounterExpectation"
        raise TypeError(message)
    if expected in (EncounterExpectation.MYSTERY, EncounterExpectation.STORY):
        message = "program battle expectation must be any, enemy, siren, or boss"
        raise ContentValidationError(message)


def _condition_cells(condition: ProgramCondition) -> frozenset[CellId]:
    if isinstance(
        condition,
        CellPropertyCondition | FleetAtCondition | BossAtCondition | CellAccessibleForFleetCondition,
    ):
        return frozenset({condition.cell})
    if isinstance(condition, CandidateEnemyCondition):
        return frozenset(condition.candidates)
    if isinstance(condition, AllProgramConditions | AnyProgramCondition):
        return frozenset(cell for nested in condition.conditions for cell in _condition_cells(nested))
    if isinstance(condition, NotProgramCondition):
        return _condition_cells(condition.condition)
    return frozenset()


def _mechanic_action_cells(action: ProgramMechanicAction) -> frozenset[CellId]:
    if isinstance(action, RoadblockAction):
        cells = action.referenced_cells
    elif isinstance(action, RescueFleet | EnsureFleetAt | FleetClearTarget | FleetClearSelectedTarget | AirStrike):
        action_cells = action.candidates if isinstance(action, FleetClearSelectedTarget) else (action.target,)
        cells = frozenset(action_cells)
    elif isinstance(action, StepFleetOn):
        cells = frozenset((*action.candidates, *(cell for road in action.roadblocks for cell in road.referenced_cells)))
    elif isinstance(action, MoveFleet):
        cells = frozenset({action.destination})
    elif isinstance(action, MoveFleetToBestCandidate):
        cells = frozenset(action.candidates)
    elif isinstance(action, PickupMapItem | ClearChosenMystery):
        cells = frozenset({action.cell})
    elif isinstance(action, ClearAllMystery):
        cells = frozenset(action.ignored)
    elif isinstance(action, ClearMechanism | ClearMapItems):
        cells = frozenset(action.cells)
    elif isinstance(action, MoveEnemy):
        cells = frozenset({action.source, action.target})
    else:
        cells = frozenset()
    return cells


def _statement_cells(statement: ProgramStatement) -> frozenset[CellId]:
    if isinstance(statement, ProgramBranch):
        cells = frozenset(
            (
                *_condition_cells(statement.condition),
                *(cell for nested in statement.when_true for cell in _statement_cells(nested)),
                *(cell for nested in statement.when_false for cell in _statement_cells(nested)),
            )
        )
    elif isinstance(statement, SetProgramFlagFromCondition | SetProgramMarkerFromCondition):
        cells = _condition_cells(statement.condition)
    elif isinstance(statement, AttemptMechanicAction | PerformMechanicAction | ReturnMechanicAction):
        cells = _mechanic_action_cells(statement.action)
    elif isinstance(statement, MechanicActionBranch):
        cells = frozenset(
            (
                *_mechanic_action_cells(statement.action),
                *(cell for nested in statement.when_applied for cell in _statement_cells(nested)),
                *(cell for nested in statement.when_not_applied for cell in _statement_cells(nested)),
            )
        )
    else:
        cells = frozenset()
    return cells


def _statement_battles(statement: ProgramStatement) -> frozenset[int]:
    if isinstance(statement, ProgramBranch):
        return frozenset(
            action_battle
            for nested in (*statement.when_true, *statement.when_false)
            for action_battle in _statement_battles(nested)
        )
    if isinstance(statement, AttemptMechanicAction | PerformMechanicAction | ReturnMechanicAction):
        return frozenset({statement.action.battle})
    if isinstance(statement, MechanicActionBranch):
        return frozenset(
            (
                statement.action.battle,
                *(battle for nested in statement.when_applied for battle in _statement_battles(nested)),
                *(battle for nested in statement.when_not_applied for battle in _statement_battles(nested)),
            )
        )
    return frozenset()
