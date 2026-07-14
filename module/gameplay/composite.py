from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, override

from module.application import (
    DailySchedule,
    DelayRange,
    DelaySampler,
    DisableTask,
    RescheduleSelf,
    Retryable,
    Succeeded,
    Task,
    TaskContext,
    TaskResult,
    UpsertTaskState,
    runtime_delay_sampler,
)

if TYPE_CHECKING:
    from module.interaction import CancellationSignal


_GUILD_INCOMPLETE_REASON = "guild logistics or operation did not complete"
_MIN_TRAINING_CHECK_DELAY = timedelta(minutes=150)
_MAX_TRAINING_CHECK_DELAY = timedelta(minutes=210)
_DORM_SHIP_DELAYS = (
    timedelta(minutes=1000),
    timedelta(minutes=556),
    timedelta(minutes=417),
    timedelta(minutes=358),
    timedelta(minutes=313),
    timedelta(minutes=278),
)
DORM_FURNITURE_CHECK_KEY = "furniture_check"
DORM_FURNITURE_CHECK_SCHEMA_VERSION = 1


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


def _validate_bool(*, value: bool, field_name: str) -> None:
    if type(value) is not bool:
        message = f"{field_name} must be a bool"
        raise TypeError(message)


def _validate_non_negative_int(value: int, *, field_name: str) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if value < 0:
        message = f"{field_name} must be non-negative"
        raise ValueError(message)


def _validate_optional_text(value: str | None, *, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        message = f"{field_name} must be a string or None"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty when provided"
        raise ValueError(message)


class FurnitureBuyOption(StrEnum):
    SET = "set"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class DormFeedPlan:
    filter: str | None

    def __post_init__(self) -> None:
        _validate_optional_text(self.filter, field_name="filter")


@dataclass(frozen=True, slots=True)
class DormFurniturePlan:
    buy_option: FurnitureBuyOption
    check_interval: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.buy_option, FurnitureBuyOption):
            message = "buy_option must be a FurnitureBuyOption"
            raise TypeError(message)
        _validate_positive_duration(self.check_interval, field_name="check_interval")


@dataclass(frozen=True, slots=True)
class DormSettings:
    feed: DormFeedPlan | None
    collect_enabled: bool
    furniture: DormFurniturePlan | None
    fallback_delay: DelayRange

    def __post_init__(self) -> None:
        if self.feed is not None and not isinstance(self.feed, DormFeedPlan):
            message = "feed must be a DormFeedPlan or None"
            raise TypeError(message)
        _validate_bool(value=self.collect_enabled, field_name="collect_enabled")
        if self.furniture is not None and not isinstance(self.furniture, DormFurniturePlan):
            message = "furniture must be a DormFurniturePlan or None"
            raise TypeError(message)
        if not isinstance(self.fallback_delay, DelayRange):
            message = "fallback_delay must be a DelayRange"
            raise TypeError(message)

    @property
    def has_work(self) -> bool:
        return self.feed is not None or self.collect_enabled or self.furniture is not None


@dataclass(frozen=True, slots=True)
class DormRunRequest:
    settings: DormSettings
    furniture_due: bool

    def __post_init__(self) -> None:
        if not isinstance(self.settings, DormSettings):
            message = "settings must be DormSettings"
            raise TypeError(message)
        _validate_bool(value=self.furniture_due, field_name="furniture_due")
        if self.furniture_due and self.settings.furniture is None:
            message = "furniture_due requires a furniture plan"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class DormReport:
    observed_at: datetime
    ships_in_dorm: int | None
    furniture_checked: bool

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.observed_at, field_name="observed_at")
        _validate_bool(value=self.furniture_checked, field_name="furniture_checked")
        if self.ships_in_dorm is None:
            return
        if type(self.ships_in_dorm) is not int:
            message = "ships_in_dorm must be an integer or None"
            raise TypeError(message)
        if not 1 <= self.ships_in_dorm <= 6:
            message = "ships_in_dorm must be between one and six"
            raise ValueError(message)


class DormWorkflow(Protocol):
    def execute(self, request: DormRunRequest, cancellation: CancellationSignal) -> DormReport: ...


class DormTask(Task):
    __slots__ = ("_delay_sampler", "_last_furniture_check_at", "_settings", "_workflow")

    def __init__(
        self,
        workflow: DormWorkflow,
        settings: DormSettings,
        *,
        delay_sampler: DelaySampler = runtime_delay_sampler,
        last_furniture_check_at: datetime | None = None,
    ) -> None:
        if not isinstance(settings, DormSettings):
            message = "settings must be DormSettings"
            raise TypeError(message)
        if last_furniture_check_at is not None:
            _validate_aware_datetime(last_furniture_check_at, field_name="last_furniture_check_at")
        if not isinstance(delay_sampler, DelaySampler):
            message = "delay_sampler must be a DelaySampler"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings
        self._delay_sampler = delay_sampler
        self._last_furniture_check_at = last_furniture_check_at

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        if not self._settings.has_work:
            return TaskResult(outcome=Succeeded(), effects=(DisableTask(context.task_id),))

        furniture_due = self._furniture_due(context.started_at)
        furniture_plan = self._settings.furniture
        if self._settings.feed is None and not self._settings.collect_enabled and not furniture_due:
            if furniture_plan is None or self._last_furniture_check_at is None:
                message = "dorm furniture state is inconsistent"
                raise RuntimeError(message)
            return TaskResult(
                outcome=Succeeded(),
                effects=(RescheduleSelf(self._last_furniture_check_at + furniture_plan.check_interval),),
            )

        request = DormRunRequest(settings=self._settings, furniture_due=furniture_due)
        report = self._workflow.execute(request, context.abort)
        if not isinstance(report, DormReport):
            message = "DormWorkflow.execute() must return a DormReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        if report.furniture_checked is not furniture_due:
            message = "DormReport.furniture_checked must match the requested furniture check"
            raise ValueError(message)

        if report.ships_in_dorm is None:
            delay = self._delay_sampler.sample(self._settings.fallback_delay)
        else:
            delay = _DORM_SHIP_DELAYS[report.ships_in_dorm - 1]
        due_at = report.observed_at + delay
        state_effects: tuple[UpsertTaskState, ...] = ()
        if furniture_plan is not None:
            checked_at = report.observed_at if report.furniture_checked else self._last_furniture_check_at
            if checked_at is None:
                message = "dorm furniture check did not produce a checkpoint"
                raise RuntimeError(message)
            due_at = min(due_at, checked_at + furniture_plan.check_interval)
            if report.furniture_checked:
                state_effects = (
                    UpsertTaskState(
                        context.task_id.value,
                        DORM_FURNITURE_CHECK_KEY,
                        DORM_FURNITURE_CHECK_SCHEMA_VERSION,
                        {"checked_at": checked_at.isoformat()},
                    ),
                )
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(due_at),),
            state_effects=state_effects,
        )

    def _furniture_due(self, now: datetime) -> bool:
        plan = self._settings.furniture
        if plan is None:
            return False
        last_check = self._last_furniture_check_at
        return last_check is None or now >= last_check + plan.check_interval


class MeowfficerTrainingMode(StrEnum):
    SEAMLESSLY = "seamlessly"
    ONCE_A_DAY = "once_a_day"


@dataclass(frozen=True, slots=True)
class MeowfficerTrainingSettings:
    mode: MeowfficerTrainingMode
    check_delay: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.mode, MeowfficerTrainingMode):
            message = "mode must be a MeowfficerTrainingMode"
            raise TypeError(message)
        _validate_positive_duration(self.check_delay, field_name="check_delay")
        if not _MIN_TRAINING_CHECK_DELAY <= self.check_delay <= _MAX_TRAINING_CHECK_DELAY:
            message = "check_delay must be between 150 and 210 minutes"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class MeowfficerSettings:
    buy_amount: int
    overflow_coin_threshold: int | None
    fort_chore_enabled: bool
    training: MeowfficerTrainingSettings | None
    schedule: DailySchedule

    def __post_init__(self) -> None:
        _validate_non_negative_int(self.buy_amount, field_name="buy_amount")
        if self.buy_amount > 15:
            message = "buy_amount must not exceed fifteen"
            raise ValueError(message)
        if self.overflow_coin_threshold is not None:
            _validate_non_negative_int(self.overflow_coin_threshold, field_name="overflow_coin_threshold")
        _validate_bool(value=self.fort_chore_enabled, field_name="fort_chore_enabled")
        if self.training is not None and not isinstance(self.training, MeowfficerTrainingSettings):
            message = "training must be MeowfficerTrainingSettings or None"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)

    @property
    def has_work(self) -> bool:
        return (
            self.buy_amount > 0
            or self.overflow_coin_threshold is not None
            or self.fort_chore_enabled
            or self.training is not None
        )


@dataclass(frozen=True, slots=True)
class MeowfficerReport:
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.observed_at, field_name="observed_at")


class MeowfficerWorkflow(Protocol):
    def execute(self, settings: MeowfficerSettings, cancellation: CancellationSignal) -> MeowfficerReport: ...


class MeowfficerTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: MeowfficerWorkflow, settings: MeowfficerSettings) -> None:
        if not isinstance(settings, MeowfficerSettings):
            message = "settings must be MeowfficerSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        if not self._settings.has_work:
            return TaskResult(outcome=Succeeded(), effects=(DisableTask(context.task_id),))

        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, MeowfficerReport):
            message = "MeowfficerWorkflow.execute() must return a MeowfficerReport"
            raise TypeError(message)
        context.abort.raise_if_requested()

        due_at = self._settings.schedule.next_after(report.observed_at)
        if self._settings.training is not None:
            due_at = min(due_at, report.observed_at + self._settings.training.check_delay)
        return TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(due_at),))


@dataclass(frozen=True, slots=True)
class GuildLogisticsPolicy:
    select_new_mission: bool
    exchange_filter: str | None

    def __post_init__(self) -> None:
        _validate_bool(value=self.select_new_mission, field_name="select_new_mission")
        _validate_optional_text(self.exchange_filter, field_name="exchange_filter")


@dataclass(frozen=True, slots=True)
class GuildOperationPolicy:
    select_new_operation: bool
    new_operation_max_date: int
    join_threshold: float
    attack_boss: bool
    boss_fleet_recommend: bool

    def __post_init__(self) -> None:
        _validate_bool(value=self.select_new_operation, field_name="select_new_operation")
        if type(self.new_operation_max_date) is not int:
            message = "new_operation_max_date must be an integer"
            raise TypeError(message)
        if not 1 <= self.new_operation_max_date <= 31:
            message = "new_operation_max_date must be between one and thirty-one"
            raise ValueError(message)
        if type(self.join_threshold) not in {int, float}:
            message = "join_threshold must be a number"
            raise TypeError(message)
        threshold = float(self.join_threshold)
        if not 0.0 <= threshold <= 1.0:
            message = "join_threshold must be between zero and one"
            raise ValueError(message)
        object.__setattr__(self, "join_threshold", threshold)
        _validate_bool(value=self.attack_boss, field_name="attack_boss")
        _validate_bool(value=self.boss_fleet_recommend, field_name="boss_fleet_recommend")


@dataclass(frozen=True, slots=True)
class GuildSettings:
    logistics: GuildLogisticsPolicy | None
    operation: GuildOperationPolicy | None
    failure_retry_delay: DelayRange
    schedule: DailySchedule

    def __post_init__(self) -> None:
        if self.logistics is not None and not isinstance(self.logistics, GuildLogisticsPolicy):
            message = "logistics must be a GuildLogisticsPolicy or None"
            raise TypeError(message)
        if self.operation is not None and not isinstance(self.operation, GuildOperationPolicy):
            message = "operation must be a GuildOperationPolicy or None"
            raise TypeError(message)
        if not isinstance(self.failure_retry_delay, DelayRange):
            message = "failure_retry_delay must be a DelayRange"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)

    @property
    def has_work(self) -> bool:
        return self.logistics is not None or self.operation is not None


@dataclass(frozen=True, slots=True)
class GuildReport:
    observed_at: datetime
    logistics_succeeded: bool | None
    operation_succeeded: bool | None

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.observed_at, field_name="observed_at")
        if self.logistics_succeeded is not None:
            _validate_bool(value=self.logistics_succeeded, field_name="logistics_succeeded")
        if self.operation_succeeded is not None:
            _validate_bool(value=self.operation_succeeded, field_name="operation_succeeded")


class GuildWorkflow(Protocol):
    def execute(self, settings: GuildSettings, cancellation: CancellationSignal) -> GuildReport: ...


class GuildTask(Task):
    __slots__ = ("_delay_sampler", "_settings", "_workflow")

    def __init__(
        self,
        workflow: GuildWorkflow,
        settings: GuildSettings,
        *,
        delay_sampler: DelaySampler = runtime_delay_sampler,
    ) -> None:
        if not isinstance(settings, GuildSettings):
            message = "settings must be GuildSettings"
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
        if not self._settings.has_work:
            return TaskResult(outcome=Succeeded(), effects=(DisableTask(context.task_id),))

        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, GuildReport):
            message = "GuildWorkflow.execute() must return a GuildReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        self._validate_report_shape(report)

        succeeded = report.logistics_succeeded is not False and report.operation_succeeded is not False
        next_server_update_at = self._settings.schedule.next_after(report.observed_at)
        if succeeded:
            return TaskResult(
                outcome=Succeeded(),
                effects=(RescheduleSelf(next_server_update_at),),
            )

        retry_at = min(
            report.observed_at + self._delay_sampler.sample(self._settings.failure_retry_delay),
            next_server_update_at,
        )
        return TaskResult(
            outcome=Retryable(_GUILD_INCOMPLETE_REASON),
            effects=(RescheduleSelf(retry_at),),
        )

    def _validate_report_shape(self, report: GuildReport) -> None:
        if (self._settings.logistics is not None) is not (report.logistics_succeeded is not None):
            message = "GuildReport.logistics_succeeded must be present exactly when logistics is enabled"
            raise ValueError(message)
        if (self._settings.operation is not None) is not (report.operation_succeeded is not None):
            message = "GuildReport.operation_succeeded must be present exactly when operation is enabled"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class RewardSettings:
    collect_oil: bool
    collect_coin: bool
    collect_exp: bool
    collect_daily_mission: bool
    collect_weekly_mission: bool
    success_delay: DelayRange

    def __post_init__(self) -> None:
        _validate_bool(value=self.collect_oil, field_name="collect_oil")
        _validate_bool(value=self.collect_coin, field_name="collect_coin")
        _validate_bool(value=self.collect_exp, field_name="collect_exp")
        _validate_bool(value=self.collect_daily_mission, field_name="collect_daily_mission")
        _validate_bool(value=self.collect_weekly_mission, field_name="collect_weekly_mission")
        if not isinstance(self.success_delay, DelayRange):
            message = "success_delay must be a DelayRange"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class RewardReport:
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.observed_at, field_name="observed_at")


class RewardWorkflow(Protocol):
    def execute(self, settings: RewardSettings, cancellation: CancellationSignal) -> RewardReport: ...


class RewardTask(Task):
    __slots__ = ("_delay_sampler", "_settings", "_workflow")

    def __init__(
        self,
        workflow: RewardWorkflow,
        settings: RewardSettings,
        *,
        delay_sampler: DelaySampler = runtime_delay_sampler,
    ) -> None:
        if not isinstance(settings, RewardSettings):
            message = "settings must be RewardSettings"
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
        if not isinstance(report, RewardReport):
            message = "RewardWorkflow.execute() must return a RewardReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(report.observed_at + self._delay_sampler.sample(self._settings.success_delay)),),
        )


@dataclass(frozen=True, slots=True)
class MailCollectionPolicy:
    claim_merit: bool
    claim_maintenance: bool
    claim_trade_license: bool
    delete_collected: bool

    def __post_init__(self) -> None:
        _validate_bool(value=self.claim_merit, field_name="claim_merit")
        _validate_bool(value=self.claim_maintenance, field_name="claim_maintenance")
        _validate_bool(value=self.claim_trade_license, field_name="claim_trade_license")
        _validate_bool(value=self.delete_collected, field_name="delete_collected")

    @property
    def has_claim_work(self) -> bool:
        return self.claim_merit or self.claim_maintenance or self.claim_trade_license


@dataclass(frozen=True, slots=True)
class DataKeyPlan:
    force_collect: bool

    def __post_init__(self) -> None:
        _validate_bool(value=self.force_collect, field_name="force_collect")


@dataclass(frozen=True, slots=True)
class SupplyPackPlan:
    collect: bool
    day_of_week: int

    def __post_init__(self) -> None:
        _validate_bool(value=self.collect, field_name="collect")
        if type(self.day_of_week) is not int:
            message = "day_of_week must be an integer"
            raise TypeError(message)
        if not 0 <= self.day_of_week <= 6:
            message = "day_of_week must be between zero and six"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class FreebiesSettings:
    collect_battle_pass: bool
    data_key: DataKeyPlan | None
    mail: MailCollectionPolicy
    supply_pack: SupplyPackPlan
    schedule: DailySchedule

    def __post_init__(self) -> None:
        _validate_bool(value=self.collect_battle_pass, field_name="collect_battle_pass")
        if self.data_key is not None and not isinstance(self.data_key, DataKeyPlan):
            message = "data_key must be a DataKeyPlan or None"
            raise TypeError(message)
        if not isinstance(self.mail, MailCollectionPolicy):
            message = "mail must be a MailCollectionPolicy"
            raise TypeError(message)
        if not isinstance(self.supply_pack, SupplyPackPlan):
            message = "supply_pack must be a SupplyPackPlan"
            raise TypeError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class FreebieCollectionReport:
    changed: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_bool(value=self.changed, field_name="changed")
        _validate_aware_datetime(self.observed_at, field_name="observed_at")


class FreebieCollectionWorkflow(Protocol):
    def collect(self, cancellation: CancellationSignal) -> FreebieCollectionReport: ...


class DataKeyWorkflow(Protocol):
    def collect(
        self,
        plan: DataKeyPlan,
        cancellation: CancellationSignal,
    ) -> FreebieCollectionReport: ...


class MailCollectionWorkflow(Protocol):
    def collect(
        self,
        policy: MailCollectionPolicy,
        cancellation: CancellationSignal,
    ) -> FreebieCollectionReport: ...


class SupplyPackWorkflow(Protocol):
    def collect(
        self,
        plan: SupplyPackPlan,
        cancellation: CancellationSignal,
    ) -> FreebieCollectionReport: ...


class FreebiesTask(Task):
    __slots__ = ("_battle_pass", "_data_key", "_mail", "_settings", "_supply_pack")

    def __init__(
        self,
        *,
        battle_pass: FreebieCollectionWorkflow,
        data_key: DataKeyWorkflow,
        mail: MailCollectionWorkflow,
        supply_pack: SupplyPackWorkflow,
        settings: FreebiesSettings,
    ) -> None:
        if not isinstance(settings, FreebiesSettings):
            message = "settings must be FreebiesSettings"
            raise TypeError(message)
        self._battle_pass = battle_pass
        self._data_key = data_key
        self._mail = mail
        self._supply_pack = supply_pack
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        last_report: FreebieCollectionReport | None = None
        if self._settings.collect_battle_pass:
            last_report = self._collect("battle_pass", self._battle_pass, context)
        data_key_plan = self._settings.data_key
        if data_key_plan is not None:
            context.abort.raise_if_requested()
            last_report = self._data_key.collect(data_key_plan, context.abort)
            self._validate_collection_report("data_key", last_report, context)

        context.abort.raise_if_requested()
        last_report = self._mail.collect(self._settings.mail, context.abort)
        self._validate_collection_report("mail", last_report, context)

        if self._settings.supply_pack.collect:
            context.abort.raise_if_requested()
            last_report = self._supply_pack.collect(self._settings.supply_pack, context.abort)
            self._validate_collection_report("supply_pack", last_report, context)
        if last_report.observed_at < context.started_at:
            message = "freebie observation must not precede the run start"
            raise ValueError(message)
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._settings.schedule.next_after(last_report.observed_at)),),
        )

    @staticmethod
    def _collect(
        capability: str,
        workflow: FreebieCollectionWorkflow,
        context: TaskContext,
    ) -> FreebieCollectionReport:
        context.abort.raise_if_requested()
        report = workflow.collect(context.abort)
        FreebiesTask._validate_collection_report(capability, report, context)
        return report

    @staticmethod
    def _validate_collection_report(
        capability: str,
        report: object,
        context: TaskContext,
    ) -> None:
        if not isinstance(report, FreebieCollectionReport):
            message = f"{capability}.collect() must return a FreebieCollectionReport"
            raise TypeError(message)
        context.abort.raise_if_requested()


class PrivateQuartersInteractionStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    UNSUPPORTED = "unsupported"
    EXHAUSTED = "exhausted"
    ROOM_UNAVAILABLE = "room_unavailable"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class PrivateQuartersSettings:
    buy_roses: bool
    buy_cake: bool
    target_ship: str | None
    schedule: DailySchedule

    def __post_init__(self) -> None:
        _validate_bool(value=self.buy_roses, field_name="buy_roses")
        _validate_bool(value=self.buy_cake, field_name="buy_cake")
        if self.target_ship is not None:
            if not isinstance(self.target_ship, str):
                message = "target_ship must be a string or None"
                raise TypeError(message)
            if not self.target_ship or self.target_ship != self.target_ship.strip():
                message = "target_ship must be a non-empty normalized identifier"
                raise ValueError(message)
        if not isinstance(self.schedule, DailySchedule):
            message = "schedule must be a DailySchedule"
            raise TypeError(message)

    @property
    def has_shop_work(self) -> bool:
        return self.buy_roses or self.buy_cake


@dataclass(frozen=True, slots=True)
class PrivateQuartersReport:
    observed_at: datetime
    shop_attempted: bool
    interaction_status: PrivateQuartersInteractionStatus

    def __post_init__(self) -> None:
        _validate_aware_datetime(self.observed_at, field_name="observed_at")
        _validate_bool(value=self.shop_attempted, field_name="shop_attempted")
        if not isinstance(self.interaction_status, PrivateQuartersInteractionStatus):
            message = "interaction_status must be a PrivateQuartersInteractionStatus"
            raise TypeError(message)


class PrivateQuartersWorkflow(Protocol):
    def execute(
        self,
        settings: PrivateQuartersSettings,
        cancellation: CancellationSignal,
    ) -> PrivateQuartersReport: ...


class PrivateQuartersTask(Task):
    __slots__ = ("_settings", "_workflow")

    def __init__(self, workflow: PrivateQuartersWorkflow, settings: PrivateQuartersSettings) -> None:
        if not isinstance(settings, PrivateQuartersSettings):
            message = "settings must be PrivateQuartersSettings"
            raise TypeError(message)
        self._workflow = workflow
        self._settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        context.abort.raise_if_requested()
        report = self._workflow.execute(self._settings, context.abort)
        if not isinstance(report, PrivateQuartersReport):
            message = "PrivateQuartersWorkflow.execute() must return a PrivateQuartersReport"
            raise TypeError(message)
        context.abort.raise_if_requested()
        self._validate_report_shape(report)
        if report.observed_at < context.started_at:
            message = "private-quarters observation must not precede the run start"
            raise ValueError(message)
        return TaskResult(
            outcome=Succeeded(),
            effects=(RescheduleSelf(self._settings.schedule.next_after(report.observed_at)),),
        )

    def _validate_report_shape(self, report: PrivateQuartersReport) -> None:
        if report.shop_attempted is not self._settings.has_shop_work:
            message = "PrivateQuartersReport.shop_attempted must match enabled shop work"
            raise ValueError(message)
        if self._settings.target_ship is None:
            if report.interaction_status is not PrivateQuartersInteractionStatus.NOT_REQUESTED:
                message = "interaction_status must be NOT_REQUESTED when no target ship is configured"
                raise ValueError(message)
            return
        if report.interaction_status is PrivateQuartersInteractionStatus.NOT_REQUESTED:
            message = "interaction_status must describe the requested interaction"
            raise ValueError(message)
