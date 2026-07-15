from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol, override

from module.application import (
    Deferred,
    DelayTask,
    DisableTask,
    RescheduleSelf,
    RescheduleTask,
    Retryable,
    ScheduleEffect,
    StateEffect,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
    WakePolicy,
    WakeTask,
)
from module.gameplay.opsi_progress import (
    WorldBossCursor,
    WorldCheckpointMode,
    WorldCheckpointPolicy,
    WorldMissionCursor,
    WorldOperation,
    WorldProgress,
    WorldProgressCursor,
    WorldProgressCycle,
    WorldZoneCursor,
    delete_world_progress,
    expected_world_cursor_type,
    upsert_world_progress,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.application import CancellationSource


_ACTION_POINTS_EXHAUSTED = "operation siren action points are exhausted"
_COOLDOWN_ACTIVE = "operation siren task is cooling down"
_EXPLORATION_ACTIVE = "operation siren exploration is still active"
_NO_WORK = "operation siren task has no work"
_RESOURCE_LIMIT = "operation siren resources are insufficient"
_SAFE_UNIT_COMPLETED = "operation siren completed one safe unit"
_STALE_PROGRESS = "operation siren progress belongs to a stale revision or reset cycle"
_WORKFLOW_FAILED = "operation siren workflow did not complete"

_AP_NORMAL_DELAY: Final = timedelta(hours=6)
_AP_LAST_DAY_DELAY: Final = timedelta(minutes=150)
_CROSS_MONTH_LEAD: Final = timedelta(minutes=10)

REWARD_TASK_ID: Final = TaskId("reward")
OPSI_DAILY_TASK_ID: Final = TaskId("opsi_daily")
OPSI_SHOP_TASK_ID: Final = TaskId("opsi_shop")
OPSI_HAZARD1_LEVELING_TASK_ID: Final = TaskId("opsi_hazard1_leveling")
OPSI_MEOWFFICER_FARMING_TASK_ID: Final = TaskId("opsi_meowfficer_farming")

_AP_BATCH_TASK_IDS: Final = (
    TaskId("opsi_explore"),
    OPSI_DAILY_TASK_ID,
    TaskId("opsi_obscure"),
    TaskId("opsi_abyssal"),
    TaskId("opsi_stronghold"),
    TaskId("opsi_archive"),
    OPSI_MEOWFFICER_FARMING_TASK_ID,
)

_EXPLORE_FOLLOW_UP_TASK_IDS: Final = (
    OPSI_DAILY_TASK_ID,
    OPSI_SHOP_TASK_ID,
    OPSI_HAZARD1_LEVELING_TASK_ID,
)


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.tzinfo is None or value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def _validate_bool(*, value: bool, field_name: str) -> None:
    if type(value) is not bool:
        message = f"{field_name} must be a bool"
        raise TypeError(message)


def _validate_int(
    value: int,
    *,
    field_name: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if minimum is not None and value < minimum:
        message = f"{field_name} must be at least {minimum}"
        raise ValueError(message)
    if maximum is not None and value > maximum:
        message = f"{field_name} must be at most {maximum}"
        raise ValueError(message)


def _validate_normalized_string(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


def _validate_settings_member(value: object, expected_type: type[object], *, field_name: str) -> None:
    if not isinstance(value, expected_type):
        message = f"{field_name} must be a {expected_type.__name__}"
        raise TypeError(message)


class RefreshPolicy(StrEnum):
    SERVER_UPDATE = "server_update"
    MONTH_RESET = "month_reset"
    ARCHIVE_REFRESH = "archive_refresh"
    WORKFLOW_TARGET = "workflow_target"
    CROSS_MONTH_WINDOW = "cross_month_window"


class ActionPointPolicy(StrEnum):
    BATCH = "batch"
    MEOWFFICER_HANDOFF = "meowfficer_handoff"
    SERVER_UPDATE = "server_update"
    CROSS_MONTH_WINDOW = "cross_month_window"


class WorldTaskStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EMPTY = "empty"
    ACTION_POINT_LIMIT = "action_point_limit"
    RESOURCE_LIMIT = "resource_limit"
    COOLDOWN = "cooldown"
    EXPLORE_IN_PROGRESS = "explore_in_progress"
    FAILED = "failed"
    DISABLED = "disabled"


class AshBeaconAttackMode(StrEnum):
    CURRENT = "current"
    CURRENT_DOSSIER = "current_dossier"


class OpsiShopPreset(StrEnum):
    MAX_BENEFIT = "max_benefit"
    MAX_BENEFIT_META = "max_benefit_meta"
    NO_META = "no_meta"
    ALL = "all"
    CUSTOM = "custom"


class MonthBossMode(StrEnum):
    NORMAL = "normal"
    NORMAL_HARD = "normal_hard"


@dataclass(frozen=True, slots=True)
class WorldGeneralSettings:
    use_logger: bool
    buy_action_point_limit: int
    oil_preserve: int
    repair_threshold: float
    random_map_events: bool
    akashi_shop_filter: str

    def __post_init__(self) -> None:
        _validate_bool(value=self.use_logger, field_name="use_logger")
        _validate_int(
            self.buy_action_point_limit,
            field_name="buy_action_point_limit",
            minimum=0,
            maximum=5,
        )
        _validate_int(self.oil_preserve, field_name="oil_preserve", minimum=0)
        if type(self.repair_threshold) is not float:
            message = "repair_threshold must be a float"
            raise TypeError(message)
        if not -1.0 <= self.repair_threshold <= 1.0:
            message = "repair_threshold must be between -1.0 and 1.0"
            raise ValueError(message)
        _validate_bool(value=self.random_map_events, field_name="random_map_events")
        _validate_normalized_string(self.akashi_shop_filter, field_name="akashi_shop_filter")


@dataclass(frozen=True, slots=True)
class FleetSettings:
    fleet_index: int
    use_submarine: bool

    def __post_init__(self) -> None:
        _validate_int(self.fleet_index, field_name="fleet_index", minimum=1, maximum=4)
        _validate_bool(value=self.use_submarine, field_name="use_submarine")


@dataclass(frozen=True, slots=True)
class AshAssistSettings:
    minimum_tier: int

    def __post_init__(self) -> None:
        _validate_int(self.minimum_tier, field_name="minimum_tier", minimum=1)


@dataclass(frozen=True, slots=True)
class AshBeaconSettings:
    attack_mode: AshBeaconAttackMode
    one_hit_mode: bool
    dossier_auto_attack: bool
    request_assist: bool
    ensure_fully_collected: bool

    def __post_init__(self) -> None:
        if not isinstance(self.attack_mode, AshBeaconAttackMode):
            message = "attack_mode must be an AshBeaconAttackMode"
            raise TypeError(message)
        _validate_bool(value=self.one_hit_mode, field_name="one_hit_mode")
        _validate_bool(value=self.dossier_auto_attack, field_name="dossier_auto_attack")
        _validate_bool(value=self.request_assist, field_name="request_assist")
        _validate_bool(value=self.ensure_fully_collected, field_name="ensure_fully_collected")


@dataclass(frozen=True, slots=True)
class ExploreSettings:
    general: WorldGeneralSettings
    fleet: FleetSettings
    special_radar: bool
    force_run: bool

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_settings_member(self.fleet, FleetSettings, field_name="fleet")
        _validate_bool(value=self.special_radar, field_name="special_radar")
        _validate_bool(value=self.force_run, field_name="force_run")


@dataclass(frozen=True, slots=True)
class ShopSettings:
    general: WorldGeneralSettings
    preset: OpsiShopPreset
    custom_filter: str

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        if not isinstance(self.preset, OpsiShopPreset):
            message = "preset must be an OpsiShopPreset"
            raise TypeError(message)
        _validate_normalized_string(self.custom_filter, field_name="custom_filter")


@dataclass(frozen=True, slots=True)
class VoucherSettings:
    general: WorldGeneralSettings
    filter: str

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_normalized_string(self.filter, field_name="filter")


@dataclass(frozen=True, slots=True)
class OpsiDailySettings:
    general: WorldGeneralSettings
    fleet: FleetSettings
    do_missions: bool
    use_tuning_samples: bool

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_settings_member(self.fleet, FleetSettings, field_name="fleet")
        _validate_bool(value=self.do_missions, field_name="do_missions")
        _validate_bool(value=self.use_tuning_samples, field_name="use_tuning_samples")


@dataclass(frozen=True, slots=True)
class ObscureSettings:
    general: WorldGeneralSettings
    fleet: FleetSettings
    force_run: bool

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_settings_member(self.fleet, FleetSettings, field_name="fleet")
        _validate_bool(value=self.force_run, field_name="force_run")


@dataclass(frozen=True, slots=True)
class AbyssalSettings:
    general: WorldGeneralSettings
    fleet_filter: str
    force_run: bool

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_normalized_string(self.fleet_filter, field_name="fleet_filter")
        _validate_bool(value=self.force_run, field_name="force_run")


@dataclass(frozen=True, slots=True)
class ArchiveSettings:
    general: WorldGeneralSettings
    fleet: FleetSettings
    voucher_filter: str

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_settings_member(self.fleet, FleetSettings, field_name="fleet")
        _validate_normalized_string(self.voucher_filter, field_name="voucher_filter")


@dataclass(frozen=True, slots=True)
class StrongholdSettings:
    general: WorldGeneralSettings
    fleet_filter: str
    force_run: bool

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_normalized_string(self.fleet_filter, field_name="fleet_filter")
        _validate_bool(value=self.force_run, field_name="force_run")


@dataclass(frozen=True, slots=True)
class MonthBossSettings:
    general: WorldGeneralSettings
    fleet_filter: str
    mode: MonthBossMode
    check_adaptability: bool
    force_run: bool

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_normalized_string(self.fleet_filter, field_name="fleet_filter")
        if not isinstance(self.mode, MonthBossMode):
            message = "mode must be a MonthBossMode"
            raise TypeError(message)
        _validate_bool(value=self.check_adaptability, field_name="check_adaptability")
        _validate_bool(value=self.force_run, field_name="force_run")


@dataclass(frozen=True, slots=True)
class MeowfficerFarmingSettings:
    general: WorldGeneralSettings
    fleet: FleetSettings
    action_point_preserve: int
    hazard_level: int
    target_zone: int
    ensure_ash_fully_collected: bool

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_settings_member(self.fleet, FleetSettings, field_name="fleet")
        _validate_int(
            self.action_point_preserve,
            field_name="action_point_preserve",
            minimum=0,
            maximum=2000,
        )
        _validate_int(self.hazard_level, field_name="hazard_level")
        if self.hazard_level not in {3, 4, 5, 6, 10}:
            message = "hazard_level must be one of [3, 4, 5, 6, 10]"
            raise ValueError(message)
        _validate_int(self.target_zone, field_name="target_zone", minimum=0)
        _validate_bool(
            value=self.ensure_ash_fully_collected,
            field_name="ensure_ash_fully_collected",
        )


@dataclass(frozen=True, slots=True)
class Hazard1LevelingSettings:
    general: WorldGeneralSettings
    fleet: FleetSettings
    target_zone: int
    ensure_ash_fully_collected: bool

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_settings_member(self.fleet, FleetSettings, field_name="fleet")
        _validate_int(self.target_zone, field_name="target_zone")
        if self.target_zone not in {0, 22, 44}:
            message = "target_zone must be one of [0, 22, 44]"
            raise ValueError(message)
        _validate_bool(
            value=self.ensure_ash_fully_collected,
            field_name="ensure_ash_fully_collected",
        )


@dataclass(frozen=True, slots=True)
class CrossMonthSettings:
    general: WorldGeneralSettings
    daily_fleet: FleetSettings
    obscure_fleet: FleetSettings
    abyssal_fleet_filter: str
    meowfficer_fleet: FleetSettings

    def __post_init__(self) -> None:
        _validate_settings_member(self.general, WorldGeneralSettings, field_name="general")
        _validate_settings_member(self.daily_fleet, FleetSettings, field_name="daily_fleet")
        _validate_settings_member(self.obscure_fleet, FleetSettings, field_name="obscure_fleet")
        _validate_normalized_string(self.abyssal_fleet_filter, field_name="abyssal_fleet_filter")
        _validate_settings_member(self.meowfficer_fleet, FleetSettings, field_name="meowfficer_fleet")


type WorldTaskSettings = (
    AshAssistSettings
    | AshBeaconSettings
    | ExploreSettings
    | ShopSettings
    | VoucherSettings
    | OpsiDailySettings
    | ObscureSettings
    | AbyssalSettings
    | ArchiveSettings
    | StrongholdSettings
    | MonthBossSettings
    | MeowfficerFarmingSettings
    | Hazard1LevelingSettings
    | CrossMonthSettings
)

_SETTINGS_TYPE_BY_OPERATION: Final[Mapping[WorldOperation, type[object]]] = MappingProxyType(
    {
        WorldOperation.ASH_ASSIST: AshAssistSettings,
        WorldOperation.ASH_BEACON: AshBeaconSettings,
        WorldOperation.EXPLORE: ExploreSettings,
        WorldOperation.SHOP: ShopSettings,
        WorldOperation.VOUCHER: VoucherSettings,
        WorldOperation.DAILY: OpsiDailySettings,
        WorldOperation.OBSCURE: ObscureSettings,
        WorldOperation.ABYSSAL: AbyssalSettings,
        WorldOperation.ARCHIVE: ArchiveSettings,
        WorldOperation.STRONGHOLD: StrongholdSettings,
        WorldOperation.MONTH_BOSS: MonthBossSettings,
        WorldOperation.MEOWFFICER_FARMING: MeowfficerFarmingSettings,
        WorldOperation.HAZARD1_LEVELING: Hazard1LevelingSettings,
        WorldOperation.CROSS_MONTH: CrossMonthSettings,
    }
)


@dataclass(frozen=True, slots=True)
class WorldTaskSpec:
    task_id: TaskId
    operation: WorldOperation
    completion_refresh: RefreshPolicy
    empty_refresh: RefreshPolicy
    action_point_policy: ActionPointPolicy
    checkpoint_policy: WorldCheckpointPolicy
    settings: WorldTaskSettings

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, TaskId):
            message = "task_id must be a TaskId"
            raise TypeError(message)
        if not isinstance(self.operation, WorldOperation):
            message = "operation must be a WorldOperation"
            raise TypeError(message)
        if self.task_id.value != self.operation.value:
            message = "task_id must match operation"
            raise ValueError(message)
        if not isinstance(self.completion_refresh, RefreshPolicy):
            message = "completion_refresh must be a RefreshPolicy"
            raise TypeError(message)
        if not isinstance(self.empty_refresh, RefreshPolicy):
            message = "empty_refresh must be a RefreshPolicy"
            raise TypeError(message)
        if not isinstance(self.action_point_policy, ActionPointPolicy):
            message = "action_point_policy must be an ActionPointPolicy"
            raise TypeError(message)
        if not isinstance(self.checkpoint_policy, WorldCheckpointPolicy):
            message = "checkpoint_policy must be a WorldCheckpointPolicy"
            raise TypeError(message)
        expected_type = _SETTINGS_TYPE_BY_OPERATION[self.operation]
        if not isinstance(self.settings, expected_type):
            message = f"{self.operation.value} settings must be a {expected_type.__name__}"
            raise TypeError(message)

    @property
    def checkpoint_mode(self) -> WorldCheckpointMode:
        return self.checkpoint_policy.mode

    @property
    def progress_cycle(self) -> WorldProgressCycle | None:
        return self.checkpoint_policy.cycle


@dataclass(frozen=True, slots=True)
class WorldSchedule:
    next_server_update_at: datetime
    next_month_reset_at: datetime
    next_archive_refresh_at: datetime

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.next_server_update_at, field_name="next_server_update_at")
        _validate_aware_datetime(self.next_month_reset_at, field_name="next_month_reset_at")
        _validate_aware_datetime(self.next_archive_refresh_at, field_name="next_archive_refresh_at")


@dataclass(frozen=True, slots=True)
class WorldScheduleDelay:
    """把一组任务的既有 due time 推迟到至少 due_at。"""

    due_at: datetime
    task_ids: tuple[TaskId, ...]

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.due_at, field_name="due_at")
        if not isinstance(self.task_ids, tuple):
            message = "task_ids must be a tuple"
            raise TypeError(message)
        if not self.task_ids:
            message = "task_ids must not be empty"
            raise ValueError(message)
        if any(not isinstance(task_id, TaskId) for task_id in self.task_ids):
            message = "task_ids must contain TaskId values"
            raise TypeError(message)
        if len(set(self.task_ids)) != len(self.task_ids):
            message = "task_ids must be unique"
            raise ValueError(message)


def _validate_schedule_after_observation(observed_at: datetime, schedule: WorldSchedule) -> None:
    for field_name, value in (
        ("next_server_update_at", schedule.next_server_update_at),
        ("next_month_reset_at", schedule.next_month_reset_at),
        ("next_archive_refresh_at", schedule.next_archive_refresh_at),
    ):
        if value <= observed_at:
            message = f"{field_name} must be after observed_at"
            raise ValueError(message)


def _validate_retry_at(observed_at: datetime, retry_at: datetime | None) -> None:
    if retry_at is None:
        return
    _validate_aware_datetime(retry_at, field_name="retry_at")
    if retry_at < observed_at:
        message = "retry_at must not be before observed_at"
        raise ValueError(message)


def _validate_affected_task_ids(
    affected_task_ids: tuple[TaskId, ...],
    *,
    status: WorldTaskStatus,
) -> None:
    if not isinstance(affected_task_ids, tuple):
        message = "affected_task_ids must be a tuple"
        raise TypeError(message)
    if any(not isinstance(task_id, TaskId) for task_id in affected_task_ids):
        message = "affected_task_ids must contain TaskId values"
        raise TypeError(message)
    if len(set(affected_task_ids)) != len(affected_task_ids):
        message = "affected_task_ids must be unique"
        raise ValueError(message)
    if affected_task_ids and status is not WorldTaskStatus.COOLDOWN:
        message = "affected_task_ids are only valid for cooldown reports"
        raise ValueError(message)


def _validate_schedule_delays(
    observed_at: datetime,
    schedule_delays: tuple[WorldScheduleDelay, ...],
) -> None:
    if not isinstance(schedule_delays, tuple):
        message = "schedule_delays must be a tuple"
        raise TypeError(message)
    if any(not isinstance(delay, WorldScheduleDelay) for delay in schedule_delays):
        message = "schedule_delays must contain WorldScheduleDelay values"
        raise TypeError(message)
    if any(delay.due_at <= observed_at for delay in schedule_delays):
        message = "schedule delay due_at must be after observed_at"
        raise ValueError(message)


def _validate_wake_task_ids(wake_task_ids: tuple[TaskId, ...]) -> None:
    if not isinstance(wake_task_ids, tuple):
        message = "wake_task_ids must be a tuple"
        raise TypeError(message)
    if any(not isinstance(task_id, TaskId) for task_id in wake_task_ids):
        message = "wake_task_ids must contain TaskId values"
        raise TypeError(message)
    if len(set(wake_task_ids)) != len(wake_task_ids):
        message = "wake_task_ids must be unique"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class WorldTaskReport:
    observed_at: datetime
    status: WorldTaskStatus
    schedule: WorldSchedule
    completed_units: int = 0
    retry_at: datetime | None = None
    affected_task_ids: tuple[TaskId, ...] = ()
    schedule_delays: tuple[WorldScheduleDelay, ...] = ()
    wake_task_ids: tuple[TaskId, ...] = ()
    has_surplus_yellow_coins: bool = False
    exploration_in_progress: bool = False
    cursor: WorldProgressCursor | None = None

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.observed_at, field_name="observed_at")
        if not isinstance(self.status, WorldTaskStatus):
            message = "status must be a WorldTaskStatus"
            raise TypeError(message)
        if not isinstance(self.schedule, WorldSchedule):
            message = "schedule must be a WorldSchedule"
            raise TypeError(message)
        _validate_schedule_after_observation(self.observed_at, self.schedule)
        if type(self.completed_units) is not int:
            message = "completed_units must be an integer"
            raise TypeError(message)
        if self.completed_units < 0:
            message = "completed_units must be non-negative"
            raise ValueError(message)
        if self.completed_units > 1:
            message = "a world task run may complete at most one safe unit"
            raise ValueError(message)
        if self.status is WorldTaskStatus.IN_PROGRESS and self.completed_units != 1:
            message = "in-progress report must complete exactly one safe unit"
            raise ValueError(message)
        _validate_retry_at(self.observed_at, self.retry_at)
        if self.status is WorldTaskStatus.COOLDOWN and self.retry_at is None:
            message = "cooldown report requires retry_at"
            raise ValueError(message)
        _validate_affected_task_ids(self.affected_task_ids, status=self.status)
        _validate_schedule_delays(self.observed_at, self.schedule_delays)
        _validate_wake_task_ids(self.wake_task_ids)
        _validate_bool(value=self.has_surplus_yellow_coins, field_name="has_surplus_yellow_coins")
        _validate_bool(value=self.exploration_in_progress, field_name="exploration_in_progress")
        if self.cursor is not None and not isinstance(
            self.cursor,
            WorldZoneCursor | WorldMissionCursor | WorldBossCursor,
        ):
            message = "cursor must be a WorldProgressCursor or None"
            raise TypeError(message)
        if self.cursor is not None and self.status is not WorldTaskStatus.IN_PROGRESS:
            message = "cursor is only valid for in-progress reports"
            raise ValueError(message)

    @property
    def is_last_reset_day(self) -> bool:
        return self.schedule.next_month_reset_at - self.observed_at < timedelta(days=1)


class OperationSirenWorkflow(Protocol):
    def execute(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSource,
    ) -> WorldTaskReport: ...


@dataclass(frozen=True, slots=True)
class WorldTaskDefinition:
    task_id: TaskId
    operation: WorldOperation
    completion_refresh: RefreshPolicy
    empty_refresh: RefreshPolicy
    action_point_policy: ActionPointPolicy
    checkpoint_policy: WorldCheckpointPolicy

    @property
    def checkpoint_mode(self) -> WorldCheckpointMode:
        return self.checkpoint_policy.mode

    @property
    def progress_cycle(self) -> WorldProgressCycle | None:
        return self.checkpoint_policy.cycle


def _definition(
    operation: WorldOperation,
    completion_refresh: RefreshPolicy,
    empty_refresh: RefreshPolicy,
    action_point_policy: ActionPointPolicy,
    checkpoint_policy: WorldCheckpointPolicy,
) -> WorldTaskDefinition:
    return WorldTaskDefinition(
        task_id=TaskId(operation.value),
        operation=operation,
        completion_refresh=completion_refresh,
        empty_refresh=empty_refresh,
        action_point_policy=action_point_policy,
        checkpoint_policy=checkpoint_policy,
    )


_BOUNDED_SERVER_UPDATE: Final = WorldCheckpointPolicy(
    WorldCheckpointMode.BOUNDED,
    WorldProgressCycle.SERVER_UPDATE,
)
_BOUNDED_MONTH_RESET: Final = WorldCheckpointPolicy(
    WorldCheckpointMode.BOUNDED,
    WorldProgressCycle.MONTH_RESET,
)
_BOUNDED_ARCHIVE_REFRESH: Final = WorldCheckpointPolicy(
    WorldCheckpointMode.BOUNDED,
    WorldProgressCycle.ARCHIVE_REFRESH,
)
_ONE_SHOT: Final = WorldCheckpointPolicy(WorldCheckpointMode.ONE_SHOT, None)


_WORLD_TASK_DEFINITION_SEQUENCE: Final = (
    _definition(
        WorldOperation.ASH_ASSIST,
        RefreshPolicy.SERVER_UPDATE,
        RefreshPolicy.WORKFLOW_TARGET,
        ActionPointPolicy.SERVER_UPDATE,
        _BOUNDED_SERVER_UPDATE,
    ),
    _definition(
        WorldOperation.ASH_BEACON,
        RefreshPolicy.SERVER_UPDATE,
        RefreshPolicy.SERVER_UPDATE,
        ActionPointPolicy.SERVER_UPDATE,
        _BOUNDED_SERVER_UPDATE,
    ),
    _definition(
        WorldOperation.EXPLORE,
        RefreshPolicy.MONTH_RESET,
        RefreshPolicy.MONTH_RESET,
        ActionPointPolicy.BATCH,
        _BOUNDED_MONTH_RESET,
    ),
    _definition(
        WorldOperation.SHOP,
        RefreshPolicy.WORKFLOW_TARGET,
        RefreshPolicy.WORKFLOW_TARGET,
        ActionPointPolicy.BATCH,
        _ONE_SHOT,
    ),
    _definition(
        WorldOperation.VOUCHER,
        RefreshPolicy.MONTH_RESET,
        RefreshPolicy.MONTH_RESET,
        ActionPointPolicy.BATCH,
        _ONE_SHOT,
    ),
    _definition(
        WorldOperation.DAILY,
        RefreshPolicy.SERVER_UPDATE,
        RefreshPolicy.SERVER_UPDATE,
        ActionPointPolicy.BATCH,
        _BOUNDED_SERVER_UPDATE,
    ),
    _definition(
        WorldOperation.OBSCURE,
        RefreshPolicy.SERVER_UPDATE,
        RefreshPolicy.SERVER_UPDATE,
        ActionPointPolicy.BATCH,
        _BOUNDED_MONTH_RESET,
    ),
    _definition(
        WorldOperation.MONTH_BOSS,
        RefreshPolicy.MONTH_RESET,
        RefreshPolicy.SERVER_UPDATE,
        ActionPointPolicy.BATCH,
        _BOUNDED_MONTH_RESET,
    ),
    _definition(
        WorldOperation.ABYSSAL,
        RefreshPolicy.SERVER_UPDATE,
        RefreshPolicy.SERVER_UPDATE,
        ActionPointPolicy.BATCH,
        _BOUNDED_MONTH_RESET,
    ),
    _definition(
        WorldOperation.ARCHIVE,
        RefreshPolicy.ARCHIVE_REFRESH,
        RefreshPolicy.ARCHIVE_REFRESH,
        ActionPointPolicy.BATCH,
        _BOUNDED_ARCHIVE_REFRESH,
    ),
    _definition(
        WorldOperation.STRONGHOLD,
        RefreshPolicy.SERVER_UPDATE,
        RefreshPolicy.SERVER_UPDATE,
        ActionPointPolicy.BATCH,
        _BOUNDED_MONTH_RESET,
    ),
    _definition(
        WorldOperation.MEOWFFICER_FARMING,
        RefreshPolicy.SERVER_UPDATE,
        RefreshPolicy.SERVER_UPDATE,
        ActionPointPolicy.MEOWFFICER_HANDOFF,
        _BOUNDED_SERVER_UPDATE,
    ),
    _definition(
        WorldOperation.HAZARD1_LEVELING,
        RefreshPolicy.SERVER_UPDATE,
        RefreshPolicy.SERVER_UPDATE,
        ActionPointPolicy.SERVER_UPDATE,
        _BOUNDED_SERVER_UPDATE,
    ),
    _definition(
        WorldOperation.CROSS_MONTH,
        RefreshPolicy.CROSS_MONTH_WINDOW,
        RefreshPolicy.CROSS_MONTH_WINDOW,
        ActionPointPolicy.CROSS_MONTH_WINDOW,
        # 旧流程跨 reset 等待并串行清场；没有幂等 stage evidence 前必须保持 one-shot。
        _ONE_SHOT,
    ),
)

WORLD_TASK_DEFINITIONS: Final[Mapping[TaskId, WorldTaskDefinition]] = MappingProxyType(
    {definition.task_id: definition for definition in _WORLD_TASK_DEFINITION_SEQUENCE}
)


def world_task_spec(task_id: TaskId, settings: WorldTaskSettings) -> WorldTaskSpec:
    if not isinstance(task_id, TaskId):
        message = "task_id must be a TaskId"
        raise TypeError(message)
    try:
        definition = WORLD_TASK_DEFINITIONS[task_id]
    except KeyError as exc:
        message = f"unknown Operation Siren task: {task_id.value}"
        raise KeyError(message) from exc
    return WorldTaskSpec(
        task_id=definition.task_id,
        operation=definition.operation,
        completion_refresh=definition.completion_refresh,
        empty_refresh=definition.empty_refresh,
        action_point_policy=definition.action_point_policy,
        checkpoint_policy=definition.checkpoint_policy,
        settings=settings,
    )


class OperationSirenTask(Task):
    __slots__ = ("_progress", "_spec", "_workflow")

    def __init__(
        self,
        workflow: OperationSirenWorkflow,
        spec: WorldTaskSpec,
        progress: WorldProgress | None = None,
    ) -> None:
        if not isinstance(spec, WorldTaskSpec):
            message = "spec must be a WorldTaskSpec"
            raise TypeError(message)
        if progress is not None and not isinstance(progress, WorldProgress):
            message = "progress must be a WorldProgress or None"
            raise TypeError(message)
        if progress is not None and (progress.task_id != spec.task_id or progress.operation is not spec.operation):
            message = "WorldProgress identity must match WorldTaskSpec"
            raise ValueError(message)
        if progress is not None and spec.checkpoint_mode is WorldCheckpointMode.ONE_SHOT:
            message = f"one-shot operation must not have progress: {spec.operation.value}"
            raise ValueError(message)
        self._workflow = workflow
        self._spec = spec
        self._progress = progress

    @override
    def run(self, context: TaskContext) -> TaskResult:
        if context.task_id != self._spec.task_id:
            message = "TaskContext.task_id must match WorldTaskSpec.task_id"
            raise ValueError(message)
        context.abort.raise_if_requested()
        stale = self._stale_progress_result(context)
        if stale is not None:
            return stale

        report = self._workflow.execute(self._spec, self._progress, context.abort)
        if not isinstance(report, WorldTaskReport):
            message = "OperationSirenWorkflow.execute() must return a WorldTaskReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        self._validate_report_checkpoint(report)
        return self._merge_schedule_intents(self._resolve(report, context), report)

    def _merge_schedule_intents(self, result: TaskResult, report: WorldTaskReport) -> TaskResult:
        effects: list[ScheduleEffect] = list(result.effects)
        delayed_until: dict[TaskId, datetime] = {}
        for delay in report.schedule_delays:
            for task_id in delay.task_ids:
                delayed_until[task_id] = max(delayed_until.get(task_id, delay.due_at), delay.due_at)
        for task_id, due_at in delayed_until.items():
            self._merge_delay(effects, task_id=task_id, due_at=due_at)
        for task_id in report.wake_task_ids:
            self._merge_wake(effects, task_id=task_id, due_at=report.observed_at)
        return TaskResult(
            outcome=result.outcome,
            effects=tuple(effects),
            state_effects=result.state_effects,
            notifications=result.notifications,
        )

    def _merge_delay(self, effects: list[ScheduleEffect], *, task_id: TaskId, due_at: datetime) -> None:
        if task_id == self._spec.task_id:
            self._merge_self_delay(effects, task_id=task_id, due_at=due_at)
            return

        for index, effect in enumerate(effects):
            if not isinstance(effect, RescheduleTask | DelayTask | WakeTask | DisableTask):
                continue
            if effect.task_id != task_id:
                continue
            if isinstance(effect, DisableTask):
                return
            merged_due_at = max(effect.due_at, due_at)
            if isinstance(effect, RescheduleTask):
                effects[index] = RescheduleTask(task_id, merged_due_at)
            elif isinstance(effect, DelayTask):
                effects[index] = DelayTask(task_id, merged_due_at)
            else:
                effects[index] = WakeTask(task_id, merged_due_at, effect.enable_policy)
            return
        effects.append(DelayTask(task_id, due_at))

    @staticmethod
    def _merge_self_delay(effects: list[ScheduleEffect], *, task_id: TaskId, due_at: datetime) -> None:
        for index, effect in enumerate(effects):
            if isinstance(effect, DisableTask) and effect.task_id == task_id:
                return
            if isinstance(effect, RescheduleSelf):
                effects[index] = RescheduleSelf(max(effect.due_at, due_at))
                return
        message = "current OpSi task delay requires a self schedule effect"
        raise AssertionError(message)

    def _merge_wake(self, effects: list[ScheduleEffect], *, task_id: TaskId, due_at: datetime) -> None:
        if task_id == self._spec.task_id:
            for index, effect in enumerate(effects):
                if isinstance(effect, DisableTask) and effect.task_id == task_id:
                    return
                if isinstance(effect, RescheduleSelf):
                    effects[index] = RescheduleSelf(due_at)
                    return
            message = "current OpSi task wake requires a self schedule effect"
            raise AssertionError(message)

        for index, effect in enumerate(effects):
            if not isinstance(effect, RescheduleTask | DelayTask | WakeTask | DisableTask):
                continue
            if effect.task_id != task_id:
                continue
            if isinstance(effect, DisableTask):
                return
            effects[index] = WakeTask(task_id, due_at, WakePolicy.FORCE_ENABLE)
            return
        effects.append(WakeTask(task_id, due_at, WakePolicy.FORCE_ENABLE))

    def _stale_progress_result(self, context: TaskContext) -> TaskResult | None:
        progress = self._progress
        if progress is None:
            return None
        metadata = context.metadata
        stale = (
            progress.settings_revision != metadata.settings_revision
            or progress.content_revision != metadata.content_revision
            or context.started_at >= progress.cycle_anchor
        )
        if not stale:
            return None
        return TaskResult(
            outcome=Deferred(_STALE_PROGRESS),
            effects=(RescheduleSelf(context.started_at),),
            state_effects=(delete_world_progress(self._spec.operation),),
        )

    def _validate_report_checkpoint(self, report: WorldTaskReport) -> None:
        if self._spec.checkpoint_mode is WorldCheckpointMode.ONE_SHOT:
            if report.status is WorldTaskStatus.IN_PROGRESS:
                message = f"one-shot operation cannot report in-progress: {self._spec.operation.value}"
                raise ValueError(message)
            return

        expected_cursor = expected_world_cursor_type(self._spec.operation)
        if report.cursor is not None:
            if expected_cursor is None:
                message = f"{self._spec.operation.value} report does not accept a cursor"
                raise ValueError(message)
            if not isinstance(report.cursor, expected_cursor):
                message = f"{self._spec.operation.value} report requires a {expected_cursor.__name__}"
                raise TypeError(message)
        completed_safe_unit = report.status is WorldTaskStatus.IN_PROGRESS
        if completed_safe_unit and expected_cursor is not None and report.cursor is None:
            message = f"{self._spec.operation.value} safe unit requires a {expected_cursor.__name__}"
            raise ValueError(message)

    def _resolve(self, report: WorldTaskReport, context: TaskContext) -> TaskResult:
        if report.status is WorldTaskStatus.IN_PROGRESS:
            return self._resolve_in_progress(report, context)
        if report.status is WorldTaskStatus.DISABLED:
            return self._resolve_disabled()
        if report.status not in {WorldTaskStatus.COMPLETED, WorldTaskStatus.EMPTY}:
            return self._resolve_waiting_state(report)
        return self._resolve_settled_state(report)

    def _resolve_in_progress(self, report: WorldTaskReport, context: TaskContext) -> TaskResult:
        progress = self._next_progress(report, context)
        if progress is None:
            message = "in-progress report did not produce resumable progress"
            raise AssertionError(message)
        return TaskResult(
            outcome=Deferred(_SAFE_UNIT_COMPLETED),
            effects=(RescheduleSelf(report.observed_at),),
            state_effects=(upsert_world_progress(progress),),
        )

    def _resolve_disabled(self) -> TaskResult:
        return TaskResult(
            outcome=Succeeded(),
            effects=(DisableTask(self._spec.task_id),),
            state_effects=self._settled_state_effects(),
        )

    def _next_progress(self, report: WorldTaskReport, context: TaskContext) -> WorldProgress | None:
        if self._spec.checkpoint_mode is WorldCheckpointMode.ONE_SHOT:
            return None
        current = self._progress
        if report.completed_units == 0 and report.cursor is None:
            return current
        completed_units = (0 if current is None else current.completed_units) + report.completed_units
        cursor = report.cursor if report.cursor is not None else (None if current is None else current.cursor)
        return WorldProgress(
            task_id=self._spec.task_id,
            operation=self._spec.operation,
            completed_units=completed_units,
            cycle_anchor=(self._progress_cycle_anchor(report) if current is None else current.cycle_anchor),
            settings_revision=context.metadata.settings_revision,
            content_revision=context.metadata.content_revision,
            cursor=cursor,
        )

    def _progress_cycle_anchor(self, report: WorldTaskReport) -> datetime:
        cycle = self._spec.progress_cycle
        if cycle is WorldProgressCycle.SERVER_UPDATE:
            return report.schedule.next_server_update_at
        if cycle is WorldProgressCycle.MONTH_RESET:
            return report.schedule.next_month_reset_at
        if cycle is WorldProgressCycle.ARCHIVE_REFRESH:
            return report.schedule.next_archive_refresh_at
        message = f"bounded operation has no progress cycle: {self._spec.operation.value}"
        raise AssertionError(message)

    def _settled_state_effects(self) -> tuple[StateEffect, ...]:
        if self._spec.checkpoint_mode is WorldCheckpointMode.ONE_SHOT:
            return ()
        return (delete_world_progress(self._spec.operation),)

    def _resolve_waiting_state(self, report: WorldTaskReport) -> TaskResult:
        if report.status is WorldTaskStatus.ACTION_POINT_LIMIT:
            return self._resolve_action_point_limit(report)
        if report.status is WorldTaskStatus.RESOURCE_LIMIT:
            return self._resolve_resource_limit(report)
        if report.status is WorldTaskStatus.EXPLORE_IN_PROGRESS:
            return TaskResult(
                outcome=Deferred(_EXPLORATION_ACTIVE),
                effects=(RescheduleSelf(report.schedule.next_server_update_at),),
            )
        if report.status is WorldTaskStatus.COOLDOWN:
            return self._resolve_cooldown(report)
        due_at = report.retry_at or report.schedule.next_server_update_at
        return TaskResult(
            outcome=Retryable(_WORKFLOW_FAILED),
            effects=(RescheduleSelf(due_at),),
        )

    def _resolve_settled_state(self, report: WorldTaskReport) -> TaskResult:
        is_empty = report.status is WorldTaskStatus.EMPTY
        policy = self._spec.empty_refresh if is_empty else self._spec.completion_refresh
        due_at = self._due_at(policy, report)
        effects = [RescheduleSelf(due_at)]
        if self._spec.operation is WorldOperation.EXPLORE:
            effects.extend(
                WakeTask(task_id, report.observed_at, WakePolicy.RESPECT_DISABLED)
                for task_id in _EXPLORE_FOLLOW_UP_TASK_IDS
            )
        outcome = Deferred(_NO_WORK) if is_empty else Succeeded()
        return TaskResult(
            outcome=outcome,
            effects=tuple(effects),
            state_effects=self._settled_state_effects(),
        )

    def _resolve_action_point_limit(self, report: WorldTaskReport) -> TaskResult:
        policy = self._spec.action_point_policy
        if policy is ActionPointPolicy.BATCH:
            delay = _AP_LAST_DAY_DELAY if report.is_last_reset_day else _AP_NORMAL_DELAY
            due_at = report.observed_at + delay
            effects = [RescheduleSelf(due_at)]
            effects.extend(
                RescheduleTask(task_id, due_at) for task_id in _AP_BATCH_TASK_IDS if task_id != self._spec.task_id
            )
        elif policy is ActionPointPolicy.MEOWFFICER_HANDOFF:
            due_at = report.schedule.next_server_update_at
            effects = [RescheduleSelf(due_at)]
            if report.is_last_reset_day:
                effects[0] = RescheduleSelf(min(due_at, report.observed_at + _AP_LAST_DAY_DELAY))
            else:
                effects.append(WakeTask(REWARD_TASK_ID, report.observed_at, WakePolicy.FORCE_ENABLE))
                if report.has_surplus_yellow_coins:
                    effects.append(
                        WakeTask(
                            OPSI_HAZARD1_LEVELING_TASK_ID,
                            report.observed_at,
                            WakePolicy.RESPECT_DISABLED,
                        )
                    )
        elif policy is ActionPointPolicy.CROSS_MONTH_WINDOW:
            effects = [RescheduleSelf(self._cross_month_due_at(report))]
        else:
            effects = [RescheduleSelf(report.schedule.next_server_update_at)]
        return TaskResult(outcome=Deferred(_ACTION_POINTS_EXHAUSTED), effects=tuple(effects))

    def _resolve_resource_limit(self, report: WorldTaskReport) -> TaskResult:
        effects = [RescheduleSelf(report.schedule.next_server_update_at)]
        if self._spec.operation is WorldOperation.HAZARD1_LEVELING and not report.exploration_in_progress:
            effects.append(
                WakeTask(
                    OPSI_MEOWFFICER_FARMING_TASK_ID,
                    report.observed_at,
                    WakePolicy.FORCE_ENABLE,
                )
            )
        return TaskResult(outcome=Deferred(_RESOURCE_LIMIT), effects=tuple(effects))

    def _resolve_cooldown(self, report: WorldTaskReport) -> TaskResult:
        if report.retry_at is None:
            message = "validated cooldown report lost retry_at"
            raise AssertionError(message)
        effects = [RescheduleSelf(report.retry_at)]
        effects.extend(
            RescheduleTask(task_id, report.retry_at)
            for task_id in report.affected_task_ids
            if task_id != self._spec.task_id
        )
        return TaskResult(outcome=Deferred(_COOLDOWN_ACTIVE), effects=tuple(effects))

    def _due_at(self, policy: RefreshPolicy, report: WorldTaskReport) -> datetime:
        if policy is RefreshPolicy.SERVER_UPDATE:
            if (
                report.status is WorldTaskStatus.EMPTY
                and report.is_last_reset_day
                and self._spec.operation in {WorldOperation.OBSCURE, WorldOperation.ABYSSAL}
            ):
                return min(
                    report.schedule.next_server_update_at,
                    report.observed_at + _AP_LAST_DAY_DELAY,
                )
            return report.schedule.next_server_update_at
        if policy is RefreshPolicy.MONTH_RESET:
            return report.schedule.next_month_reset_at
        if policy is RefreshPolicy.ARCHIVE_REFRESH:
            return report.schedule.next_archive_refresh_at
        if policy is RefreshPolicy.CROSS_MONTH_WINDOW:
            return self._cross_month_due_at(report)
        if report.retry_at is None:
            message = f"{self._spec.operation.value} report requires retry_at"
            raise ValueError(message)
        return report.retry_at

    @staticmethod
    def _cross_month_due_at(report: WorldTaskReport) -> datetime:
        due_at = report.schedule.next_month_reset_at - _CROSS_MONTH_LEAD
        if due_at <= report.observed_at:
            message = "cross-month window must be after observed_at"
            raise ValueError(message)
        return due_at


def create_operation_siren_task(
    task_id: TaskId,
    workflow: OperationSirenWorkflow,
    settings: WorldTaskSettings,
    progress: WorldProgress | None = None,
) -> OperationSirenTask:
    return OperationSirenTask(workflow, world_task_spec(task_id, settings), progress)
