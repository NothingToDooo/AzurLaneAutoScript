from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, Protocol, cast

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    DailySchedule,
    DisableTask,
    ExecutionMode,
    RescheduleSelf,
    RunMetadata,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.gameplay.market import (
    AwakenAttempt,
    AwakenLevelCap,
    AwakenPlan,
    AwakenReport,
    AwakenRunResult,
    AwakenSettings,
    AwakenTask,
    CoreShopPlan,
    GachaPlan,
    GachaPool,
    GachaReport,
    GachaSettings,
    GachaTask,
    GeneralShopPlan,
    GuildShopPlan,
    MedalShopPlan,
    MeritShopPlan,
    ShipyardPlan,
    ShipyardPurchasePlan,
    ShipyardReport,
    ShipyardSettings,
    ShipyardTask,
    ShopFrequentReport,
    ShopFrequentSettings,
    ShopFrequentTask,
    ShopOncePlan,
    ShopOnceReport,
    ShopOnceSettings,
    ShopOnceTask,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_NEXT_SERVER_UPDATE_AT = datetime(2026, 7, 14, 4, tzinfo=UTC)
_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(12),))


class _RecordedWorkflow(Protocol):
    execute_calls: int
    received_settings: list[object]


class _Workflow[T]:
    def __init__(
        self,
        report: T,
        *,
        after_execute: Callable[[], None] | None = None,
    ) -> None:
        self._report = report
        self._after_execute = after_execute
        self.execute_calls = 0
        self.received_settings: list[object] = []

    def execute(self, settings: object, cancellation: CancellationSource) -> T:
        cancellation.raise_if_requested()
        self.execute_calls += 1
        self.received_settings.append(settings)
        if self._after_execute is not None:
            self._after_execute()
        return self._report


def _context(task_id: str, abort: AbortToken | None = None) -> TaskContext:
    return TaskContext(
        task_id=TaskId(task_id),
        started_at=datetime(2026, 7, 13, 4, tzinfo=UTC),
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def _awaken_settings(level_cap: AwakenLevelCap = AwakenLevelCap.LEVEL_120) -> AwakenSettings:
    return AwakenSettings(
        plan=AwakenPlan(level_cap=level_cap, favourite_only=False),
        schedule=_SCHEDULE,
    )


def _shipyard_settings(*, pr_buy_amount: int, dr_buy_amount: int) -> ShipyardSettings:
    return ShipyardSettings(
        plan=ShipyardPlan(
            pr=ShipyardPurchasePlan(research_series=1, ship_index=0, buy_amount=pr_buy_amount),
            dr=ShipyardPurchasePlan(research_series=2, ship_index=0, buy_amount=dr_buy_amount),
        ),
        schedule=_SCHEDULE,
    )


def _gacha_settings() -> GachaSettings:
    return GachaSettings(
        plan=GachaPlan(
            pool=GachaPool.LIGHT,
            amount=1,
            use_ticket=True,
            use_drill=False,
        ),
        schedule=_SCHEDULE,
    )


def _shop_frequent_settings(*, schedule: DailySchedule = _SCHEDULE) -> ShopFrequentSettings:
    return ShopFrequentSettings(
        plan=GeneralShopPlan(
            filter="Cube",
            refresh=False,
            use_gems=False,
            consume_coins=False,
            buy_skin_box=False,
        ),
        schedule=schedule,
    )


def _shop_once_settings(*, schedule: DailySchedule = _SCHEDULE) -> ShopOnceSettings:
    return ShopOnceSettings(
        plan=ShopOncePlan(
            merit=MeritShopPlan(filter="Cube", refresh=False),
            guild=GuildShopPlan(
                filter="PlateT4",
                refresh=True,
                box_t3="ironblood",
                box_t4="ironblood",
                book_t2="red",
                book_t3="red",
                retrofit_t2="cl",
                retrofit_t3="cl",
                plate_t2="general",
                plate_t3="general",
                plate_t4="gun",
                pr1="neptune",
                pr2="seattle",
                pr3="cheshire",
            ),
            core=CoreShopPlan(filter="Array"),
            medal=MedalShopPlan(
                filter="DR > PR",
                retrofit_t1="cl",
                retrofit_t2="cl",
                retrofit_t3="cl",
                plate_t1="general",
                plate_t2="general",
                plate_t3="general",
            ),
        ),
        schedule=schedule,
    )


def _build_task(
    task_name: str,
    *,
    after_execute: Callable[[], None] | None = None,
) -> tuple[Task, _RecordedWorkflow]:
    if task_name == "awaken":
        workflow = _Workflow(
            AwakenReport(
                attempts=(AwakenAttempt(AwakenLevelCap.LEVEL_120, AwakenRunResult.FINISHED),),
            ),
            after_execute=after_execute,
        )
        return AwakenTask(workflow, _awaken_settings()), workflow
    if task_name == "shipyard":
        workflow = _Workflow(ShipyardReport(pr_processed=True, dr_processed=False), after_execute=after_execute)
        return ShipyardTask(workflow, _shipyard_settings(pr_buy_amount=1, dr_buy_amount=0)), workflow
    if task_name == "gacha":
        workflow = _Workflow(GachaReport(submitted=True), after_execute=after_execute)
        return GachaTask(workflow, _gacha_settings()), workflow
    if task_name == "shop_frequent":
        workflow = _Workflow(ShopFrequentReport(), after_execute=after_execute)
        return (
            ShopFrequentTask(workflow, _shop_frequent_settings()),
            workflow,
        )
    if task_name == "shop_once":
        workflow = _Workflow(ShopOnceReport(), after_execute=after_execute)
        return ShopOnceTask(workflow, _shop_once_settings()), workflow
    raise AssertionError(task_name)


def test_awaken_level125_runs_level120_after_non_timeout_and_reschedules_to_server_update() -> None:
    report = AwakenReport(
        attempts=(
            AwakenAttempt(AwakenLevelCap.LEVEL_125, AwakenRunResult.INSUFFICIENT),
            AwakenAttempt(AwakenLevelCap.LEVEL_120, AwakenRunResult.FINISHED),
        )
    )
    workflow = _Workflow(report)

    result = AwakenTask(workflow, _awaken_settings(AwakenLevelCap.LEVEL_125)).run(_context("awaken"))

    assert workflow.execute_calls == 1
    assert workflow.received_settings == [_awaken_settings(AwakenLevelCap.LEVEL_125)]
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_NEXT_SERVER_UPDATE_AT),),
    )


def test_awaken_level125_timeout_skips_level120_but_keeps_server_update_schedule() -> None:
    report = AwakenReport(
        attempts=(AwakenAttempt(AwakenLevelCap.LEVEL_125, AwakenRunResult.TIMED_OUT),),
    )
    workflow = _Workflow(report)

    result = AwakenTask(workflow, _awaken_settings(AwakenLevelCap.LEVEL_125)).run(_context("awaken"))

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_NEXT_SERVER_UPDATE_AT),),
    )


def test_awaken_rejects_report_that_does_not_match_configured_level_cap() -> None:
    workflow = _Workflow(
        AwakenReport(
            attempts=(AwakenAttempt(AwakenLevelCap.LEVEL_125, AwakenRunResult.TIMED_OUT),),
        )
    )

    with pytest.raises(ValueError, match="level120 awaken plan"):
        AwakenTask(workflow, _awaken_settings()).run(_context("awaken"))


def test_awaken_level125_requires_level120_after_non_timeout() -> None:
    workflow = _Workflow(
        AwakenReport(
            attempts=(AwakenAttempt(AwakenLevelCap.LEVEL_125, AwakenRunResult.FINISHED),),
        )
    )

    with pytest.raises(ValueError, match="skip level120 only after a timeout"):
        AwakenTask(workflow, _awaken_settings(AwakenLevelCap.LEVEL_125)).run(_context("awaken"))


def test_shipyard_without_any_purchase_disables_itself_without_opening_workflow() -> None:
    workflow = _Workflow(ShipyardReport(pr_processed=False, dr_processed=False))

    result = ShipyardTask(workflow, _shipyard_settings(pr_buy_amount=0, dr_buy_amount=0)).run(_context("shipyard"))

    assert workflow.execute_calls == 0
    assert workflow.received_settings == []
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(DisableTask(TaskId("shipyard")),),
    )


def test_shipyard_with_any_purchase_runs_and_reschedules_to_server_update() -> None:
    workflow = _Workflow(ShipyardReport(pr_processed=False, dr_processed=True))

    result = ShipyardTask(workflow, _shipyard_settings(pr_buy_amount=0, dr_buy_amount=2)).run(_context("shipyard"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_NEXT_SERVER_UPDATE_AT),),
    )


def test_gacha_without_submitted_order_is_still_a_completed_daily_check() -> None:
    workflow = _Workflow(GachaReport(submitted=False))

    result = GachaTask(workflow, _gacha_settings()).run(_context("gacha"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_NEXT_SERVER_UPDATE_AT),),
    )


def test_shop_frequent_reschedules_to_its_server_update() -> None:
    workflow = _Workflow(ShopFrequentReport())

    result = ShopFrequentTask(workflow, _shop_frequent_settings()).run(_context("shop_frequent"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_NEXT_SERVER_UPDATE_AT),),
    )


def test_shop_once_reschedules_instead_of_disabling_itself() -> None:
    workflow = _Workflow(ShopOnceReport())

    result = ShopOnceTask(workflow, _shop_once_settings()).run(_context("shop_once"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_NEXT_SERVER_UPDATE_AT),),
    )


@pytest.mark.parametrize("task_name", ["awaken", "shipyard", "gacha", "shop_frequent", "shop_once"])
def test_market_abort_before_run_prevents_external_side_effects(task_name: str) -> None:
    abort = AbortToken()
    abort.request("manual stop")
    task, workflow = _build_task(task_name)

    with pytest.raises(AbortRequested, match="manual stop"):
        task.run(_context(task_name, abort))

    assert workflow.execute_calls == 0


@pytest.mark.parametrize("task_name", ["awaken", "shipyard", "gacha", "shop_frequent", "shop_once"])
def test_market_abort_after_workflow_discards_schedule_result(task_name: str) -> None:
    abort = AbortToken()

    def request_abort() -> None:
        abort.request("stop after workflow")

    task, workflow = _build_task(task_name, after_execute=request_abort)

    with pytest.raises(AbortRequested, match="stop after workflow"):
        task.run(_context(task_name, abort))

    assert workflow.execute_calls == 1


def test_market_tasks_reject_invalid_port_outputs() -> None:
    invalid = object()
    cases: tuple[tuple[Task, str, str], ...] = (
        (
            AwakenTask(_Workflow(cast("AwakenReport", invalid)), _awaken_settings()),
            "awaken",
            "AwakenWorkflow.execute",
        ),
        (
            ShipyardTask(
                _Workflow(cast("ShipyardReport", invalid)),
                _shipyard_settings(pr_buy_amount=1, dr_buy_amount=0),
            ),
            "shipyard",
            "ShipyardWorkflow.execute",
        ),
        (
            GachaTask(_Workflow(cast("GachaReport", invalid)), _gacha_settings()),
            "gacha",
            "GachaWorkflow.execute",
        ),
        (
            ShopFrequentTask(
                _Workflow(cast("ShopFrequentReport", invalid)),
                _shop_frequent_settings(),
            ),
            "shop_frequent",
            "ShopFrequentWorkflow.execute",
        ),
        (
            ShopOnceTask(
                _Workflow(cast("ShopOnceReport", invalid)),
                _shop_once_settings(),
            ),
            "shop_once",
            "ShopOnceWorkflow.execute",
        ),
    )

    for task, task_name, contract in cases:
        with pytest.raises(TypeError, match=contract):
            task.run(_context(task_name))


def test_market_settings_require_a_daily_schedule() -> None:
    invalid = cast("DailySchedule", object())

    with pytest.raises(TypeError, match="DailySchedule"):
        AwakenSettings(AwakenPlan(AwakenLevelCap.LEVEL_120, favourite_only=False), invalid)
    with pytest.raises(TypeError, match="DailySchedule"):
        ShipyardSettings(_shipyard_settings(pr_buy_amount=1, dr_buy_amount=1).plan, invalid)
    with pytest.raises(TypeError, match="DailySchedule"):
        GachaSettings(_gacha_settings().plan, invalid)
    with pytest.raises(TypeError, match="DailySchedule"):
        _shop_frequent_settings(schedule=invalid)
    with pytest.raises(TypeError, match="DailySchedule"):
        _shop_once_settings(schedule=invalid)


def test_market_settings_and_reports_reject_invalid_values() -> None:
    with pytest.raises(TypeError, match="AwakenLevelCap"):
        AwakenPlan(cast("AwakenLevelCap", "level120"), favourite_only=False)
    with pytest.raises(TypeError, match="must be a bool"):
        AwakenPlan(AwakenLevelCap.LEVEL_120, cast("bool", 1))
    with pytest.raises(ValueError, match="one or two"):
        AwakenReport(())
    with pytest.raises(ValueError, match="non-timeout level125"):
        AwakenReport(
            (
                AwakenAttempt(AwakenLevelCap.LEVEL_125, AwakenRunResult.TIMED_OUT),
                AwakenAttempt(AwakenLevelCap.LEVEL_120, AwakenRunResult.FINISHED),
            )
        )
    with pytest.raises(ValueError, match="must be positive"):
        ShipyardPurchasePlan(research_series=0, ship_index=0, buy_amount=1)
    with pytest.raises(ValueError, match="must be non-negative"):
        ShipyardPurchasePlan(research_series=1, ship_index=-1, buy_amount=1)
    with pytest.raises(ValueError, match="must be non-negative"):
        ShipyardPurchasePlan(research_series=1, ship_index=0, buy_amount=-1)
    with pytest.raises(TypeError, match="must be a bool"):
        ShipyardReport(pr_processed=cast("bool", 1), dr_processed=False)
    with pytest.raises(TypeError, match="GachaPool"):
        GachaPlan(
            cast("GachaPool", "light"),
            1,
            use_ticket=True,
            use_drill=False,
        )
    with pytest.raises(ValueError, match="must be positive"):
        GachaPlan(GachaPool.LIGHT, 0, use_ticket=True, use_drill=False)
    with pytest.raises(TypeError, match="must be a bool"):
        GachaReport(submitted=cast("bool", 1))


def test_market_schedule_type_error_is_explicit() -> None:
    with pytest.raises(TypeError, match="DailySchedule"):
        _shop_once_settings(schedule=cast("DailySchedule", "tomorrow"))
