from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    DailySchedule,
    Deferred,
    ExecutionMode,
    PreemptionRequest,
    RescheduleSelf,
    RescheduleTask,
    Retryable,
    RunId,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.gameplay import (
    CommissionPreset,
    CommissionReport,
    CommissionSelectionPolicy,
    CommissionSettings,
    CommissionTask,
    ResearchReport,
    ResearchResourcePolicy,
    ResearchSelectionPolicy,
    ResearchSettings,
    ResearchTask,
    TacticalExperienceOverflowPolicy,
    TacticalRapidTrainingSlot,
    TacticalReport,
    TacticalSettings,
    TacticalStudentPolicy,
    TacticalTask,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.interaction import CancellationSignal


_OBSERVED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 14, 4, tzinfo=UTC)
_SERVER_UPDATE_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(12),))
_RESEARCH_SELECTION = ResearchSelectionPolicy(
    use_cube=ResearchResourcePolicy.ONLY_HALF_HOUR,
    use_coin=ResearchResourcePolicy.ALWAYS_USE,
    use_part=ResearchResourcePolicy.ALWAYS_USE,
    allow_delay=True,
    preset_filter="series_9_blueprint_only",
    custom_filter="Q > G > shortest",
)
_COMMISSION_SELECTION = CommissionSelectionPolicy(
    preset_filter=CommissionPreset.CUBE,
    custom_filter="DailyEvent > Gem-4 > shortest",
    do_major_commission=False,
)
_TACTICAL_OVERFLOW = TacticalExperienceOverflowPolicy(
    enabled=True,
    t1_allow=200,
    t2_allow=200,
    t3_allow=100,
    t4_allow=100,
)
_TACTICAL_STUDENT = TacticalStudentPolicy(enabled=False, favorite=False, minimum_level=50)


def _research_settings(schedule: DailySchedule = _SERVER_UPDATE_SCHEDULE) -> ResearchSettings:
    return ResearchSettings(schedule, _RESEARCH_SELECTION)


def _commission_settings(*, enabled: bool = False, delay: timedelta = timedelta(minutes=30)) -> CommissionSettings:
    return CommissionSettings(delay, enabled, _COMMISSION_SELECTION)


def _tactical_settings(delay: timedelta = timedelta(minutes=20)) -> TacticalSettings:
    return TacticalSettings(
        delay,
        _SERVER_UPDATE_SCHEDULE,
        "SameT4 > SameT3 > first",
        TacticalRapidTrainingSlot.DISABLED,
        _TACTICAL_OVERFLOW,
        _TACTICAL_STUDENT,
    )


class _ResearchWorkflow:
    def __init__(
        self,
        report: ResearchReport,
        *,
        on_execute: Callable[[], None] | None = None,
    ) -> None:
        self._report = report
        self._on_execute = on_execute
        self.execute_calls = 0
        self.settings: ResearchSettings | None = None

    def execute(self, settings: ResearchSettings, cancellation: CancellationSignal) -> ResearchReport:
        cancellation.raise_if_requested()
        self.settings = settings
        self.execute_calls += 1
        if self._on_execute is not None:
            self._on_execute()
        return self._report


class _CommissionWorkflow:
    def __init__(
        self,
        report: CommissionReport,
        *,
        on_execute: Callable[[], None] | None = None,
    ) -> None:
        self._report = report
        self._on_execute = on_execute
        self.execute_calls = 0
        self.settings: CommissionSettings | None = None

    def execute(self, settings: CommissionSettings, cancellation: CancellationSignal) -> CommissionReport:
        cancellation.raise_if_requested()
        self.settings = settings
        self.execute_calls += 1
        if self._on_execute is not None:
            self._on_execute()
        return self._report


class _TacticalWorkflow:
    def __init__(
        self,
        report: TacticalReport,
        *,
        on_execute: Callable[[], None] | None = None,
    ) -> None:
        self._report = report
        self._on_execute = on_execute
        self.execute_calls = 0
        self.settings: TacticalSettings | None = None

    def execute(self, settings: TacticalSettings, cancellation: CancellationSignal) -> TacticalReport:
        cancellation.raise_if_requested()
        self.settings = settings
        self.execute_calls += 1
        if self._on_execute is not None:
            self._on_execute()
        return self._report


def _context(
    task_id: str,
    abort: AbortToken | None = None,
    *,
    started_at: datetime = _OBSERVED_AT,
) -> TaskContext:
    return TaskContext(
        task_id=TaskId(task_id),
        run_id=RunId(f"run-{task_id}"),
        started_at=started_at,
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1", client_ui_revision="ui-1"),
        abort=AbortToken() if abort is None else abort,
        preemption=PreemptionRequest(),
    )


def _request_abort(abort: AbortToken, reason: str) -> None:
    abort.request(reason)


def _commission_report(
    *,
    finish_times: tuple[datetime, ...] = (),
    daily_pending: int = 0,
    filtered_urgent_pending: int = 0,
) -> CommissionReport:
    return CommissionReport(
        observed_at=_OBSERVED_AT,
        finish_times=finish_times,
        daily_pending=daily_pending,
        filtered_urgent_pending=filtered_urgent_pending,
    )


def test_research_empty_queue_defers_until_server_update() -> None:
    workflow = _ResearchWorkflow(ResearchReport(observed_at=_OBSERVED_AT, available_slots=5, first_finish_at=None))

    result = ResearchTask(workflow, _research_settings()).run(_context("research"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Deferred("no research project is running"),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
    )


def test_research_server_update_rolls_over_when_run_starts_at_the_trigger() -> None:
    context = _context("research", started_at=_SERVER_UPDATE_AT)
    workflow = _ResearchWorkflow(
        ResearchReport(observed_at=context.started_at, available_slots=5, first_finish_at=None)
    )

    result = ResearchTask(workflow, _research_settings()).run(context)

    expected_due_at = _SERVER_UPDATE_AT + timedelta(days=1)
    assert result.effects == (RescheduleSelf(expected_due_at),)
    assert expected_due_at > context.started_at


def test_research_empty_queue_schedules_from_observation_when_run_crosses_server_update() -> None:
    started_at = _SERVER_UPDATE_AT - timedelta(minutes=1)
    observed_at = _SERVER_UPDATE_AT + timedelta(minutes=1)
    workflow = _ResearchWorkflow(ResearchReport(observed_at=observed_at, available_slots=5, first_finish_at=None))

    result = ResearchTask(workflow, _research_settings()).run(_context("research", started_at=started_at))

    assert result.effects == (RescheduleSelf(_SERVER_UPDATE_AT + timedelta(days=1)),)


def test_research_four_available_slots_retries_ten_minutes_before_finish() -> None:
    finish_at = _OBSERVED_AT + timedelta(hours=2)
    workflow = _ResearchWorkflow(ResearchReport(observed_at=_OBSERVED_AT, available_slots=4, first_finish_at=finish_at))

    result = ResearchTask(workflow, _research_settings()).run(_context("research"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(finish_at - timedelta(minutes=10)),),
    )


@pytest.mark.parametrize("available_slots", [0, 1, 2, 3])
def test_research_non_empty_queue_uses_first_finish(available_slots: int) -> None:
    finish_at = _OBSERVED_AT + timedelta(hours=1)
    workflow = _ResearchWorkflow(
        ResearchReport(observed_at=_OBSERVED_AT, available_slots=available_slots, first_finish_at=finish_at)
    )

    result = ResearchTask(workflow, _research_settings()).run(_context("research"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(finish_at),))


def test_commission_uses_nearest_finish() -> None:
    nearest_finish = _OBSERVED_AT + timedelta(hours=1)
    workflow = _CommissionWorkflow(_commission_report(finish_times=(_OBSERVED_AT + timedelta(hours=3), nearest_finish)))
    settings = _commission_settings()

    result = CommissionTask(workflow, settings).run(_context("commission"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(nearest_finish),))


def test_commission_without_running_commission_uses_failure_retry() -> None:
    workflow = _CommissionWorkflow(_commission_report())
    settings = _commission_settings()

    result = CommissionTask(workflow, settings).run(_context("commission"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Retryable("no commission is running"),
        effects=(RescheduleSelf(_OBSERVED_AT + timedelta(minutes=30)),),
    )


def test_commission_limit_defers_gems_for_daily_and_filtered_urgent_work() -> None:
    finish_at = _OBSERVED_AT + timedelta(hours=3)
    workflow = _CommissionWorkflow(
        _commission_report(finish_times=(finish_at,), daily_pending=1, filtered_urgent_pending=1)
    )
    settings = _commission_settings(enabled=True)

    result = CommissionTask(workflow, settings).run(_context("commission"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(
            RescheduleSelf(finish_at),
            RescheduleTask(TaskId("gems_farming"), _OBSERVED_AT + timedelta(hours=2)),
        ),
    )


def test_commission_limit_defers_gems_to_earlier_finish_for_four_urgent_commissions() -> None:
    finish_at = _OBSERVED_AT + timedelta(hours=1)
    workflow = _CommissionWorkflow(_commission_report(finish_times=(finish_at,), filtered_urgent_pending=4))
    settings = _commission_settings(enabled=True)

    result = CommissionTask(workflow, settings).run(_context("commission"))

    assert workflow.execute_calls == 1
    assert result.effects == (
        RescheduleSelf(finish_at),
        RescheduleTask(TaskId("gems_farming"), finish_at),
    )


@pytest.mark.parametrize(
    ("enabled", "daily_pending", "filtered_urgent_pending"),
    [
        (False, 1, 4),
        (True, 1, 0),
        (True, 0, 3),
    ],
)
def test_commission_limit_does_not_defer_gems_outside_limit_rules(
    daily_pending: int,
    filtered_urgent_pending: int,
    *,
    enabled: bool,
) -> None:
    finish_at = _OBSERVED_AT + timedelta(hours=1)
    workflow = _CommissionWorkflow(
        _commission_report(
            finish_times=(finish_at,),
            daily_pending=daily_pending,
            filtered_urgent_pending=filtered_urgent_pending,
        )
    )
    settings = _commission_settings(enabled=enabled)

    result = CommissionTask(workflow, settings).run(_context("commission"))

    assert workflow.execute_calls == 1
    assert result.effects == (RescheduleSelf(finish_at),)


def test_commission_limit_without_finish_uses_two_hour_gems_deferral() -> None:
    workflow = _CommissionWorkflow(_commission_report(daily_pending=1, filtered_urgent_pending=1))
    settings = _commission_settings(enabled=True)

    result = CommissionTask(workflow, settings).run(_context("commission"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Retryable("no commission is running"),
        effects=(
            RescheduleSelf(_OBSERVED_AT + timedelta(minutes=30)),
            RescheduleTask(TaskId("gems_farming"), _OBSERVED_AT + timedelta(hours=2)),
        ),
    )


def test_tactical_uses_finish_time() -> None:
    finish_at = _OBSERVED_AT + timedelta(hours=4)
    workflow = _TacticalWorkflow(TacticalReport(observed_at=_OBSERVED_AT, finish_at=finish_at))

    result = TacticalTask(workflow, _tactical_settings()).run(_context("tactical"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(finish_at),))


def test_tactical_without_running_training_uses_failure_retry() -> None:
    workflow = _TacticalWorkflow(TacticalReport(observed_at=_OBSERVED_AT, finish_at=None))

    result = TacticalTask(workflow, _tactical_settings()).run(_context("tactical"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Retryable("no tactical training is running"),
        effects=(RescheduleSelf(_OBSERVED_AT + timedelta(minutes=20)),),
    )


@pytest.mark.parametrize("task_name", ["research", "commission", "tactical"])
def test_facility_abort_before_run_prevents_external_side_effects(task_name: str) -> None:
    abort = AbortToken()
    abort.request("manual stop")
    if task_name == "research":
        workflow = _ResearchWorkflow(ResearchReport(observed_at=_OBSERVED_AT, available_slots=5, first_finish_at=None))
        task = ResearchTask(workflow, _research_settings())
    elif task_name == "commission":
        workflow = _CommissionWorkflow(_commission_report())
        task = CommissionTask(
            workflow,
            _commission_settings(),
        )
    else:
        workflow = _TacticalWorkflow(TacticalReport(observed_at=_OBSERVED_AT, finish_at=None))
        task = TacticalTask(workflow, _tactical_settings())

    with pytest.raises(AbortRequested, match="manual stop"):
        task.run(_context(task_name, abort))

    assert workflow.execute_calls == 0


def test_research_abort_after_workflow_discards_schedule_result() -> None:
    abort = AbortToken()
    workflow = _ResearchWorkflow(
        ResearchReport(observed_at=_OBSERVED_AT, available_slots=5, first_finish_at=None),
        on_execute=lambda: _request_abort(abort, "stop after research"),
    )

    with pytest.raises(AbortRequested, match="stop after research"):
        ResearchTask(workflow, _research_settings()).run(_context("research", abort))

    assert workflow.execute_calls == 1


def test_commission_abort_after_workflow_discards_all_schedule_results() -> None:
    abort = AbortToken()
    workflow = _CommissionWorkflow(
        _commission_report(daily_pending=1, filtered_urgent_pending=1),
        on_execute=lambda: _request_abort(abort, "stop after commission"),
    )
    settings = _commission_settings(enabled=True)

    with pytest.raises(AbortRequested, match="stop after commission"):
        CommissionTask(workflow, settings).run(_context("commission", abort))

    assert workflow.execute_calls == 1


def test_tactical_abort_after_workflow_discards_schedule_result() -> None:
    abort = AbortToken()
    workflow = _TacticalWorkflow(
        TacticalReport(observed_at=_OBSERVED_AT, finish_at=None),
        on_execute=lambda: _request_abort(abort, "stop after tactical"),
    )

    with pytest.raises(AbortRequested, match="stop after tactical"):
        TacticalTask(workflow, _tactical_settings()).run(_context("tactical", abort))

    assert workflow.execute_calls == 1


def test_facility_datetimes_must_be_timezone_aware() -> None:
    naive = datetime(2026, 7, 13, 12)

    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchReport(observed_at=naive, available_slots=5, first_finish_at=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchReport(observed_at=_OBSERVED_AT, available_slots=4, first_finish_at=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        CommissionReport(naive, (), 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        CommissionReport(_OBSERVED_AT, (naive,), 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        TacticalReport(naive, None)
    with pytest.raises(ValueError, match="timezone-aware"):
        TacticalReport(_OBSERVED_AT, naive)


def test_facility_rejects_invalid_report_and_settings_values() -> None:
    with pytest.raises(ValueError, match="between zero and five"):
        ResearchReport(observed_at=_OBSERVED_AT, available_slots=6, first_finish_at=_OBSERVED_AT)
    with pytest.raises(ValueError, match="empty research queue"):
        ResearchReport(observed_at=_OBSERVED_AT, available_slots=5, first_finish_at=_OBSERVED_AT)
    with pytest.raises(ValueError, match="non-empty research queue"):
        ResearchReport(observed_at=_OBSERVED_AT, available_slots=0, first_finish_at=None)
    with pytest.raises(ValueError, match="must be positive"):
        CommissionSettings(timedelta(0), commission_limit_enabled=False, selection=_COMMISSION_SELECTION)
    with pytest.raises(TypeError, match="must be a bool"):
        CommissionSettings(timedelta(minutes=1), cast("bool", 1), _COMMISSION_SELECTION)
    with pytest.raises(ValueError, match="must be non-negative"):
        CommissionReport(_OBSERVED_AT, (), daily_pending=-1, filtered_urgent_pending=0)
    with pytest.raises(ValueError, match="must be positive"):
        _tactical_settings(timedelta(0))


def test_facility_datetime_type_errors_are_not_treated_as_naive_datetimes() -> None:
    with pytest.raises(TypeError, match="schedule must be a DailySchedule"):
        ResearchSettings(cast("DailySchedule", "tomorrow"), _RESEARCH_SELECTION)
    with pytest.raises(TypeError, match="must be a datetime"):
        TacticalReport(_OBSERVED_AT, cast("datetime", "later"))
