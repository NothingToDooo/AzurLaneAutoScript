from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, override

from module.application import (
    Blocked,
    Cancelled,
    DailySchedule,
    Deferred,
    DelayRange,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
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
)
from module.content.activity_catalog import CoalitionActivity, EventStoryActivity, RaidActivity
from module.content.activity_profile import CoalitionFleetMode, CoalitionStageId, RaidMode

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.application import CancellationSource


_ACTIVITY_UNAVAILABLE = "activity is unavailable"
_ACTIVITY_IN_PROGRESS = "activity batch is still in progress"
_STALE_ACTIVITY_PROGRESS = "stale activity progress was discarded"
MINIGAME_PROGRESS_KEY = "progress"
MINIGAME_PROGRESS_SCHEMA_VERSION = 1
_ENCOUNTER_IN_PROGRESS = "encounter batch is still in progress"
_STALE_ENCOUNTER_PROGRESS = "stale encounter progress was discarded"
ENCOUNTER_PROGRESS_KEY = "progress"
ENCOUNTER_PROGRESS_SCHEMA_VERSION = 1
_EVENT_UNAVAILABLE = "event is unavailable"
_ATTEMPTS_EXHAUSTED = "encounter attempts are exhausted"
_RESOURCE_LIMIT_REACHED = "encounter resource limit was reached"
_RECOVERY_REQUIRED = "encounter recovery is required"
_WORKFLOW_FAILED = "encounter workflow did not complete"
_BALANCER_SWITCH = "encounter yielded to the configured balancing task"
_ASSIST_ABORTED = "assist session aborted"


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def _validate_positive_integer(value: int, *, field_name: str) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if value <= 0:
        message = f"{field_name} must be positive"
        raise ValueError(message)


def _validate_non_negative_integer(value: int, *, field_name: str) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if value < 0:
        message = f"{field_name} must be non-negative"
        raise ValueError(message)


def _validate_bool(*, value: bool, field_name: str) -> None:
    if type(value) is not bool:
        message = f"{field_name} must be a bool"
        raise TypeError(message)


def _validate_positive_duration(value: timedelta, *, field_name: str) -> None:
    if not isinstance(value, timedelta):
        message = f"{field_name} must be a timedelta"
        raise TypeError(message)
    if value <= timedelta(0):
        message = f"{field_name} must be positive"
        raise ValueError(message)


def _validate_trimmed_string(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


def _require_method(value: object, method_name: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method_name, None)):
        message = f"{field_name} must implement {method_name}()"
        raise TypeError(message)


class GameplayTaskFamily(StrEnum):
    ACTIVITY = "activity"
    ENCOUNTER = "encounter"
    ASSIST_SESSION = "assist_session"


@dataclass(frozen=True, slots=True)
class GameplayCommandProfile:
    family: GameplayTaskFamily
    execution_mode: ExecutionMode

    def __post_init__(self) -> None:
        if not isinstance(self.family, GameplayTaskFamily):
            message = "family must be a GameplayTaskFamily"
            raise TypeError(message)
        if not isinstance(self.execution_mode, ExecutionMode):
            message = "execution_mode must be an ExecutionMode"
            raise TypeError(message)


GAMEPLAY_COMMAND_PROFILES: Mapping[str, GameplayCommandProfile] = MappingProxyType(
    {
        "minigame": GameplayCommandProfile(GameplayTaskFamily.ACTIVITY, ExecutionMode.SCHEDULED_JOB),
        "event_story": GameplayCommandProfile(GameplayTaskFamily.ACTIVITY, ExecutionMode.DIRECT_COMMAND),
        "raid_daily": GameplayCommandProfile(GameplayTaskFamily.ENCOUNTER, ExecutionMode.SCHEDULED_JOB),
        "maritime_escort": GameplayCommandProfile(GameplayTaskFamily.ENCOUNTER, ExecutionMode.SCHEDULED_JOB),
        "raid": GameplayCommandProfile(GameplayTaskFamily.ENCOUNTER, ExecutionMode.SCHEDULED_JOB),
        "hospital": GameplayCommandProfile(GameplayTaskFamily.ENCOUNTER, ExecutionMode.SCHEDULED_JOB),
        "coalition": GameplayCommandProfile(GameplayTaskFamily.ENCOUNTER, ExecutionMode.SCHEDULED_JOB),
        "coalition_sp": GameplayCommandProfile(GameplayTaskFamily.ENCOUNTER, ExecutionMode.SCHEDULED_JOB),
        "daemon": GameplayCommandProfile(GameplayTaskFamily.ASSIST_SESSION, ExecutionMode.ASSIST_SESSION),
        "opsi_daemon": GameplayCommandProfile(GameplayTaskFamily.ASSIST_SESSION, ExecutionMode.ASSIST_SESSION),
    }
)


def _validate_context(context: TaskContext, command: str) -> None:
    profile = GAMEPLAY_COMMAND_PROFILES[command]
    if context.task_id != TaskId(command):
        message = f"task context id must be {command!r}"
        raise ValueError(message)
    if context.mode is not profile.execution_mode:
        message = f"task {command!r} requires {profile.execution_mode.value} execution mode"
        raise ValueError(message)


class ActivityCommand(StrEnum):
    MINIGAME = "minigame"
    EVENT_STORY = "event_story"


class ActivityDisposition(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class MinigameKind(StrEnum):
    NEW_YEAR_CHALLENGE = "new_year_challenge"


@dataclass(frozen=True, slots=True)
class MinigameProgress:
    operations_completed: int
    cycle_ends_at: datetime
    settings_revision: int
    content_revision: str

    def __post_init__(self) -> None:
        _validate_positive_integer(self.operations_completed, field_name="operations_completed")
        _validate_aware_datetime(self.cycle_ends_at, field_name="cycle_ends_at")
        _validate_positive_integer(self.settings_revision, field_name="settings_revision")
        if not isinstance(self.content_revision, str):
            message = "content_revision must be a string"
            raise TypeError(message)
        if not self.content_revision or self.content_revision != self.content_revision.strip():
            message = "content_revision must be trimmed and non-empty"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class ActivitySpec:
    command: ActivityCommand
    schedule: DailySchedule | None = None
    operation_limit: int | None = None
    progress: MinigameProgress | None = None
    minigame_kind: MinigameKind | None = None
    skip_battle: bool | None = None
    activity: EventStoryActivity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.command, ActivityCommand):
            message = "command must be an ActivityCommand"
            raise TypeError(message)
        if self.command is ActivityCommand.MINIGAME:
            self._validate_minigame()
            return
        self._validate_event_story()

    def _validate_minigame(self) -> None:
        if self.schedule is None:
            message = "minigame requires schedule"
            raise ValueError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)
        if self.operation_limit is None:
            message = "minigame requires operation_limit"
            raise ValueError(message)
        _validate_positive_integer(self.operation_limit, field_name="operation_limit")
        if self.progress is not None and not isinstance(self.progress, MinigameProgress):
            message = "progress must be MinigameProgress or None"
            raise TypeError(message)
        if not isinstance(self.minigame_kind, MinigameKind):
            message = "minigame requires minigame_kind"
            raise TypeError(message)
        if self.skip_battle is not None or self.activity is not None:
            message = "minigame must not define event story options"
            raise ValueError(message)

    def _validate_event_story(self) -> None:
        if self.schedule is not None:
            message = "event_story must not define schedule"
            raise ValueError(message)
        if self.operation_limit is not None:
            message = "event_story must not define operation_limit"
            raise ValueError(message)
        if self.progress is not None:
            message = "event_story must not define progress"
            raise ValueError(message)
        if self.minigame_kind is not None:
            message = "event_story must not define minigame_kind"
            raise ValueError(message)
        if type(self.skip_battle) is not bool:
            message = "event_story requires skip_battle"
            raise TypeError(message)
        if not isinstance(self.activity, EventStoryActivity):
            message = "event_story requires an EventStoryActivity"
            raise TypeError(message)

    @classmethod
    def minigame(
        cls,
        *,
        schedule: DailySchedule,
        operation_limit: int = 10,
        progress: MinigameProgress | None = None,
        kind: MinigameKind = MinigameKind.NEW_YEAR_CHALLENGE,
    ) -> ActivitySpec:
        return cls(
            command=ActivityCommand.MINIGAME,
            schedule=schedule,
            operation_limit=operation_limit,
            progress=progress,
            minigame_kind=kind,
        )

    @classmethod
    def event_story(cls, *, activity: EventStoryActivity, skip_battle: bool) -> ActivitySpec:
        return cls(command=ActivityCommand.EVENT_STORY, skip_battle=skip_battle, activity=activity)

    @property
    def remaining_operations(self) -> int | None:
        if self.operation_limit is None:
            return None
        completed = 0 if self.progress is None else self.progress.operations_completed
        return max(0, self.operation_limit - completed)


@dataclass(frozen=True, slots=True)
class ActivityReport:
    command: ActivityCommand
    disposition: ActivityDisposition
    observed_at: datetime
    operations_completed: int

    def __post_init__(self) -> None:
        if not isinstance(self.command, ActivityCommand):
            message = "command must be an ActivityCommand"
            raise TypeError(message)
        if not isinstance(self.disposition, ActivityDisposition):
            message = "disposition must be an ActivityDisposition"
            raise TypeError(message)
        _validate_aware_datetime(self.observed_at, field_name="observed_at")
        _validate_non_negative_integer(self.operations_completed, field_name="operations_completed")
        if self.command is ActivityCommand.EVENT_STORY and self.operations_completed:
            message = "event_story must not report completed operations"
            raise ValueError(message)
        if self.command is ActivityCommand.MINIGAME and self.operations_completed > 1:
            message = "minigame must complete at most one operation per run"
            raise ValueError(message)
        if self.disposition is ActivityDisposition.IN_PROGRESS:
            if self.command is not ActivityCommand.MINIGAME:
                message = "in_progress is only valid for minigame"
                raise ValueError(message)
            if self.operations_completed != 1:
                message = "in_progress minigame must report exactly one completed operation"
                raise ValueError(message)
        if self.disposition is ActivityDisposition.UNAVAILABLE and self.operations_completed:
            message = "unavailable activity must not report completed operations"
            raise ValueError(message)


class ActivityWorkflow(Protocol):
    def execute(
        self,
        spec: ActivitySpec,
        cancellation: CancellationSource,
    ) -> ActivityReport:
        """在一次操作完成后的安全点返回。"""


class ActivityTask(Task):
    __slots__ = ("_spec", "_workflow")

    def __init__(self, workflow: ActivityWorkflow, spec: ActivitySpec) -> None:
        _require_method(workflow, "execute", field_name="workflow")
        if not isinstance(spec, ActivitySpec):
            message = "spec must be an ActivitySpec"
            raise TypeError(message)
        self._workflow = workflow
        self._spec = spec

    @override
    def run(self, context: TaskContext) -> TaskResult:
        command = self._spec.command.value
        _validate_context(context, command)
        context.abort.raise_if_requested()
        execution_spec, stale_progress = self._execution_spec(context)
        stale_effects = (self._delete_progress(context),) if stale_progress else ()
        if stale_progress:
            return TaskResult(
                outcome=Deferred(_STALE_ACTIVITY_PROGRESS),
                effects=(RescheduleSelf(context.started_at),),
                state_effects=stale_effects,
            )
        limit_reached = self._limit_reached_result(context, execution_spec)
        if limit_reached is not None:
            return limit_reached

        report = self._workflow.execute(execution_spec, context.abort)
        if not isinstance(report, ActivityReport):
            message = "ActivityWorkflow.execute() must return an ActivityReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        self._validate_report(context, execution_spec, report)
        progress = self._progress_after_report(context, execution_spec, report)
        return self._result_from_report(context, execution_spec, report, progress)

    def _execution_spec(self, context: TaskContext) -> tuple[ActivitySpec, bool]:
        progress = self._spec.progress
        if progress is None:
            return self._spec, False
        schedule = self._spec.schedule
        if schedule is None:
            message = "minigame progress requires a schedule"
            raise ValueError(message)
        is_current = (
            progress.settings_revision == context.metadata.settings_revision
            and progress.content_revision == context.metadata.content_revision
            and progress.cycle_ends_at == schedule.next_after(context.started_at)
        )
        if is_current:
            return self._spec, False
        return replace(self._spec, progress=None), True

    def _limit_reached_result(self, context: TaskContext, spec: ActivitySpec) -> TaskResult | None:
        progress = spec.progress
        operation_limit = spec.operation_limit
        if progress is None or operation_limit is None or progress.operations_completed < operation_limit:
            return None
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(progress.cycle_ends_at),),
            state_effects=(self._delete_progress(context),),
        )

    def _validate_report(self, context: TaskContext, spec: ActivitySpec, report: ActivityReport) -> None:
        if report.command is not spec.command:
            message = "activity report command must match the activity spec"
            raise ValueError(message)
        if report.observed_at < context.started_at:
            message = "activity report observed_at must not precede the run start"
            raise ValueError(message)
        operation_limit = spec.operation_limit
        if operation_limit is None:
            return
        operations_completed = self._operations_after_report(spec, report)
        if operations_completed > operation_limit:
            message = "activity report exceeds the configured operation_limit"
            raise ValueError(message)
        if report.disposition is ActivityDisposition.IN_PROGRESS and operations_completed >= operation_limit:
            message = "in_progress activity must leave at least one operation remaining"
            raise ValueError(message)

    @staticmethod
    def _operations_after_report(spec: ActivitySpec, report: ActivityReport) -> int:
        operations_completed = report.operations_completed
        progress = spec.progress
        schedule = spec.schedule
        if (
            progress is not None
            and schedule is not None
            and progress.cycle_ends_at == schedule.next_after(report.observed_at)
        ):
            operations_completed += progress.operations_completed
        return operations_completed

    def _progress_after_report(
        self,
        context: TaskContext,
        spec: ActivitySpec,
        report: ActivityReport,
    ) -> MinigameProgress | None:
        if spec.command is not ActivityCommand.MINIGAME or report.operations_completed == 0:
            return None
        schedule = spec.schedule
        if schedule is None:
            message = "minigame progress requires a schedule"
            raise ValueError(message)
        return MinigameProgress(
            operations_completed=self._operations_after_report(spec, report),
            cycle_ends_at=schedule.next_after(report.observed_at),
            settings_revision=context.metadata.settings_revision,
            content_revision=context.metadata.content_revision,
        )

    def _result_from_report(
        self,
        context: TaskContext,
        spec: ActivitySpec,
        report: ActivityReport,
        progress: MinigameProgress | None,
    ) -> TaskResult:
        if report.disposition is ActivityDisposition.IN_PROGRESS:
            if progress is None:
                message = "in_progress activity must produce a progress checkpoint"
                raise ValueError(message)
            return TaskResult(
                outcome=Deferred(_ACTIVITY_IN_PROGRESS),
                effects=(RescheduleSelf(report.observed_at),),
                state_effects=(self._upsert_progress(context, progress),),
            )

        outcome = Succeeded()
        if report.disposition is ActivityDisposition.UNAVAILABLE:
            outcome = Blocked(_ACTIVITY_UNAVAILABLE)

        if spec.schedule is None:
            return TaskResult(outcome=outcome)
        return TaskResult(
            outcome=outcome,
            effects=(RescheduleSelf(spec.schedule.next_after(report.observed_at)),),
            state_effects=(self._delete_progress(context),),
        )

    @staticmethod
    def _upsert_progress(context: TaskContext, progress: MinigameProgress) -> UpsertTaskState:
        return UpsertTaskState(
            namespace=context.task_id.value,
            key=MINIGAME_PROGRESS_KEY,
            schema_version=MINIGAME_PROGRESS_SCHEMA_VERSION,
            payload={
                "operations_completed": progress.operations_completed,
                "cycle_ends_at": progress.cycle_ends_at.isoformat(),
                "settings_revision": progress.settings_revision,
                "content_revision": progress.content_revision,
            },
        )

    @staticmethod
    def _delete_progress(context: TaskContext) -> DeleteTaskState:
        return DeleteTaskState(namespace=context.task_id.value, key=MINIGAME_PROGRESS_KEY)


class EncounterCommand(StrEnum):
    RAID_DAILY = "raid_daily"
    MARITIME_ESCORT = "maritime_escort"
    RAID = "raid"
    HOSPITAL = "hospital"
    COALITION = "coalition"
    COALITION_SP = "coalition_sp"


class EncounterStopReason(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    NO_DAILY_CONTENT = "no_daily_content"
    EVENT_UNAVAILABLE = "event_unavailable"
    EVENT_LIMIT = "event_limit"
    RUN_LIMIT = "run_limit"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    RESOURCE_LIMIT = "resource_limit"
    RECOVERY_REQUIRED = "recovery_required"
    BALANCER_SWITCH = "balancer_switch"
    FAILED = "failed"


_RESUMABLE_ENCOUNTER_STOPS = frozenset(
    {
        EncounterStopReason.RESOURCE_LIMIT,
        EncounterStopReason.RECOVERY_REQUIRED,
        EncounterStopReason.BALANCER_SWITCH,
        EncounterStopReason.FAILED,
    }
)
_SERVER_UPDATE_ENCOUNTERS = frozenset(
    {
        EncounterCommand.RAID_DAILY,
        EncounterCommand.MARITIME_ESCORT,
        EncounterCommand.HOSPITAL,
        EncounterCommand.COALITION_SP,
    }
)
_CONTINUOUS_ENCOUNTERS = frozenset({EncounterCommand.RAID, EncounterCommand.COALITION})
_ALLOWED_ENCOUNTER_STOPS: Mapping[EncounterCommand, frozenset[EncounterStopReason]] = MappingProxyType(
    {
        EncounterCommand.RAID_DAILY: frozenset(
            {
                EncounterStopReason.IN_PROGRESS,
                EncounterStopReason.COMPLETED,
                EncounterStopReason.NO_DAILY_CONTENT,
                EncounterStopReason.EVENT_UNAVAILABLE,
                EncounterStopReason.EVENT_LIMIT,
                EncounterStopReason.RESOURCE_LIMIT,
                EncounterStopReason.RECOVERY_REQUIRED,
                EncounterStopReason.FAILED,
            }
        ),
        EncounterCommand.MARITIME_ESCORT: frozenset(
            {
                EncounterStopReason.IN_PROGRESS,
                EncounterStopReason.COMPLETED,
                EncounterStopReason.EVENT_UNAVAILABLE,
                EncounterStopReason.EVENT_LIMIT,
                EncounterStopReason.FAILED,
            }
        ),
        EncounterCommand.RAID: frozenset(
            {
                EncounterStopReason.IN_PROGRESS,
                EncounterStopReason.EVENT_UNAVAILABLE,
                EncounterStopReason.EVENT_LIMIT,
                EncounterStopReason.RUN_LIMIT,
                EncounterStopReason.ATTEMPTS_EXHAUSTED,
                EncounterStopReason.RESOURCE_LIMIT,
                EncounterStopReason.RECOVERY_REQUIRED,
                EncounterStopReason.BALANCER_SWITCH,
                EncounterStopReason.FAILED,
            }
        ),
        EncounterCommand.HOSPITAL: frozenset(
            {
                EncounterStopReason.IN_PROGRESS,
                EncounterStopReason.COMPLETED,
                EncounterStopReason.EVENT_UNAVAILABLE,
                EncounterStopReason.EVENT_LIMIT,
                EncounterStopReason.RESOURCE_LIMIT,
                EncounterStopReason.RECOVERY_REQUIRED,
                EncounterStopReason.FAILED,
            }
        ),
        EncounterCommand.COALITION: frozenset(
            {
                EncounterStopReason.IN_PROGRESS,
                EncounterStopReason.EVENT_UNAVAILABLE,
                EncounterStopReason.EVENT_LIMIT,
                EncounterStopReason.RUN_LIMIT,
                EncounterStopReason.RESOURCE_LIMIT,
                EncounterStopReason.RECOVERY_REQUIRED,
                EncounterStopReason.BALANCER_SWITCH,
                EncounterStopReason.FAILED,
            }
        ),
        EncounterCommand.COALITION_SP: frozenset(
            {
                EncounterStopReason.IN_PROGRESS,
                EncounterStopReason.COMPLETED,
                EncounterStopReason.EVENT_UNAVAILABLE,
                EncounterStopReason.EVENT_LIMIT,
                EncounterStopReason.RESOURCE_LIMIT,
                EncounterStopReason.RECOVERY_REQUIRED,
                EncounterStopReason.FAILED,
            }
        ),
    }
)


class EmotionMode(StrEnum):
    CALCULATE = "calculate"
    IGNORE = "ignore"
    CALCULATE_IGNORE = "calculate_ignore"


class EmotionControl(StrEnum):
    KEEP_EXP_BONUS = "keep_exp_bonus"
    PREVENT_GREEN_FACE = "prevent_green_face"
    PREVENT_YELLOW_FACE = "prevent_yellow_face"
    PREVENT_RED_FACE = "prevent_red_face"


class EmotionRecoverLocation(StrEnum):
    NOT_IN_DORMITORY = "not_in_dormitory"
    DORMITORY_FLOOR_1 = "dormitory_floor_1"
    DORMITORY_FLOOR_2 = "dormitory_floor_2"


@dataclass(frozen=True, slots=True)
class FleetEmotionPolicy:
    control: EmotionControl
    recover: EmotionRecoverLocation
    oath: bool

    def __post_init__(self) -> None:
        if not isinstance(self.control, EmotionControl):
            message = "control must be an EmotionControl"
            raise TypeError(message)
        if not isinstance(self.recover, EmotionRecoverLocation):
            message = "recover must be an EmotionRecoverLocation"
            raise TypeError(message)
        _validate_bool(value=self.oath, field_name="oath")


@dataclass(frozen=True, slots=True)
class EmotionPolicy:
    mode: EmotionMode
    fleet1: FleetEmotionPolicy
    fleet2: FleetEmotionPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.mode, EmotionMode):
            message = "mode must be an EmotionMode"
            raise TypeError(message)
        if not isinstance(self.fleet1, FleetEmotionPolicy):
            message = "fleet1 must be a FleetEmotionPolicy"
            raise TypeError(message)
        if not isinstance(self.fleet2, FleetEmotionPolicy):
            message = "fleet2 must be a FleetEmotionPolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class EncounterPolicy:
    failure_retry_delay: DelayRange
    resource_retry_delay: timedelta
    oil_limit: int = 0
    event_point_limit: int = 0
    event_deadline_at: datetime | None = None
    use_2x_book: bool = False
    emotion: EmotionPolicy | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.failure_retry_delay, DelayRange):
            message = "failure_retry_delay must be a DelayRange"
            raise TypeError(message)
        _validate_positive_duration(self.resource_retry_delay, field_name="resource_retry_delay")
        _validate_non_negative_integer(self.oil_limit, field_name="oil_limit")
        _validate_non_negative_integer(self.event_point_limit, field_name="event_point_limit")
        if self.event_deadline_at is not None:
            _validate_aware_datetime(self.event_deadline_at, field_name="event_deadline_at")
        _validate_bool(value=self.use_2x_book, field_name="use_2x_book")
        if self.emotion is not None and not isinstance(self.emotion, EmotionPolicy):
            message = "emotion must be an EmotionPolicy or None"
            raise TypeError(message)

    @property
    def effective_oil_limit(self) -> int:
        return max(500, self.oil_limit)


@dataclass(frozen=True, slots=True)
class EncounterBalancerPolicy:
    target_task_id: TaskId
    coin_limit: int
    retry_delay: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not isinstance(self.target_task_id, TaskId):
            message = "target_task_id must be a TaskId"
            raise TypeError(message)
        _validate_non_negative_integer(self.coin_limit, field_name="coin_limit")
        _validate_positive_duration(self.retry_delay, field_name="retry_delay")


@dataclass(frozen=True, slots=True)
class RaidDailyOptions:
    activity: RaidActivity
    stages: tuple[RaidMode, ...]
    use_ticket: bool
    collect_daily_mission: bool
    policy: EncounterPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.activity, RaidActivity):
            message = "activity must be a RaidActivity"
            raise TypeError(message)
        if not isinstance(self.stages, tuple) or not self.stages:
            message = "stages must be a non-empty tuple"
            raise TypeError(message)
        if any(not isinstance(stage, RaidMode) for stage in self.stages):
            message = "stages must contain RaidMode values"
            raise TypeError(message)
        if len(set(self.stages)) != len(self.stages):
            message = "stages must not contain duplicates"
            raise ValueError(message)
        definition = self.activity.definition
        if definition.supports_daily and not set(self.stages).issubset(definition.daily_modes):
            message = "stages must be supported daily modes for the selected raid"
            raise ValueError(message)
        _validate_bool(value=self.use_ticket, field_name="use_ticket")
        _validate_bool(value=self.collect_daily_mission, field_name="collect_daily_mission")
        if not isinstance(self.policy, EncounterPolicy):
            message = "policy must be an EncounterPolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MaritimeEscortOptions:
    policy: EncounterPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.policy, EncounterPolicy):
            message = "policy must be an EncounterPolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class RaidOptions:
    activity: RaidActivity
    mode: RaidMode
    use_ticket: bool
    policy: EncounterPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.activity, RaidActivity):
            message = "activity must be a RaidActivity"
            raise TypeError(message)
        if not isinstance(self.mode, RaidMode):
            message = "mode must be a RaidMode"
            raise TypeError(message)
        if self.mode not in self.activity.definition.modes:
            message = "mode must be supported by the selected raid"
            raise ValueError(message)
        _validate_bool(value=self.use_ticket, field_name="use_ticket")
        if not isinstance(self.policy, EncounterPolicy):
            message = "policy must be an EncounterPolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class HospitalOptions:
    use_recommended_fleet: bool
    policy: EncounterPolicy

    def __post_init__(self) -> None:
        _validate_bool(value=self.use_recommended_fleet, field_name="use_recommended_fleet")
        if not isinstance(self.policy, EncounterPolicy):
            message = "policy must be an EncounterPolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CoalitionOptions:
    activity: CoalitionActivity
    stage: CoalitionStageId
    fleet: CoalitionFleetMode
    policy: EncounterPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.activity, CoalitionActivity):
            message = "activity must be a CoalitionActivity"
            raise TypeError(message)
        if not isinstance(self.stage, CoalitionStageId):
            message = "stage must be a CoalitionStageId"
            raise TypeError(message)
        if not isinstance(self.fleet, CoalitionFleetMode):
            message = "fleet must be a CoalitionFleetMode"
            raise TypeError(message)
        stage = self.activity.definition.get_stage(self.stage)
        if stage is None:
            message = "stage must belong to the selected coalition"
            raise ValueError(message)
        if not stage.fleet_rule.allows(self.fleet):
            message = "fleet must satisfy the selected coalition stage rule"
            raise ValueError(message)
        if not isinstance(self.policy, EncounterPolicy):
            message = "policy must be an EncounterPolicy"
            raise TypeError(message)


type EncounterOptions = RaidDailyOptions | MaritimeEscortOptions | RaidOptions | HospitalOptions | CoalitionOptions


@dataclass(frozen=True, slots=True)
class EncounterProgress:
    runs_completed: int
    cycle_ends_at: datetime | None
    settings_revision: int
    content_revision: str

    def __post_init__(self) -> None:
        _validate_positive_integer(self.runs_completed, field_name="runs_completed")
        if self.cycle_ends_at is not None:
            _validate_aware_datetime(self.cycle_ends_at, field_name="cycle_ends_at")
        _validate_positive_integer(self.settings_revision, field_name="settings_revision")
        _validate_trimmed_string(self.content_revision, field_name="content_revision")


@dataclass(frozen=True, slots=True)
class EncounterSpec:
    command: EncounterCommand
    options: EncounterOptions
    schedule: DailySchedule | None = None
    run_limit: int | None = None
    balancer: EncounterBalancerPolicy | None = None
    progress: EncounterProgress | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.command, EncounterCommand):
            message = "command must be an EncounterCommand"
            raise TypeError(message)

        self._validate_schedule()
        self._validate_run_limit()
        self._validate_options()
        self._validate_balancer()
        self._validate_progress()

    def _validate_schedule(self) -> None:
        command = self.command

        if command in _SERVER_UPDATE_ENCOUNTERS:
            if self.schedule is None:
                message = f"{command.value} requires schedule"
                raise ValueError(message)
            if not isinstance(self.schedule, DailySchedule):
                message = "schedule must be a DailySchedule"
                raise TypeError(message)
        elif self.schedule is not None:
            message = f"{command.value} must not define schedule"
            raise ValueError(message)

    def _validate_run_limit(self) -> None:
        if self.run_limit is not None:
            _validate_positive_integer(self.run_limit, field_name="run_limit")
        if self.command is EncounterCommand.COALITION_SP:
            if self.run_limit != 1:
                message = "coalition_sp run_limit must be one"
                raise ValueError(message)
        elif self.command not in _CONTINUOUS_ENCOUNTERS and self.run_limit is not None:
            message = f"{self.command.value} must not define run_limit"
            raise ValueError(message)

    def _validate_balancer(self) -> None:
        if self.balancer is not None:
            if not isinstance(self.balancer, EncounterBalancerPolicy):
                message = "balancer must be an EncounterBalancerPolicy or None"
                raise TypeError(message)
            if self.command not in _CONTINUOUS_ENCOUNTERS:
                message = "balancer is only valid for raid and coalition"
                raise ValueError(message)
            if self.balancer.target_task_id == TaskId(self.command.value):
                message = "balancer target must identify a different task"
                raise ValueError(message)

    def _validate_options(self) -> None:
        expected: type[EncounterOptions]
        if self.command is EncounterCommand.RAID_DAILY:
            expected = RaidDailyOptions
        elif self.command is EncounterCommand.MARITIME_ESCORT:
            expected = MaritimeEscortOptions
        elif self.command is EncounterCommand.RAID:
            expected = RaidOptions
        elif self.command is EncounterCommand.HOSPITAL:
            expected = HospitalOptions
        else:
            expected = CoalitionOptions
        if not isinstance(self.options, expected):
            message = f"{self.command.value} requires {expected.__name__}"
            raise TypeError(message)
        if (
            self.command is EncounterCommand.COALITION_SP
            and isinstance(self.options, CoalitionOptions)
            and self.options.stage.value != "sp"
        ):
            message = "coalition_sp requires the sp stage"
            raise ValueError(message)
        if (
            self.command is EncounterCommand.COALITION_SP
            and isinstance(self.options, CoalitionOptions)
            and self.options.fleet is not CoalitionFleetMode.MULTI
        ):
            message = "coalition_sp requires the multi-fleet mode"
            raise ValueError(message)
        if (
            self.command is EncounterCommand.COALITION
            and isinstance(self.options, CoalitionOptions)
            and self.options.stage.value == "sp"
        ):
            message = "coalition must not use the sp stage"
            raise ValueError(message)

    def _validate_progress(self) -> None:
        progress = self.progress
        if progress is None:
            return
        if not isinstance(progress, EncounterProgress):
            message = "progress must be an EncounterProgress or None"
            raise TypeError(message)
        if self.schedule is None and progress.cycle_ends_at is not None:
            message = "continuous encounter progress must not define cycle_ends_at"
            raise ValueError(message)
        if self.schedule is not None and progress.cycle_ends_at is None:
            message = "scheduled encounter progress requires cycle_ends_at"
            raise ValueError(message)

    @property
    def runs_completed(self) -> int:
        return 0 if self.progress is None else self.progress.runs_completed

    @property
    def remaining_runs(self) -> int | None:
        if self.run_limit is None:
            return None
        return max(0, self.run_limit - self.runs_completed)


@dataclass(frozen=True, slots=True)
class EncounterReport:
    command: EncounterCommand
    stop_reason: EncounterStopReason
    observed_at: datetime
    runs_completed: int
    resume_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.command, EncounterCommand):
            message = "command must be an EncounterCommand"
            raise TypeError(message)
        if not isinstance(self.stop_reason, EncounterStopReason):
            message = "stop_reason must be an EncounterStopReason"
            raise TypeError(message)
        if self.stop_reason not in _ALLOWED_ENCOUNTER_STOPS[self.command]:
            message = f"{self.stop_reason.value} is not valid for {self.command.value}"
            raise ValueError(message)
        _validate_aware_datetime(self.observed_at, field_name="observed_at")
        _validate_non_negative_integer(self.runs_completed, field_name="runs_completed")
        if self.runs_completed > 1:
            message = "encounter must complete at most one safe unit per run"
            raise ValueError(message)
        self._validate_resume_at()
        self._validate_stop_evidence()

    def _validate_resume_at(self) -> None:
        if self.stop_reason in _RESUMABLE_ENCOUNTER_STOPS:
            if self.resume_at is None:
                message = f"{self.stop_reason.value} requires resume_at"
                raise ValueError(message)
            _validate_aware_datetime(self.resume_at, field_name="resume_at")
            if self.resume_at <= self.observed_at:
                message = "resume_at must be later than observed_at"
                raise ValueError(message)
        elif self.resume_at is not None:
            message = f"{self.stop_reason.value} must not define resume_at"
            raise ValueError(message)

    def _validate_stop_evidence(self) -> None:
        if self.stop_reason is EncounterStopReason.NO_DAILY_CONTENT and self.runs_completed:
            message = "no_daily_content must not report completed runs"
            raise ValueError(message)
        if self.stop_reason is EncounterStopReason.RUN_LIMIT and not self.runs_completed:
            message = "run_limit must report at least one completed run"
            raise ValueError(message)
        if (
            self.stop_reason is EncounterStopReason.IN_PROGRESS
            and self.command in _CONTINUOUS_ENCOUNTERS
            and self.runs_completed != 1
        ):
            message = "continuous in_progress report must contain exactly one completed run"
            raise ValueError(message)


class EncounterWorkflow(Protocol):
    def execute(self, spec: EncounterSpec, cancellation: CancellationSource) -> EncounterReport: ...


class EncounterTask(Task):
    __slots__ = ("_spec", "_workflow")

    def __init__(self, workflow: EncounterWorkflow, spec: EncounterSpec) -> None:
        _require_method(workflow, "execute", field_name="workflow")
        if not isinstance(spec, EncounterSpec):
            message = "spec must be an EncounterSpec"
            raise TypeError(message)
        self._workflow = workflow
        self._spec = spec

    @override
    def run(self, context: TaskContext) -> TaskResult:
        command = self._spec.command.value
        _validate_context(context, command)
        context.abort.raise_if_requested()
        execution_spec, stale_progress = self._execution_spec(context)
        if stale_progress:
            return TaskResult(
                outcome=Deferred(_STALE_ENCOUNTER_PROGRESS),
                effects=(RescheduleSelf(context.started_at),),
                state_effects=(self._delete_progress(context),),
            )
        limit_reached = self._limit_reached_result(context, execution_spec)
        if limit_reached is not None:
            return limit_reached

        report = self._workflow.execute(execution_spec, context.abort)
        if not isinstance(report, EncounterReport):
            message = "EncounterWorkflow.execute() must return an EncounterReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        self._validate_report(context, execution_spec, report)
        progress = self._progress_after_report(context, execution_spec, report)
        return self._result_from_report(context, execution_spec, report, progress)

    def _execution_spec(self, context: TaskContext) -> tuple[EncounterSpec, bool]:
        progress = self._spec.progress
        if progress is None:
            return self._spec, False
        is_current = (
            progress.settings_revision == context.metadata.settings_revision
            and progress.content_revision == context.metadata.content_revision
        )
        schedule = self._spec.schedule
        if schedule is not None:
            is_current = is_current and progress.cycle_ends_at == schedule.next_after(context.started_at)
        if is_current:
            return self._spec, False
        return replace(self._spec, progress=None), True

    def _limit_reached_result(self, context: TaskContext, spec: EncounterSpec) -> TaskResult | None:
        run_limit = spec.run_limit
        progress = spec.progress
        if run_limit is None or progress is None or progress.runs_completed < run_limit:
            return None
        state_effects = (self._delete_progress(context),)
        schedule = spec.schedule
        if schedule is not None:
            cycle_ends_at = progress.cycle_ends_at
            if cycle_ends_at is None:
                message = "scheduled encounter progress requires cycle_ends_at"
                raise ValueError(message)
            return TaskResult(
                outcome=Succeeded(),
                effects=(RescheduleSelf(cycle_ends_at),),
                state_effects=state_effects,
            )
        return TaskResult(
            outcome=Succeeded(),
            effects=(DisableTask(context.task_id),),
            state_effects=state_effects,
        )

    @staticmethod
    def _validate_report(context: TaskContext, spec: EncounterSpec, report: EncounterReport) -> None:
        if report.command is not spec.command:
            message = "encounter report command must match the encounter spec"
            raise ValueError(message)
        if report.observed_at < context.started_at:
            message = "encounter report observed_at must not precede the run start"
            raise ValueError(message)
        runs_completed = spec.runs_completed + report.runs_completed
        if spec.run_limit is not None and runs_completed > spec.run_limit:
            message = "encounter report exceeds the configured run_limit"
            raise ValueError(message)
        if report.stop_reason is EncounterStopReason.RUN_LIMIT and (
            spec.run_limit is None or runs_completed != spec.run_limit
        ):
            message = "run_limit report must cumulatively settle the configured run_limit"
            raise ValueError(message)
        if (
            report.stop_reason is EncounterStopReason.IN_PROGRESS
            and spec.run_limit is not None
            and runs_completed >= spec.run_limit
        ):
            message = "in_progress encounter must leave at least one run remaining"
            raise ValueError(message)
        if (
            spec.command is EncounterCommand.COALITION_SP
            and report.stop_reason is EncounterStopReason.COMPLETED
            and runs_completed != 1
        ):
            message = "completed coalition_sp report must contain exactly one run"
            raise ValueError(message)
        if report.stop_reason is EncounterStopReason.BALANCER_SWITCH and spec.balancer is None:
            message = "balancer_switch requires a configured balancer_task_id"
            raise ValueError(message)

    @staticmethod
    def _progress_after_report(
        context: TaskContext,
        spec: EncounterSpec,
        report: EncounterReport,
    ) -> EncounterProgress | None:
        completed = spec.runs_completed + report.runs_completed
        if completed == 0:
            return None
        schedule = spec.schedule
        cycle_ends_at = None if schedule is None else schedule.next_after(context.started_at)
        return EncounterProgress(
            runs_completed=completed,
            cycle_ends_at=cycle_ends_at,
            settings_revision=context.metadata.settings_revision,
            content_revision=context.metadata.content_revision,
        )

    def _result_from_report(
        self,
        context: TaskContext,
        spec: EncounterSpec,
        report: EncounterReport,
        progress: EncounterProgress | None,
    ) -> TaskResult:
        stop_reason = report.stop_reason
        if stop_reason is EncounterStopReason.IN_PROGRESS:
            state_effects = () if progress is None else (self._upsert_progress(context, progress),)
            return TaskResult(
                outcome=Deferred(_ENCOUNTER_IN_PROGRESS),
                effects=(RescheduleSelf(report.observed_at),),
                state_effects=state_effects,
            )

        if stop_reason is EncounterStopReason.COMPLETED:
            schedule = spec.schedule
            if schedule is None:
                message = "continuous encounters must terminate with an explicit stop reason"
                raise ValueError(message)
            return TaskResult(
                outcome=Succeeded(),
                effects=(RescheduleSelf(schedule.next_after(report.observed_at)),),
                state_effects=self._cleanup_effects(context, spec),
            )

        if stop_reason not in _RESUMABLE_ENCOUNTER_STOPS:
            return self._terminal_result(context, spec, stop_reason)

        return self._resumable_result(context, spec, report, progress)

    @staticmethod
    def _terminal_result(
        context: TaskContext,
        spec: EncounterSpec,
        stop_reason: EncounterStopReason,
    ) -> TaskResult:
        if stop_reason is EncounterStopReason.EVENT_UNAVAILABLE:
            outcome = Blocked(_EVENT_UNAVAILABLE)
        elif stop_reason is EncounterStopReason.ATTEMPTS_EXHAUSTED:
            outcome = Deferred(_ATTEMPTS_EXHAUSTED)
        elif stop_reason in {
            EncounterStopReason.NO_DAILY_CONTENT,
            EncounterStopReason.EVENT_LIMIT,
            EncounterStopReason.RUN_LIMIT,
        }:
            outcome = Succeeded()
        else:
            message = f"unsupported terminal encounter stop reason: {stop_reason.value}"
            raise ValueError(message)
        return TaskResult(
            outcome=outcome,
            effects=(DisableTask(context.task_id),),
            state_effects=EncounterTask._cleanup_effects(context, spec),
        )

    def _resumable_result(
        self,
        context: TaskContext,
        spec: EncounterSpec,
        report: EncounterReport,
        progress: EncounterProgress | None,
    ) -> TaskResult:
        stop_reason = report.stop_reason
        resume_at = report.resume_at
        if resume_at is None:
            message = f"{stop_reason.value} report is missing resume_at"
            raise ValueError(message)
        state_effects = () if progress is None else (self._upsert_progress(context, progress),)
        if stop_reason is EncounterStopReason.BALANCER_SWITCH:
            balancer = spec.balancer
            if balancer is None:
                message = "balancer_switch requires a configured balancer_task_id"
                raise ValueError(message)
            return TaskResult(
                outcome=Deferred(_BALANCER_SWITCH),
                effects=(
                    RescheduleSelf(resume_at),
                    WakeTask(balancer.target_task_id, report.observed_at, WakePolicy.FORCE_ENABLE),
                ),
                state_effects=state_effects,
            )

        reason = {
            EncounterStopReason.RESOURCE_LIMIT: _RESOURCE_LIMIT_REACHED,
            EncounterStopReason.RECOVERY_REQUIRED: _RECOVERY_REQUIRED,
            EncounterStopReason.FAILED: _WORKFLOW_FAILED,
        }[stop_reason]
        return TaskResult(
            outcome=Retryable(reason),
            effects=(RescheduleSelf(resume_at),),
            state_effects=state_effects,
        )

    @staticmethod
    def _upsert_progress(context: TaskContext, progress: EncounterProgress) -> UpsertTaskState:
        return UpsertTaskState(
            namespace=context.task_id.value,
            key=ENCOUNTER_PROGRESS_KEY,
            schema_version=ENCOUNTER_PROGRESS_SCHEMA_VERSION,
            payload={
                "runs_completed": progress.runs_completed,
                "cycle_ends_at": None if progress.cycle_ends_at is None else progress.cycle_ends_at.isoformat(),
                "settings_revision": progress.settings_revision,
                "content_revision": progress.content_revision,
            },
        )

    @staticmethod
    def _delete_progress(context: TaskContext) -> DeleteTaskState:
        return DeleteTaskState(namespace=context.task_id.value, key=ENCOUNTER_PROGRESS_KEY)

    @staticmethod
    def _cleanup_effects(context: TaskContext, spec: EncounterSpec) -> tuple[DeleteTaskState, ...]:
        if spec.progress is None:
            return ()
        return (EncounterTask._delete_progress(context),)


class AssistSessionCommand(StrEnum):
    DAEMON = "daemon"
    OPSI_DAEMON = "opsi_daemon"


@dataclass(frozen=True, slots=True)
class DaemonOptions:
    enter_map: bool

    def __post_init__(self) -> None:
        _validate_bool(value=self.enter_map, field_name="enter_map")


@dataclass(frozen=True, slots=True)
class OpsiDaemonOptions:
    repair_ship: bool
    select_enemy: bool

    def __post_init__(self) -> None:
        _validate_bool(value=self.repair_ship, field_name="repair_ship")
        _validate_bool(value=self.select_enemy, field_name="select_enemy")


type AssistSessionOptions = DaemonOptions | OpsiDaemonOptions


@dataclass(frozen=True, slots=True)
class AssistSessionSpec:
    command: AssistSessionCommand
    options: AssistSessionOptions

    def __post_init__(self) -> None:
        if not isinstance(self.command, AssistSessionCommand):
            message = "command must be an AssistSessionCommand"
            raise TypeError(message)
        if self.command is AssistSessionCommand.DAEMON and not isinstance(self.options, DaemonOptions):
            message = "daemon requires DaemonOptions"
            raise TypeError(message)
        if self.command is AssistSessionCommand.OPSI_DAEMON and not isinstance(self.options, OpsiDaemonOptions):
            message = "opsi_daemon requires OpsiDaemonOptions"
            raise TypeError(message)


class AssistSessionState(StrEnum):
    CONTINUE = "continue"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class AssistSessionReport:
    command: AssistSessionCommand
    state: AssistSessionState

    def __post_init__(self) -> None:
        if not isinstance(self.command, AssistSessionCommand):
            message = "command must be an AssistSessionCommand"
            raise TypeError(message)
        if not isinstance(self.state, AssistSessionState):
            message = "state must be an AssistSessionState"
            raise TypeError(message)
        if self.command is AssistSessionCommand.OPSI_DAEMON and self.state is AssistSessionState.COMPLETED:
            message = "opsi_daemon has no automatic completion state"
            raise ValueError(message)


class AssistSessionWorkflow(Protocol):
    def advance_to_safe_point(
        self,
        spec: AssistSessionSpec,
        cancellation: CancellationSource,
    ) -> AssistSessionReport: ...


class AssistSessionTask(Task):
    """每次只推进一个有界步骤，并只在步骤边界响应停止信号。"""

    __slots__ = ("_spec", "_workflow")

    def __init__(self, workflow: AssistSessionWorkflow, spec: AssistSessionSpec) -> None:
        _require_method(workflow, "advance_to_safe_point", field_name="workflow")
        if not isinstance(spec, AssistSessionSpec):
            message = "spec must be an AssistSessionSpec"
            raise TypeError(message)
        self._workflow = workflow
        self._spec = spec

    @override
    def run(self, context: TaskContext) -> TaskResult:
        command = self._spec.command.value
        _validate_context(context, command)
        while 1:
            cancelled = self._cancelled_at_safe_point(context)
            if cancelled is not None:
                return cancelled

            report = self._workflow.advance_to_safe_point(self._spec, context.abort)
            if not isinstance(report, AssistSessionReport):
                message = "AssistSessionWorkflow.advance_to_safe_point() must return an AssistSessionReport"
                raise TypeError(message)
            if report.command is not self._spec.command:
                message = "assist session report command must match the assist session spec"
                raise ValueError(message)

            cancelled = self._cancelled_at_safe_point(context)
            if cancelled is not None:
                return cancelled
            if report.state is AssistSessionState.COMPLETED:
                return TaskResult(outcome=Succeeded())
        message = "assist session loop exited unexpectedly"
        raise AssertionError(message)

    @staticmethod
    def _cancelled_at_safe_point(context: TaskContext) -> TaskResult | None:
        if context.abort.is_requested:
            return TaskResult(outcome=Cancelled(context.abort.reason or _ASSIST_ABORTED))
        return None
