import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Never, Protocol, cast, override

from module.application import (
    Blocked,
    DailySchedule,
    Deferred,
    DelayRange,
    DelaySampler,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
    OperatorNotificationKind,
    OperatorNotificationRequest,
    RequestAppRestart,
    RescheduleSelf,
    Retryable,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
    UpsertTaskState,
    WakePolicy,
    WakeTask,
    runtime_delay_sampler,
)
from module.content import battle_program as program_model
from module.content.campaign_session import (
    BattleAttempt,
    BattleFailed,
    BattleSucceeded,
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionError,
    CampaignSessionState,
    CampaignSessionStatus,
    NoBattleTarget,
)
from module.content.campaign_session_source import CampaignStageSelection
from module.content.models import StageRef
from module.gameplay.battle_program import BattleProgramExecution, BattleProgramReducer
from module.gameplay.emotion import EmotionSettings
from module.gameplay.validation import (
    validate_aware_datetime,
    validate_bool,
    validate_non_negative_integer,
    validate_positive_duration,
    validate_positive_integer,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from module.application import CancellationSource


_MIN_RESOURCE_RETRY = timedelta(minutes=120)
_MAX_RESOURCE_RETRY = timedelta(minutes=240)
_RESTART_REASON = "campaign detected the emotion calculation bug"
_IN_PROGRESS_REASON = "campaign battle batch is still in progress"
_STALE_PROGRESS_REASON = "stale campaign progress was discarded"
CAMPAIGN_PROGRESS_KEY = "progress"
CAMPAIGN_PROGRESS_SCHEMA_VERSION = 4


def _invalid(message: str) -> Never:
    raise ValueError(message)


class CampaignJobKind(StrEnum):
    STANDARD = "standard"
    EVENT = "event"
    EVENT_SP = "event_sp"
    EVENT_DAILY = "event_daily"
    WAR_ARCHIVES = "war_archives"
    GEMS_FARMING = "gems_farming"


class CampaignDifficulty(StrEnum):
    """关卡入口难度；不要与进入地图后检测到的 normal/loop 布局混用。"""

    NORMAL = "normal"
    HARD = "hard"


class CampaignMapAchievement(StrEnum):
    NON_STOP = "non_stop"
    FULL_CLEAR = "100_percent_clear"
    THREE_STARS = "map_3_stars"
    THREAT_SAFE = "threat_safe"
    THREAT_SAFE_WITHOUT_THREE_STARS = "threat_safe_without_3_stars"


class GemsFlagshipChange(StrEnum):
    SHIP = "ship"
    SHIP_AND_EQUIPMENT = "ship_equip"


class GemsCommonCarrier(StrEnum):
    ANY = "any"
    LANGLEY = "langley"
    BOGUE = "bogue"
    RANGER = "ranger"
    HERMES = "hermes"


class GemsVanguardChange(StrEnum):
    DISABLED = "disabled"
    SHIP = "ship"
    SHIP_AND_EQUIPMENT = "ship_equip"


class GemsCommonDestroyer(StrEnum):
    ANY = "any"
    FAVOURITE = "favourite"
    AULICK_OR_FOOTE = "aulick_or_foote"
    CASSIN_OR_DOWNES = "cassin_or_downes"
    Z20_OR_Z21 = "z20_or_z21"


class GemsFleetReplacementTrigger(StrEnum):
    LEVEL = "level"
    EMOTION = "emotion"
    HARD_PREPARATION = "hard_preparation"


class GemsFleetReplacementBoundary(StrEnum):
    PRE_ENTRY = "pre_entry"
    MAP_WITHDRAWN = "map_withdrawn"
    POST_MAP = "post_map"


@dataclass(frozen=True, slots=True)
class GemsFleetReplacementRequest:
    trigger: GemsFleetReplacementTrigger
    boundary: GemsFleetReplacementBoundary

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, GemsFleetReplacementTrigger):
            message = "gems replacement trigger must be a GemsFleetReplacementTrigger"
            raise TypeError(message)
        if not isinstance(self.boundary, GemsFleetReplacementBoundary):
            message = "gems replacement boundary must be a GemsFleetReplacementBoundary"
            raise TypeError(message)


class FleetMode(StrEnum):
    COMBAT_AUTO = "combat_auto"
    COMBAT_MANUAL = "combat_manual"
    STAND_STILL_IN_THE_MIDDLE = "stand_still_in_the_middle"
    HIDE_IN_BOTTOM_LEFT = "hide_in_bottom_left"
    HIDE_IN_UPPER_LEFT = "hide_in_upper_left"


class FleetOrder(StrEnum):
    FLEET1_MOB_FLEET2_BOSS = "fleet1_mob_fleet2_boss"
    FLEET1_BOSS_FLEET2_MOB = "fleet1_boss_fleet2_mob"
    FLEET1_ALL_FLEET2_STANDBY = "fleet1_all_fleet2_standby"
    FLEET1_STANDBY_FLEET2_ALL = "fleet1_standby_fleet2_all"


class SubmarineMode(StrEnum):
    DO_NOT_USE = "do_not_use"
    HUNT_ONLY = "hunt_only"
    BOSS_ONLY = "boss_only"
    HUNT_AND_BOSS = "hunt_and_boss"
    EVERY_COMBAT = "every_combat"


class SubmarineAutoSearchMode(StrEnum):
    STANDBY = "sub_standby"
    AUTO_CALL = "sub_auto_call"


class SubmarineDistanceToBoss(StrEnum):
    TO_BOSS_POSITION = "to_boss_position"
    ONE_GRID_TO_BOSS = "1_grid_to_boss"
    TWO_GRIDS_TO_BOSS = "2_grid_to_boss"
    USE_OPEN_OCEAN_SUPPORT = "use_open_ocean_support"


class EnemyPriorityMode(StrEnum):
    DEFAULT = "default_mode"
    LARGE_ENEMY_FIRST = "S3_enemy_first"
    SMALL_ENEMY_FIRST = "S1_enemy_first"


CAMPAIGN_JOB_KINDS: Mapping[TaskId, CampaignJobKind] = MappingProxyType(
    {
        TaskId("event_sp"): CampaignJobKind.EVENT_SP,
        TaskId("event_a"): CampaignJobKind.EVENT_DAILY,
        TaskId("event_b"): CampaignJobKind.EVENT_DAILY,
        TaskId("event_c"): CampaignJobKind.EVENT_DAILY,
        TaskId("event_d"): CampaignJobKind.EVENT_DAILY,
        TaskId("main"): CampaignJobKind.STANDARD,
        TaskId("main2"): CampaignJobKind.STANDARD,
        TaskId("main3"): CampaignJobKind.STANDARD,
        TaskId("event"): CampaignJobKind.EVENT,
        TaskId("event2"): CampaignJobKind.EVENT,
        TaskId("war_archives"): CampaignJobKind.WAR_ARCHIVES,
        TaskId("gems_farming"): CampaignJobKind.GEMS_FARMING,
    }
)


_EVENT_TASK_IDS = (
    TaskId("event"),
    TaskId("event2"),
    TaskId("event_a"),
    TaskId("event_b"),
    TaskId("event_c"),
    TaskId("event_d"),
    TaskId("event_sp"),
)
_RAID_TASK_IDS = (TaskId("raid"), TaskId("raid_daily"))
_COALITION_TASK_IDS = (TaskId("coalition"), TaskId("coalition_sp"))
_HOSPITAL_TASK_IDS = (TaskId("hospital"),)
_MARITIME_TASK_IDS = (TaskId("maritime_escort"),)
_EVENT_POINT_LIMIT_TASK_IDS = _EVENT_TASK_IDS + _RAID_TASK_IDS + _COALITION_TASK_IDS + _HOSPITAL_TASK_IDS
_EVENT_TIME_LIMIT_TASK_IDS = _EVENT_POINT_LIMIT_TASK_IDS + _MARITIME_TASK_IDS


def _validate_int_range(value: int, *, field_name: str, minimum: int, maximum: int) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if not minimum <= value <= maximum:
        message = f"{field_name} must be between {minimum} and {maximum}"
        raise ValueError(message)


def _validate_probability(value: float, *, field_name: str) -> None:
    if type(value) is not float:
        message = f"{field_name} must be a float"
        raise TypeError(message)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        message = f"{field_name} must be finite and between 0.0 and 1.0"
        raise ValueError(message)


def _validate_revision(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        _invalid(f"{field_name} must be trimmed and non-empty")


def _validate_progress_state(
    variant: CampaignRunVariant,
    state: CampaignSessionState,
) -> None:
    if state.variant is not variant:
        _invalid("campaign progress variant must match session_state.variant")
    if state.status is not CampaignSessionStatus.ACTIVE:
        _invalid("campaign progress must contain an active session state")
    if state.pending is not None:
        _invalid("campaign progress must not contain a pending battle attempt")


@dataclass(frozen=True, slots=True)
class CampaignAutomationSettings:
    ambush_evade: bool
    use_2x_book: bool
    use_auto_search: bool
    use_clear_mode: bool
    use_fleet_lock: bool

    def __post_init__(self) -> None:
        for field_name in (
            "ambush_evade",
            "use_2x_book",
            "use_auto_search",
            "use_clear_mode",
            "use_fleet_lock",
        ):
            validate_bool(value=getattr(self, field_name), field_name=field_name)


@dataclass(frozen=True, slots=True)
class CampaignFleetSettings:
    fleet1: int
    fleet1_mode: FleetMode
    fleet1_step: int
    fleet2: int
    fleet2_mode: FleetMode
    fleet2_step: int
    order: FleetOrder

    def __post_init__(self) -> None:
        _validate_int_range(self.fleet1, field_name="fleet1", minimum=1, maximum=6)
        _validate_int_range(self.fleet2, field_name="fleet2", minimum=0, maximum=6)
        _validate_int_range(self.fleet1_step, field_name="fleet1_step", minimum=2, maximum=5)
        _validate_int_range(self.fleet2_step, field_name="fleet2_step", minimum=2, maximum=5)
        if not isinstance(self.fleet1_mode, FleetMode):
            message = "fleet1_mode must be a FleetMode"
            raise TypeError(message)
        if not isinstance(self.fleet2_mode, FleetMode):
            message = "fleet2_mode must be a FleetMode"
            raise TypeError(message)
        if not isinstance(self.order, FleetOrder):
            message = "order must be a FleetOrder"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CampaignSubmarineSettings:
    fleet: int
    mode: SubmarineMode
    auto_search_mode: SubmarineAutoSearchMode
    distance_to_boss: SubmarineDistanceToBoss

    def __post_init__(self) -> None:
        _validate_int_range(self.fleet, field_name="fleet", minimum=0, maximum=2)
        if not isinstance(self.mode, SubmarineMode):
            message = "mode must be a SubmarineMode"
            raise TypeError(message)
        if not isinstance(self.auto_search_mode, SubmarineAutoSearchMode):
            message = "auto_search_mode must be a SubmarineAutoSearchMode"
            raise TypeError(message)
        if not isinstance(self.distance_to_boss, SubmarineDistanceToBoss):
            message = "distance_to_boss must be a SubmarineDistanceToBoss"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CampaignHpControlSettings:
    use_hp_balance: bool
    use_emergency_repair: bool
    use_low_hp_retreat: bool
    hp_balance_threshold: float
    hp_balance_weight: tuple[int, int, int]
    repair_use_single_threshold: float
    repair_use_multi_threshold: float
    low_hp_retreat_threshold: float

    def __post_init__(self) -> None:
        for field_name in ("use_hp_balance", "use_emergency_repair", "use_low_hp_retreat"):
            validate_bool(value=getattr(self, field_name), field_name=field_name)
        for field_name in (
            "hp_balance_threshold",
            "repair_use_single_threshold",
            "repair_use_multi_threshold",
            "low_hp_retreat_threshold",
        ):
            _validate_probability(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.hp_balance_weight, tuple):
            message = "hp_balance_weight must be a tuple"
            raise TypeError(message)
        if len(self.hp_balance_weight) != 3:
            message = "hp_balance_weight must contain exactly three integers"
            raise ValueError(message)
        if any(type(weight) is not int for weight in self.hp_balance_weight):
            message = "hp_balance_weight must contain integers"
            raise TypeError(message)
        if any(weight <= 0 for weight in self.hp_balance_weight):
            message = "hp_balance_weight must contain exactly three positive integers"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CampaignEnemyPrioritySettings:
    scale_balance_weight: EnemyPriorityMode

    def __post_init__(self) -> None:
        if not isinstance(self.scale_balance_weight, EnemyPriorityMode):
            message = "scale_balance_weight must be an EnemyPriorityMode"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CampaignExecutionSettings:
    automation: CampaignAutomationSettings
    fleets: CampaignFleetSettings
    submarine: CampaignSubmarineSettings
    emotion: EmotionSettings
    hp_control: CampaignHpControlSettings
    enemy_priority: CampaignEnemyPrioritySettings

    def __post_init__(self) -> None:
        expected = (
            ("automation", CampaignAutomationSettings),
            ("fleets", CampaignFleetSettings),
            ("submarine", CampaignSubmarineSettings),
            ("emotion", EmotionSettings),
            ("hp_control", CampaignHpControlSettings),
            ("enemy_priority", CampaignEnemyPrioritySettings),
        )
        for field_name, expected_type in expected:
            if not isinstance(getattr(self, field_name), expected_type):
                message = f"{field_name} must be {expected_type.__name__}"
                raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CampaignLimits:
    run_count: int = 0
    reach_level: int = 0
    oil: int = 0
    stop_on_new_ship: bool = False
    event_points: int = 0
    event_deadline_at: datetime | None = None
    map_achievement: CampaignMapAchievement = CampaignMapAchievement.NON_STOP
    stage_increase: bool = False

    def __post_init__(self) -> None:
        validate_non_negative_integer(self.run_count, field_name="run_count")
        validate_non_negative_integer(self.reach_level, field_name="reach_level")
        validate_non_negative_integer(self.oil, field_name="oil")
        validate_non_negative_integer(self.event_points, field_name="event_points")
        validate_bool(value=self.stop_on_new_ship, field_name="stop_on_new_ship")
        if not isinstance(self.map_achievement, CampaignMapAchievement):
            message = "map_achievement must be a CampaignMapAchievement"
            raise TypeError(message)
        validate_bool(value=self.stage_increase, field_name="stage_increase")
        if self.stage_increase and self.map_achievement is CampaignMapAchievement.NON_STOP:
            _invalid("stage_increase requires a map achievement stop condition")
        if self.event_deadline_at is not None:
            validate_aware_datetime(self.event_deadline_at, field_name="event_deadline_at")

    @property
    def effective_oil_limit(self) -> int:
        # 旧玩法即使配置为零也会保留 500 油的安全底线。
        return max(500, self.oil)


@dataclass(frozen=True, slots=True)
class CampaignCompletionPolicy:
    achievement: CampaignMapAchievement
    stage_increase: bool
    next_stage_ref: StageRef | None = None
    resource_free: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.achievement, CampaignMapAchievement):
            message = "achievement must be a CampaignMapAchievement"
            raise TypeError(message)
        if type(self.stage_increase) is not bool or type(self.resource_free) is not bool:
            message = "campaign completion policy flags must be booleans"
            raise TypeError(message)
        if self.next_stage_ref is not None and not isinstance(self.next_stage_ref, StageRef):
            message = "next_stage_ref must be a StageRef or None"
            raise TypeError(message)
        if self.next_stage_ref is not None and not self.stage_increase:
            _invalid("next_stage_ref requires stage_increase")
        if self.stage_increase and self.achievement is CampaignMapAchievement.NON_STOP:
            _invalid("stage_increase requires a map achievement")

    def reached(
        self,
        *,
        full_clear: bool,
        three_stars: bool,
        threat_safe: bool,
    ) -> bool:
        if any(type(value) is not bool for value in (full_clear, three_stars, threat_safe)):
            message = "map achievement evidence must contain booleans"
            raise TypeError(message)
        if self.achievement is CampaignMapAchievement.NON_STOP:
            return False
        if self.achievement is CampaignMapAchievement.FULL_CLEAR:
            return full_clear
        if self.achievement is CampaignMapAchievement.THREE_STARS:
            return full_clear and three_stars
        if self.achievement is CampaignMapAchievement.THREAT_SAFE_WITHOUT_THREE_STARS:
            return full_clear and threat_safe
        if self.achievement is CampaignMapAchievement.THREAT_SAFE:
            return full_clear and three_stars and threat_safe
        _invalid("unsupported campaign map achievement")


@dataclass(frozen=True, slots=True)
class TaskBalancerPolicy:
    target_task_id: TaskId
    coin_limit: int
    retry_delay: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not isinstance(self.target_task_id, TaskId):
            message = "target_task_id must be a TaskId"
            raise TypeError(message)
        validate_non_negative_integer(self.coin_limit, field_name="coin_limit")
        validate_positive_duration(self.retry_delay, field_name="retry_delay")


@dataclass(frozen=True, slots=True)
class GemsFarmingSettings:
    fallback_ref: StageRef
    flagship_change: GemsFlagshipChange
    common_carrier: GemsCommonCarrier
    vanguard_change: GemsVanguardChange
    common_destroyer: GemsCommonDestroyer
    replacement_retry_delay: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if not isinstance(self.fallback_ref, StageRef):
            message = "fallback_ref must be a StageRef"
            raise TypeError(message)
        if not isinstance(self.flagship_change, GemsFlagshipChange):
            message = "flagship_change must be a GemsFlagshipChange"
            raise TypeError(message)
        if not isinstance(self.common_carrier, GemsCommonCarrier):
            message = "common_carrier must be a GemsCommonCarrier"
            raise TypeError(message)
        if not isinstance(self.vanguard_change, GemsVanguardChange):
            message = "vanguard_change must be a GemsVanguardChange"
            raise TypeError(message)
        if not isinstance(self.common_destroyer, GemsCommonDestroyer):
            message = "common_destroyer must be a GemsCommonDestroyer"
            raise TypeError(message)
        validate_positive_duration(self.replacement_retry_delay, field_name="replacement_retry_delay")


@dataclass(frozen=True, slots=True)
class CampaignJobSettings:
    task_id: TaskId
    stage_refs: tuple[StageRef, ...]
    difficulty: CampaignDifficulty
    execution: CampaignExecutionSettings
    schedule: DailySchedule
    failure_retry_delay: DelayRange
    resource_retry_delay: timedelta
    limits: CampaignLimits
    task_balancer: TaskBalancerPolicy | None = None
    gems_farming: GemsFarmingSettings | None = None

    def __post_init__(self) -> None:
        self._validate_task_id()
        self._validate_stage_refs()
        self._validate_execution_settings()
        self._validate_limit_scope()
        self._validate_gems_settings()

    def _validate_task_id(self) -> None:
        if not isinstance(self.task_id, TaskId):
            message = "task_id must be a TaskId"
            raise TypeError(message)
        if self.task_id not in CAMPAIGN_JOB_KINDS:
            message = f"unsupported campaign task: {self.task_id.value}"
            raise ValueError(message)

    def _validate_execution_settings(self) -> None:
        if not isinstance(self.difficulty, CampaignDifficulty):
            message = "difficulty must be a CampaignDifficulty"
            raise TypeError(message)
        if not isinstance(self.execution, CampaignExecutionSettings):
            message = "execution must be CampaignExecutionSettings"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be DailySchedule"
            raise TypeError(message)
        if not isinstance(self.failure_retry_delay, DelayRange):
            message = "failure_retry_delay must be a DelayRange"
            raise TypeError(message)
        validate_positive_duration(self.resource_retry_delay, field_name="resource_retry_delay")
        if not _MIN_RESOURCE_RETRY <= self.resource_retry_delay <= _MAX_RESOURCE_RETRY:
            message = "resource_retry_delay must be between 120 and 240 minutes"
            raise ValueError(message)
        if not isinstance(self.limits, CampaignLimits):
            message = "limits must be CampaignLimits"
            raise TypeError(message)
        if self.task_balancer is not None and not isinstance(self.task_balancer, TaskBalancerPolicy):
            message = "task_balancer must be a TaskBalancerPolicy or None"
            raise TypeError(message)

    def _validate_gems_settings(self) -> None:
        if self.kind is CampaignJobKind.GEMS_FARMING:
            if not isinstance(self.gems_farming, GemsFarmingSettings):
                message = "gems_farming jobs require GemsFarmingSettings"
                raise TypeError(message)
        elif self.gems_farming is not None:
            message = "gems_farming settings are only valid for gems_farming jobs"
            raise ValueError(message)

    @property
    def kind(self) -> CampaignJobKind:
        return CAMPAIGN_JOB_KINDS[self.task_id]

    def _validate_stage_refs(self) -> None:
        if not isinstance(self.stage_refs, tuple):
            message = "stage_refs must be a tuple"
            raise TypeError(message)
        if any(not isinstance(ref, StageRef) for ref in self.stage_refs):
            message = "stage_refs must contain StageRef values"
            raise TypeError(message)
        if len(set(self.stage_refs)) != len(self.stage_refs):
            message = "stage_refs must not contain duplicates"
            raise ValueError(message)
        if self.kind is CampaignJobKind.EVENT_SP:
            if len(self.stage_refs) > 1:
                message = "event_sp stage_refs must contain at most one stage"
                raise ValueError(message)
        elif self.kind is not CampaignJobKind.EVENT_DAILY and len(self.stage_refs) != 1:
            message = f"{self.kind.value} stage_refs must contain exactly one stage"
            raise ValueError(message)

    def _validate_limit_scope(self) -> None:
        supports_event_limits = self.kind in {
            CampaignJobKind.EVENT,
            CampaignJobKind.EVENT_SP,
            CampaignJobKind.EVENT_DAILY,
            CampaignJobKind.GEMS_FARMING,
        }
        if not supports_event_limits and (self.limits.event_points or self.limits.event_deadline_at is not None):
            message = "event limits are only valid for event or gems-farming jobs"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class GemsFarmingPolicy:
    fallback_session: CampaignSession
    flagship_change: GemsFlagshipChange
    common_carrier: GemsCommonCarrier
    vanguard_change: GemsVanguardChange
    common_destroyer: GemsCommonDestroyer
    replacement_retry_delay: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if not isinstance(self.fallback_session, CampaignSession):
            message = "fallback_session must be a CampaignSession"
            raise TypeError(message)
        if not isinstance(self.flagship_change, GemsFlagshipChange):
            message = "flagship_change must be a GemsFlagshipChange"
            raise TypeError(message)
        if not isinstance(self.common_carrier, GemsCommonCarrier):
            message = "common_carrier must be a GemsCommonCarrier"
            raise TypeError(message)
        if not isinstance(self.vanguard_change, GemsVanguardChange):
            message = "vanguard_change must be a GemsVanguardChange"
            raise TypeError(message)
        if not isinstance(self.common_destroyer, GemsCommonDestroyer):
            message = "common_destroyer must be a GemsCommonDestroyer"
            raise TypeError(message)
        validate_positive_duration(self.replacement_retry_delay, field_name="replacement_retry_delay")

    @property
    def changes_vanguard(self) -> bool:
        return self.vanguard_change is not GemsVanguardChange.DISABLED

    @property
    def level_cap(self) -> int:
        return 32

    @property
    def emotion_after_replacement(self) -> int:
        return 150


@dataclass(frozen=True, slots=True)
class CampaignProgress:
    """一个地图 battle 安全点上的完整可恢复状态。"""

    stage_ref: StageRef
    variant: CampaignRunVariant
    session_state: CampaignSessionState
    runs_completed: int
    settings_revision: int
    content_revision: str
    pending_gems_replacement: GemsFleetReplacementRequest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage_ref, StageRef):
            message = "stage_ref must be a StageRef"
            raise TypeError(message)
        if not isinstance(self.variant, CampaignRunVariant):
            message = "variant must be a CampaignRunVariant"
            raise TypeError(message)
        if not isinstance(self.session_state, CampaignSessionState):
            message = "session_state must be a CampaignSessionState"
            raise TypeError(message)
        _validate_progress_state(self.variant, self.session_state)
        validate_non_negative_integer(self.runs_completed, field_name="runs_completed")
        validate_positive_integer(self.settings_revision, field_name="settings_revision")
        _validate_revision(self.content_revision, field_name="content_revision")
        if self.pending_gems_replacement is not None and not isinstance(
            self.pending_gems_replacement,
            GemsFleetReplacementRequest,
        ):
            message = "pending_gems_replacement must be a GemsFleetReplacementRequest or None"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CampaignJobSpec:
    task_id: TaskId
    sessions: tuple[CampaignSession, ...]
    difficulty: CampaignDifficulty
    execution: CampaignExecutionSettings
    schedule: DailySchedule
    failure_retry_delay: DelayRange
    resource_retry_delay: timedelta
    limits: CampaignLimits = field(default_factory=CampaignLimits)
    task_balancer: TaskBalancerPolicy | None = None
    gems_farming: GemsFarmingPolicy | None = None
    progress: CampaignProgress | None = None
    stage_selections: tuple[CampaignStageSelection, ...] = ()
    transition_sessions: tuple[CampaignSession, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, TaskId):
            message = "task_id must be a TaskId"
            raise TypeError(message)
        if self.task_id not in CAMPAIGN_JOB_KINDS:
            message = f"unsupported campaign task: {self.task_id.value}"
            raise ValueError(message)
        sessions = self._validated_sessions()
        if not isinstance(self.difficulty, CampaignDifficulty):
            message = "difficulty must be a CampaignDifficulty"
            raise TypeError(message)
        if not isinstance(self.execution, CampaignExecutionSettings):
            message = "execution must be CampaignExecutionSettings"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be DailySchedule"
            raise TypeError(message)
        self._validate_failure_retry_delay()
        validate_positive_duration(self.resource_retry_delay, field_name="resource_retry_delay")
        if not _MIN_RESOURCE_RETRY <= self.resource_retry_delay <= _MAX_RESOURCE_RETRY:
            message = "resource_retry_delay must be between 120 and 240 minutes"
            raise ValueError(message)
        if not isinstance(self.limits, CampaignLimits):
            message = "limits must be CampaignLimits"
            raise TypeError(message)
        if self.task_balancer is not None and not isinstance(self.task_balancer, TaskBalancerPolicy):
            message = "task_balancer must be a TaskBalancerPolicy or None"
            raise TypeError(message)
        if self.progress is not None and not isinstance(self.progress, CampaignProgress):
            message = "progress must be a CampaignProgress or None"
            raise TypeError(message)
        primary_refs = tuple(dict.fromkeys(session.definition.ref for session in sessions))
        selections = self._validated_stage_selections(primary_refs)
        transitions = self._validated_transition_sessions(primary_refs, selections)
        self._validate_gems_policy(primary_refs)
        object.__setattr__(self, "sessions", sessions)
        object.__setattr__(self, "stage_selections", selections)
        object.__setattr__(self, "transition_sessions", transitions)

    def _validate_failure_retry_delay(self) -> None:
        if not isinstance(self.failure_retry_delay, DelayRange):
            message = "failure_retry_delay must be a DelayRange"
            raise TypeError(message)

    def _validated_sessions(self) -> tuple[CampaignSession, ...]:
        sessions = tuple(self.sessions)
        if any(not isinstance(session, CampaignSession) for session in sessions):
            message = "sessions must contain CampaignSession values"
            raise TypeError(message)
        if not sessions and self.kind not in (CampaignJobKind.EVENT_SP, CampaignJobKind.EVENT_DAILY):
            message = f"{self.kind.value} campaign jobs require a primary session"
            raise ValueError(message)
        keys = tuple((session.definition.ref, session.variant) for session in sessions)
        if len(set(keys)) != len(keys):
            message = "campaign session stage/variant pairs must be unique"
            raise ValueError(message)
        refs = tuple(dict.fromkeys(session.definition.ref for session in sessions))
        for ref in refs:
            variants = {session.variant for session in sessions if session.definition.ref == ref}
            if variants != set(CampaignRunVariant):
                message = f"campaign stage must provide normal and loop sessions: {ref.pack_id}/{ref.stage_id}"
                raise ValueError(message)
        if self.kind not in (CampaignJobKind.EVENT_SP, CampaignJobKind.EVENT_DAILY) and len(refs) != 1:
            message = f"{self.kind.value} campaign jobs require exactly one primary session"
            raise ValueError(message)
        if self.kind is CampaignJobKind.EVENT_SP and len(refs) > 1:
            message = "event_sp campaign jobs accept at most one primary session"
            raise ValueError(message)
        return sessions

    @property
    def kind(self) -> CampaignJobKind:
        return CAMPAIGN_JOB_KINDS[self.task_id]

    @property
    def stage_refs(self) -> tuple[StageRef, ...]:
        return tuple(dict.fromkeys(session.definition.ref for session in self.sessions))

    @property
    def resumable_sessions(self) -> tuple[CampaignSession, ...]:
        sessions = (*self.sessions, *self.transition_sessions)
        if self.gems_farming is not None:
            fallback = self.gems_farming.fallback_session
            sessions += tuple(CampaignSession(fallback.definition, variant) for variant in CampaignRunVariant)
        return sessions

    def session_for(self, ref: StageRef, variant: CampaignRunVariant) -> CampaignSession | None:
        for session in self.resumable_sessions:
            if session.definition.ref == ref and session.variant is variant:
                return session
        return None

    def selection_for(self, ref: StageRef) -> CampaignStageSelection | None:
        for selection in self.stage_selections:
            if selection.selected_ref == ref:
                return selection
        return None

    def completion_for(self, ref: StageRef) -> CampaignCompletionPolicy:
        selection = self.selection_for(ref)
        achievement = self.limits.map_achievement
        stage_increase = self.limits.stage_increase
        resource_free = False
        next_ref = None
        if selection is not None:
            if selection.force_threat_safe and achievement is not CampaignMapAchievement.NON_STOP:
                achievement = CampaignMapAchievement.THREAT_SAFE
            if selection.resource_free:
                achievement = CampaignMapAchievement.FULL_CLEAR
                stage_increase = True
                resource_free = True
            if selection.loop_stage_switch:
                achievement = CampaignMapAchievement.NON_STOP
                stage_increase = False
            fallback = dict(selection.map_achievement_fallbacks).get(achievement.value)
            if fallback is not None:
                achievement = CampaignMapAchievement(fallback)
            if stage_increase:
                next_ref = selection.next_ref
        return CampaignCompletionPolicy(
            achievement=achievement,
            stage_increase=stage_increase,
            next_stage_ref=next_ref,
            resource_free=resource_free,
        )

    def _validated_stage_selections(
        self,
        primary_refs: tuple[StageRef, ...],
    ) -> tuple[CampaignStageSelection, ...]:
        selections = tuple(self.stage_selections)
        if not selections:
            return tuple(CampaignStageSelection(ref, ref) for ref in primary_refs)
        if any(not isinstance(selection, CampaignStageSelection) for selection in selections):
            message = "stage_selections must contain CampaignStageSelection values"
            raise TypeError(message)
        if tuple(selection.selected_ref for selection in selections) != primary_refs:
            message = "stage_selections must match the ordered primary campaign stages"
            raise ValueError(message)
        requested_refs = tuple(selection.requested_ref for selection in selections)
        if len(set(requested_refs)) != len(requested_refs):
            message = "stage_selections requested refs must be unique"
            raise ValueError(message)
        return selections

    def _validated_transition_sessions(
        self,
        primary_refs: tuple[StageRef, ...],
        selections: tuple[CampaignStageSelection, ...],
    ) -> tuple[CampaignSession, ...]:
        transitions = tuple(self.transition_sessions)
        if any(not isinstance(session, CampaignSession) for session in transitions):
            message = "transition_sessions must contain CampaignSession values"
            raise TypeError(message)
        keys = tuple((session.definition.ref, session.variant) for session in transitions)
        if len(set(keys)) != len(keys):
            message = "campaign transition stage/variant pairs must be unique"
            raise ValueError(message)
        refs = tuple(dict.fromkeys(session.definition.ref for session in transitions))
        expected_refs = tuple(
            dict.fromkeys(
                selection.next_ref
                for selection in selections
                if selection.next_ref is not None and selection.next_ref not in primary_refs
            )
        )
        if refs != expected_refs:
            message = "transition_sessions must match the selected stages' next refs"
            raise ValueError(message)
        for ref in refs:
            variants = {session.variant for session in transitions if session.definition.ref == ref}
            if variants != set(CampaignRunVariant):
                message = f"campaign transition must provide normal and loop sessions: {ref.pack_id}/{ref.stage_id}"
                raise ValueError(message)
        return transitions

    def _validate_gems_policy(self, primary_refs: tuple[StageRef, ...]) -> None:
        if self.kind is CampaignJobKind.GEMS_FARMING:
            if not isinstance(self.gems_farming, GemsFarmingPolicy):
                message = "gems_farming jobs require GemsFarmingPolicy"
                raise TypeError(message)
            fallback_ref = self.gems_farming.fallback_session.definition.ref
            if fallback_ref in primary_refs and fallback_ref.pack_id != "campaign_main":
                message = "gems farming fallback stage must differ from its primary stage"
                raise ValueError(message)
            return
        if self.progress is not None and self.progress.pending_gems_replacement is not None:
            message = "pending gems replacement is only valid for gems_farming"
            raise ValueError(message)
        if self.gems_farming is not None:
            message = "GemsFarmingPolicy is only valid for gems_farming"
            raise ValueError(message)


class CampaignStopReason(StrEnum):
    IN_PROGRESS = "in_progress"
    PROGRAM_CONTINUE = "program_continue"
    COMPLETED = "completed"
    RUN_COUNT_LIMIT = "run_count_limit"
    REACH_LEVEL_LIMIT = "reach_level_limit"
    OIL_LIMIT = "oil_limit"
    AUTO_SEARCH_OIL_LIMIT = "auto_search_oil_limit"
    NEW_SHIP = "new_ship"
    EVENT_POINT_LIMIT = "event_point_limit"
    EVENT_TIME_LIMIT = "event_time_limit"
    EVENT_UNAVAILABLE = "event_unavailable"
    NO_ELIGIBLE_STAGE = "no_eligible_stage"
    CONTENT_UNAVAILABLE = "content_unavailable"
    DATA_KEYS_EXHAUSTED = "data_keys_exhausted"
    COIN_LIMIT = "coin_limit"
    EMOTION_BUG = "emotion_bug"
    ONE_TIME_STAGE = "one_time_stage"
    LOOP_STAGE_SWITCH = "loop_stage_switch"
    MAP_ACHIEVEMENT = "map_achievement"
    STAGE_INCREASE = "stage_increase"
    GEMS_EVENT_FALLBACK = "gems_event_fallback"
    GEMS_FLEET_REPLACED = "gems_fleet_replaced"
    GEMS_LEVEL_REPLACEMENT_FAILED = "gems_level_replacement_failed"
    GEMS_EMOTION_REPLACEMENT_FAILED = "gems_emotion_replacement_failed"
    GEMS_HARD_PREPARATION_FAILED = "gems_hard_preparation_failed"
    CHECKPOINT_RESET = "checkpoint_reset"
    CANCELLED = "cancelled"  # AbortRequested 的 runtime 清理语义，不作为正常 workflow report。
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CampaignRunReport:
    stage_ref: StageRef
    observed_at: datetime
    stop_reason: CampaignStopReason
    session_state: CampaignSessionState
    runs_completed: int = 0
    next_stage_ref: StageRef | None = None
    gems_replacement: GemsFleetReplacementRequest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage_ref, StageRef):
            message = "stage_ref must be a StageRef"
            raise TypeError(message)
        validate_aware_datetime(self.observed_at, field_name="observed_at")
        if not isinstance(self.stop_reason, CampaignStopReason):
            message = "stop_reason must be a CampaignStopReason"
            raise TypeError(message)
        if not isinstance(self.session_state, CampaignSessionState):
            message = "session_state must be a CampaignSessionState"
            raise TypeError(message)
        if self.session_state.pending is not None:
            _invalid("campaign workflow report must not contain a pending battle attempt")
        validate_non_negative_integer(self.runs_completed, field_name="runs_completed")
        if self.runs_completed > 1:
            _invalid("campaign workflow must complete at most one map run per task run")
        if self.next_stage_ref is not None and not isinstance(self.next_stage_ref, StageRef):
            message = "next_stage_ref must be a StageRef or None"
            raise TypeError(message)
        _validate_report_transition(self.stop_reason, self.next_stage_ref, self.gems_replacement)
        completed = self.session_state.status is CampaignSessionStatus.COMPLETED
        if completed != (self.runs_completed == 1):
            _invalid("runs_completed must be one exactly when the session state is completed")
        if self.stop_reason is CampaignStopReason.IN_PROGRESS and self.session_state.status not in (
            CampaignSessionStatus.ACTIVE,
            CampaignSessionStatus.COMPLETED,
        ):
            _invalid("in-progress campaign report must contain a resumable session state")
        _validate_program_continue_state(self.stop_reason, self.session_state.status)


def _validate_program_continue_state(
    reason: CampaignStopReason,
    status: CampaignSessionStatus,
) -> None:
    if reason is CampaignStopReason.PROGRAM_CONTINUE and status is not CampaignSessionStatus.ACTIVE:
        _invalid("program-continue report must contain an active session state")


def _validate_optional_gems_replacement(value: GemsFleetReplacementRequest | None) -> None:
    if value is not None and not isinstance(value, GemsFleetReplacementRequest):
        message = "gems_replacement must be a GemsFleetReplacementRequest or None"
        raise TypeError(message)


def _validate_report_transition(
    reason: CampaignStopReason,
    next_stage_ref: StageRef | None,
    gems_replacement: GemsFleetReplacementRequest | None,
) -> None:
    _validate_optional_gems_replacement(gems_replacement)
    if next_stage_ref is not None and gems_replacement is not None:
        _invalid("campaign report cannot combine stage increase with gems replacement")
    if (reason is CampaignStopReason.STAGE_INCREASE) is not (next_stage_ref is not None):
        _invalid("stage-increase reports must contain exactly one next_stage_ref")


class CampaignWorkflow(Protocol):
    def discard_checkpoint(self) -> None:
        """释放只属于已失效 checkpoint 的运行时资源。"""

    def execute(
        self,
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> CampaignRunReport:
        """最多确认一个 battle，并在 pending 已清空的安全点返回。"""


class CampaignTask(Task):
    __slots__ = ("_delay_sampler", "_job", "_workflow")

    def __init__(
        self,
        workflow: CampaignWorkflow,
        job: CampaignJobSpec,
        *,
        delay_sampler: DelaySampler = runtime_delay_sampler,
    ) -> None:
        if not isinstance(job, CampaignJobSpec):
            message = "job must be a CampaignJobSpec"
            raise TypeError(message)
        if not isinstance(delay_sampler, DelaySampler):
            message = "delay_sampler must be a DelaySampler"
            raise TypeError(message)
        self._workflow = workflow
        self._job = job
        self._delay_sampler = delay_sampler

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        if context.task_id != self._job.task_id:
            message = "TaskContext.task_id must match CampaignJobSpec.task_id"
            raise ValueError(message)

        progress, stale_progress = self._current_progress(context)
        if stale_progress:
            self._workflow.discard_checkpoint()
            return self._for_execution_mode(
                context.mode,
                TaskResult(
                    outcome=Deferred(_STALE_PROGRESS_REASON),
                    effects=(RescheduleSelf(context.started_at),),
                    state_effects=(self._delete_progress(context),),
                ),
            )
        if not self._job.sessions:
            return self._for_execution_mode(
                context.mode,
                self._terminal_result(context, self._content_unavailable_result(None)),
            )
        if progress is not None and self._run_budget_exhausted(progress.runs_completed):
            return self._for_execution_mode(
                context.mode,
                self._terminal_result(context, self._disable_self_result(None)),
            )

        report = self._workflow.execute(self._job, context.abort)
        if not isinstance(report, CampaignRunReport):
            message = "CampaignWorkflow.execute() must return a CampaignRunReport"
            raise TypeError(message)
        self._validate_report(context, report, progress)
        if report.stop_reason in (
            CampaignStopReason.IN_PROGRESS,
            CampaignStopReason.PROGRAM_CONTINUE,
            CampaignStopReason.GEMS_EVENT_FALLBACK,
            CampaignStopReason.GEMS_FLEET_REPLACED,
            CampaignStopReason.STAGE_INCREASE,
            CampaignStopReason.CHECKPOINT_RESET,
        ):
            checkpoint = self._progress_after_report(context, report, progress)
            result = self._checkpoint_result(context, report, checkpoint, report.stop_reason)
        elif report.stop_reason in (
            CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_HARD_PREPARATION_FAILED,
        ):
            checkpoint = self._progress_after_report(context, report, progress)
            result = self._gems_replacement_checkpoint_result(context, report, checkpoint)
        else:
            result = self._terminal_result(context, self._result(report))
        return self._for_execution_mode(context.mode, result)

    @staticmethod
    def _for_execution_mode(mode: ExecutionMode, result: TaskResult) -> TaskResult:
        if mode is ExecutionMode.SCHEDULED_JOB:
            return result
        return TaskResult(
            outcome=result.outcome,
            effects=tuple(effect for effect in result.effects if isinstance(effect, RequestAppRestart)),
            state_effects=result.state_effects,
            notifications=result.notifications,
        )

    def _current_progress(self, context: TaskContext) -> tuple[CampaignProgress | None, bool]:
        progress = self._job.progress
        if progress is None:
            return None, False
        session = self._job.session_for(progress.stage_ref, progress.variant)
        is_current = (
            session is not None
            and progress.settings_revision == context.metadata.settings_revision
            and progress.content_revision == context.metadata.content_revision
        )
        if not is_current:
            return None, True
        session.validate_state(progress.session_state)
        if progress.pending_gems_replacement is not None and progress.session_state != session.initial_state():
            _invalid("pending gems replacement must be stored at a fresh map boundary")
        if self._job.limits.run_count and progress.runs_completed > self._job.limits.run_count:
            _invalid("campaign progress exceeds the configured run_count limit")
        return progress, False

    def _validate_report(
        self,
        context: TaskContext,
        report: CampaignRunReport,
        progress: CampaignProgress | None,
    ) -> None:
        if report.observed_at < context.started_at:
            _invalid("campaign report observed_at must not precede the run start")
        session = self._job.session_for(report.stage_ref, report.session_state.variant)
        if session is None:
            _invalid("campaign report stage and variant do not belong to the campaign job")
        switched_to_gems_fallback = self._is_gems_event_fallback(report, progress)
        if (
            progress is not None
            and not switched_to_gems_fallback
            and (report.stage_ref != progress.stage_ref or report.session_state.variant is not progress.variant)
        ):
            _invalid("campaign workflow cannot switch stage while resuming a checkpoint")
        session.validate_state(report.session_state)
        self._validate_checkpoint_reset(report, progress, session)
        pending_replacement = None if progress is None else progress.pending_gems_replacement
        units = self._report_units(
            report,
            session,
            progress,
            switched_to_gems_fallback=switched_to_gems_fallback,
        )
        self._validate_report_units(report, units, pending_replacement)
        if (
            report.session_state.status is CampaignSessionStatus.FAILED
            and report.stop_reason is not CampaignStopReason.FAILED
        ):
            _invalid("failed session state requires the failed stop reason")
        if (
            report.session_state.status is CampaignSessionStatus.BLOCKED
            and report.stop_reason is not CampaignStopReason.BLOCKED
        ):
            _invalid("blocked session state requires the blocked stop reason")
        runs_completed = report.runs_completed + (0 if progress is None else progress.runs_completed)
        self._validate_run_count(report, runs_completed)
        self._validate_configured_stop(report)
        self._validate_job_specific_stop(report)

    @staticmethod
    def _validate_checkpoint_reset(
        report: CampaignRunReport,
        progress: CampaignProgress | None,
        session: CampaignSession,
    ) -> None:
        if report.stop_reason is not CampaignStopReason.CHECKPOINT_RESET:
            return
        if progress is None:
            _invalid("checkpoint reset requires existing campaign progress")
        if report.session_state != session.initial_state():
            _invalid("checkpoint reset must report the initial session state")
        if report.runs_completed != 0:
            _invalid("checkpoint reset must not complete a map run")
        if report.next_stage_ref is not None or report.gems_replacement is not None:
            _invalid("checkpoint reset cannot transition stage or replace a gems fleet")

    @staticmethod
    def _report_units(
        report: CampaignRunReport,
        session: CampaignSession,
        progress: CampaignProgress | None,
        *,
        switched_to_gems_fallback: bool,
    ) -> int:
        if report.stop_reason is CampaignStopReason.CHECKPOINT_RESET:
            return 0
        replacement = report.gems_replacement
        pending_replacement = None if progress is None else progress.pending_gems_replacement
        if pending_replacement is not None and replacement != pending_replacement:
            _invalid("campaign workflow must consume the pending gems replacement before entering a map")
        map_withdrawn = (
            replacement is not None
            and replacement.boundary is GemsFleetReplacementBoundary.MAP_WITHDRAWN
            and pending_replacement is None
        )
        if map_withdrawn and report.session_state != session.initial_state():
            _invalid("map-withdrawn gems replacement must reset to the initial session state")
        if switched_to_gems_fallback or map_withdrawn:
            return 0
        initial_state = session.initial_state() if progress is None else progress.session_state
        return _confirmed_battle_units(session, initial_state, report.session_state)

    @staticmethod
    def _validate_report_units(
        report: CampaignRunReport,
        units: int,
        pending_replacement: GemsFleetReplacementRequest | None,
    ) -> None:
        if report.stop_reason is CampaignStopReason.IN_PROGRESS and units != 1:
            _invalid("in-progress campaign report must confirm exactly one battle unit")
        if report.stop_reason is CampaignStopReason.PROGRAM_CONTINUE and units != 0:
            _invalid("program continue must checkpoint a battle-free program unit")
        if report.stop_reason is CampaignStopReason.GEMS_EVENT_FALLBACK and units != 0:
            _invalid("gems event fallback must switch at a battle-free map boundary")
        if report.stop_reason is CampaignStopReason.STAGE_INCREASE and units != 0:
            _invalid("stage increase must switch at a battle-free map boundary")
        if report.stop_reason is CampaignStopReason.CHECKPOINT_RESET and units != 0:
            _invalid("checkpoint reset must not confirm a battle unit")
        replacement_failures = (
            CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_HARD_PREPARATION_FAILED,
        )
        if report.stop_reason in replacement_failures and report.gems_replacement is None:
            _invalid("gems replacement failure must preserve its typed replacement request")
        if report.stop_reason is CampaignStopReason.GEMS_FLEET_REPLACED and report.gems_replacement is None:
            _invalid("gems replacement checkpoint must preserve its typed replacement request")
        replacement = report.gems_replacement
        if replacement is None:
            return
        retrying = pending_replacement == replacement
        expected_units = 1 if replacement.boundary is GemsFleetReplacementBoundary.POST_MAP and not retrying else 0
        if units != expected_units:
            _invalid(f"gems replacement at {replacement.boundary.value} confirmed {units} battle units")

    def _validate_configured_stop(self, report: CampaignRunReport) -> None:
        reason = report.stop_reason
        if reason is CampaignStopReason.REACH_LEVEL_LIMIT and self._job.limits.reach_level == 0:
            _invalid("reach-level stop requires a configured reach_level limit")
        if reason is CampaignStopReason.NEW_SHIP and not self._job.limits.stop_on_new_ship:
            _invalid("new-ship stop requires stop_on_new_ship")
        if reason is CampaignStopReason.COIN_LIMIT and self._job.task_balancer is None:
            _invalid("coin-limit stop requires TaskBalancerPolicy")
        completion = self._job.completion_for(report.stage_ref)
        if reason is CampaignStopReason.MAP_ACHIEVEMENT:
            if completion.achievement is CampaignMapAchievement.NON_STOP:
                _invalid("map-achievement stop requires a configured achievement")
            if completion.next_stage_ref is not None:
                _invalid("map-achievement stop cannot discard an available stage increase")
        if reason is CampaignStopReason.STAGE_INCREASE:
            if completion.next_stage_ref != report.next_stage_ref:
                _invalid("stage-increase report must use the content progression target")
            target = cast("StageRef", report.next_stage_ref)
            next_session = self._job.session_for(target, CampaignRunVariant.NORMAL)
            if next_session is None:
                _invalid("stage-increase target does not belong to the campaign job")

    def _validate_job_specific_stop(self, report: CampaignRunReport) -> None:
        reason = report.stop_reason
        event_kinds = (
            CampaignJobKind.EVENT,
            CampaignJobKind.EVENT_SP,
            CampaignJobKind.EVENT_DAILY,
            CampaignJobKind.GEMS_FARMING,
        )
        if reason is CampaignStopReason.EVENT_POINT_LIMIT and (
            self._job.kind not in event_kinds or self._job.limits.event_points == 0
        ):
            _invalid("event-point stop requires an event job with a point limit")
        if reason is CampaignStopReason.EVENT_TIME_LIMIT:
            deadline = self._job.limits.event_deadline_at
            if self._job.kind not in event_kinds or deadline is None or report.observed_at <= deadline:
                _invalid("event-time stop requires an expired event deadline")
        if reason is CampaignStopReason.EVENT_UNAVAILABLE and self._job.kind not in event_kinds:
            _invalid("event-unavailable stop requires an event job")
        if reason is CampaignStopReason.NO_ELIGIBLE_STAGE and self._job.kind is not CampaignJobKind.EVENT_DAILY:
            _invalid("no-eligible-stage stop requires an event-daily job")
        if reason is CampaignStopReason.DATA_KEYS_EXHAUSTED and self._job.kind is not CampaignJobKind.WAR_ARCHIVES:
            _invalid("data-key stop requires a war-archives job")
        gems_reasons = (
            CampaignStopReason.GEMS_FLEET_REPLACED,
            CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_HARD_PREPARATION_FAILED,
        )
        if reason in gems_reasons and self._job.kind is not CampaignJobKind.GEMS_FARMING:
            _invalid("gems replacement stop requires a gems-farming job")
        self._validate_gems_replacement_report(report)
        if reason is CampaignStopReason.GEMS_EVENT_FALLBACK and self._job.kind is not CampaignJobKind.GEMS_FARMING:
            _invalid("gems event fallback requires a gems-farming job")
        if self._job.kind is CampaignJobKind.GEMS_FARMING and reason in (
            CampaignStopReason.EVENT_POINT_LIMIT,
            CampaignStopReason.EVENT_TIME_LIMIT,
            CampaignStopReason.EVENT_UNAVAILABLE,
        ):
            _invalid("gems workflow must switch to its fallback session before returning")

    def _validate_gems_replacement_report(self, report: CampaignRunReport) -> None:
        replacement = report.gems_replacement
        if replacement is None:
            return
        if self._job.kind is not CampaignJobKind.GEMS_FARMING:
            _invalid("gems replacement request requires a gems-farming job")
        allowed_reasons = (
            CampaignStopReason.IN_PROGRESS,
            CampaignStopReason.RUN_COUNT_LIMIT,
            CampaignStopReason.GEMS_FLEET_REPLACED,
            CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_HARD_PREPARATION_FAILED,
        )
        if report.stop_reason not in allowed_reasons:
            _invalid("gems replacement request is attached to an unrelated stop reason")
        failure_by_trigger = {
            GemsFleetReplacementTrigger.LEVEL: CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
            GemsFleetReplacementTrigger.EMOTION: CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED,
            GemsFleetReplacementTrigger.HARD_PREPARATION: CampaignStopReason.GEMS_HARD_PREPARATION_FAILED,
        }
        failures = tuple(failure_by_trigger.values())
        if report.stop_reason in failures and report.stop_reason is not failure_by_trigger[replacement.trigger]:
            _invalid("gems replacement failure reason does not match its trigger")
        if (
            replacement.trigger is GemsFleetReplacementTrigger.HARD_PREPARATION
            and replacement.boundary is not GemsFleetReplacementBoundary.PRE_ENTRY
        ):
            _invalid("hard preparation replacement must occur before map entry")

    def _is_gems_event_fallback(
        self,
        report: CampaignRunReport,
        progress: CampaignProgress | None,
    ) -> bool:
        if report.stop_reason is not CampaignStopReason.GEMS_EVENT_FALLBACK:
            return False
        policy = self._job.gems_farming
        if self._job.kind is not CampaignJobKind.GEMS_FARMING or policy is None:
            _invalid("gems event fallback requires GemsFarmingPolicy")
        fallback = self._job.session_for(policy.fallback_session.definition.ref, CampaignRunVariant.NORMAL)
        if fallback is None:
            _invalid("gems event fallback session does not belong to the job")
        if report.stage_ref != fallback.definition.ref or report.session_state != fallback.initial_state():
            _invalid("gems event fallback must select the configured normal fallback session")
        if progress is None:
            if not self._job.stage_refs:
                _invalid("gems event fallback requires an event-stage map boundary")
            current = self._job.session_for(self._job.stage_refs[0], CampaignRunVariant.NORMAL)
            if current is None or current.definition.ref.pack_id == "campaign_main":
                _invalid("gems event fallback requires an event-stage map boundary")
        else:
            current = self._job.session_for(progress.stage_ref, progress.variant)
            if current is None or current.definition.ref.pack_id == "campaign_main":
                _invalid("gems event fallback requires an event-stage map boundary")
            if progress.session_state != current.initial_state():
                _invalid("gems event fallback cannot abandon an active map")
        return True

    def _validate_run_count(self, report: CampaignRunReport, runs_completed: int) -> None:
        limit = self._job.limits.run_count
        if limit == 0:
            if report.stop_reason is CampaignStopReason.RUN_COUNT_LIMIT:
                _invalid("run-count stop requires a configured run_count limit")
            return
        if runs_completed > limit:
            _invalid("runs_completed must not exceed the configured run_count limit")
        exhausted = runs_completed == limit
        if report.stop_reason is CampaignStopReason.RUN_COUNT_LIMIT and not exhausted:
            _invalid("run-count stop requires the run budget to be exhausted")
        if exhausted and report.stop_reason is not CampaignStopReason.RUN_COUNT_LIMIT:
            _invalid("an exhausted run budget must report the run-count stop")

    def _run_budget_exhausted(self, runs_completed: int) -> bool:
        limit = self._job.limits.run_count
        return limit > 0 and runs_completed == limit

    def _progress_after_report(
        self,
        context: TaskContext,
        report: CampaignRunReport,
        previous: CampaignProgress | None,
    ) -> CampaignProgress:
        session = self._job.session_for(report.stage_ref, report.session_state.variant)
        if session is None:
            _invalid("campaign report stage and variant do not belong to the campaign job")
        if report.stop_reason is CampaignStopReason.CHECKPOINT_RESET:
            if previous is None:
                _invalid("checkpoint reset requires existing campaign progress")
            return replace(previous, session_state=session.initial_state())
        if report.next_stage_ref is not None:
            next_session = self._job.session_for(report.next_stage_ref, CampaignRunVariant.NORMAL)
            if next_session is None:
                _invalid("campaign transition target does not belong to the campaign job")
            return CampaignProgress(
                stage_ref=report.next_stage_ref,
                variant=CampaignRunVariant.NORMAL,
                session_state=next_session.initial_state(),
                runs_completed=report.runs_completed + (0 if previous is None else previous.runs_completed),
                settings_revision=context.metadata.settings_revision,
                content_revision=context.metadata.content_revision,
                pending_gems_replacement=self._pending_gems_replacement(report),
            )
        state = report.session_state
        if state.status is CampaignSessionStatus.COMPLETED:
            state = session.initial_state()
        elif state.status is not CampaignSessionStatus.ACTIVE:
            _invalid("only active or completed campaign states can be checkpointed")
        return CampaignProgress(
            stage_ref=report.stage_ref,
            variant=report.session_state.variant,
            session_state=state,
            runs_completed=report.runs_completed + (0 if previous is None else previous.runs_completed),
            settings_revision=context.metadata.settings_revision,
            content_revision=context.metadata.content_revision,
            pending_gems_replacement=self._pending_gems_replacement(report),
        )

    @staticmethod
    def _pending_gems_replacement(
        report: CampaignRunReport,
    ) -> GemsFleetReplacementRequest | None:
        if report.stop_reason in (
            CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED,
            CampaignStopReason.GEMS_HARD_PREPARATION_FAILED,
        ):
            return report.gems_replacement
        return None

    def _checkpoint_result(
        self,
        context: TaskContext,
        report: CampaignRunReport,
        progress: CampaignProgress,
        reason: CampaignStopReason,
    ) -> TaskResult:
        if reason is CampaignStopReason.GEMS_EVENT_FALLBACK:
            message = "gems farming switched to its configured fallback stage"
        elif reason is CampaignStopReason.STAGE_INCREASE:
            message = "campaign advanced to the next stage"
        elif reason is CampaignStopReason.PROGRAM_CONTINUE:
            message = "campaign program action completed at a safe point"
        elif reason is CampaignStopReason.GEMS_FLEET_REPLACED:
            message = "gems farming fleet replacement completed at a map boundary"
        elif reason is CampaignStopReason.CHECKPOINT_RESET:
            message = "campaign checkpoint was reset to a fresh map boundary"
        else:
            message = _IN_PROGRESS_REASON
        return TaskResult(
            outcome=Deferred(message),
            effects=(RescheduleSelf(report.observed_at),),
            state_effects=(self._upsert_progress(context, progress),),
        )

    def _gems_replacement_checkpoint_result(
        self,
        context: TaskContext,
        report: CampaignRunReport,
        progress: CampaignProgress,
    ) -> TaskResult:
        retry = self._gems_replacement_result(report)
        return TaskResult(
            outcome=retry.outcome,
            effects=retry.effects,
            state_effects=(self._upsert_progress(context, progress),),
            notifications=retry.notifications,
        )

    def _terminal_result(self, context: TaskContext, result: TaskResult) -> TaskResult:
        return TaskResult(
            outcome=result.outcome,
            effects=result.effects,
            state_effects=(self._delete_progress(context),),
            notifications=result.notifications,
        )

    def _result(self, report: CampaignRunReport) -> TaskResult:
        handlers: Mapping[CampaignStopReason, Callable[[CampaignRunReport], TaskResult]] = {
            CampaignStopReason.COMPLETED: self._completion_result,
            CampaignStopReason.RUN_COUNT_LIMIT: self._disable_self_result,
            CampaignStopReason.REACH_LEVEL_LIMIT: self._disable_self_result,
            CampaignStopReason.OIL_LIMIT: self._oil_result,
            CampaignStopReason.AUTO_SEARCH_OIL_LIMIT: self._oil_result,
            CampaignStopReason.NEW_SHIP: self._disable_self_result,
            CampaignStopReason.EVENT_POINT_LIMIT: self._event_result,
            CampaignStopReason.EVENT_TIME_LIMIT: self._event_result,
            CampaignStopReason.EVENT_UNAVAILABLE: self._event_result,
            CampaignStopReason.NO_ELIGIBLE_STAGE: self._content_unavailable_result,
            CampaignStopReason.CONTENT_UNAVAILABLE: self._content_unavailable_result,
            CampaignStopReason.DATA_KEYS_EXHAUSTED: self._data_keys_result,
            CampaignStopReason.COIN_LIMIT: self._coin_result,
            CampaignStopReason.EMOTION_BUG: self._restart_result,
            CampaignStopReason.ONE_TIME_STAGE: self._completion_result,
            CampaignStopReason.LOOP_STAGE_SWITCH: self._completion_result,
            CampaignStopReason.MAP_ACHIEVEMENT: self._disable_self_result,
            CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED: self._gems_replacement_result,
            CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED: self._gems_replacement_result,
            CampaignStopReason.GEMS_HARD_PREPARATION_FAILED: self._gems_replacement_result,
            CampaignStopReason.FAILED: self._failure_result,
            CampaignStopReason.BLOCKED: self._blocked_result,
        }
        handler = handlers.get(report.stop_reason)
        if handler is None:
            _invalid("unsupported campaign stop reason")
        return handler(report)

    def _completion_result(self, report: CampaignRunReport) -> TaskResult:
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._job.schedule.next_after(report.observed_at)),),
        )

    def _disable_self_result(self, report: CampaignRunReport | None) -> TaskResult:
        reason = CampaignStopReason.RUN_COUNT_LIMIT if report is None else report.stop_reason
        notification_kind = {
            CampaignStopReason.RUN_COUNT_LIMIT: OperatorNotificationKind.CAMPAIGN_RUN_COUNT_LIMIT,
            CampaignStopReason.REACH_LEVEL_LIMIT: OperatorNotificationKind.CAMPAIGN_REACH_LEVEL_LIMIT,
            CampaignStopReason.NEW_SHIP: OperatorNotificationKind.CAMPAIGN_NEW_SHIP,
        }.get(reason)
        notifications: tuple[OperatorNotificationRequest, ...] = ()
        if notification_kind is not None:
            stage_ref = report.stage_ref if report is not None else self._notification_stage_ref()
            if stage_ref is not None:
                resource = f"{stage_ref.pack_id}/{stage_ref.stage_id}"
                notifications = (OperatorNotificationRequest(notification_kind, resource=resource),)
        return TaskResult(
            outcome=Succeeded(),
            effects=(DisableTask(self._job.task_id),),
            notifications=notifications,
        )

    def _notification_stage_ref(self) -> StageRef | None:
        if self._job.progress is not None:
            return self._job.progress.stage_ref
        if self._job.stage_refs:
            return self._job.stage_refs[0]
        return None

    def _oil_result(self, report: CampaignRunReport) -> TaskResult:
        return TaskResult(
            outcome=Retryable("campaign oil reserve reached its limit"),
            effects=(RescheduleSelf(report.observed_at + self._job.resource_retry_delay),),
        )

    @staticmethod
    def _event_result(report: CampaignRunReport) -> TaskResult:
        if report.stop_reason is CampaignStopReason.EVENT_POINT_LIMIT:
            return _disabled_event_result("event point limit was reached", _EVENT_POINT_LIMIT_TASK_IDS)
        if report.stop_reason is CampaignStopReason.EVENT_TIME_LIMIT:
            return _disabled_event_result("event time limit was reached", _EVENT_TIME_LIMIT_TASK_IDS)
        return _disabled_event_result("event entrance is unavailable", _EVENT_TIME_LIMIT_TASK_IDS, blocked=True)

    def _content_unavailable_result(self, _report: CampaignRunReport | None) -> TaskResult:
        return TaskResult(
            outcome=Blocked("campaign content is unavailable"),
            effects=(DisableTask(self._job.task_id),),
        )

    def _data_keys_result(self, report: CampaignRunReport) -> TaskResult:
        return TaskResult(
            outcome=Deferred("war archives data keys are exhausted"),
            effects=(RescheduleSelf(self._job.schedule.next_after(report.observed_at)),),
        )

    def _coin_result(self, report: CampaignRunReport) -> TaskResult:
        policy = cast("TaskBalancerPolicy", self._job.task_balancer)
        return TaskResult(
            outcome=Deferred("campaign coin limit was reached"),
            effects=(
                RescheduleSelf(report.observed_at + policy.retry_delay),
                WakeTask(policy.target_task_id, report.observed_at, WakePolicy.FORCE_ENABLE),
            ),
        )

    @staticmethod
    def _restart_result(report: CampaignRunReport) -> TaskResult:
        return TaskResult(
            outcome=Deferred(_RESTART_REASON),
            effects=(RescheduleSelf(report.observed_at), RequestAppRestart(_RESTART_REASON)),
        )

    def _gems_replacement_result(self, report: CampaignRunReport) -> TaskResult:
        policy = cast("GemsFarmingPolicy", self._job.gems_farming)
        return TaskResult(
            outcome=Retryable("gems farming fleet replacement failed"),
            effects=(RescheduleSelf(report.observed_at + policy.replacement_retry_delay),),
        )

    def _failure_result(self, report: CampaignRunReport) -> TaskResult:
        return TaskResult(
            outcome=Retryable("campaign workflow did not complete"),
            effects=(RescheduleSelf(report.observed_at + self._delay_sampler.sample(self._job.failure_retry_delay)),),
        )

    def _blocked_result(self, report: CampaignRunReport) -> TaskResult:
        return TaskResult(
            outcome=Blocked("campaign workflow is blocked"),
            effects=(RescheduleSelf(report.observed_at + self._delay_sampler.sample(self._job.failure_retry_delay)),),
        )

    @staticmethod
    def _upsert_progress(context: TaskContext, progress: CampaignProgress) -> UpsertTaskState:
        state = progress.session_state
        pending = state.pending
        if pending is not None:
            _invalid("campaign checkpoint cannot persist a pending battle attempt")
        return UpsertTaskState(
            namespace=context.task_id.value,
            key=CAMPAIGN_PROGRESS_KEY,
            schema_version=CAMPAIGN_PROGRESS_SCHEMA_VERSION,
            payload={
                "stage_ref": {
                    "pack_id": progress.stage_ref.pack_id,
                    "stage_id": progress.stage_ref.stage_id,
                },
                "variant": progress.variant.value,
                "session_state": {
                    "variant": state.variant.value,
                    "status": state.status.value,
                    "battle_index": state.battle_index,
                    "remaining": {
                        "enemy": state.remaining.enemy,
                        "siren": state.remaining.siren,
                        "mystery": state.remaining.mystery,
                        "boss": state.remaining.boss,
                    },
                    "next_attempt_id": state.next_attempt_id,
                    "next_intent_index": state.next_intent_index,
                    "pending": None,
                    "reason": state.reason,
                    "program_state_initialized": state.program_state_initialized,
                    "program_flags": sorted(flag.value for flag in state.program_flags),
                    "program_markers": sorted(marker.value for marker in state.program_markers),
                },
                "runs_completed": progress.runs_completed,
                "settings_revision": progress.settings_revision,
                "content_revision": progress.content_revision,
                "pending_gems_replacement": (
                    None
                    if progress.pending_gems_replacement is None
                    else {
                        "trigger": progress.pending_gems_replacement.trigger.value,
                        "boundary": progress.pending_gems_replacement.boundary.value,
                    }
                ),
            },
        )

    @staticmethod
    def _delete_progress(context: TaskContext) -> DeleteTaskState:
        return DeleteTaskState(namespace=context.task_id.value, key=CAMPAIGN_PROGRESS_KEY)


def _confirmed_battle_units(
    session: CampaignSession,
    before: CampaignSessionState,
    after: CampaignSessionState,
) -> int:
    """证明两个安全点之间至多经过一次 decide/reduce。"""
    if before.status is not CampaignSessionStatus.ACTIVE or before.pending is not None:
        _invalid("campaign workflow requires an active pending-free starting state")
    if after == before:
        return 0

    program_units = _confirmed_program_units(session, before, after)
    if program_units is not None:
        return program_units

    standard_units = _confirmed_standard_units(session, before, after)
    if standard_units is not None:
        return standard_units

    delegated_before = BattleProgramReducer.reduce(
        session,
        before,
        BattleProgramExecution(
            program_model.ProgramDelegated(program_model.BattleProgramDelegation.STAGE_POLICY),
            after.program_flags,
            after.program_markers,
        ),
    )
    delegated_units = _confirmed_standard_units(session, delegated_before, after)
    if delegated_units is not None:
        return delegated_units

    _invalid("campaign workflow crossed more than one battle safe unit or returned an invalid state")


def _confirmed_standard_units(
    session: CampaignSession,
    before: CampaignSessionState,
    after: CampaignSessionState,
) -> int | None:

    no_target_decision = replace(
        before,
        status=CampaignSessionStatus.BLOCKED,
        pending=None,
        reason=f"battle {before.battle_index} has no eligible target",
    )
    if after == no_target_decision:
        return 0

    plan = session.battle_plan(before.battle_index)
    for intent_index in range(before.next_intent_index, len(plan.intents)):
        attempt = BattleAttempt(
            battle_index=before.battle_index,
            attempt_id=before.next_attempt_id,
            intent_index=intent_index,
            intent=plan.intents[intent_index],
        )
        pending = replace(
            before,
            next_attempt_id=before.next_attempt_id + 1,
            pending=attempt,
        )
        candidates = [session.reduce(pending, NoBattleTarget(attempt))]
        if after.status is CampaignSessionStatus.FAILED and after.reason is not None:
            candidates.append(session.reduce(pending, BattleFailed(attempt, after.reason)))
        for target in BattleTarget:
            try:
                candidates.append(session.reduce(pending, BattleSucceeded(attempt, target)))
            except CampaignSessionError:
                continue
        if after in candidates:
            return 1
    return None


def _confirmed_program_units(
    session: CampaignSession,
    before: CampaignSessionState,
    after: CampaignSessionState,
) -> int | None:
    results: list[program_model.CompleteBattleProgramResult] = [
        program_model.ProgramContinue(),
        program_model.ProgramNoTarget(),
        program_model.ProgramCampaignEnded(),
    ]
    results.extend(program_model.ProgramDelegated(target) for target in program_model.BattleProgramDelegation)
    if after.status is CampaignSessionStatus.FAILED and after.reason is not None:
        results.append(program_model.ProgramFailed(after.reason))
    results.extend(
        program_model.ProgramBattleSettled(target, advances_wave)
        for target in program_model.ProgramBattleTarget
        for advances_wave in (False, True)
    )
    for result in results:
        candidate = BattleProgramReducer.reduce(
            session,
            before,
            BattleProgramExecution(
                result,
                after.program_flags,
                after.program_markers,
            ),
        )
        if candidate == after:
            return int(isinstance(result, program_model.ProgramBattleSettled))
    return None


def _disabled_event_result(
    reason: str,
    task_ids: tuple[TaskId, ...],
    *,
    blocked: bool = False,
) -> TaskResult:
    outcome = Blocked(reason) if blocked else Deferred(reason)
    return TaskResult(outcome=outcome, effects=tuple(DisableTask(task_id) for task_id in task_ids))
