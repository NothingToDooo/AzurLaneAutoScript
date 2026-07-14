from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Protocol, override

from module.application import (
    DailySchedule,
    Deferred,
    DeleteTaskState,
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

if TYPE_CHECKING:
    from module.interaction import CancellationSignal


REWARD_TASK_ID = TaskId("reward")
EXERCISE_PROGRESS_KEY = "opponent-refreshes"
EXERCISE_PROGRESS_SCHEMA_VERSION = 1

_DAILY_ATTEMPTS_EXHAUSTED = "daily attempts are exhausted"
_DAILY_ATTEMPTS_UNAVAILABLE = "daily attempts were not completed"
_DAILY_IN_PROGRESS = "daily categories remain"
_HARD_ATTEMPTS_EXHAUSTED = "hard attempts are exhausted"
_HARD_RESOURCE_LIMIT = "hard resources are insufficient"
_HARD_WORKFLOW_FAILED = "hard workflow did not complete"
_HARD_IN_PROGRESS = "hard attempts remain"
_EXERCISE_ATTEMPTS_EXHAUSTED = "exercise attempts are exhausted"
_EXERCISE_ATTEMPTS_PRESERVED = "exercise attempts are preserved"
_EXERCISE_REFRESHES_EXHAUSTED = "exercise opponent refreshes are exhausted"
_EXERCISE_WORKFLOW_FAILED = "exercise attempt did not settle"
_EXERCISE_IN_PROGRESS = "exercise attempts remain"


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.tzinfo is None or value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def _validate_positive_duration(value: timedelta, *, field_name: str) -> None:
    if not isinstance(value, timedelta):
        message = f"{field_name} must be a timedelta"
        raise TypeError(message)
    if value <= timedelta(0):
        message = f"{field_name} must be positive"
        raise ValueError(message)


def _validate_non_negative_count(value: int, *, field_name: str) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if value < 0:
        message = f"{field_name} must be non-negative"
        raise ValueError(message)


def _validate_positive_count(value: int, *, field_name: str) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if value <= 0:
        message = f"{field_name} must be positive"
        raise ValueError(message)


class DailyStageSelection(StrEnum):
    SKIP = "skip"
    FIRST = "first"
    SECOND = "second"
    THIRD = "third"


@dataclass(frozen=True, slots=True)
class DailyMissionPlan:
    stage: DailyStageSelection
    fleet: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, DailyStageSelection):
            message = "stage must be a DailyStageSelection"
            raise TypeError(message)
        if self.fleet is not None and (type(self.fleet) is not int or not 1 <= self.fleet <= 6):
            message = "fleet must be null or an integer from 1 through 6"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class DailyMissionPlans:
    escort: DailyMissionPlan
    advance: DailyMissionPlan
    fierce_assault: DailyMissionPlan
    tactical_training: DailyMissionPlan
    supply_line_disruption: DailyMissionPlan
    module_development: DailyMissionPlan
    emergency_module_development: DailyMissionPlan

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            if not isinstance(getattr(self, field_name), DailyMissionPlan):
                message = f"{field_name} must be a DailyMissionPlan"
                raise TypeError(message)
        fleet_missions = (
            self.escort,
            self.advance,
            self.fierce_assault,
            self.tactical_training,
            self.module_development,
            self.emergency_module_development,
        )
        if any(mission.fleet is None for mission in fleet_missions):
            message = "surface daily missions must select a fleet"
            raise ValueError(message)
        if self.supply_line_disruption.fleet is not None:
            message = "supply_line_disruption fleet must be null"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class DailySettings:
    schedule: DailySchedule
    use_daily_skip: bool
    missions: DailyMissionPlans

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)
        if type(self.use_daily_skip) is not bool:
            message = "use_daily_skip must be a boolean"
            raise TypeError(message)
        if not isinstance(self.missions, DailyMissionPlans):
            message = "missions must be DailyMissionPlans"
            raise TypeError(message)


class DailyStopReason(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DailyReport:
    attempts_available: int
    attempts_completed: int
    stop_reason: DailyStopReason = DailyStopReason.COMPLETED

    def __post_init__(self) -> None:
        _validate_non_negative_count(self.attempts_available, field_name="attempts_available")
        _validate_non_negative_count(self.attempts_completed, field_name="attempts_completed")
        if self.attempts_completed > self.attempts_available:
            message = "attempts_completed must not exceed attempts_available"
            raise ValueError(message)
        if not isinstance(self.stop_reason, DailyStopReason):
            message = "stop_reason must be a DailyStopReason"
            raise TypeError(message)
        if self.stop_reason is DailyStopReason.IN_PROGRESS and self.attempts_completed == 0:
            message = "in-progress daily report must complete at least one attempt"
            raise ValueError(message)


class DailyWorkflow(Protocol):
    def execute(self, settings: DailySettings, cancellation: CancellationSignal) -> DailyReport: ...


class DailyTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: DailyWorkflow, settings: DailySettings) -> None:
        if not isinstance(settings, DailySettings):
            message = "settings must be DailySettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, DailyReport):
            message = "DailyWorkflow.execute() must return a DailyReport"
            raise TypeError(message)
        context.abort.raise_if_requested()

        if report.stop_reason is DailyStopReason.IN_PROGRESS:
            return TaskResult(
                outcome=Deferred(_DAILY_IN_PROGRESS),
                effects=(RescheduleSelf(context.started_at),),
            )
        if report.attempts_completed:
            outcome = Succeeded()
        elif report.attempts_available:
            outcome = Deferred(_DAILY_ATTEMPTS_UNAVAILABLE)
        else:
            outcome = Deferred(_DAILY_ATTEMPTS_EXHAUSTED)
        due_at = self._settings.schedule.next_after(context.started_at)
        return TaskResult(outcome=outcome, effects=(RescheduleSelf(due_at),))


class HardFleet(IntEnum):
    FLEET_1 = 1
    FLEET_2 = 2


@dataclass(frozen=True, slots=True)
class HardSettings:
    schedule: DailySchedule
    failure_retry_delay: timedelta
    resource_retry_delay: timedelta
    stage: str
    fleet: HardFleet

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)
        _validate_positive_duration(self.failure_retry_delay, field_name="failure_retry_delay")
        _validate_positive_duration(self.resource_retry_delay, field_name="resource_retry_delay")
        if not isinstance(self.stage, str):
            message = "stage must be a string"
            raise TypeError(message)
        if not self.stage or self.stage != self.stage.strip():
            message = "stage must be trimmed and non-empty"
            raise ValueError(message)
        if not isinstance(self.fleet, HardFleet):
            message = "fleet must be a HardFleet"
            raise TypeError(message)


class HardStopReason(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    RESOURCE_LIMIT = "resource_limit"
    FAILED = "failed"


class HardBattleOutcome(StrEnum):
    SETTLED = "settled"
    RESOURCE_LIMIT = "resource_limit"
    FAILED = "failed"


class HardCampaignPort(Protocol):
    def remaining_attempts(
        self,
        settings: HardSettings,
        cancellation: CancellationSignal,
    ) -> int: ...

    def advance_one(
        self,
        settings: HardSettings,
        cancellation: CancellationSignal,
    ) -> HardBattleOutcome: ...

    def exit_ui(
        self,
        settings: HardSettings,
        cancellation: CancellationSignal,
    ) -> None: ...

    def release(self) -> None: ...


@dataclass(frozen=True, slots=True)
class HardReport:
    observed_at: datetime
    attempts_available: int
    attempts_completed: int
    stop_reason: HardStopReason

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.observed_at, field_name="observed_at")
        _validate_non_negative_count(self.attempts_available, field_name="attempts_available")
        _validate_non_negative_count(self.attempts_completed, field_name="attempts_completed")
        if not isinstance(self.stop_reason, HardStopReason):
            message = "stop_reason must be a HardStopReason"
            raise TypeError(message)
        if self.attempts_completed > self.attempts_available:
            message = "attempts_completed must not exceed attempts_available"
            raise ValueError(message)
        if self.stop_reason is HardStopReason.COMPLETED and self.attempts_completed != self.attempts_available:
            message = "completed hard report must settle every available attempt"
            raise ValueError(message)
        if self.stop_reason is HardStopReason.IN_PROGRESS and self.attempts_completed != 1:
            message = "in-progress hard report must settle exactly one attempt"
            raise ValueError(message)


class HardWorkflow(Protocol):
    def execute(self, settings: HardSettings, cancellation: CancellationSignal) -> HardReport: ...


class HardTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: HardWorkflow, settings: HardSettings) -> None:
        if not isinstance(settings, HardSettings):
            message = "settings must be HardSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, HardReport):
            message = "HardWorkflow.execute() must return a HardReport"
            raise TypeError(message)
        context.abort.raise_if_requested()

        if report.stop_reason is HardStopReason.RESOURCE_LIMIT:
            return TaskResult(
                outcome=Retryable(_HARD_RESOURCE_LIMIT),
                effects=(RescheduleSelf(report.observed_at + self._settings.resource_retry_delay),),
            )
        if report.stop_reason is HardStopReason.FAILED:
            return TaskResult(
                outcome=Retryable(_HARD_WORKFLOW_FAILED),
                effects=(RescheduleSelf(report.observed_at + self._settings.failure_retry_delay),),
            )
        if report.stop_reason is HardStopReason.IN_PROGRESS:
            return TaskResult(
                outcome=Deferred(_HARD_IN_PROGRESS),
                effects=(RescheduleSelf(report.observed_at),),
            )

        outcome = Succeeded() if report.attempts_completed else Deferred(_HARD_ATTEMPTS_EXHAUSTED)
        due_at = self._settings.schedule.next_after(report.observed_at)
        return TaskResult(
            outcome=outcome,
            effects=(
                RescheduleSelf(due_at),
                WakeTask(REWARD_TASK_ID, report.observed_at, WakePolicy.FORCE_ENABLE),
            ),
        )


class ExerciseOpponentMode(StrEnum):
    MAX_EXP = "max_exp"
    EASIEST = "easiest"
    LEFTMOST = "leftmost"
    EASIEST_ELSE_EXP = "easiest_else_exp"


class ExerciseStrategy(StrEnum):
    AGGRESSIVE = "aggressive"
    FRI_18 = "fri18"
    SAT_00 = "sat0"
    SAT_12 = "sat12"
    SAT_18 = "sat18"
    SUN_00 = "sun0"
    SUN_12 = "sun12"
    SUN_18 = "sun18"


@dataclass(frozen=True, slots=True)
class ExerciseProgress:
    opponent_refreshes_used: int = 0

    def __post_init__(self) -> None:
        _validate_non_negative_count(self.opponent_refreshes_used, field_name="opponent_refreshes_used")


@dataclass(frozen=True, slots=True)
class ExerciseSettings:
    schedule: DailySchedule
    failure_retry_delay: timedelta
    opponent_refresh_limit: int
    opponent_mode: ExerciseOpponentMode
    opponent_trials: int
    strategy: ExerciseStrategy
    low_hp_threshold: float
    low_hp_confirm_wait_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)
        _validate_positive_duration(self.failure_retry_delay, field_name="failure_retry_delay")
        _validate_positive_count(self.opponent_refresh_limit, field_name="opponent_refresh_limit")
        if not isinstance(self.opponent_mode, ExerciseOpponentMode):
            message = "opponent_mode must be an ExerciseOpponentMode"
            raise TypeError(message)
        _validate_positive_count(self.opponent_trials, field_name="opponent_trials")
        if not isinstance(self.strategy, ExerciseStrategy):
            message = "strategy must be an ExerciseStrategy"
            raise TypeError(message)
        if type(self.low_hp_threshold) not in {int, float}:
            message = "low_hp_threshold must be a number"
            raise TypeError(message)
        if not 0 <= self.low_hp_threshold <= 1:
            message = "low_hp_threshold must be between zero and one"
            raise ValueError(message)
        if type(self.low_hp_confirm_wait_seconds) not in {int, float}:
            message = "low_hp_confirm_wait_seconds must be a number"
            raise TypeError(message)
        if self.low_hp_confirm_wait_seconds < 0:
            message = "low_hp_confirm_wait_seconds must be non-negative"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class ExerciseReport:
    observed_at: datetime
    attempts_remaining: int
    attempts_preserved: int
    attempts_completed: int
    opponent_refreshes_used: int

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.observed_at, field_name="observed_at")
        _validate_non_negative_count(self.attempts_remaining, field_name="attempts_remaining")
        _validate_non_negative_count(self.attempts_preserved, field_name="attempts_preserved")
        _validate_non_negative_count(self.attempts_completed, field_name="attempts_completed")
        _validate_non_negative_count(self.opponent_refreshes_used, field_name="opponent_refreshes_used")


class ExerciseWorkflow(Protocol):
    def execute(
        self,
        settings: ExerciseSettings,
        progress: ExerciseProgress,
        cancellation: CancellationSignal,
    ) -> ExerciseReport: ...


class ExerciseTask(Task):
    __slots__ = ("_progress", "_settings", "_workflow")

    def __init__(
        self,
        workflow: ExerciseWorkflow,
        settings: ExerciseSettings,
        progress: ExerciseProgress | None = None,
    ) -> None:
        if not isinstance(settings, ExerciseSettings):
            message = "settings must be ExerciseSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings
        self._progress = ExerciseProgress() if progress is None else progress
        if not isinstance(self._progress, ExerciseProgress):
            message = "progress must be an ExerciseProgress"
            raise TypeError(message)

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, self._progress, context.abort)
        if not isinstance(report, ExerciseReport):
            message = "ExerciseWorkflow.execute() must return an ExerciseReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        if report.opponent_refreshes_used > self._settings.opponent_refresh_limit:
            message = "opponent_refreshes_used must not exceed opponent_refresh_limit"
            raise ValueError(message)

        if report.attempts_remaining <= report.attempts_preserved:
            if report.attempts_completed:
                outcome = Succeeded()
            elif report.attempts_remaining:
                outcome = Deferred(_EXERCISE_ATTEMPTS_PRESERVED)
            else:
                outcome = Deferred(_EXERCISE_ATTEMPTS_EXHAUSTED)
            due_at = self._settings.schedule.next_after(report.observed_at)
            return TaskResult(
                outcome=outcome,
                effects=(RescheduleSelf(due_at),),
                state_effects=(DeleteTaskState(context.task_id.value, EXERCISE_PROGRESS_KEY),),
            )

        if report.opponent_refreshes_used == self._settings.opponent_refresh_limit:
            due_at = self._settings.schedule.next_after(report.observed_at)
            return TaskResult(
                outcome=Deferred(_EXERCISE_REFRESHES_EXHAUSTED),
                effects=(RescheduleSelf(due_at),),
                state_effects=(DeleteTaskState(context.task_id.value, EXERCISE_PROGRESS_KEY),),
            )

        progress_effect = UpsertTaskState(
            context.task_id.value,
            EXERCISE_PROGRESS_KEY,
            EXERCISE_PROGRESS_SCHEMA_VERSION,
            {"opponent_refreshes_used": report.opponent_refreshes_used},
        )
        if report.attempts_completed:
            return TaskResult(
                outcome=Deferred(_EXERCISE_IN_PROGRESS),
                effects=(RescheduleSelf(report.observed_at),),
                state_effects=(progress_effect,),
            )

        return TaskResult(
            outcome=Retryable(_EXERCISE_WORKFLOW_FAILED),
            effects=(RescheduleSelf(report.observed_at + self._settings.failure_retry_delay),),
            state_effects=(progress_effect,),
        )
