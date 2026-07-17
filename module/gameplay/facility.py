from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, cast, override

from module.application import (
    DailySchedule,
    Deferred,
    DelayRange,
    DelaySampler,
    RescheduleSelf,
    RescheduleTask,
    Retryable,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
    runtime_delay_sampler,
)
from module.gameplay.validation import (
    validate_aware_datetime,
    validate_bool,
    validate_non_negative_integer,
    validate_positive_duration,
)

if TYPE_CHECKING:
    from module.application import CancellationSource


GEMS_FARMING_TASK_ID = TaskId("gems_farming")
_RESEARCH_EMPTY_REASON = "no research project is running"
_COMMISSION_EMPTY_REASON = "no commission is running"
_TACTICAL_EMPTY_REASON = "no tactical training is running"


def _validate_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


class ResearchResourcePolicy(StrEnum):
    ALWAYS_USE = "always_use"
    ONLY_HALF_HOUR = "only_05_hour"
    ONLY_NO_PROJECT = "only_no_project"
    DO_NOT_USE = "do_not_use"


@dataclass(frozen=True, slots=True)
class ResearchSelectionPolicy:
    use_cube: ResearchResourcePolicy
    use_coin: ResearchResourcePolicy
    use_part: ResearchResourcePolicy
    allow_delay: bool
    preset_filter: str
    custom_filter: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("use_cube", self.use_cube),
            ("use_coin", self.use_coin),
            ("use_part", self.use_part),
        ):
            if not isinstance(value, ResearchResourcePolicy):
                message = f"{field_name} must be a ResearchResourcePolicy"
                raise TypeError(message)
        validate_bool(value=self.allow_delay, field_name="allow_delay")
        _validate_text(self.preset_filter, field_name="preset_filter")
        _validate_text(self.custom_filter, field_name="custom_filter")


@dataclass(frozen=True, slots=True)
class ResearchSettings:
    schedule: DailySchedule
    selection: ResearchSelectionPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)
        if not isinstance(self.selection, ResearchSelectionPolicy):
            message = "selection must be a ResearchSelectionPolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ResearchReport:
    observed_at: datetime
    available_slots: int
    first_finish_at: datetime | None

    def __post_init__(self) -> None:
        validate_aware_datetime(self.observed_at, field_name="observed_at")
        if type(self.available_slots) is not int:
            message = "available_slots must be an integer"
            raise TypeError(message)
        if not 0 <= self.available_slots <= 5:
            message = "available_slots must be between zero and five"
            raise ValueError(message)

        if self.available_slots == 5:
            if self.first_finish_at is not None:
                message = "an empty research queue must not have a first finish time"
                raise ValueError(message)
            return

        if self.first_finish_at is None:
            message = "a non-empty research queue must have a first finish time"
            raise ValueError(message)
        validate_aware_datetime(self.first_finish_at, field_name="first_finish_at")


class ResearchWorkflow(Protocol):
    def execute(self, settings: ResearchSettings, cancellation: CancellationSource) -> ResearchReport: ...


class ResearchTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: ResearchWorkflow, settings: ResearchSettings) -> None:
        if not isinstance(settings, ResearchSettings):
            message = "settings must be ResearchSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, ResearchReport):
            message = "ResearchWorkflow.execute() must return a ResearchReport"
            raise TypeError(message)
        context.abort.raise_if_requested()

        if report.available_slots == 5:
            return TaskResult(
                outcome=Deferred(_RESEARCH_EMPTY_REASON),
                effects=(RescheduleSelf(self._settings.schedule.next_after(report.observed_at)),),
            )

        finish_at = cast("datetime", report.first_finish_at)
        if report.available_slots == 4:
            finish_at -= timedelta(minutes=10)
        return TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(finish_at),))


class CommissionPreset(StrEnum):
    CUBE = "cube"
    CUBE_24H = "cube_24h"
    CHIP = "chip"
    CHIP_24H = "chip_24h"
    OIL = "oil"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class CommissionSelectionPolicy:
    preset_filter: CommissionPreset
    custom_filter: str
    do_major_commission: bool

    def __post_init__(self) -> None:
        if not isinstance(self.preset_filter, CommissionPreset):
            message = "preset_filter must be a CommissionPreset"
            raise TypeError(message)
        _validate_text(self.custom_filter, field_name="custom_filter")
        validate_bool(value=self.do_major_commission, field_name="do_major_commission")


@dataclass(frozen=True, slots=True)
class CommissionSettings:
    failure_retry_delay: DelayRange
    commission_limit_enabled: bool
    selection: CommissionSelectionPolicy
    gems_farming_deferral: timedelta = timedelta(hours=2)

    def __post_init__(self) -> None:
        if not isinstance(self.failure_retry_delay, DelayRange):
            message = "failure_retry_delay must be a DelayRange"
            raise TypeError(message)
        validate_bool(value=self.commission_limit_enabled, field_name="commission_limit_enabled")
        if not isinstance(self.selection, CommissionSelectionPolicy):
            message = "selection must be a CommissionSelectionPolicy"
            raise TypeError(message)
        validate_positive_duration(self.gems_farming_deferral, field_name="gems_farming_deferral")


@dataclass(frozen=True, slots=True)
class CommissionReport:
    observed_at: datetime
    finish_times: tuple[datetime, ...]
    daily_pending: int
    filtered_urgent_pending: int

    def __post_init__(self) -> None:
        validate_aware_datetime(self.observed_at, field_name="observed_at")
        if not isinstance(self.finish_times, tuple):
            message = "finish_times must be a tuple"
            raise TypeError(message)
        for finish_at in self.finish_times:
            validate_aware_datetime(finish_at, field_name="finish_times item")
        validate_non_negative_integer(self.daily_pending, field_name="daily_pending")
        validate_non_negative_integer(self.filtered_urgent_pending, field_name="filtered_urgent_pending")


class CommissionWorkflow(Protocol):
    def execute(self, settings: CommissionSettings, cancellation: CancellationSource) -> CommissionReport: ...


class CommissionTask(Task):
    __slots__ = ("_delay_sampler", "_settings", "_workflow")

    def __init__(
        self,
        workflow: CommissionWorkflow,
        settings: CommissionSettings,
        *,
        delay_sampler: DelaySampler = runtime_delay_sampler,
    ) -> None:
        if not isinstance(settings, CommissionSettings):
            message = "settings must be CommissionSettings"
            raise TypeError(message)
        if not isinstance(delay_sampler, DelaySampler):
            message = "delay_sampler must be a DelaySampler"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings
        self._delay_sampler = delay_sampler

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, CommissionReport):
            message = "CommissionWorkflow.execute() must return a CommissionReport"
            raise TypeError(message)
        context.abort.raise_if_requested()

        nearest_finish = min(report.finish_times, default=None)
        if nearest_finish is None:
            outcome = Retryable(_COMMISSION_EMPTY_REASON)
            self_due_at = report.observed_at + self._delay_sampler.sample(self._settings.failure_retry_delay)
        else:
            outcome = Succeeded()
            self_due_at = nearest_finish

        effects: list[RescheduleSelf | RescheduleTask] = [RescheduleSelf(self_due_at)]
        if self._must_defer_gems_farming(report):
            gems_due_at = report.observed_at + self._settings.gems_farming_deferral
            if nearest_finish is not None:
                gems_due_at = min(gems_due_at, nearest_finish)
            effects.append(RescheduleTask(GEMS_FARMING_TASK_ID, gems_due_at))
        return TaskResult(outcome=outcome, effects=tuple(effects))

    def _must_defer_gems_farming(self, report: CommissionReport) -> bool:
        if not self._settings.commission_limit_enabled:
            return False
        if report.daily_pending > 0 and report.filtered_urgent_pending >= 1:
            return True
        return report.filtered_urgent_pending >= 4


class TacticalRapidTrainingSlot(StrEnum):
    DISABLED = "do_not_use"
    SLOT_1 = "slot_1"
    SLOT_2 = "slot_2"
    SLOT_3 = "slot_3"
    SLOT_4 = "slot_4"


@dataclass(frozen=True, slots=True)
class TacticalExperienceOverflowPolicy:
    enabled: bool
    t1_allow: int
    t2_allow: int
    t3_allow: int
    t4_allow: int

    def __post_init__(self) -> None:
        validate_bool(value=self.enabled, field_name="enabled")
        for field_name, value in (
            ("t1_allow", self.t1_allow),
            ("t2_allow", self.t2_allow),
            ("t3_allow", self.t3_allow),
            ("t4_allow", self.t4_allow),
        ):
            validate_non_negative_integer(value, field_name=field_name)


@dataclass(frozen=True, slots=True)
class TacticalStudentPolicy:
    enabled: bool
    favorite: bool
    minimum_level: int

    def __post_init__(self) -> None:
        validate_bool(value=self.enabled, field_name="enabled")
        validate_bool(value=self.favorite, field_name="favorite")
        if type(self.minimum_level) is not int:
            message = "minimum_level must be an integer"
            raise TypeError(message)
        if not 1 <= self.minimum_level <= 125:
            message = "minimum_level must be between 1 and 125"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class TacticalSettings:
    failure_retry_delay: DelayRange
    server_update_schedule: DailySchedule
    tactical_filter: str
    rapid_training_slot: TacticalRapidTrainingSlot
    experience_overflow: TacticalExperienceOverflowPolicy
    student: TacticalStudentPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.failure_retry_delay, DelayRange):
            message = "failure_retry_delay must be a DelayRange"
            raise TypeError(message)
        if not isinstance(self.server_update_schedule, DailySchedule):
            message = "server_update_schedule must be a DailySchedule"
            raise TypeError(message)
        _validate_text(self.tactical_filter, field_name="tactical_filter")
        if not isinstance(self.rapid_training_slot, TacticalRapidTrainingSlot):
            message = "rapid_training_slot must be a TacticalRapidTrainingSlot"
            raise TypeError(message)
        if not isinstance(self.experience_overflow, TacticalExperienceOverflowPolicy):
            message = "experience_overflow must be a TacticalExperienceOverflowPolicy"
            raise TypeError(message)
        if not isinstance(self.student, TacticalStudentPolicy):
            message = "student must be a TacticalStudentPolicy"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class TacticalReport:
    observed_at: datetime
    finish_at: datetime | None

    def __post_init__(self) -> None:
        validate_aware_datetime(self.observed_at, field_name="observed_at")
        if self.finish_at is not None:
            validate_aware_datetime(self.finish_at, field_name="finish_at")


class TacticalWorkflow(Protocol):
    def execute(self, settings: TacticalSettings, cancellation: CancellationSource) -> TacticalReport: ...


class TacticalTask(Task):
    __slots__ = ("_delay_sampler", "_settings", "_workflow")

    def __init__(
        self,
        workflow: TacticalWorkflow,
        settings: TacticalSettings,
        *,
        delay_sampler: DelaySampler = runtime_delay_sampler,
    ) -> None:
        if not isinstance(settings, TacticalSettings):
            message = "settings must be TacticalSettings"
            raise TypeError(message)
        if not isinstance(delay_sampler, DelaySampler):
            message = "delay_sampler must be a DelaySampler"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings
        self._delay_sampler = delay_sampler

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, TacticalReport):
            message = "TacticalWorkflow.execute() must return a TacticalReport"
            raise TypeError(message)
        context.abort.raise_if_requested()

        if report.finish_at is None:
            return TaskResult(
                outcome=Retryable(_TACTICAL_EMPTY_REASON),
                effects=(
                    RescheduleSelf(report.observed_at + self._delay_sampler.sample(self._settings.failure_retry_delay)),
                ),
            )
        return TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(report.finish_at),))
