from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    DailySchedule,
    DelayRange,
    DelaySampler,
    DisableTask,
    ExecutionMode,
    RescheduleSelf,
    Retryable,
    RunMetadata,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.gameplay.composite import (
    DataKeyPlan,
    DormFeedPlan,
    DormReport,
    DormRunRequest,
    DormSettings,
    DormTask,
    DormWorkflow,
    FreebieCollectionReport,
    FreebiesSettings,
    FreebiesTask,
    GuildLogisticsPolicy,
    GuildOperationPolicy,
    GuildReport,
    GuildSettings,
    GuildTask,
    GuildWorkflow,
    MailCollectionPolicy,
    MeowfficerReport,
    MeowfficerSettings,
    MeowfficerTask,
    MeowfficerTrainingMode,
    MeowfficerTrainingSettings,
    MeowfficerWorkflow,
    PrivateQuartersInteractionStatus,
    PrivateQuartersReport,
    PrivateQuartersSettings,
    PrivateQuartersTask,
    PrivateQuartersWorkflow,
    RewardReport,
    RewardSettings,
    RewardTask,
    RewardWorkflow,
    SupplyPackPlan,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_OBSERVED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 14, 4, tzinfo=UTC)
_DAILY_SCHEDULE = DailySchedule("UTC", (time(4),))
_FIXED_FAILURE_RETRY = DelayRange(1_800, 1_800)


class _Workflow[SettingsT, ReportT]:
    def __init__(
        self,
        report: ReportT,
        *,
        call_log: list[str] | None = None,
        name: str = "workflow",
        on_execute: Callable[[], None] | None = None,
    ) -> None:
        self._report = report
        self._call_log = call_log
        self._name = name
        self._on_execute = on_execute
        self.calls = 0
        self.received_settings: SettingsT | None = None

    def execute(self, settings: SettingsT, cancellation: CancellationSource) -> ReportT:
        cancellation.raise_if_requested()
        self.calls += 1
        self.received_settings = settings
        if self._call_log is not None:
            self._call_log.append(self._name)
        if self._on_execute is not None:
            self._on_execute()
        return self._report


@dataclass(slots=True)
class _Collector:
    name: str
    call_log: list[str]
    report: object = FreebieCollectionReport(changed=True, observed_at=_OBSERVED_AT)
    on_collect: Callable[[], None] | None = None

    def _collect(self, cancellation: CancellationSource) -> FreebieCollectionReport:
        cancellation.raise_if_requested()
        self.call_log.append(self.name)
        if self.on_collect is not None:
            self.on_collect()
        return cast("FreebieCollectionReport", self.report)


class _FreebieCollector(_Collector):
    def collect(self, cancellation: CancellationSource) -> FreebieCollectionReport:
        return self._collect(cancellation)


class _MailCollector(_Collector):
    def collect(
        self,
        policy: MailCollectionPolicy,
        cancellation: CancellationSource,
    ) -> FreebieCollectionReport:
        if not isinstance(policy, MailCollectionPolicy):
            raise TypeError
        return self._collect(cancellation)


class _DataKeyCollector(_Collector):
    def collect(
        self,
        plan: DataKeyPlan,
        cancellation: CancellationSource,
    ) -> FreebieCollectionReport:
        if not isinstance(plan, DataKeyPlan):
            raise TypeError
        return self._collect(cancellation)


class _SupplyPackCollector(_Collector):
    def collect(
        self,
        plan: SupplyPackPlan,
        cancellation: CancellationSource,
    ) -> FreebieCollectionReport:
        if not isinstance(plan, SupplyPackPlan):
            raise TypeError
        return self._collect(cancellation)


def _context(task_id: str, abort: AbortToken | None = None) -> TaskContext:
    return TaskContext(
        task_id=TaskId(task_id),
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def _request_abort(abort: AbortToken, reason: str) -> None:
    abort.request(reason)


def _dorm_settings(*, enabled: bool = True) -> DormSettings:
    return DormSettings(
        feed=DormFeedPlan("20000 > 10000") if enabled else None,
        collect_enabled=False,
        furniture=None,
        fallback_delay=DelayRange(2_700, 2_700),
    )


def _training(delay: timedelta = timedelta(minutes=180)) -> MeowfficerTrainingSettings:
    return MeowfficerTrainingSettings(mode=MeowfficerTrainingMode.SEAMLESSLY, check_delay=delay)


def _meowfficer_settings(
    *,
    training: MeowfficerTrainingSettings | None = None,
    buy_amount: int = 1,
    schedule: DailySchedule = _DAILY_SCHEDULE,
) -> MeowfficerSettings:
    return MeowfficerSettings(
        buy_amount=buy_amount,
        overflow_coin_threshold=None,
        fort_chore_enabled=False,
        training=training,
        schedule=schedule,
    )


def _guild_settings(
    *,
    logistics_enabled: bool = True,
    operation_enabled: bool = True,
    failure_retry_delay: DelayRange = _FIXED_FAILURE_RETRY,
    schedule: DailySchedule = _DAILY_SCHEDULE,
) -> GuildSettings:
    return GuildSettings(
        logistics=(
            GuildLogisticsPolicy(select_new_mission=False, exchange_filter="Coin > Oil") if logistics_enabled else None
        ),
        operation=(
            GuildOperationPolicy(
                select_new_operation=False,
                new_operation_max_date=15,
                join_threshold=1.0,
                attack_boss=True,
                boss_fleet_recommend=False,
            )
            if operation_enabled
            else None
        ),
        failure_retry_delay=failure_retry_delay,
        schedule=schedule,
    )


def _reward_settings() -> RewardSettings:
    return RewardSettings(
        collect_oil=True,
        collect_coin=True,
        collect_exp=True,
        collect_daily_mission=True,
        collect_weekly_mission=True,
        success_delay=DelayRange(3_600, 3_600),
    )


def _freebies_settings(
    *,
    battle_pass: bool = True,
    data_key: bool = True,
    supply_pack: bool = True,
) -> FreebiesSettings:
    return FreebiesSettings(
        collect_battle_pass=battle_pass,
        data_key=DataKeyPlan(force_collect=False) if data_key else None,
        mail=MailCollectionPolicy(
            claim_merit=True,
            claim_maintenance=False,
            claim_trade_license=False,
            delete_collected=True,
        ),
        supply_pack=SupplyPackPlan(collect=supply_pack, day_of_week=0),
        schedule=_DAILY_SCHEDULE,
    )


def _private_quarters_settings(
    *,
    buy_roses: bool = True,
    buy_cake: bool = False,
    target_ship: str | None = "anchorage",
) -> PrivateQuartersSettings:
    return PrivateQuartersSettings(
        buy_roses=buy_roses,
        buy_cake=buy_cake,
        target_ship=target_ship,
        schedule=_DAILY_SCHEDULE,
    )


def test_dorm_without_enabled_work_disables_itself_without_opening_ui() -> None:
    workflow = _Workflow(_dorm_report())

    result = DormTask(cast("DormWorkflow", workflow), _dorm_settings(enabled=False)).run(_context("dorm"))

    assert workflow.calls == 0
    assert result == TaskResult(outcome=Succeeded(), effects=(DisableTask(TaskId("dorm")),))


def _dorm_report(*, ships_in_dorm: int | None = 3) -> DormReport:
    return DormReport(
        observed_at=_OBSERVED_AT,
        ships_in_dorm=ships_in_dorm,
        furniture_checked=False,
    )


@pytest.mark.parametrize(
    ("ships_in_dorm", "delay"),
    [
        (1, timedelta(minutes=1000)),
        (6, timedelta(minutes=278)),
        (None, timedelta(minutes=45)),
    ],
)
def test_dorm_preserves_ship_count_dependent_schedule(
    ships_in_dorm: int | None,
    delay: timedelta,
) -> None:
    settings = _dorm_settings()
    workflow = _Workflow(_dorm_report(ships_in_dorm=ships_in_dorm))

    result = DormTask(cast("DormWorkflow", workflow), settings).run(_context("dorm"))

    request = cast("DormRunRequest", workflow.received_settings)
    assert request.settings is settings
    assert not request.furniture_due
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_OBSERVED_AT + delay),),
    )


@pytest.mark.parametrize(
    ("schedule", "expected_due_at"),
    [
        (_DAILY_SCHEDULE, _OBSERVED_AT + timedelta(minutes=180)),
        (DailySchedule("UTC", (time(13),)), _OBSERVED_AT + timedelta(hours=1)),
    ],
)
def test_meowfficer_training_uses_earlier_periodic_check_or_server_update(
    schedule: DailySchedule,
    expected_due_at: datetime,
) -> None:
    settings = _meowfficer_settings(training=_training(), schedule=schedule)
    workflow = _Workflow(MeowfficerReport(_OBSERVED_AT, training_active=True))

    result = MeowfficerTask(workflow, settings).run(_context("meowfficer"))

    assert workflow.received_settings is settings
    assert result == TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(expected_due_at),))


@pytest.mark.parametrize(
    ("schedule", "expected_due_at"),
    [
        (_DAILY_SCHEDULE, _OBSERVED_AT + timedelta(minutes=30)),
        (DailySchedule("UTC", (time(12, 10),)), _OBSERVED_AT + timedelta(minutes=10)),
    ],
)
def test_guild_failure_uses_earlier_failure_retry_or_server_update(
    schedule: DailySchedule,
    expected_due_at: datetime,
) -> None:
    settings = _guild_settings(schedule=schedule)
    report = GuildReport(observed_at=_OBSERVED_AT, logistics_succeeded=True, operation_succeeded=False)

    result = GuildTask(_Workflow(report), settings).run(_context("guild"))

    assert result == TaskResult(
        outcome=Retryable("guild logistics or operation did not complete"),
        effects=(RescheduleSelf(expected_due_at),),
    )


def test_reward_samples_success_interval_for_each_reschedule() -> None:
    settings = RewardSettings(
        collect_oil=True,
        collect_coin=True,
        collect_exp=True,
        collect_daily_mission=True,
        collect_weekly_mission=True,
        success_delay=DelayRange(lower_seconds=3_600, upper_seconds=7_200),
    )
    workflow = _Workflow(RewardReport(_OBSERVED_AT))
    draws = iter((3_600, 3_600, 7_200, 7_200, 7_200, 7_200))
    sampler = DelaySampler(randint=lambda _lower, _upper: next(draws))
    task = RewardTask(workflow, settings, delay_sampler=sampler)

    first = task.run(_context("reward"))
    second = task.run(_context("reward"))

    assert first.effects == (RescheduleSelf(_OBSERVED_AT + timedelta(seconds=4_800)),)
    assert second.effects == (RescheduleSelf(_OBSERVED_AT + timedelta(seconds=7_200)),)


def test_freebies_always_collects_mail_and_skips_disabled_optional_collectors() -> None:
    call_log: list[str] = []
    task = FreebiesTask(
        battle_pass=_FreebieCollector("battle_pass", call_log),
        data_key=_DataKeyCollector("data_key", call_log),
        mail=_MailCollector("mail", call_log),
        supply_pack=_SupplyPackCollector("supply_pack", call_log),
        settings=_freebies_settings(battle_pass=False, data_key=False, supply_pack=False),
    )

    task.run(_context("freebies"))

    assert call_log == ["mail"]


def test_private_quarters_completed_interaction_waits_for_server_update() -> None:
    settings = _private_quarters_settings()
    report = PrivateQuartersReport(
        observed_at=_OBSERVED_AT,
        shop_attempted=True,
        interaction_status=PrivateQuartersInteractionStatus.COMPLETED,
    )
    workflow = _Workflow(report)

    result = PrivateQuartersTask(workflow, settings).run(_context("private_quarters"))

    assert workflow.received_settings is settings
    assert result == TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(_SERVER_UPDATE_AT),))


def test_freebies_abort_between_collectors_stops_remaining_work_and_discards_schedule() -> None:
    abort = AbortToken()
    call_log: list[str] = []
    task = FreebiesTask(
        battle_pass=_FreebieCollector(
            "battle_pass",
            call_log,
            on_collect=lambda: _request_abort(abort, "stop after battle pass"),
        ),
        data_key=_DataKeyCollector("data_key", call_log),
        mail=_MailCollector("mail", call_log),
        supply_pack=_SupplyPackCollector("supply_pack", call_log),
        settings=_freebies_settings(),
    )

    with pytest.raises(AbortRequested, match="stop after battle pass"):
        task.run(_context("freebies", abort))

    assert call_log == ["battle_pass"]


@pytest.mark.parametrize(
    ("task_name", "build_task", "report", "due_at"),
    [
        (
            "dorm",
            lambda workflow: DormTask(cast("DormWorkflow", workflow), _dorm_settings()),
            _dorm_report(),
            _OBSERVED_AT + timedelta(minutes=417),
        ),
        (
            "meowfficer",
            lambda workflow: MeowfficerTask(cast("MeowfficerWorkflow", workflow), _meowfficer_settings()),
            MeowfficerReport(_OBSERVED_AT, training_active=False),
            _SERVER_UPDATE_AT,
        ),
        (
            "guild",
            lambda workflow: GuildTask(cast("GuildWorkflow", workflow), _guild_settings()),
            GuildReport(observed_at=_OBSERVED_AT, logistics_succeeded=True, operation_succeeded=True),
            _SERVER_UPDATE_AT,
        ),
        (
            "reward",
            lambda workflow: RewardTask(cast("RewardWorkflow", workflow), _reward_settings()),
            RewardReport(_OBSERVED_AT),
            _OBSERVED_AT + timedelta(hours=1),
        ),
        (
            "private_quarters",
            lambda workflow: PrivateQuartersTask(
                cast("PrivateQuartersWorkflow", workflow),
                _private_quarters_settings(),
            ),
            PrivateQuartersReport(
                observed_at=_OBSERVED_AT,
                shop_attempted=True,
                interaction_status=PrivateQuartersInteractionStatus.COMPLETED,
            ),
            _SERVER_UPDATE_AT,
        ),
    ],
)
def test_composite_workflow_late_abort_preserves_schedule_and_stops_the_next_entry(
    task_name: str,
    build_task: Callable[[_Workflow[object, object]], Task],
    report: object,
    due_at: datetime,
) -> None:
    abort = AbortToken()
    workflow = _Workflow[object, object](
        report,
        on_execute=lambda: _request_abort(abort, "stop after workflow"),
    )
    task = build_task(workflow)
    context = _context(task_name, abort)

    assert task.run(context) == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(due_at),),
    )

    with pytest.raises(AbortRequested, match="stop after workflow"):
        task.run(context)
    assert workflow.calls == 1
