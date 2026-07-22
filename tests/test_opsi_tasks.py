from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    Deferred,
    DelayTask,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
    RescheduleSelf,
    RescheduleTask,
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
from module.gameplay.opsi import (
    OPSI_DAILY_TASK_ID,
    OPSI_HAZARD1_LEVELING_TASK_ID,
    OPSI_MEOWFFICER_FARMING_TASK_ID,
    OPSI_SHOP_TASK_ID,
    REWARD_TASK_ID,
    WORLD_TASK_DEFINITIONS,
    AbyssalSettings,
    ActionPointPolicy,
    ArchiveSettings,
    AshAssistSettings,
    AshBeaconAttackMode,
    AshBeaconSettings,
    CrossMonthSettings,
    ExploreSettings,
    FleetSettings,
    Hazard1LevelingSettings,
    MeowfficerFarmingSettings,
    MonthBossMode,
    MonthBossSettings,
    ObscureSettings,
    OperationSirenTask,
    OperationSirenWorkflow,
    OpsiDailySettings,
    OpsiShopPreset,
    RefreshPolicy,
    ShopSettings,
    StrongholdSettings,
    VoucherSettings,
    WorldBossCursor,
    WorldCheckpointMode,
    WorldGeneralSettings,
    WorldMissionCursor,
    WorldOperation,
    WorldProgress,
    WorldSchedule,
    WorldScheduleDelay,
    WorldTaskReport,
    WorldTaskSettings,
    WorldTaskSpec,
    WorldTaskStatus,
    WorldZoneCursor,
    create_operation_siren_task,
    world_task_spec,
)
from module.gameplay.opsi_progress import WorldBossPhase, WorldMissionEvidenceKind

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_OBSERVED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 14, 4, tzinfo=UTC)
_MONTH_RESET_AT = datetime(2026, 8, 1, tzinfo=UTC)
_ARCHIVE_REFRESH_AT = datetime(2026, 7, 15, tzinfo=UTC)
_RETRY_AT = datetime(2026, 7, 13, 12, 15, tzinfo=UTC)
_STARTED_AT = datetime(2026, 7, 13, tzinfo=UTC)

_LAST_DAY_OBSERVED_AT = datetime(2026, 7, 31, 12, tzinfo=UTC)
_LAST_DAY_SERVER_UPDATE_AT = datetime(2026, 8, 1, 4, tzinfo=UTC)
_LAST_DAY_MONTH_RESET_AT = datetime(2026, 8, 1, tzinfo=UTC)
_LAST_DAY_ARCHIVE_REFRESH_AT = datetime(2026, 8, 5, tzinfo=UTC)

_GENERAL = WorldGeneralSettings(
    use_logger=True,
    buy_action_point_limit=0,
    oil_preserve=1000,
    repair_threshold=0.4,
    random_map_events=True,
    akashi_shop_filter="ActionPoint > PurpleCoins",
)
_FLEET = FleetSettings(fleet_index=1, use_submarine=False)
_FLEET_FILTER = "Fleet-4 > CallSubmarine > Fleet-2 > Fleet-3 > Fleet-1"

_SETTINGS_BY_TASK: dict[str, WorldTaskSettings] = {
    "opsi_ash_assist": AshAssistSettings(minimum_tier=15),
    "opsi_ash_beacon": AshBeaconSettings(
        attack_mode=AshBeaconAttackMode.CURRENT,
        one_hit_mode=True,
        dossier_auto_attack=False,
        request_assist=True,
        ensure_fully_collected=True,
    ),
    "opsi_explore": ExploreSettings(
        general=_GENERAL,
        fleet=_FLEET,
        special_radar=False,
        force_run=False,
    ),
    "opsi_shop": ShopSettings(_GENERAL, OpsiShopPreset.MAX_BENEFIT_META, "ActionPoint > PurpleCoins"),
    "opsi_voucher": VoucherSettings(_GENERAL, "LoggerAbyssal > LoggerObscure > Book > Coin > Fragment"),
    "opsi_daily": OpsiDailySettings(
        general=_GENERAL,
        fleet=_FLEET,
        do_missions=True,
        use_tuning_samples=True,
    ),
    "opsi_obscure": ObscureSettings(general=_GENERAL, fleet=_FLEET, force_run=False),
    "opsi_month_boss": MonthBossSettings(
        general=_GENERAL,
        fleet_filter=_FLEET_FILTER,
        mode=MonthBossMode.NORMAL,
        check_adaptability=True,
        force_run=False,
    ),
    "opsi_abyssal": AbyssalSettings(general=_GENERAL, fleet_filter=_FLEET_FILTER, force_run=False),
    "opsi_archive": ArchiveSettings(
        _GENERAL,
        _FLEET,
        "LoggerAbyssal > LoggerObscure > Book > Coin > Fragment",
    ),
    "opsi_stronghold": StrongholdSettings(
        general=_GENERAL,
        fleet_filter=_FLEET_FILTER,
        force_run=False,
    ),
    "opsi_meowfficer_farming": MeowfficerFarmingSettings(
        general=_GENERAL,
        fleet=_FLEET,
        action_point_preserve=1000,
        hazard_level=5,
        target_zone=0,
        ensure_ash_fully_collected=True,
    ),
    "opsi_hazard1_leveling": Hazard1LevelingSettings(
        general=_GENERAL,
        fleet=_FLEET,
        target_zone=0,
        ensure_ash_fully_collected=True,
    ),
    "opsi_cross_month": CrossMonthSettings(_GENERAL, _FLEET, _FLEET, _FLEET_FILTER, _FLEET),
}


class _Workflow:
    def __init__(
        self,
        report: object,
        *,
        on_execute: Callable[[], None] | None = None,
    ) -> None:
        self._report = report
        self._on_execute = on_execute
        self.calls = 0
        self.received_spec: WorldTaskSpec | None = None
        self.received_progress: WorldProgress | None = None
        self.received_cancellation: CancellationSource | None = None

    def execute(
        self,
        spec: WorldTaskSpec,
        progress: WorldProgress | None,
        cancellation: CancellationSource,
    ) -> WorldTaskReport:
        cancellation.raise_if_requested()
        self.calls += 1
        self.received_spec = spec
        self.received_progress = progress
        self.received_cancellation = cancellation
        if self._on_execute is not None:
            self._on_execute()
        return cast("WorldTaskReport", self._report)


def _schedule(*, last_day: bool = False) -> WorldSchedule:
    if last_day:
        return WorldSchedule(
            next_server_update_at=_LAST_DAY_SERVER_UPDATE_AT,
            next_month_reset_at=_LAST_DAY_MONTH_RESET_AT,
            next_archive_refresh_at=_LAST_DAY_ARCHIVE_REFRESH_AT,
        )
    return WorldSchedule(
        next_server_update_at=_SERVER_UPDATE_AT,
        next_month_reset_at=_MONTH_RESET_AT,
        next_archive_refresh_at=_ARCHIVE_REFRESH_AT,
    )


def _report(  # ruff:ignore[too-many-arguments] - 测试构造器显式暴露 report 的独立契约轴。
    status: WorldTaskStatus = WorldTaskStatus.COMPLETED,
    *,
    completed_units: int = 0,
    retry_at: datetime | None = None,
    affected_task_ids: tuple[TaskId, ...] = (),
    schedule_delays: tuple[WorldScheduleDelay, ...] = (),
    wake_task_ids: tuple[TaskId, ...] = (),
    has_surplus_yellow_coins: bool = False,
    exploration_in_progress: bool = False,
    cursor: WorldZoneCursor | WorldMissionCursor | WorldBossCursor | None = None,
) -> WorldTaskReport:
    return WorldTaskReport(
        observed_at=_OBSERVED_AT,
        status=status,
        schedule=_schedule(),
        completed_units=completed_units,
        retry_at=retry_at,
        affected_task_ids=affected_task_ids,
        schedule_delays=schedule_delays,
        wake_task_ids=wake_task_ids,
        has_surplus_yellow_coins=has_surplus_yellow_coins,
        exploration_in_progress=exploration_in_progress,
        cursor=cursor,
    )


def _last_day_report(
    status: WorldTaskStatus,
    *,
    has_surplus_yellow_coins: bool = False,
) -> WorldTaskReport:
    return WorldTaskReport(
        observed_at=_LAST_DAY_OBSERVED_AT,
        status=status,
        schedule=_schedule(last_day=True),
        has_surplus_yellow_coins=has_surplus_yellow_coins,
    )


def _request_abort(abort: AbortToken) -> None:
    abort.request("stop after current action")


def _context(
    task_id: str,
    *,
    abort: AbortToken | None = None,
) -> TaskContext:
    return TaskContext(
        task_id=TaskId(task_id),
        started_at=_STARTED_AT,
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def _run(task_id: str, report: WorldTaskReport) -> tuple[TaskResult, _Workflow]:
    workflow = _Workflow(report)
    result = create_operation_siren_task(TaskId(task_id), workflow, _SETTINGS_BY_TASK[task_id]).run(_context(task_id))
    return result, workflow


def _task(
    task_id: str,
    workflow: _Workflow,
    progress: WorldProgress | None = None,
) -> OperationSirenTask:
    return create_operation_siren_task(TaskId(task_id), workflow, _SETTINGS_BY_TASK[task_id], progress)


def _cursor_for_task(task_id: str) -> WorldZoneCursor | WorldMissionCursor | WorldBossCursor | None:
    operation = WorldOperation(task_id)
    if operation in {
        WorldOperation.EXPLORE,
        WorldOperation.OBSCURE,
        WorldOperation.ABYSSAL,
        WorldOperation.STRONGHOLD,
        WorldOperation.MEOWFFICER_FARMING,
        WorldOperation.HAZARD1_LEVELING,
    }:
        return WorldZoneCursor(22)
    if operation in {WorldOperation.DAILY, WorldOperation.ARCHIVE}:
        return WorldMissionCursor(WorldMissionEvidenceKind.PINNED_ZONE, 1)
    if operation is WorldOperation.MONTH_BOSS:
        return WorldBossCursor(WorldBossPhase.HARD)
    return None


def _progress(
    task_id: str,
    *,
    completed_units: int = 2,
    settings_revision: int = 1,
    content_revision: str = "content-1",
    cycle_anchor: datetime | None = None,
) -> WorldProgress:
    return WorldProgress(
        task_id=TaskId(task_id),
        operation=WorldOperation(task_id),
        completed_units=completed_units,
        cycle_anchor=_SERVER_UPDATE_AT if cycle_anchor is None else cycle_anchor,
        settings_revision=settings_revision,
        content_revision=content_revision,
        cursor=_cursor_for_task(task_id),
    )


def test_catalog_maps_all_fourteen_scheduler_commands_to_typed_specs() -> None:
    expected_commands = {
        "opsi_ash_assist",
        "opsi_ash_beacon",
        "opsi_explore",
        "opsi_shop",
        "opsi_voucher",
        "opsi_daily",
        "opsi_obscure",
        "opsi_month_boss",
        "opsi_abyssal",
        "opsi_archive",
        "opsi_stronghold",
        "opsi_meowfficer_farming",
        "opsi_hazard1_leveling",
        "opsi_cross_month",
    }

    assert {task_id.value for task_id in WORLD_TASK_DEFINITIONS} == expected_commands
    assert {definition.operation.value for definition in WORLD_TASK_DEFINITIONS.values()} == expected_commands
    assert all(definition.task_id == task_id for task_id, definition in WORLD_TASK_DEFINITIONS.items())
    assert len(WORLD_TASK_DEFINITIONS) == len(WorldOperation) == 14


def test_catalog_explicitly_separates_bounded_and_one_shot_operations() -> None:
    one_shot = {
        WorldOperation.SHOP,
        WorldOperation.VOUCHER,
        WorldOperation.CROSS_MONTH,
    }
    actual_one_shot = {
        definition.operation
        for definition in WORLD_TASK_DEFINITIONS.values()
        if definition.checkpoint_mode is WorldCheckpointMode.ONE_SHOT
    }

    assert actual_one_shot == one_shot
    assert all(
        definition.progress_cycle is None
        for definition in WORLD_TASK_DEFINITIONS.values()
        if definition.operation in one_shot
    )
    assert all(
        definition.progress_cycle is not None
        for definition in WORLD_TASK_DEFINITIONS.values()
        if definition.operation not in one_shot
    )


def test_in_progress_run_upserts_one_cumulative_safe_unit_and_reschedules_immediately() -> None:
    existing = _progress("opsi_daily", completed_units=2)
    workflow = _Workflow(
        _report(
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldMissionCursor(WorldMissionEvidenceKind.PINNED_ZONE, 3),
        )
    )

    result = _task("opsi_daily", workflow, existing).run(_context("opsi_daily"))

    next_progress = WorldProgress(
        task_id=TaskId("opsi_daily"),
        operation=WorldOperation.DAILY,
        completed_units=3,
        cycle_anchor=_SERVER_UPDATE_AT,
        settings_revision=1,
        content_revision="content-1",
        cursor=WorldMissionCursor(WorldMissionEvidenceKind.PINNED_ZONE, 3),
    )
    assert workflow.calls == 1
    assert workflow.received_progress is existing
    assert result == TaskResult(
        outcome=Deferred("operation siren completed one safe unit"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(
            UpsertTaskState(
                "opsi_daily",
                "world_progress",
                1,
                next_progress.to_payload(),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("task_id", "cursor", "expected_anchor"),
    [
        ("opsi_ash_assist", None, _SERVER_UPDATE_AT),
        ("opsi_explore", WorldZoneCursor(22), _MONTH_RESET_AT),
        (
            "opsi_archive",
            WorldMissionCursor(WorldMissionEvidenceKind.ARCHIVE_ZONE),
            _ARCHIVE_REFRESH_AT,
        ),
    ],
)
def test_first_safe_unit_uses_the_operation_cycle_anchor(
    task_id: str,
    cursor: WorldZoneCursor | WorldMissionCursor | None,
    expected_anchor: datetime,
) -> None:
    workflow = _Workflow(_report(WorldTaskStatus.IN_PROGRESS, completed_units=1, cursor=cursor))

    result = _task(task_id, workflow).run(_context(task_id))

    assert len(result.state_effects) == 1
    effect = result.state_effects[0]
    assert isinstance(effect, UpsertTaskState)
    assert isinstance(effect.payload, Mapping)
    payload = cast("Mapping[str, object]", effect.payload)
    assert payload["cycle_anchor"] == expected_anchor.isoformat(timespec="microseconds")


@pytest.mark.parametrize(
    "progress",
    [
        _progress("opsi_daily", settings_revision=2),
        _progress("opsi_daily", content_revision="content-2"),
        _progress("opsi_daily", cycle_anchor=_STARTED_AT),
    ],
)
def test_stale_progress_is_deleted_and_immediately_rescheduled_without_entering_workflow(
    progress: WorldProgress,
) -> None:
    workflow = _Workflow(_report())

    result = _task("opsi_daily", workflow, progress).run(_context("opsi_daily"))

    assert workflow.calls == 0
    assert result == TaskResult(
        outcome=Deferred("operation siren progress belongs to a stale revision or reset cycle"),
        effects=(RescheduleSelf(_STARTED_AT),),
        state_effects=(DeleteTaskState("opsi_daily", "world_progress"),),
    )


@pytest.mark.parametrize(
    "status",
    [WorldTaskStatus.COMPLETED, WorldTaskStatus.EMPTY, WorldTaskStatus.DISABLED],
)
def test_settled_bounded_operation_deletes_existing_progress(status: WorldTaskStatus) -> None:
    result = _task("opsi_daily", _Workflow(_report(status)), _progress("opsi_daily")).run(_context("opsi_daily"))

    assert result.state_effects == (DeleteTaskState("opsi_daily", "world_progress"),)


def test_waiting_state_keeps_existing_progress_unchanged() -> None:
    existing = _progress("opsi_daily")
    workflow = _Workflow(_report(WorldTaskStatus.ACTION_POINT_LIMIT))

    result = _task("opsi_daily", workflow, existing).run(_context("opsi_daily"))

    assert workflow.received_progress is existing
    assert result.state_effects == ()


def test_operation_specific_cursor_type_is_enforced() -> None:
    workflow = _Workflow(
        _report(
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldZoneCursor(22),
        )
    )

    with pytest.raises(TypeError, match="opsi_daily report requires a WorldMissionCursor"):
        _task("opsi_daily", workflow).run(_context("opsi_daily"))


@pytest.mark.parametrize(
    ("task_id", "expected_due_at"),
    [
        ("opsi_ash_assist", _SERVER_UPDATE_AT),
        ("opsi_ash_beacon", _SERVER_UPDATE_AT),
        ("opsi_explore", _MONTH_RESET_AT),
        ("opsi_shop", _RETRY_AT),
        ("opsi_voucher", _MONTH_RESET_AT),
        ("opsi_daily", _SERVER_UPDATE_AT),
        ("opsi_obscure", _SERVER_UPDATE_AT),
        ("opsi_month_boss", _MONTH_RESET_AT),
        ("opsi_abyssal", _SERVER_UPDATE_AT),
        ("opsi_archive", _ARCHIVE_REFRESH_AT),
        ("opsi_stronghold", _SERVER_UPDATE_AT),
        ("opsi_meowfficer_farming", _SERVER_UPDATE_AT),
        ("opsi_hazard1_leveling", _SERVER_UPDATE_AT),
        ("opsi_cross_month", _MONTH_RESET_AT - timedelta(minutes=10)),
    ],
)
def test_completed_command_uses_its_explicit_refresh_policy(task_id: str, expected_due_at: datetime) -> None:
    retry_at = _RETRY_AT if task_id == "opsi_shop" else None

    result, workflow = _run(task_id, _report(retry_at=retry_at))

    assert workflow.calls == 1
    assert workflow.received_spec is not None
    assert workflow.received_spec == world_task_spec(TaskId(task_id), _SETTINGS_BY_TASK[task_id])
    assert workflow.received_spec.settings is _SETTINGS_BY_TASK[task_id]
    assert result.outcome == Succeeded()
    assert result.effects[0] == RescheduleSelf(expected_due_at)


def test_explore_completion_wakes_follow_ups_without_enabling_disabled_tasks() -> None:
    result, _ = _run("opsi_explore", _report())

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(
            RescheduleSelf(_MONTH_RESET_AT),
            WakeTask(OPSI_DAILY_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
            WakeTask(OPSI_SHOP_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
            WakeTask(OPSI_HAZARD1_LEVELING_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
        ),
        state_effects=(DeleteTaskState("opsi_explore", "world_progress"),),
    )


def test_finished_explore_with_no_remaining_zone_still_wakes_follow_ups() -> None:
    result, _ = _run("opsi_explore", _report(WorldTaskStatus.EMPTY))

    assert result == TaskResult(
        outcome=Deferred("operation siren task has no work"),
        effects=(
            RescheduleSelf(_MONTH_RESET_AT),
            WakeTask(OPSI_DAILY_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
            WakeTask(OPSI_SHOP_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
            WakeTask(OPSI_HAZARD1_LEVELING_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
        ),
        state_effects=(DeleteTaskState("opsi_explore", "world_progress"),),
    )


def test_action_point_limit_batch_reschedules_tasks_without_changing_enabled_state() -> None:
    due_at = _OBSERVED_AT + timedelta(hours=6)

    result, _ = _run("opsi_daily", _report(WorldTaskStatus.ACTION_POINT_LIMIT))

    assert result == TaskResult(
        outcome=Deferred("operation siren action points are exhausted"),
        effects=(
            RescheduleSelf(due_at),
            RescheduleTask(TaskId("opsi_explore"), due_at),
            RescheduleTask(TaskId("opsi_obscure"), due_at),
            RescheduleTask(TaskId("opsi_abyssal"), due_at),
            RescheduleTask(TaskId("opsi_stronghold"), due_at),
            RescheduleTask(TaskId("opsi_archive"), due_at),
            RescheduleTask(OPSI_MEOWFFICER_FARMING_TASK_ID, due_at),
        ),
    )
    assert not any(isinstance(effect, WakeTask) for effect in result.effects)


def test_action_point_batch_also_reschedules_a_current_task_outside_the_shared_batch() -> None:
    due_at = _OBSERVED_AT + timedelta(hours=6)

    result, _ = _run("opsi_month_boss", _report(WorldTaskStatus.ACTION_POINT_LIMIT))

    assert result.effects[0] == RescheduleSelf(due_at)
    assert result.effects[1:] == tuple(
        RescheduleTask(task_id, due_at)
        for task_id in (
            TaskId("opsi_explore"),
            OPSI_DAILY_TASK_ID,
            TaskId("opsi_obscure"),
            TaskId("opsi_abyssal"),
            TaskId("opsi_stronghold"),
            TaskId("opsi_archive"),
            OPSI_MEOWFFICER_FARMING_TASK_ID,
        )
    )


def test_action_point_batch_uses_150_minutes_during_the_last_reset_day() -> None:
    due_at = _LAST_DAY_OBSERVED_AT + timedelta(minutes=150)

    result, _ = _run("opsi_daily", _last_day_report(WorldTaskStatus.ACTION_POINT_LIMIT))

    assert all(
        effect.due_at == due_at for effect in result.effects if isinstance(effect, RescheduleSelf | RescheduleTask)
    )


def test_meowfficer_action_point_limit_hands_work_to_reward_and_optional_cl1() -> None:
    result, _ = _run(
        "opsi_meowfficer_farming",
        _report(WorldTaskStatus.ACTION_POINT_LIMIT, has_surplus_yellow_coins=True),
    )

    assert result == TaskResult(
        outcome=Deferred("operation siren action points are exhausted"),
        effects=(
            RescheduleSelf(_SERVER_UPDATE_AT),
            WakeTask(REWARD_TASK_ID, _OBSERVED_AT, WakePolicy.FORCE_ENABLE),
            WakeTask(OPSI_HAZARD1_LEVELING_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
        ),
    )


def test_meowfficer_last_day_action_point_limit_does_not_start_follow_up_work() -> None:
    due_at = _LAST_DAY_OBSERVED_AT + timedelta(minutes=150)

    result, _ = _run(
        "opsi_meowfficer_farming",
        _last_day_report(
            WorldTaskStatus.ACTION_POINT_LIMIT,
            has_surplus_yellow_coins=True,
        ),
    )

    assert result == TaskResult(
        outcome=Deferred("operation siren action points are exhausted"),
        effects=(RescheduleSelf(due_at),),
    )


@pytest.mark.parametrize("exploration_in_progress", [False, True])
def test_hazard1_resource_limit_hands_back_to_meowfficer_only_outside_explore(
    *,
    exploration_in_progress: bool,
) -> None:
    result, _ = _run(
        "opsi_hazard1_leveling",
        _report(WorldTaskStatus.RESOURCE_LIMIT, exploration_in_progress=exploration_in_progress),
    )

    expected_effects = [RescheduleSelf(_SERVER_UPDATE_AT)]
    if not exploration_in_progress:
        expected_effects.append(WakeTask(OPSI_MEOWFFICER_FARMING_TASK_ID, _OBSERVED_AT, WakePolicy.FORCE_ENABLE))
    assert result == TaskResult(
        outcome=Deferred("operation siren resources are insufficient"),
        effects=tuple(expected_effects),
    )


@pytest.mark.parametrize("task_id", ["opsi_obscure", "opsi_abyssal"])
def test_empty_monthly_coordinate_task_checks_again_in_150_minutes_on_last_day(task_id: str) -> None:
    result, _ = _run(task_id, _last_day_report(WorldTaskStatus.EMPTY))

    assert result == TaskResult(
        outcome=Deferred("operation siren task has no work"),
        effects=(RescheduleSelf(_LAST_DAY_OBSERVED_AT + timedelta(minutes=150)),),
        state_effects=(DeleteTaskState(task_id, "world_progress"),),
    )


def test_month_boss_empty_and_completed_have_distinct_daily_and_monthly_refreshes() -> None:
    empty, _ = _run("opsi_month_boss", _report(WorldTaskStatus.EMPTY))
    completed, _ = _run("opsi_month_boss", _report(WorldTaskStatus.COMPLETED))

    assert empty.effects == (RescheduleSelf(_SERVER_UPDATE_AT),)
    assert completed.effects == (RescheduleSelf(_MONTH_RESET_AT),)


@pytest.mark.parametrize("status", [WorldTaskStatus.EMPTY, WorldTaskStatus.COMPLETED])
def test_shop_uses_inventory_dependent_target_reported_by_workflow(status: WorldTaskStatus) -> None:
    result, _ = _run("opsi_shop", _report(status, retry_at=_RETRY_AT))

    assert result.effects == (RescheduleSelf(_RETRY_AT),)


def test_workflow_target_is_required_for_empty_ash_assist() -> None:
    task = _task("opsi_ash_assist", _Workflow(_report(WorldTaskStatus.EMPTY)))

    with pytest.raises(ValueError, match="opsi_ash_assist report requires retry_at"):
        task.run(_context("opsi_ash_assist"))


def test_cooldown_reschedules_dependencies_without_waking_or_enabling_them() -> None:
    affected = (TaskId("opsi_daily"), TaskId("opsi_month_boss"), TaskId("opsi_archive"))

    result, _ = _run(
        "opsi_month_boss",
        _report(WorldTaskStatus.COOLDOWN, retry_at=_RETRY_AT, affected_task_ids=affected),
    )

    assert result == TaskResult(
        outcome=Deferred("operation siren task is cooling down"),
        effects=(
            RescheduleSelf(_RETRY_AT),
            RescheduleTask(TaskId("opsi_daily"), _RETRY_AT),
            RescheduleTask(TaskId("opsi_archive"), _RETRY_AT),
        ),
    )
    assert not any(isinstance(effect, WakeTask) for effect in result.effects)


def test_live_schedule_intents_merge_with_domain_schedule_without_duplicate_writes() -> None:
    recon_due = _OBSERVED_AT + timedelta(minutes=27)
    submarine_due = _OBSERVED_AT + timedelta(minutes=60)
    result, _ = _run(
        "opsi_explore",
        _report(
            WorldTaskStatus.COMPLETED,
            schedule_delays=(
                WorldScheduleDelay(recon_due, (TaskId("opsi_obscure"),)),
                WorldScheduleDelay(submarine_due, (TaskId("opsi_daily"), TaskId("opsi_obscure"))),
            ),
            wake_task_ids=(TaskId("opsi_ash_beacon"),),
        ),
    )

    assert result.effects == (
        RescheduleSelf(_MONTH_RESET_AT),
        WakeTask(TaskId("opsi_daily"), submarine_due, WakePolicy.RESPECT_DISABLED),
        WakeTask(OPSI_SHOP_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
        WakeTask(OPSI_HAZARD1_LEVELING_TASK_ID, _OBSERVED_AT, WakePolicy.RESPECT_DISABLED),
        DelayTask(TaskId("opsi_obscure"), submarine_due),
        WakeTask(TaskId("opsi_ash_beacon"), _OBSERVED_AT, WakePolicy.FORCE_ENABLE),
    )


def test_live_delay_for_current_partial_task_becomes_its_single_self_schedule() -> None:
    due_at = _OBSERVED_AT + timedelta(minutes=27)
    result, _ = _run(
        "opsi_obscure",
        _report(
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=WorldZoneCursor(22),
            schedule_delays=(WorldScheduleDelay(due_at, (TaskId("opsi_obscure"),)),),
        ),
    )

    assert result.effects == (RescheduleSelf(due_at),)


def test_cross_month_action_point_limit_returns_to_next_month_window() -> None:
    result, _ = _run("opsi_cross_month", _report(WorldTaskStatus.ACTION_POINT_LIMIT))

    assert result == TaskResult(
        outcome=Deferred("operation siren action points are exhausted"),
        effects=(RescheduleSelf(_MONTH_RESET_AT - timedelta(minutes=10)),),
    )


def test_explore_in_progress_waits_for_server_update() -> None:
    result, _ = _run("opsi_archive", _report(WorldTaskStatus.EXPLORE_IN_PROGRESS))

    assert result == TaskResult(
        outcome=Deferred("operation siren exploration is still active"),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
    )


def test_retryable_failure_uses_workflow_target_or_server_update() -> None:
    targeted, _ = _run("opsi_daily", _report(WorldTaskStatus.FAILED, retry_at=_RETRY_AT))
    defaulted, _ = _run("opsi_daily", _report(WorldTaskStatus.FAILED))

    assert targeted == TaskResult(
        outcome=Retryable("operation siren workflow did not complete"),
        effects=(RescheduleSelf(_RETRY_AT),),
    )
    assert defaulted.effects == (RescheduleSelf(_SERVER_UPDATE_AT),)


def test_disabled_workflow_state_disables_only_the_current_task() -> None:
    result, _ = _run("opsi_ash_assist", _report(WorldTaskStatus.DISABLED))

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(DisableTask(TaskId("opsi_ash_assist")),),
        state_effects=(DeleteTaskState("opsi_ash_assist", "world_progress"),),
    )


@pytest.mark.parametrize("status", list(WorldTaskStatus))
@pytest.mark.parametrize("task_id", sorted(task_id.value for task_id in WORLD_TASK_DEFINITIONS))
def test_every_world_task_status_advances_or_disables_the_scheduled_task(
    task_id: str,
    status: WorldTaskStatus,
) -> None:
    definition = WORLD_TASK_DEFINITIONS[TaskId(task_id)]
    is_bounded = definition.checkpoint_mode is WorldCheckpointMode.BOUNDED
    safe_point = status is WorldTaskStatus.IN_PROGRESS and is_bounded
    workflow = _Workflow(
        _report(
            status,
            completed_units=1 if status is WorldTaskStatus.IN_PROGRESS else 0,
            retry_at=_RETRY_AT,
            cursor=_cursor_for_task(task_id) if safe_point else None,
        ),
    )

    if status is WorldTaskStatus.IN_PROGRESS and not is_bounded:
        with pytest.raises(ValueError, match="one-shot operation cannot report in-progress"):
            _task(task_id, workflow).run(_context(task_id))
        assert workflow.calls == 1
        return

    result = _task(task_id, workflow).run(_context(task_id))

    self_schedule_effects = tuple(
        effect
        for effect in result.effects
        if isinstance(effect, RescheduleSelf) or (isinstance(effect, DisableTask) and effect.task_id == TaskId(task_id))
    )
    assert len(self_schedule_effects) == 1
    if status is WorldTaskStatus.DISABLED:
        assert self_schedule_effects == (DisableTask(TaskId(task_id)),)
    else:
        assert isinstance(self_schedule_effects[0], RescheduleSelf)

    if is_bounded and status is WorldTaskStatus.IN_PROGRESS:
        assert len(result.state_effects) == 1
        assert isinstance(result.state_effects[0], UpsertTaskState)
    elif is_bounded and status in {
        WorldTaskStatus.COMPLETED,
        WorldTaskStatus.EMPTY,
        WorldTaskStatus.DISABLED,
    }:
        assert result.state_effects == (DeleteTaskState(task_id, "world_progress"),)
    else:
        assert result.state_effects == ()


def test_abort_before_execution_prevents_workflow_side_effects() -> None:
    abort = AbortToken()
    abort.request("manual stop")
    workflow = _Workflow(_report())

    with pytest.raises(AbortRequested, match="manual stop"):
        _task("opsi_daily", workflow).run(_context("opsi_daily", abort=abort))

    assert workflow.calls == 0


def test_abort_after_safe_workflow_return_preserves_checkpoint_and_stops_next_entry() -> None:
    abort = AbortToken()
    cursor = WorldMissionCursor(WorldMissionEvidenceKind.PINNED_ZONE, 3)
    workflow = _Workflow(
        _report(
            WorldTaskStatus.IN_PROGRESS,
            completed_units=1,
            cursor=cursor,
        ),
        on_execute=lambda: _request_abort(abort),
    )
    task = _task("opsi_daily", workflow)

    result = task.run(_context("opsi_daily", abort=abort))

    progress = WorldProgress(
        task_id=TaskId("opsi_daily"),
        operation=WorldOperation.DAILY,
        completed_units=1,
        cycle_anchor=_SERVER_UPDATE_AT,
        settings_revision=1,
        content_revision="content-1",
        cursor=cursor,
    )
    assert result == TaskResult(
        outcome=Deferred("operation siren completed one safe unit"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(
            UpsertTaskState(
                "opsi_daily",
                "world_progress",
                1,
                progress.to_payload(),
            ),
        ),
    )

    with pytest.raises(AbortRequested, match="stop after current action"):
        task.run(_context("opsi_daily", abort=abort))

    assert workflow.calls == 1


def test_workflow_receives_the_same_abort_signal_from_context() -> None:
    abort = AbortToken()
    workflow = _Workflow(_report())

    _task("opsi_daily", workflow).run(_context("opsi_daily", abort=abort))

    assert workflow.received_cancellation is abort


def test_task_rejects_wrong_context_id_and_invalid_workflow_report() -> None:
    task = _task("opsi_daily", _Workflow(_report()))
    with pytest.raises(ValueError, match="must match WorldTaskSpec"):
        task.run(_context("opsi_shop"))

    invalid = OperationSirenTask(
        cast("OperationSirenWorkflow", _Workflow(object())),
        world_task_spec(TaskId("opsi_daily"), _SETTINGS_BY_TASK["opsi_daily"]),
    )
    with pytest.raises(TypeError, match=r"Workflow\.execute\(\) must return a WorldTaskReport"):
        invalid.run(_context("opsi_daily"))


def test_unknown_task_and_invalid_spec_fail_at_the_boundary() -> None:
    with pytest.raises(KeyError, match="unknown Operation Siren task"):
        world_task_spec(TaskId("campaign"), _SETTINGS_BY_TASK["opsi_daily"])
    with pytest.raises(ValueError, match="task_id must match operation"):
        WorldTaskSpec(
            task_id=TaskId("opsi_daily"),
            operation=WorldOperation.SHOP,
            completion_refresh=RefreshPolicy.SERVER_UPDATE,
            empty_refresh=RefreshPolicy.SERVER_UPDATE,
            action_point_policy=ActionPointPolicy.BATCH,
            checkpoint_policy=WORLD_TASK_DEFINITIONS[TaskId("opsi_daily")].checkpoint_policy,
            settings=_SETTINGS_BY_TASK["opsi_daily"],
        )
    with pytest.raises(TypeError, match="opsi_shop settings must be a ShopSettings"):
        world_task_spec(TaskId("opsi_shop"), _SETTINGS_BY_TASK["opsi_daily"])


def test_world_schedule_and_report_require_aware_future_datetimes() -> None:
    naive = datetime(2026, 7, 13, 12)
    with pytest.raises(ValueError, match="timezone-aware"):
        WorldSchedule(naive, _MONTH_RESET_AT, _ARCHIVE_REFRESH_AT)

    invalid_schedule = WorldSchedule(
        next_server_update_at=_OBSERVED_AT,
        next_month_reset_at=_MONTH_RESET_AT,
        next_archive_refresh_at=_ARCHIVE_REFRESH_AT,
    )
    with pytest.raises(ValueError, match="next_server_update_at must be after observed_at"):
        WorldTaskReport(_OBSERVED_AT, WorldTaskStatus.COMPLETED, invalid_schedule)
    with pytest.raises(ValueError, match="retry_at must not be before observed_at"):
        _report(WorldTaskStatus.FAILED, retry_at=_OBSERVED_AT - timedelta(seconds=1))


def test_world_report_rejects_ambiguous_or_invalid_state_payloads() -> None:
    with pytest.raises(ValueError, match="cooldown report requires retry_at"):
        _report(WorldTaskStatus.COOLDOWN)
    with pytest.raises(ValueError, match="affected_task_ids are only valid"):
        _report(WorldTaskStatus.COMPLETED, affected_task_ids=(TaskId("opsi_daily"),))
    with pytest.raises(ValueError, match="must be unique"):
        _report(
            WorldTaskStatus.COOLDOWN,
            retry_at=_RETRY_AT,
            affected_task_ids=(TaskId("opsi_daily"), TaskId("opsi_daily")),
        )
    with pytest.raises(ValueError, match="completed_units must be non-negative"):
        WorldTaskReport(_OBSERVED_AT, WorldTaskStatus.COMPLETED, _schedule(), completed_units=-1)
    with pytest.raises(ValueError, match="at most one safe unit"):
        WorldTaskReport(_OBSERVED_AT, WorldTaskStatus.COMPLETED, _schedule(), completed_units=2)
    with pytest.raises(TypeError, match="has_surplus_yellow_coins must be a bool"):
        WorldTaskReport(
            _OBSERVED_AT,
            WorldTaskStatus.COMPLETED,
            _schedule(),
            has_surplus_yellow_coins=cast("bool", 1),
        )


def test_cross_month_rejects_a_calendar_without_a_future_ten_minute_window() -> None:
    observed_at = datetime(2026, 7, 31, 23, 55, tzinfo=UTC)
    report = WorldTaskReport(
        observed_at=observed_at,
        status=WorldTaskStatus.EMPTY,
        schedule=WorldSchedule(
            next_server_update_at=datetime(2026, 8, 1, 4, tzinfo=UTC),
            next_month_reset_at=datetime(2026, 8, 1, tzinfo=UTC),
            next_archive_refresh_at=datetime(2026, 8, 5, tzinfo=UTC),
        ),
    )

    with pytest.raises(ValueError, match="cross-month window must be after observed_at"):
        _task("opsi_cross_month", _Workflow(report)).run(_context("opsi_cross_month"))
