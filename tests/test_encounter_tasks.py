from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast, overload

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    DailySchedule,
    Deferred,
    DelayRange,
    DeleteTaskState,
    ExecutionMode,
    RescheduleSelf,
    Retryable,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
    UpsertTaskState,
    WakePolicy,
    WakeTask,
)
from module.gameplay.encounter import (
    EXERCISE_PROGRESS_KEY,
    EXERCISE_PROGRESS_SCHEMA_VERSION,
    REWARD_TASK_ID,
    DailyMissionPlan,
    DailyMissionPlans,
    DailyReport,
    DailySettings,
    DailyStageSelection,
    DailyStopReason,
    DailyTask,
    DailyWorkflow,
    ExerciseOpponentMode,
    ExerciseProgress,
    ExerciseReport,
    ExerciseSettings,
    ExerciseStrategy,
    ExerciseTask,
    ExerciseWorkflow,
    HardFleet,
    HardReport,
    HardSettings,
    HardStopReason,
    HardTask,
    HardWorkflow,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_OBSERVED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 14, 4, tzinfo=UTC)
_SERVER_UPDATE_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(12),))
_FAILURE_RETRY = timedelta(minutes=30)
_FAILURE_RETRY_RANGE = DelayRange(1_800, 1_800)
_RESOURCE_RETRY = timedelta(hours=3)


class _Workflow[ReportT]:
    def __init__(self, report: ReportT, *, on_execute: Callable[[], None] | None = None) -> None:
        self._report = report
        self._on_execute = on_execute
        self.execute_calls = 0

    @overload
    def execute(self, settings: DailySettings, cancellation: CancellationSource) -> ReportT: ...

    @overload
    def execute(self, settings: HardSettings, cancellation: CancellationSource) -> ReportT: ...

    @overload
    def execute(
        self,
        settings: ExerciseSettings,
        progress: ExerciseProgress,
        cancellation: CancellationSource,
    ) -> ReportT: ...

    def execute(self, *args: object) -> ReportT:
        cancellation = cast("CancellationSource", args[-1])
        cancellation.raise_if_requested()
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
        started_at=started_at,
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def _hard_settings() -> HardSettings:
    return HardSettings(
        schedule=_SERVER_UPDATE_SCHEDULE,
        failure_retry_delay=_FAILURE_RETRY_RANGE,
        resource_retry_delay=_RESOURCE_RETRY,
        stage="11-4",
        fleet=HardFleet.FLEET_1,
    )


_MISSION = DailyMissionPlan(DailyStageSelection.FIRST, 1)
_DAILY_MISSIONS = DailyMissionPlans(
    escort=_MISSION,
    advance=_MISSION,
    fierce_assault=_MISSION,
    tactical_training=_MISSION,
    supply_line_disruption=DailyMissionPlan(DailyStageSelection.SECOND, None),
    module_development=_MISSION,
    emergency_module_development=_MISSION,
)


def _daily_settings() -> DailySettings:
    return DailySettings(_SERVER_UPDATE_SCHEDULE, use_daily_skip=True, missions=_DAILY_MISSIONS)


def _hard_report(
    *,
    observed_at: datetime = _OBSERVED_AT,
    attempts_available: int = 3,
    attempts_completed: int = 3,
    stop_reason: HardStopReason = HardStopReason.COMPLETED,
) -> HardReport:
    return HardReport(
        observed_at=observed_at,
        attempts_available=attempts_available,
        attempts_completed=attempts_completed,
        stop_reason=stop_reason,
    )


def _exercise_report(
    *,
    observed_at: datetime = _OBSERVED_AT,
    attempts_remaining: int,
    attempts_preserved: int = 0,
    attempts_completed: int = 0,
    opponent_refreshes_used: int = 0,
) -> ExerciseReport:
    return ExerciseReport(
        observed_at=observed_at,
        attempts_remaining=attempts_remaining,
        attempts_preserved=attempts_preserved,
        attempts_completed=attempts_completed,
        opponent_refreshes_used=opponent_refreshes_used,
    )


def _exercise_settings(*, refresh_limit: int = 5) -> ExerciseSettings:
    return ExerciseSettings(
        schedule=_SERVER_UPDATE_SCHEDULE,
        failure_retry_delay=_FAILURE_RETRY_RANGE,
        opponent_refresh_limit=refresh_limit,
        opponent_mode=ExerciseOpponentMode.MAX_EXP,
        opponent_trials=1,
        strategy=ExerciseStrategy.AGGRESSIVE,
        low_hp_threshold=0.4,
        low_hp_confirm_wait_seconds=0.1,
    )


def test_daily_success_waits_for_server_update() -> None:
    workflow = _Workflow(DailyReport(attempts_available=6, attempts_completed=4))

    result = DailyTask(workflow, _daily_settings()).run(_context("daily"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(_SERVER_UPDATE_AT),))


def test_daily_in_progress_requeues_the_next_category_immediately() -> None:
    workflow = _Workflow(DailyReport(3, 3, DailyStopReason.IN_PROGRESS))

    result = DailyTask(workflow, _daily_settings()).run(_context("daily"))

    assert result == TaskResult(
        outcome=Deferred("daily categories remain"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
    )


def test_daily_without_attempts_defers_until_server_update() -> None:
    workflow = _Workflow(DailyReport(attempts_available=0, attempts_completed=0))

    result = DailyTask(workflow, _daily_settings()).run(_context("daily"))

    assert result == TaskResult(
        outcome=Deferred("daily attempts are exhausted"),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
    )


def test_daily_unavailable_attempts_keep_server_update_schedule() -> None:
    workflow = _Workflow(DailyReport(attempts_available=3, attempts_completed=0))

    result = DailyTask(workflow, _daily_settings()).run(_context("daily"))

    assert result == TaskResult(
        outcome=Deferred("daily attempts were not completed"),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
    )


def test_daily_schedule_rolls_over_when_run_starts_at_the_trigger() -> None:
    workflow = _Workflow(DailyReport(attempts_available=0, attempts_completed=0))
    context = _context("daily", started_at=_SERVER_UPDATE_AT)

    result = DailyTask(workflow, _daily_settings()).run(context)

    expected_due_at = _SERVER_UPDATE_AT + timedelta(days=1)
    assert result.effects == (RescheduleSelf(expected_due_at),)
    assert expected_due_at > context.started_at


def test_hard_completion_waits_for_server_update_and_forces_reward() -> None:
    workflow = _Workflow(_hard_report())

    result = HardTask(workflow, _hard_settings()).run(_context("hard"))

    assert workflow.execute_calls == 1
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(
            RescheduleSelf(_SERVER_UPDATE_AT),
            WakeTask(REWARD_TASK_ID, _OBSERVED_AT, WakePolicy.FORCE_ENABLE),
        ),
    )


def test_hard_daily_schedule_rolls_over_from_report_observation() -> None:
    report = _hard_report(observed_at=_SERVER_UPDATE_AT)

    result = HardTask(_Workflow(report), _hard_settings()).run(_context("hard"))

    expected_due_at = _SERVER_UPDATE_AT + timedelta(days=1)
    assert result.effects[0] == RescheduleSelf(expected_due_at)
    assert expected_due_at > report.observed_at


def test_hard_without_attempts_still_forces_reward() -> None:
    workflow = _Workflow(_hard_report(attempts_available=0, attempts_completed=0))

    result = HardTask(workflow, _hard_settings()).run(_context("hard"))

    assert result == TaskResult(
        outcome=Deferred("hard attempts are exhausted"),
        effects=(
            RescheduleSelf(_SERVER_UPDATE_AT),
            WakeTask(REWARD_TASK_ID, _OBSERVED_AT, WakePolicy.FORCE_ENABLE),
        ),
    )


def test_hard_resource_limit_retries_without_waking_reward() -> None:
    workflow = _Workflow(
        _hard_report(
            attempts_available=3,
            attempts_completed=1,
            stop_reason=HardStopReason.RESOURCE_LIMIT,
        )
    )

    result = HardTask(workflow, _hard_settings()).run(_context("hard"))

    assert result == TaskResult(
        outcome=Retryable("hard resources are insufficient"),
        effects=(RescheduleSelf(_OBSERVED_AT + _RESOURCE_RETRY),),
    )


def test_hard_failure_uses_failure_retry_without_waking_reward() -> None:
    workflow = _Workflow(
        _hard_report(
            attempts_available=3,
            attempts_completed=2,
            stop_reason=HardStopReason.FAILED,
        )
    )

    result = HardTask(workflow, _hard_settings()).run(_context("hard"))

    assert result == TaskResult(
        outcome=Retryable("hard workflow did not complete"),
        effects=(RescheduleSelf(_OBSERVED_AT + _FAILURE_RETRY),),
    )


def test_hard_in_progress_requeues_after_one_confirmed_battle() -> None:
    workflow = _Workflow(_hard_report(attempts_completed=1, stop_reason=HardStopReason.IN_PROGRESS))

    result = HardTask(workflow, _hard_settings()).run(_context("hard"))

    assert result == TaskResult(
        outcome=Deferred("hard attempts remain"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
    )


def test_exercise_completion_at_preserve_threshold_waits_for_server_update() -> None:
    workflow = _Workflow(_exercise_report(attempts_remaining=5, attempts_preserved=5, attempts_completed=2))

    result = ExerciseTask(workflow, _exercise_settings()).run(_context("exercise"))

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(DeleteTaskState("exercise", EXERCISE_PROGRESS_KEY),),
    )


def test_exercise_without_attempts_defers_until_server_update() -> None:
    workflow = _Workflow(_exercise_report(attempts_remaining=0))

    result = ExerciseTask(workflow, _exercise_settings()).run(_context("exercise"))

    assert result == TaskResult(
        outcome=Deferred("exercise attempts are exhausted"),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(DeleteTaskState("exercise", EXERCISE_PROGRESS_KEY),),
    )


def test_exercise_preserved_attempts_defer_until_server_update() -> None:
    workflow = _Workflow(_exercise_report(attempts_remaining=5, attempts_preserved=5))

    result = ExerciseTask(workflow, _exercise_settings()).run(_context("exercise"))

    assert result == TaskResult(
        outcome=Deferred("exercise attempts are preserved"),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(DeleteTaskState("exercise", EXERCISE_PROGRESS_KEY),),
    )


def test_exercise_refresh_exhaustion_defers_until_server_update() -> None:
    workflow = _Workflow(_exercise_report(attempts_remaining=6, attempts_preserved=5, opponent_refreshes_used=5))

    result = ExerciseTask(workflow, _exercise_settings()).run(_context("exercise"))

    assert result == TaskResult(
        outcome=Deferred("exercise opponent refreshes are exhausted"),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(DeleteTaskState("exercise", EXERCISE_PROGRESS_KEY),),
    )


def test_exercise_daily_schedule_rolls_over_from_report_observation() -> None:
    report = _exercise_report(observed_at=_SERVER_UPDATE_AT, attempts_remaining=0)

    result = ExerciseTask(_Workflow(report), _exercise_settings()).run(_context("exercise"))

    expected_due_at = _SERVER_UPDATE_AT + timedelta(days=1)
    assert result.effects == (RescheduleSelf(expected_due_at),)
    assert result.state_effects == (DeleteTaskState("exercise", EXERCISE_PROGRESS_KEY),)
    assert expected_due_at > report.observed_at


def test_exercise_unsettled_attempt_uses_failure_retry() -> None:
    workflow = _Workflow(_exercise_report(attempts_remaining=6, attempts_preserved=5, opponent_refreshes_used=4))

    result = ExerciseTask(workflow, _exercise_settings()).run(_context("exercise"))

    assert result == TaskResult(
        outcome=Retryable("exercise attempt did not settle"),
        effects=(RescheduleSelf(_OBSERVED_AT + _FAILURE_RETRY),),
        state_effects=(
            UpsertTaskState(
                "exercise",
                EXERCISE_PROGRESS_KEY,
                EXERCISE_PROGRESS_SCHEMA_VERSION,
                {"opponent_refreshes_used": 4},
            ),
        ),
    )


def test_exercise_confirmed_battle_persists_refresh_progress_and_requeues() -> None:
    workflow = _Workflow(
        _exercise_report(
            attempts_remaining=9,
            attempts_completed=1,
            opponent_refreshes_used=2,
        )
    )

    result = ExerciseTask(workflow, _exercise_settings()).run(_context("exercise"))

    assert result == TaskResult(
        outcome=Deferred("exercise attempts remain"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(
            UpsertTaskState(
                "exercise",
                EXERCISE_PROGRESS_KEY,
                EXERCISE_PROGRESS_SCHEMA_VERSION,
                {"opponent_refreshes_used": 2},
            ),
        ),
    )


@pytest.mark.parametrize("task_name", ["daily", "hard", "exercise"])
def test_encounter_abort_before_run_prevents_workflow_side_effects(task_name: str) -> None:
    abort = AbortToken()
    abort.request("manual stop")
    if task_name == "daily":
        workflow = _Workflow(DailyReport(0, 0))
        task = DailyTask(workflow, _daily_settings())
    elif task_name == "hard":
        workflow = _Workflow(_hard_report())
        task = HardTask(workflow, _hard_settings())
    else:
        workflow = _Workflow(_exercise_report(attempts_remaining=0))
        task = ExerciseTask(workflow, _exercise_settings())

    with pytest.raises(AbortRequested, match="manual stop"):
        task.run(_context(task_name, abort))

    assert workflow.execute_calls == 0


@pytest.mark.parametrize("task_name", ["daily", "hard", "exercise"])
def test_encounter_abort_after_workflow_discards_schedule_effects(task_name: str) -> None:
    abort = AbortToken()

    def on_execute() -> None:
        abort.request("stop after workflow")

    if task_name == "daily":
        workflow = _Workflow(DailyReport(0, 0), on_execute=on_execute)
        task = DailyTask(workflow, _daily_settings())
    elif task_name == "hard":
        workflow = _Workflow(_hard_report(), on_execute=on_execute)
        task = HardTask(workflow, _hard_settings())
    else:
        workflow = _Workflow(_exercise_report(attempts_remaining=0), on_execute=on_execute)
        task = ExerciseTask(workflow, _exercise_settings())

    with pytest.raises(AbortRequested, match="stop after workflow"):
        task.run(_context(task_name, abort))

    assert workflow.execute_calls == 1


@pytest.mark.parametrize("task_name", ["daily", "hard", "exercise"])
def test_encounter_tasks_reject_invalid_workflow_output(task_name: str) -> None:
    if task_name == "daily":
        task = DailyTask(cast("DailyWorkflow", _Workflow(object())), _daily_settings())
        expected = r"DailyWorkflow.execute\(\) must return a DailyReport"
    elif task_name == "hard":
        task = HardTask(cast("HardWorkflow", _Workflow(object())), _hard_settings())
        expected = r"HardWorkflow.execute\(\) must return a HardReport"
    else:
        task = ExerciseTask(cast("ExerciseWorkflow", _Workflow(object())), _exercise_settings())
        expected = r"ExerciseWorkflow.execute\(\) must return an ExerciseReport"

    with pytest.raises(TypeError, match=expected):
        task.run(_context(task_name))


def test_encounter_datetimes_must_be_timezone_aware() -> None:
    naive = datetime(2026, 7, 13, 12)

    with pytest.raises(ValueError, match="timezone-aware"):
        HardReport(naive, 0, 0, HardStopReason.COMPLETED)
    with pytest.raises(ValueError, match="timezone-aware"):
        ExerciseReport(naive, 0, 0, 0, 0)


def test_encounter_settings_and_reports_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="must not exceed"):
        DailyReport(attempts_available=1, attempts_completed=2)
    with pytest.raises(TypeError, match="failure_retry_delay must be a DelayRange"):
        HardSettings(
            _SERVER_UPDATE_SCHEDULE,
            cast("DelayRange", timedelta(0)),
            _RESOURCE_RETRY,
            "11-4",
            HardFleet.FLEET_1,
        )
    with pytest.raises(ValueError, match="settle every available attempt"):
        _hard_report(attempts_available=3, attempts_completed=2)
    with pytest.raises(TypeError, match="HardStopReason"):
        HardReport(_OBSERVED_AT, 1, 0, cast("HardStopReason", "failed"))
    with pytest.raises(ValueError, match="must be positive"):
        _exercise_settings(refresh_limit=0)
    with pytest.raises(ValueError, match="must be non-negative"):
        _exercise_report(attempts_remaining=-1)


def test_encounter_settings_require_daily_schedules() -> None:
    invalid = cast("DailySchedule", object())

    with pytest.raises(TypeError, match="schedule must be a DailySchedule"):
        DailySettings(invalid, use_daily_skip=True, missions=_DAILY_MISSIONS)
    with pytest.raises(TypeError, match="schedule must be a DailySchedule"):
        HardSettings(invalid, _FAILURE_RETRY_RANGE, _RESOURCE_RETRY, "11-4", HardFleet.FLEET_1)
    with pytest.raises(TypeError, match="schedule must be a DailySchedule"):
        ExerciseSettings(
            invalid,
            _FAILURE_RETRY_RANGE,
            5,
            ExerciseOpponentMode.MAX_EXP,
            1,
            ExerciseStrategy.AGGRESSIVE,
            0.4,
            0.1,
        )


def test_exercise_rejects_refresh_count_above_game_rule() -> None:
    workflow = _Workflow(_exercise_report(attempts_remaining=6, opponent_refreshes_used=6))

    with pytest.raises(ValueError, match="must not exceed opponent_refresh_limit"):
        ExerciseTask(workflow, _exercise_settings()).run(_context("exercise"))


def test_encounter_datetime_type_errors_are_not_treated_as_naive() -> None:
    with pytest.raises(TypeError, match="schedule must be a DailySchedule"):
        DailySettings(
            cast("DailySchedule", "tomorrow"),
            use_daily_skip=True,
            missions=_DAILY_MISSIONS,
        )
    with pytest.raises(TypeError, match="must be a datetime"):
        HardReport(cast("datetime", "now"), 0, 0, HardStopReason.COMPLETED)
    with pytest.raises(TypeError, match="must be a datetime"):
        ExerciseReport(cast("datetime", "now"), 0, 0, 0, 0)
