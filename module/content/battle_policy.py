from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from module.content.cell import CellId
from module.content.errors import ContentValidationError

type BattlePolicyName = Literal[
    "siren_then_filtered_enemy",
    "filtered_enemy_then_default",
    "fleet_boss",
]

_FILTERED_POLICIES = frozenset({"siren_then_filtered_enemy", "filtered_enemy_then_default"})
_POLICY_NAMES = (*_FILTERED_POLICIES, "fleet_boss")
_ENEMY_SORT_KEYS = frozenset({"weight", "cost", "cost_1", "cost_2", "enemy_scale"})


class BossStrategy(StrEnum):
    FLEET_BOSS = "fleet_boss"
    MAP_SEARCH = "map_search"
    FLEET_1 = "fleet_1"
    BRUTE_FORCE = "brute_force"


@dataclass(frozen=True, slots=True)
class ClearSiren:
    genres: tuple[str, ...] = ()
    include_hidden_candidates: bool = False

    def __post_init__(self) -> None:
        genres = tuple(self.genres)
        if any(not isinstance(genre, str) or not genre for genre in genres):
            message = "siren genres must contain non-empty strings"
            raise ContentValidationError(message)
        object.__setattr__(self, "genres", genres)
        if type(self.include_hidden_candidates) is not bool:
            message = "siren include_hidden_candidates must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ClearFilteredEnemy:
    preserve: int
    enemy_filter: str | None = None

    def __post_init__(self) -> None:
        if type(self.preserve) is not int or self.preserve < 0:
            message = "filtered enemy preserve must be a non-negative integer"
            raise ContentValidationError(message)
        if self.enemy_filter is not None and (not isinstance(self.enemy_filter, str) or not self.enemy_filter.strip()):
            message = "filtered enemy override must be a non-empty string"
            raise ContentValidationError(message)


def _string_tuple(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    normalized = tuple(values)
    if any(not isinstance(value, str) or not value for value in normalized):
        message = f"{field_name} must contain non-empty strings"
        raise ContentValidationError(message)
    return normalized


def _enemy_sort(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = _string_tuple(values, field_name="enemy sort")
    unknown = tuple(value for value in normalized if value not in _ENEMY_SORT_KEYS)
    if unknown:
        message = f"unsupported enemy sort keys: {', '.join(unknown)}"
        raise ContentValidationError(message)
    if len(set(normalized)) != len(normalized):
        message = "enemy sort keys must not contain duplicates"
        raise ContentValidationError(message)
    return normalized


def _scales(values: tuple[int, ...]) -> tuple[int, ...]:
    normalized = tuple(values)
    if any(type(value) is not int or value <= 0 for value in normalized):
        message = "enemy scales must contain positive integers"
        raise ContentValidationError(message)
    if len(set(normalized)) != len(normalized):
        message = "enemy scales must not contain duplicates"
        raise ContentValidationError(message)
    return normalized


@dataclass(frozen=True, slots=True)
class ClearEnemy:
    scales: tuple[int, ...] = ()
    genres: tuple[str, ...] = ()
    sort: tuple[str, ...] = ()
    strongest: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "scales", _scales(self.scales))
        object.__setattr__(self, "genres", _string_tuple(self.genres, field_name="enemy genres"))
        object.__setattr__(self, "sort", _enemy_sort(self.sort))
        if type(self.strongest) is not bool:
            message = "enemy strongest must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ClearAnyEnemy:
    genres: tuple[str, ...] = ()
    sort: tuple[str, ...] = ()
    strongest: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "genres", _string_tuple(self.genres, field_name="enemy genres"))
        object.__setattr__(self, "sort", _enemy_sort(self.sort))
        if type(self.strongest) is not bool:
            message = "enemy strongest must be a boolean"
            raise TypeError(message)


class TargetExpectation(StrEnum):
    ENEMY = "enemy"
    SIREN = "siren"


@dataclass(frozen=True, slots=True)
class ClearChosenEnemy:
    target: CellId
    expected: TargetExpectation = TargetExpectation.ENEMY

    def __post_init__(self) -> None:
        if not isinstance(self.target, CellId):
            message = "chosen enemy target must be a CellId"
            raise TypeError(message)
        if not isinstance(self.expected, TargetExpectation):
            message = "chosen enemy expectation must be a TargetExpectation"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ClearSelectedEnemy:
    candidates: tuple[CellId, ...]
    excluded_genres: tuple[str, ...] = ()
    expected: TargetExpectation = TargetExpectation.ENEMY

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        if not candidates or any(not isinstance(cell, CellId) for cell in candidates):
            message = "selected enemy candidates must contain CellId values"
            raise ContentValidationError(message)
        if len(set(candidates)) != len(candidates):
            message = "selected enemy candidates must not contain duplicates"
            raise ContentValidationError(message)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(
            self,
            "excluded_genres",
            _string_tuple(self.excluded_genres, field_name="selected enemy excluded genres"),
        )
        if not isinstance(self.expected, TargetExpectation):
            message = "selected enemy expectation must be a TargetExpectation"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ClearPriorityEnemy:
    include_scale_1: bool = False

    def __post_init__(self) -> None:
        if type(self.include_scale_1) is not bool:
            message = "priority enemy include_scale_1 must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class DefaultBattle:
    pass


@dataclass(frozen=True, slots=True)
class ClearBoss:
    strategy: BossStrategy

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, BossStrategy):
            message = "boss strategy must be a BossStrategy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ClearBossRoadblock:
    strategy: BossStrategy

    def __post_init__(self) -> None:
        if self.strategy not in (BossStrategy.MAP_SEARCH, BossStrategy.BRUTE_FORCE):
            message = "boss roadblock strategy must be map_search or brute_force"
            raise ContentValidationError(message)


class BattleFlag(StrEnum):
    CLEAR_MODE = "clear_mode"
    MAP_HAS_MOB_MOVE = "map_has_mob_move"
    USE_SINGLE_FLEET = "use_single_fleet"


@dataclass(frozen=True, slots=True)
class FlagCondition:
    flag: BattleFlag
    value: bool

    def __post_init__(self) -> None:
        if not isinstance(self.flag, BattleFlag):
            message = "flag condition requires a BattleFlag"
            raise TypeError(message)
        if type(self.value) is not bool:
            message = "flag condition value must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CellAccessibleCondition:
    cell: CellId

    def __post_init__(self) -> None:
        if not isinstance(self.cell, CellId):
            message = "cell accessible condition requires a CellId"
            raise TypeError(message)


type AtomicBattleCondition = FlagCondition | CellAccessibleCondition


@dataclass(frozen=True, slots=True)
class AllConditions:
    conditions: tuple[AtomicBattleCondition | AllConditions | AnyCondition | NotCondition, ...]

    def __post_init__(self) -> None:
        conditions = tuple(self.conditions)
        if len(conditions) < 2 or any(not isinstance(condition, _CONDITION_TYPES) for condition in conditions):
            message = "all condition requires at least two valid conditions"
            raise ContentValidationError(message)
        object.__setattr__(self, "conditions", conditions)


@dataclass(frozen=True, slots=True)
class AnyCondition:
    conditions: tuple[AtomicBattleCondition | AllConditions | AnyCondition | NotCondition, ...]

    def __post_init__(self) -> None:
        conditions = tuple(self.conditions)
        if len(conditions) < 2 or any(not isinstance(condition, _CONDITION_TYPES) for condition in conditions):
            message = "any condition requires at least two valid conditions"
            raise ContentValidationError(message)
        object.__setattr__(self, "conditions", conditions)


@dataclass(frozen=True, slots=True)
class NotCondition:
    condition: AtomicBattleCondition | AllConditions | AnyCondition | NotCondition

    def __post_init__(self) -> None:
        if not isinstance(self.condition, _CONDITION_TYPES):
            message = "not condition requires a valid condition"
            raise TypeError(message)


_CONDITION_TYPES = (FlagCondition, CellAccessibleCondition, AllConditions, AnyCondition, NotCondition)
type BattleCondition = AtomicBattleCondition | AllConditions | AnyCondition | NotCondition


type UnguardedBattleStep = (
    ClearSiren
    | ClearFilteredEnemy
    | ClearEnemy
    | ClearAnyEnemy
    | ClearChosenEnemy
    | ClearSelectedEnemy
    | ClearPriorityEnemy
    | DefaultBattle
    | ClearBossRoadblock
    | ClearBoss
)


@dataclass(frozen=True, slots=True)
class GuardedBattleStep:
    condition: BattleCondition
    step: UnguardedBattleStep

    def __post_init__(self) -> None:
        if not isinstance(self.condition, _CONDITION_TYPES):
            message = "guarded battle step requires a BattleCondition"
            raise TypeError(message)
        if not isinstance(self.step, _STEP_TYPES):
            message = "guarded battle step contains an invalid action"
            raise TypeError(message)


_STEP_TYPES = (
    ClearSiren,
    ClearFilteredEnemy,
    ClearEnemy,
    ClearAnyEnemy,
    ClearChosenEnemy,
    ClearSelectedEnemy,
    ClearPriorityEnemy,
    DefaultBattle,
    ClearBossRoadblock,
    ClearBoss,
)

type BattleStep = UnguardedBattleStep | GuardedBattleStep
type BattleIntent = BattleStep


def is_battle_step(value: object) -> bool:
    return isinstance(value, (*_STEP_TYPES, GuardedBattleStep))


def _validated_steps(steps: tuple[BattleStep, ...]) -> tuple[BattleStep, ...]:
    normalized = tuple(steps)
    if not normalized:
        message = "battle steps must not be empty"
        raise ContentValidationError(message)
    if any(not is_battle_step(step) for step in normalized):
        message = "battle steps contain an invalid intent"
        raise TypeError(message)
    return normalized


@dataclass(frozen=True, slots=True)
class BattlePlan:
    intents: tuple[BattleIntent, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "intents", _validated_steps(self.intents))


@dataclass(frozen=True, slots=True)
class StagePolicy:
    steps: tuple[BattleStep, ...]

    def __post_init__(self) -> None:
        steps = _validated_steps(self.steps)
        self._validate_boss_steps(steps)
        object.__setattr__(self, "steps", steps)

    @staticmethod
    def _validate_boss_steps(steps: tuple[BattleStep, ...]) -> None:
        unguarded = tuple(step.step if isinstance(step, GuardedBattleStep) else step for step in steps)
        boss_steps = tuple(index for index, step in enumerate(unguarded) if isinstance(step, ClearBoss))
        if len(boss_steps) > 1 or (boss_steps and boss_steps[0] != len(steps) - 1):
            message = "a stage policy may contain one ClearBoss step, and it must be last"
            raise ContentValidationError(message)
        for index, step in enumerate(unguarded):
            if not isinstance(step, ClearBossRoadblock):
                continue
            if index + 1 >= len(steps):
                message = "ClearBossRoadblock must be immediately followed by ClearBoss"
                raise ContentValidationError(message)
            next_step = unguarded[index + 1]
            if not isinstance(next_step, ClearBoss) or next_step.strategy is not step.strategy:
                message = "ClearBossRoadblock and ClearBoss must use the same strategy"
                raise ContentValidationError(message)
        if not boss_steps:
            return
        boss = unguarded[boss_steps[0]]
        if isinstance(boss, ClearBoss) and boss.strategy in (BossStrategy.MAP_SEARCH, BossStrategy.BRUTE_FORCE):
            previous = unguarded[boss_steps[0] - 1] if boss_steps[0] > 0 else None
            if not isinstance(previous, ClearBossRoadblock):
                message = f"{boss.strategy.value} ClearBoss requires an explicit roadblock step"
                raise ContentValidationError(message)

    def to_plan(self) -> BattlePlan:
        return BattlePlan(self.steps)


@dataclass(frozen=True, slots=True)
class BattlePolicy:
    """少量常见策略的类型安全构造器；内容文件直接声明 BattleStep。"""

    name: BattlePolicyName
    preserve: int | None = None

    def __post_init__(self) -> None:
        if self.name not in _POLICY_NAMES:
            message = f"unknown battle policy: {self.name!r}"
            raise ContentValidationError(message)
        if self.name in _FILTERED_POLICIES:
            if type(self.preserve) is not int or self.preserve < 0:
                message = f"battle policy {self.name} preserve must be a non-negative integer"
                raise ContentValidationError(message)
        elif self.preserve is not None:
            message = f"battle policy {self.name} does not accept preserve"
            raise ContentValidationError(message)

    def to_stage_policy(self) -> StagePolicy:
        if self.name == "fleet_boss":
            return StagePolicy((ClearBoss(strategy=BossStrategy.FLEET_BOSS),))
        preserve = self.preserve
        if type(preserve) is not int:
            message = f"battle policy {self.name} has no compiled preserve value"
            raise ContentValidationError(message)
        filtered_enemy = ClearFilteredEnemy(preserve=preserve)
        if self.name == "siren_then_filtered_enemy":
            return StagePolicy((ClearSiren(), filtered_enemy, DefaultBattle()))
        return StagePolicy((filtered_enemy, DefaultBattle()))

    def to_plan(self) -> BattlePlan:
        return self.to_stage_policy().to_plan()
