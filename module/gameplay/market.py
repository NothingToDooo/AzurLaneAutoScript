from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, override

from module.application import DailySchedule, DisableTask, RescheduleSelf, Succeeded, Task, TaskContext, TaskResult
from module.gameplay.validation import validate_bool, validate_non_negative_integer, validate_positive_integer

if TYPE_CHECKING:
    from module.application import CancellationSource


def _validate_filter(value: str | None, *, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        message = f"{field_name} must be a string or None"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty when provided"
        raise ValueError(message)


def _validate_choice(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


class AwakenLevelCap(StrEnum):
    LEVEL_120 = "level120"
    LEVEL_125 = "level125"


class AwakenRunResult(StrEnum):
    INSUFFICIENT = "insufficient"
    FINISHED = "finish"
    TIMED_OUT = "timeout"


@dataclass(frozen=True, slots=True)
class AwakenPlan:
    level_cap: AwakenLevelCap
    favourite_only: bool

    def __post_init__(self) -> None:
        if not isinstance(self.level_cap, AwakenLevelCap):
            message = "level_cap must be an AwakenLevelCap"
            raise TypeError(message)
        validate_bool(value=self.favourite_only, field_name="favourite_only")


@dataclass(frozen=True, slots=True)
class AwakenSettings:
    plan: AwakenPlan
    schedule: DailySchedule

    def __post_init__(self) -> None:
        if not isinstance(self.plan, AwakenPlan):
            message = "plan must be an AwakenPlan"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class AwakenAttempt:
    level_cap: AwakenLevelCap
    result: AwakenRunResult

    def __post_init__(self) -> None:
        if not isinstance(self.level_cap, AwakenLevelCap):
            message = "level_cap must be an AwakenLevelCap"
            raise TypeError(message)
        if not isinstance(self.result, AwakenRunResult):
            message = "result must be an AwakenRunResult"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class AwakenReport:
    attempts: tuple[AwakenAttempt, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.attempts, tuple) or any(
            not isinstance(attempt, AwakenAttempt) for attempt in self.attempts
        ):
            message = "attempts must be a tuple of AwakenAttempt values"
            raise TypeError(message)
        if not 1 <= len(self.attempts) <= 2:
            message = "attempts must contain one or two awaken attempts"
            raise ValueError(message)
        if len(self.attempts) == 2:
            first, second = self.attempts
            if (
                first.level_cap is not AwakenLevelCap.LEVEL_125
                or first.result is AwakenRunResult.TIMED_OUT
                or second.level_cap is not AwakenLevelCap.LEVEL_120
            ):
                message = "two awaken attempts must be a non-timeout level125 pass followed by level120"
                raise ValueError(message)


class AwakenWorkflow(Protocol):
    def execute(self, settings: AwakenSettings, cancellation: CancellationSource) -> AwakenReport: ...


class AwakenTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: AwakenWorkflow, settings: AwakenSettings) -> None:
        if not isinstance(settings, AwakenSettings):
            message = "settings must be AwakenSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, AwakenReport):
            message = "AwakenWorkflow.execute() must return an AwakenReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        self._validate_report(report)
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._settings.schedule.next_after(context.started_at)),),
        )

    def _validate_report(self, report: AwakenReport) -> None:
        attempts = report.attempts
        if self._settings.plan.level_cap is AwakenLevelCap.LEVEL_120:
            if len(attempts) != 1 or attempts[0].level_cap is not AwakenLevelCap.LEVEL_120:
                message = "level120 awaken plan must report exactly one level120 attempt"
                raise ValueError(message)
            return

        first = attempts[0]
        if first.level_cap is not AwakenLevelCap.LEVEL_125:
            message = "level125 awaken plan must start with a level125 attempt"
            raise ValueError(message)
        expected_attempts = 1 if first.result is AwakenRunResult.TIMED_OUT else 2
        if len(attempts) != expected_attempts:
            message = "level125 awaken plan must skip level120 only after a timeout"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class ShipyardPurchasePlan:
    research_series: int
    ship_index: int
    buy_amount: int

    def __post_init__(self) -> None:
        validate_positive_integer(self.research_series, field_name="research_series")
        validate_non_negative_integer(self.ship_index, field_name="ship_index")
        validate_non_negative_integer(self.buy_amount, field_name="buy_amount")


@dataclass(frozen=True, slots=True)
class ShipyardPlan:
    pr: ShipyardPurchasePlan
    dr: ShipyardPurchasePlan

    def __post_init__(self) -> None:
        if not isinstance(self.pr, ShipyardPurchasePlan):
            message = "pr must be a ShipyardPurchasePlan"
            raise TypeError(message)
        if not isinstance(self.dr, ShipyardPurchasePlan):
            message = "dr must be a ShipyardPurchasePlan"
            raise TypeError(message)

    @property
    def has_purchase(self) -> bool:
        return self.pr.buy_amount > 0 or self.dr.buy_amount > 0


@dataclass(frozen=True, slots=True)
class ShipyardSettings:
    plan: ShipyardPlan
    schedule: DailySchedule

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ShipyardPlan):
            message = "plan must be a ShipyardPlan"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ShipyardReport:
    pr_processed: bool
    dr_processed: bool

    def __post_init__(self) -> None:
        validate_bool(value=self.pr_processed, field_name="pr_processed")
        validate_bool(value=self.dr_processed, field_name="dr_processed")


class ShipyardWorkflow(Protocol):
    def execute(self, settings: ShipyardSettings, cancellation: CancellationSource) -> ShipyardReport: ...


class ShipyardTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: ShipyardWorkflow, settings: ShipyardSettings) -> None:
        if not isinstance(settings, ShipyardSettings):
            message = "settings must be ShipyardSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        if not self._settings.plan.has_purchase:
            return TaskResult(
                outcome=Succeeded(),
                effects=(DisableTask(context.task_id),),
            )

        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, ShipyardReport):
            message = "ShipyardWorkflow.execute() must return a ShipyardReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._settings.schedule.next_after(context.started_at)),),
        )


class GachaPool(StrEnum):
    LIGHT = "light"
    HEAVY = "heavy"
    SPECIAL = "special"
    EVENT = "event"
    WISHING_WELL = "wishing_well"


@dataclass(frozen=True, slots=True)
class GachaPlan:
    pool: GachaPool
    amount: int
    use_ticket: bool
    use_drill: bool

    def __post_init__(self) -> None:
        if not isinstance(self.pool, GachaPool):
            message = "pool must be a GachaPool"
            raise TypeError(message)
        validate_positive_integer(self.amount, field_name="amount")
        validate_bool(value=self.use_ticket, field_name="use_ticket")
        validate_bool(value=self.use_drill, field_name="use_drill")


@dataclass(frozen=True, slots=True)
class GachaSettings:
    plan: GachaPlan
    schedule: DailySchedule

    def __post_init__(self) -> None:
        if not isinstance(self.plan, GachaPlan):
            message = "plan must be a GachaPlan"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class GachaReport:
    submitted: bool

    def __post_init__(self) -> None:
        validate_bool(value=self.submitted, field_name="submitted")


class GachaWorkflow(Protocol):
    def execute(self, settings: GachaSettings, cancellation: CancellationSource) -> GachaReport: ...


class GachaTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: GachaWorkflow, settings: GachaSettings) -> None:
        if not isinstance(settings, GachaSettings):
            message = "settings must be GachaSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, GachaReport):
            message = "GachaWorkflow.execute() must return a GachaReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._settings.schedule.next_after(context.started_at)),),
        )


@dataclass(frozen=True, slots=True)
class GeneralShopPlan:
    filter: str | None
    refresh: bool
    use_gems: bool
    consume_coins: bool
    buy_skin_box: bool

    def __post_init__(self) -> None:
        _validate_filter(self.filter, field_name="filter")
        validate_bool(value=self.refresh, field_name="refresh")
        validate_bool(value=self.use_gems, field_name="use_gems")
        validate_bool(value=self.consume_coins, field_name="consume_coins")
        validate_bool(value=self.buy_skin_box, field_name="buy_skin_box")


@dataclass(frozen=True, slots=True)
class MeritShopPlan:
    filter: str | None
    refresh: bool

    def __post_init__(self) -> None:
        _validate_filter(self.filter, field_name="filter")
        validate_bool(value=self.refresh, field_name="refresh")


@dataclass(frozen=True, slots=True)
class GuildShopPlan:
    filter: str | None
    refresh: bool
    box_t3: str
    box_t4: str
    book_t2: str
    book_t3: str
    retrofit_t2: str
    retrofit_t3: str
    plate_t2: str
    plate_t3: str
    plate_t4: str
    pr1: str
    pr2: str
    pr3: str

    def __post_init__(self) -> None:
        _validate_filter(self.filter, field_name="filter")
        validate_bool(value=self.refresh, field_name="refresh")
        for field_name in (
            "box_t3",
            "box_t4",
            "book_t2",
            "book_t3",
            "retrofit_t2",
            "retrofit_t3",
            "plate_t2",
            "plate_t3",
            "plate_t4",
            "pr1",
            "pr2",
            "pr3",
        ):
            _validate_choice(getattr(self, field_name), field_name=field_name)


@dataclass(frozen=True, slots=True)
class CoreShopPlan:
    filter: str | None

    def __post_init__(self) -> None:
        _validate_filter(self.filter, field_name="filter")


@dataclass(frozen=True, slots=True)
class MedalShopPlan:
    filter: str | None
    retrofit_t1: str
    retrofit_t2: str
    retrofit_t3: str
    plate_t1: str
    plate_t2: str
    plate_t3: str

    def __post_init__(self) -> None:
        _validate_filter(self.filter, field_name="filter")
        for field_name in (
            "retrofit_t1",
            "retrofit_t2",
            "retrofit_t3",
            "plate_t1",
            "plate_t2",
            "plate_t3",
        ):
            _validate_choice(getattr(self, field_name), field_name=field_name)


@dataclass(frozen=True, slots=True)
class ShopOncePlan:
    merit: MeritShopPlan
    guild: GuildShopPlan
    core: CoreShopPlan
    medal: MedalShopPlan

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("merit", MeritShopPlan),
            ("guild", GuildShopPlan),
            ("core", CoreShopPlan),
            ("medal", MedalShopPlan),
        ):
            if not isinstance(getattr(self, field_name), expected):
                message = f"{field_name} must be a {expected.__name__}"
                raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ShopFrequentSettings:
    plan: GeneralShopPlan
    schedule: DailySchedule

    def __post_init__(self) -> None:
        if not isinstance(self.plan, GeneralShopPlan):
            message = "plan must be a GeneralShopPlan"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ShopFrequentReport:
    pass


class ShopFrequentWorkflow(Protocol):
    def execute(
        self,
        settings: ShopFrequentSettings,
        cancellation: CancellationSource,
    ) -> ShopFrequentReport: ...


class ShopFrequentTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: ShopFrequentWorkflow, settings: ShopFrequentSettings) -> None:
        if not isinstance(settings, ShopFrequentSettings):
            message = "settings must be ShopFrequentSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, ShopFrequentReport):
            message = "ShopFrequentWorkflow.execute() must return a ShopFrequentReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._settings.schedule.next_after(context.started_at)),),
        )


@dataclass(frozen=True, slots=True)
class ShopOnceSettings:
    plan: ShopOncePlan
    schedule: DailySchedule

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ShopOncePlan):
            message = "plan must be a ShopOncePlan"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ShopOnceReport:
    pass


class ShopOnceWorkflow(Protocol):
    def execute(self, settings: ShopOnceSettings, cancellation: CancellationSource) -> ShopOnceReport: ...


class ShopOnceTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: ShopOnceWorkflow, settings: ShopOnceSettings) -> None:
        if not isinstance(settings, ShopOnceSettings):
            message = "settings must be ShopOnceSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, ShopOnceReport):
            message = "ShopOnceWorkflow.execute() must return a ShopOnceReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._settings.schedule.next_after(context.started_at)),),
        )
