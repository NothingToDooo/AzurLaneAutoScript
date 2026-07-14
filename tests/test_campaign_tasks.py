from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    Blocked,
    DailySchedule,
    Deferred,
    DelayRange,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
    OperatorNotificationKind,
    OperatorNotificationRequest,
    PreemptionRequest,
    RequestAppRestart,
    RescheduleSelf,
    Retryable,
    RunId,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
    UpsertTaskState,
    WakePolicy,
    WakeTask,
)
from module.content.battle_policy import BattlePolicy
from module.content.battle_program import (
    BattleProgram,
    BattleProgramDelegation,
    BattleProgramMode,
    NamedProgramMarker,
    ProgramBattleSettled,
    ProgramBattleTarget,
    ProgramDelegated,
    ProgramFlag,
    ReturnProgramContinue,
)
from module.content.campaign_session import (
    BattlefieldObservation,
    BattleSucceeded,
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
    CampaignSessionStatus,
    RemainingSpawns,
)
from module.content.campaign_session_source import CampaignStageSelection
from module.content.models import StageRef
from module.content.stage_definition import (
    CampaignStageDefinition,
    CellId,
    CellSpec,
    GridShape,
    MapDefinition,
    RunVariant,
    SpawnWave,
)
from module.content.stage_rules import MapFeatures, RepeatableCompletion, StageRules, StarRequirements
from module.gameplay.battle_program import BattleProgramExecution, BattleProgramReducer
from module.gameplay.campaign import (
    CAMPAIGN_JOB_KINDS,
    CampaignAutomationSettings,
    CampaignDifficulty,
    CampaignEmotionSettings,
    CampaignEnemyPrioritySettings,
    CampaignExecutionSettings,
    CampaignFleetEmotionSettings,
    CampaignFleetSettings,
    CampaignHpControlSettings,
    CampaignJobKind,
    CampaignJobSpec,
    CampaignLimits,
    CampaignMapAchievement,
    CampaignProgress,
    CampaignRunReport,
    CampaignStopReason,
    CampaignSubmarineSettings,
    CampaignTask,
    CampaignWorkflow,
    EmotionControl,
    EmotionMode,
    EmotionRecoverLocation,
    EnemyPriorityMode,
    FleetMode,
    FleetOrder,
    GemsCommonCarrier,
    GemsCommonDestroyer,
    GemsFarmingPolicy,
    GemsFlagshipChange,
    GemsFleetReplacementBoundary,
    GemsFleetReplacementRequest,
    GemsFleetReplacementTrigger,
    GemsVanguardChange,
    PreemptionSignal,
    SubmarineAutoSearchMode,
    SubmarineDistanceToBoss,
    SubmarineMode,
    TaskBalancerPolicy,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.interaction import CancellationSignal


_OBSERVED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)
_STARTED_AT = datetime(2026, 7, 13, 11, 59, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 13, 20, tzinfo=UTC)
_DAILY_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(4),))
_FAILURE_RETRY = timedelta(minutes=30)
_FAILURE_RETRY_RANGE = DelayRange(1_800, 1_800)
_RESOURCE_RETRY = timedelta(minutes=180)


def _execution() -> CampaignExecutionSettings:
    fleet_emotion = CampaignFleetEmotionSettings(
        value=119,
        recorded_at=_OBSERVED_AT,
        control=EmotionControl.PREVENT_GREEN_FACE,
        recover=EmotionRecoverLocation.NOT_IN_DORMITORY,
        oath=False,
    )
    return CampaignExecutionSettings(
        automation=CampaignAutomationSettings(
            ambush_evade=True,
            use_2x_book=False,
            use_auto_search=True,
            use_clear_mode=True,
            use_fleet_lock=True,
        ),
        fleets=CampaignFleetSettings(
            fleet1=1,
            fleet1_mode=FleetMode.COMBAT_AUTO,
            fleet1_step=3,
            fleet2=2,
            fleet2_mode=FleetMode.COMBAT_AUTO,
            fleet2_step=2,
            order=FleetOrder.FLEET1_MOB_FLEET2_BOSS,
        ),
        submarine=CampaignSubmarineSettings(
            fleet=0,
            mode=SubmarineMode.DO_NOT_USE,
            auto_search_mode=SubmarineAutoSearchMode.STANDBY,
            distance_to_boss=SubmarineDistanceToBoss.TWO_GRIDS_TO_BOSS,
        ),
        emotion=CampaignEmotionSettings(
            mode=EmotionMode.CALCULATE,
            fleet1=fleet_emotion,
            fleet2=fleet_emotion,
        ),
        hp_control=CampaignHpControlSettings(
            use_hp_balance=False,
            use_emergency_repair=False,
            use_low_hp_retreat=False,
            hp_balance_threshold=0.2,
            hp_balance_weight=(1_000, 1_000, 1_000),
            repair_use_single_threshold=0.3,
            repair_use_multi_threshold=0.6,
            low_hp_retreat_threshold=0.3,
        ),
        enemy_priority=CampaignEnemyPrioritySettings(EnemyPriorityMode.DEFAULT),
    )


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
        self.discard_calls = 0
        self.received_job: CampaignJobSpec | None = None

    def discard_checkpoint(self) -> None:
        self.discard_calls += 1

    def execute(
        self,
        job: CampaignJobSpec,
        cancellation: CancellationSignal,
        preemption: PreemptionSignal,
    ) -> CampaignRunReport:
        cancellation.raise_if_requested()
        assert not preemption.is_requested
        self.calls += 1
        self.received_job = job
        if self._on_execute is not None:
            self._on_execute()
        return cast("CampaignRunReport", self._report)


def _session(
    pack_id: str = "campaign_main",
    stage_id: str = "1-1",
    variant: CampaignRunVariant = CampaignRunVariant.NORMAL,
    spawn_waves: tuple[SpawnWave, ...] | None = None,
) -> CampaignSession:
    cells = (CellSpec(CellId(0, 0), "MB", 1.0),)
    waves = (SpawnWave(battle=0, boss=1),) if spawn_waves is None else spawn_waves
    run_variant = RunVariant(cells=cells, spawn_waves=waves)
    definition = CampaignStageDefinition(
        ref=StageRef(pack_id, stage_id),
        map=MapDefinition(
            name=stage_id,
            shape=GridShape(1, 1),
            camera_data=(),
            camera_data_spawn_point=(),
            normal=run_variant,
            loop=run_variant,
        ),
        rules=StageRules(
            features=MapFeatures(
                siren_templates=(),
                movable_enemy_turns=(),
                has_siren=False,
                has_movable_enemy=False,
                has_map_story=False,
                has_fleet_step=False,
                has_ambush=False,
                has_mystery=False,
            ),
            completion=RepeatableCompletion(StarRequirements()),
        ),
        enemy_filter="1L > 1M > 1E",
        battle_policies={wave.battle: BattlePolicy("fleet_boss") for wave in waves if wave.boss},
    )
    return CampaignSession(definition, variant)


def _spec(
    task_id: str = "main",
    *,
    sessions: tuple[CampaignSession, ...] | None = None,
    limits: CampaignLimits | None = None,
    task_balancer: TaskBalancerPolicy | None = None,
    progress: CampaignProgress | None = None,
) -> CampaignJobSpec:
    gems_policy = None
    if task_id == "gems_farming":
        if sessions is None:
            sessions = (_session("event_20260625_cn", "d3"),)
        gems_policy = GemsFarmingPolicy(
            fallback_session=_session("campaign_main", "2-4"),
            flagship_change=GemsFlagshipChange.SHIP,
            common_carrier=GemsCommonCarrier.ANY,
            vanguard_change=GemsVanguardChange.SHIP,
            common_destroyer=GemsCommonDestroyer.ANY,
            equipment_code_config="DD: null",
        )
    elif sessions is None:
        sessions = (_session(),)
    by_ref = {item.definition.ref: item.definition for item in sessions}
    complete_sessions = tuple(
        CampaignSession(definition, variant) for definition in by_ref.values() for variant in CampaignRunVariant
    )
    return CampaignJobSpec(
        task_id=TaskId(task_id),
        sessions=complete_sessions,
        difficulty=CampaignDifficulty.NORMAL,
        execution=_execution(),
        schedule=_DAILY_SCHEDULE,
        failure_retry_delay=_FAILURE_RETRY_RANGE,
        resource_retry_delay=_RESOURCE_RETRY,
        limits=CampaignLimits() if limits is None else limits,
        task_balancer=task_balancer,
        gems_farming=gems_policy,
        progress=progress,
    )


def _completed_state(session: CampaignSession) -> CampaignSessionState:
    decision = session.decide(
        session.initial_state(),
        BattlefieldObservation(battle_index=0, boss=1),
    )
    assert decision.command is not None
    return session.reduce(
        decision.state,
        BattleSucceeded(decision.command, BattleTarget.BOSS),
    )


def _succeed_battle(
    session: CampaignSession,
    state: CampaignSessionState,
    *,
    target: BattleTarget,
) -> CampaignSessionState:
    observation = BattlefieldObservation(
        battle_index=state.battle_index,
        enemy=1 if target is BattleTarget.ENEMY else 0,
        siren=1 if target is BattleTarget.SIREN else 0,
        boss=1 if target is BattleTarget.BOSS else 0,
    )
    decision = session.decide(state, observation)
    assert decision.command is not None
    return session.reduce(decision.state, BattleSucceeded(decision.command, target))


def _progress(  # noqa: PLR0913 - 测试工厂显式暴露 checkpoint 维度。
    *,
    session: CampaignSession | None = None,
    runs_completed: int = 0,
    settings_revision: int = 1,
    content_revision: str = "content-1",
    state: CampaignSessionState | None = None,
    pending_gems_replacement: GemsFleetReplacementRequest | None = None,
) -> CampaignProgress:
    selected = _session() if session is None else session
    return CampaignProgress(
        stage_ref=selected.definition.ref,
        variant=selected.variant,
        session_state=selected.initial_state() if state is None else state,
        runs_completed=runs_completed,
        settings_revision=settings_revision,
        content_revision=content_revision,
        pending_gems_replacement=pending_gems_replacement,
    )


def _report(  # noqa: PLR0913 - 测试工厂显式暴露 report 维度。
    reason: CampaignStopReason,
    *,
    runs_completed: int = 0,
    session: CampaignSession | None = None,
    session_state: CampaignSessionState | None = None,
    observed_at: datetime = _OBSERVED_AT,
    gems_replacement: GemsFleetReplacementRequest | None = None,
) -> CampaignRunReport:
    selected = _session() if session is None else session
    state = session_state
    if state is None:
        state = _completed_state(selected) if runs_completed else selected.initial_state()
    return CampaignRunReport(
        stage_ref=selected.definition.ref,
        observed_at=observed_at,
        stop_reason=reason,
        session_state=state,
        runs_completed=runs_completed,
        gems_replacement=gems_replacement,
    )


def _stage_increase_report(next_stage_ref: StageRef) -> CampaignRunReport:
    selected = _session()
    return CampaignRunReport(
        stage_ref=selected.definition.ref,
        observed_at=_OBSERVED_AT,
        stop_reason=CampaignStopReason.STAGE_INCREASE,
        session_state=selected.initial_state(),
        runs_completed=0,
        next_stage_ref=next_stage_ref,
    )


def _delete_effect(task_id: str = "main") -> DeleteTaskState:
    return DeleteTaskState(task_id, "progress")


def _progress_effect(progress: CampaignProgress, task_id: str = "main") -> UpsertTaskState:
    state = progress.session_state
    return UpsertTaskState(
        namespace=task_id,
        key="progress",
        schema_version=4,
        payload={
            "stage_ref": {
                "pack_id": progress.stage_ref.pack_id,
                "stage_id": progress.stage_ref.stage_id,
            },
            "variant": progress.variant.value,
            "session_state": {
                "variant": state.variant.value,
                "status": state.status.value,
                "battle_index": state.battle_index,
                "remaining": {
                    "enemy": state.remaining.enemy,
                    "siren": state.remaining.siren,
                    "mystery": state.remaining.mystery,
                    "boss": state.remaining.boss,
                },
                "next_attempt_id": state.next_attempt_id,
                "next_intent_index": state.next_intent_index,
                "pending": None,
                "reason": state.reason,
                "program_state_initialized": state.program_state_initialized,
                "program_flags": sorted(flag.value for flag in state.program_flags),
                "program_markers": sorted(marker.value for marker in state.program_markers),
            },
            "runs_completed": progress.runs_completed,
            "settings_revision": progress.settings_revision,
            "content_revision": progress.content_revision,
            "pending_gems_replacement": (
                None
                if progress.pending_gems_replacement is None
                else {
                    "trigger": progress.pending_gems_replacement.trigger.value,
                    "boundary": progress.pending_gems_replacement.boundary.value,
                }
            ),
        },
    )


def _context(
    task_id: str,
    *,
    mode: ExecutionMode = ExecutionMode.SCHEDULED_JOB,
    abort: AbortToken | None = None,
    preemption: PreemptionRequest | None = None,
) -> TaskContext:
    return TaskContext(
        task_id=TaskId(task_id),
        run_id=RunId(f"run-{task_id}"),
        started_at=_STARTED_AT,
        mode=mode,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1", client_ui_revision="ui-1"),
        abort=AbortToken() if abort is None else abort,
        preemption=PreemptionRequest() if preemption is None else preemption,
    )


def _case_for_stop_reason(
    reason: CampaignStopReason,
) -> tuple[str, CampaignJobSpec, CampaignRunReport]:
    if reason is CampaignStopReason.PROGRAM_CONTINUE:
        base = _session()
        definition = replace(
            base.definition,
            battle_programs={
                0: BattleProgram(
                    0,
                    frozenset({BattleProgramMode.NORMAL}),
                    (ReturnProgramContinue(),),
                )
            },
        )
        session = CampaignSession(definition, CampaignRunVariant.NORMAL)
        state = replace(session.initial_state(), program_state_initialized=True)
        report = _report(
            CampaignStopReason.PROGRAM_CONTINUE,
            session=session,
            session_state=state,
        )
        return "main", _spec(sessions=(session,)), report

    if reason is CampaignStopReason.STAGE_INCREASE:
        next_ref = StageRef("campaign_main", "1-2")
        next_definition = _session(next_ref.pack_id, next_ref.stage_id).definition
        transition_sessions = tuple(CampaignSession(next_definition, variant) for variant in CampaignRunVariant)
        job = replace(
            _spec(
                limits=CampaignLimits(
                    map_achievement=CampaignMapAchievement.FULL_CLEAR,
                    stage_increase=True,
                ),
            ),
            stage_selections=(
                CampaignStageSelection(
                    StageRef("campaign_main", "1-1"),
                    StageRef("campaign_main", "1-1"),
                    next_ref=next_ref,
                ),
            ),
            transition_sessions=transition_sessions,
        )
        return "main", job, _stage_increase_report(next_ref)

    gems_job = _spec("gems_farming")
    gems_policy = gems_job.gems_farming
    assert gems_policy is not None
    gems_fallback = gems_job.session_for(
        gems_policy.fallback_session.definition.ref,
        CampaignRunVariant.NORMAL,
    )
    assert gems_fallback is not None
    level_replacement = GemsFleetReplacementRequest(
        GemsFleetReplacementTrigger.LEVEL,
        GemsFleetReplacementBoundary.POST_MAP,
    )
    emotion_replacement = GemsFleetReplacementRequest(
        GemsFleetReplacementTrigger.EMOTION,
        GemsFleetReplacementBoundary.POST_MAP,
    )
    hard_replacement = GemsFleetReplacementRequest(
        GemsFleetReplacementTrigger.HARD_PREPARATION,
        GemsFleetReplacementBoundary.PRE_ENTRY,
    )
    cases = {
        CampaignStopReason.IN_PROGRESS: (
            "main",
            _spec(),
            _report(reason, runs_completed=1),
        ),
        CampaignStopReason.RUN_COUNT_LIMIT: (
            "main",
            _spec(limits=CampaignLimits(run_count=1)),
            _report(reason, runs_completed=1),
        ),
        CampaignStopReason.REACH_LEVEL_LIMIT: (
            "main",
            _spec(limits=CampaignLimits(reach_level=120)),
            _report(reason),
        ),
        CampaignStopReason.NEW_SHIP: (
            "main",
            _spec(limits=CampaignLimits(stop_on_new_ship=True)),
            _report(reason),
        ),
        CampaignStopReason.EVENT_POINT_LIMIT: (
            "event",
            _spec("event", limits=CampaignLimits(event_points=100_000)),
            _report(reason),
        ),
        CampaignStopReason.EVENT_TIME_LIMIT: (
            "event",
            _spec(
                "event",
                limits=CampaignLimits(event_deadline_at=_OBSERVED_AT - timedelta(seconds=1)),
            ),
            _report(reason),
        ),
        CampaignStopReason.EVENT_UNAVAILABLE: (
            "event",
            _spec("event"),
            _report(reason),
        ),
        CampaignStopReason.NO_ELIGIBLE_STAGE: (
            "event_a",
            _spec("event_a"),
            _report(reason),
        ),
        CampaignStopReason.DATA_KEYS_EXHAUSTED: (
            "war_archives",
            _spec("war_archives"),
            _report(reason),
        ),
        CampaignStopReason.COIN_LIMIT: (
            "main",
            _spec(task_balancer=TaskBalancerPolicy(TaskId("commission"), coin_limit=20_000)),
            _report(reason, runs_completed=1),
        ),
        CampaignStopReason.MAP_ACHIEVEMENT: (
            "main",
            _spec(limits=CampaignLimits(map_achievement=CampaignMapAchievement.FULL_CLEAR)),
            _report(CampaignStopReason.MAP_ACHIEVEMENT),
        ),
        CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED: (
            "gems_farming",
            gems_job,
            _report(
                reason,
                runs_completed=1,
                session=gems_job.sessions[0],
                gems_replacement=level_replacement,
            ),
        ),
        CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED: (
            "gems_farming",
            gems_job,
            _report(
                reason,
                runs_completed=1,
                session=gems_job.sessions[0],
                gems_replacement=emotion_replacement,
            ),
        ),
        CampaignStopReason.GEMS_HARD_PREPARATION_FAILED: (
            "gems_farming",
            gems_job,
            _report(
                reason,
                session=gems_job.sessions[0],
                gems_replacement=hard_replacement,
            ),
        ),
        CampaignStopReason.GEMS_FLEET_REPLACED: (
            "gems_farming",
            gems_job,
            _report(
                reason,
                session=gems_job.sessions[0],
                gems_replacement=GemsFleetReplacementRequest(
                    GemsFleetReplacementTrigger.EMOTION,
                    GemsFleetReplacementBoundary.PRE_ENTRY,
                ),
            ),
        ),
        CampaignStopReason.GEMS_EVENT_FALLBACK: (
            "gems_farming",
            gems_job,
            _report(reason, session=gems_fallback),
        ),
    }
    case = cases.get(reason)
    if case is not None:
        return case
    return "main", _spec(), _report(reason)


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("event_sp", CampaignJobKind.EVENT_SP),
        ("event_a", CampaignJobKind.EVENT_DAILY),
        ("event_b", CampaignJobKind.EVENT_DAILY),
        ("event_c", CampaignJobKind.EVENT_DAILY),
        ("event_d", CampaignJobKind.EVENT_DAILY),
        ("main", CampaignJobKind.STANDARD),
        ("main2", CampaignJobKind.STANDARD),
        ("main3", CampaignJobKind.STANDARD),
        ("event", CampaignJobKind.EVENT),
        ("event2", CampaignJobKind.EVENT),
        ("war_archives", CampaignJobKind.WAR_ARCHIVES),
        ("gems_farming", CampaignJobKind.GEMS_FARMING),
    ],
)
def test_every_campaign_scheduler_command_maps_to_one_job_kind(command: str, kind: CampaignJobKind) -> None:
    assert CAMPAIGN_JOB_KINDS[TaskId(command)] is kind


def test_hard_is_owned_by_the_encounter_domain() -> None:
    assert TaskId("hard") not in CAMPAIGN_JOB_KINDS


def test_standard_campaign_passes_compiled_session_to_workflow() -> None:
    job = _spec()
    workflow = _Workflow(_report(CampaignStopReason.COMPLETED, runs_completed=1))

    result = CampaignTask(workflow, job).run(_context("main"))

    assert workflow.calls == 1
    assert workflow.received_job is job
    assert job.stage_refs == (StageRef("campaign_main", "1-1"),)
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(_delete_effect(),),
    )


def test_in_progress_map_clear_commits_fresh_session_and_accumulated_run_budget() -> None:
    session = _session()
    report = _report(CampaignStopReason.IN_PROGRESS, runs_completed=1, session=session)

    result = CampaignTask(_Workflow(report), _spec(sessions=(session,))).run(_context("main"))

    checkpoint = _progress(session=session, runs_completed=1)
    assert result == TaskResult(
        outcome=Deferred("campaign battle batch is still in progress"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_progress_effect(checkpoint),),
    )


def test_resumed_campaign_confirms_one_battle_and_preserves_cumulative_budget() -> None:
    session = _session(
        spawn_waves=(
            SpawnWave(battle=0, enemy=1),
            SpawnWave(battle=1, boss=1),
        )
    )
    after_first_battle = _succeed_battle(session, session.initial_state(), target=BattleTarget.ENEMY)
    previous = _progress(session=session, runs_completed=2, state=after_first_battle)
    completed = _succeed_battle(session, after_first_battle, target=BattleTarget.BOSS)
    report = _report(
        CampaignStopReason.IN_PROGRESS,
        runs_completed=1,
        session=session,
        session_state=completed,
    )

    result = CampaignTask(
        _Workflow(report),
        _spec(sessions=(session,), progress=previous),
    ).run(_context("main"))

    checkpoint = _progress(session=session, runs_completed=3)
    assert result.state_effects == (_progress_effect(checkpoint),)


@pytest.mark.parametrize(
    "progress",
    [
        _progress(settings_revision=2),
        _progress(content_revision="content-2"),
        _progress(session=_session(stage_id="1-2")),
    ],
)
def test_stale_campaign_progress_is_deleted_before_external_work(progress: CampaignProgress) -> None:
    workflow = _Workflow(_report(CampaignStopReason.COMPLETED))

    result = CampaignTask(workflow, _spec(progress=progress)).run(_context("main"))

    assert workflow.calls == 0
    assert workflow.discard_calls == 1
    assert result == TaskResult(
        outcome=Deferred("stale campaign progress was discarded"),
        effects=(RescheduleSelf(_STARTED_AT),),
        state_effects=(_delete_effect(),),
    )


def test_physically_unavailable_campaign_checkpoint_is_deleted_and_retried_immediately() -> None:
    session = _session()
    progress = _progress(session=session, runs_completed=2)
    report = _report(
        CampaignStopReason.CHECKPOINT_UNAVAILABLE,
        session=session,
        session_state=progress.session_state,
    )

    result = CampaignTask(_Workflow(report), _spec(sessions=(session,), progress=progress)).run(_context("main"))

    assert result == TaskResult(
        outcome=Deferred("campaign client session no longer matches its checkpoint"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_delete_effect(),),
    )


def test_preemption_at_a_restored_safe_point_atomically_preserves_progress() -> None:
    progress = _progress(runs_completed=2)
    preemption = PreemptionRequest()
    preemption.request("higher priority task")
    workflow = _Workflow(_report(CampaignStopReason.COMPLETED))

    result = CampaignTask(workflow, _spec(progress=progress)).run(_context("main", preemption=preemption))

    assert workflow.calls == 0
    assert result == TaskResult(
        outcome=Deferred("campaign yielded at a safe point"),
        effects=(RescheduleSelf(_STARTED_AT),),
        state_effects=(_progress_effect(progress),),
    )


def test_campaign_report_cannot_cross_two_battle_safe_units() -> None:
    session = _session(
        spawn_waves=(
            SpawnWave(battle=0, enemy=1),
            SpawnWave(battle=1, boss=1),
        )
    )
    after_first = _succeed_battle(session, session.initial_state(), target=BattleTarget.ENEMY)
    after_second = _succeed_battle(session, after_first, target=BattleTarget.BOSS)
    report = _report(
        CampaignStopReason.COMPLETED,
        runs_completed=1,
        session=session,
        session_state=after_second,
    )

    with pytest.raises(ValueError, match="more than one battle safe unit"):
        CampaignTask(_Workflow(report), _spec(sessions=(session,))).run(_context("main"))


def test_campaign_report_accepts_a_generic_program_safe_unit() -> None:
    session = _session(
        spawn_waves=(
            SpawnWave(battle=0, enemy=1),
            SpawnWave(battle=1, boss=1),
        )
    )
    marker = NamedProgramMarker("runtime.clear-all")
    state = BattleProgramReducer.reduce(
        session,
        session.initial_state(),
        BattleProgramExecution(
            ProgramBattleSettled(ProgramBattleTarget.ENEMY),
            frozenset({ProgramFlag.CLEAR_ALL}),
            frozenset({marker}),
        ),
    )
    report = _report(
        CampaignStopReason.IN_PROGRESS,
        session=session,
        session_state=state,
    )

    result = CampaignTask(_Workflow(report), _spec(sessions=(session,))).run(_context("main"))

    checkpoint = cast("UpsertTaskState", result.state_effects[0])
    payload = cast("dict[str, object]", checkpoint.payload)
    session_payload = cast("dict[str, object]", payload["session_state"])
    assert session_payload["program_markers"] == (marker.value,)


def test_program_reducer_completes_immediately_after_an_early_boss() -> None:
    session = _session(
        spawn_waves=(
            SpawnWave(battle=0, enemy=1, boss=1),
            SpawnWave(battle=1, enemy=3),
        )
    )

    completed = BattleProgramReducer.reduce(
        session,
        session.initial_state(),
        BattleProgramExecution(
            ProgramBattleSettled(ProgramBattleTarget.BOSS),
            frozenset(),
        ),
    )

    assert completed.status is CampaignSessionStatus.COMPLETED
    assert completed.battle_index == 1
    assert completed.remaining == RemainingSpawns(enemy=1)
    session.validate_state(completed)


def test_program_reducer_keeps_a_boss_map_active_past_its_spawn_schedule() -> None:
    session = _session(spawn_waves=(SpawnWave(battle=0, enemy=1, boss=1),))

    after_enemy = BattleProgramReducer.reduce(
        session,
        session.initial_state(),
        BattleProgramExecution(
            ProgramBattleSettled(ProgramBattleTarget.ENEMY),
            frozenset(),
        ),
    )
    completed = BattleProgramReducer.reduce(
        session,
        after_enemy,
        BattleProgramExecution(
            ProgramBattleSettled(ProgramBattleTarget.BOSS),
            frozenset(),
        ),
    )

    assert after_enemy.status is CampaignSessionStatus.ACTIVE
    assert after_enemy.battle_index == 1
    assert after_enemy.remaining == RemainingSpawns(boss=1)
    assert completed.status is CampaignSessionStatus.COMPLETED
    assert completed.battle_index == 2


def test_campaign_report_accepts_program_facts_followed_by_one_delegated_stage_policy() -> None:
    session = _session(
        spawn_waves=(
            SpawnWave(battle=0, enemy=1),
            SpawnWave(battle=1, boss=1),
        )
    )
    marker = NamedProgramMarker("runtime.delegated")
    delegated = BattleProgramReducer.reduce(
        session,
        session.initial_state(),
        BattleProgramExecution(
            ProgramDelegated(BattleProgramDelegation.STAGE_POLICY),
            frozenset({ProgramFlag.CLEAR_MODE}),
            frozenset({marker}),
        ),
    )
    state = _succeed_battle(session, delegated, target=BattleTarget.ENEMY)
    report = _report(
        CampaignStopReason.IN_PROGRESS,
        session=session,
        session_state=state,
    )

    result = CampaignTask(_Workflow(report), _spec(sessions=(session,))).run(_context("main"))

    checkpoint = cast("UpsertTaskState", result.state_effects[0])
    payload = cast("dict[str, object]", checkpoint.payload)
    session_payload = cast("dict[str, object]", payload["session_state"])
    assert session_payload["program_markers"] == (marker.value,)


def test_campaign_report_rejects_an_unconfirmed_pending_action() -> None:
    session = _session()
    decision = session.decide(
        session.initial_state(),
        BattlefieldObservation(battle_index=0, boss=1),
    )

    with pytest.raises(ValueError, match="pending battle attempt"):
        _report(
            CampaignStopReason.IN_PROGRESS,
            session=session,
            session_state=decision.state,
        )


@pytest.mark.parametrize("task_id", ["event_sp", "event_a", "event_b", "event_c", "event_d"])
def test_daily_campaign_commands_wait_for_the_next_server_update(task_id: str) -> None:
    result = CampaignTask(_Workflow(_report(CampaignStopReason.COMPLETED, runs_completed=1)), _spec(task_id)).run(
        _context(task_id)
    )

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(_delete_effect(task_id),),
    )


def test_daily_completion_uses_the_strict_trigger_after_the_report_observation() -> None:
    observed_at_trigger = datetime(2026, 7, 13, 20, tzinfo=UTC)
    next_trigger = datetime(2026, 7, 14, 20, tzinfo=UTC)
    report = _report(CampaignStopReason.COMPLETED, observed_at=observed_at_trigger)

    result = CampaignTask(_Workflow(report), _spec()).run(_context("main"))

    assert result.effects == (RescheduleSelf(next_trigger),)


def test_run_count_exhaustion_disables_the_campaign() -> None:
    limits = CampaignLimits(run_count=2)
    session = _session()
    report = _report(CampaignStopReason.RUN_COUNT_LIMIT, runs_completed=1, session=session)

    result = CampaignTask(
        _Workflow(report),
        _spec(sessions=(session,), limits=limits, progress=_progress(session=session, runs_completed=1)),
    ).run(_context("main"))

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(DisableTask(TaskId("main")),),
        state_effects=(_delete_effect(),),
        notifications=(
            OperatorNotificationRequest(
                OperatorNotificationKind.CAMPAIGN_RUN_COUNT_LIMIT,
                resource="campaign_main/1-1",
            ),
        ),
    )


@pytest.mark.parametrize(
    "reason",
    [CampaignStopReason.OIL_LIMIT, CampaignStopReason.AUTO_SEARCH_OIL_LIMIT],
)
def test_oil_limits_use_the_legacy_two_to_four_hour_resource_retry(reason: CampaignStopReason) -> None:
    result = CampaignTask(_Workflow(_report(reason)), _spec()).run(_context("main"))

    assert result == TaskResult(
        outcome=Retryable("campaign oil reserve reached its limit"),
        effects=(RescheduleSelf(_OBSERVED_AT + _RESOURCE_RETRY),),
        state_effects=(_delete_effect(),),
    )


@pytest.mark.parametrize(
    ("reason", "limits"),
    [
        (CampaignStopReason.REACH_LEVEL_LIMIT, CampaignLimits(reach_level=120)),
        (CampaignStopReason.NEW_SHIP, CampaignLimits(stop_on_new_ship=True)),
    ],
)
def test_permanent_player_stop_conditions_disable_the_campaign(
    reason: CampaignStopReason,
    limits: CampaignLimits,
) -> None:
    result = CampaignTask(_Workflow(_report(reason)), _spec(limits=limits)).run(_context("main"))

    assert result.effects == (DisableTask(TaskId("main")),)
    expected_kind = {
        CampaignStopReason.REACH_LEVEL_LIMIT: OperatorNotificationKind.CAMPAIGN_REACH_LEVEL_LIMIT,
        CampaignStopReason.NEW_SHIP: OperatorNotificationKind.CAMPAIGN_NEW_SHIP,
    }[reason]
    assert result.notifications == (OperatorNotificationRequest(expected_kind, resource="campaign_main/1-1"),)


def test_event_point_limit_disables_event_raid_coalition_and_hospital_but_not_gems_or_maritime() -> None:
    limits = CampaignLimits(event_points=100_000)

    result = CampaignTask(
        _Workflow(_report(CampaignStopReason.EVENT_POINT_LIMIT)),
        _spec("event", limits=limits),
    ).run(_context("event"))

    disabled = {effect.task_id for effect in result.effects if isinstance(effect, DisableTask)}
    assert result.outcome == Deferred("event point limit was reached")
    assert disabled == {
        TaskId("event"),
        TaskId("event2"),
        TaskId("event_a"),
        TaskId("event_b"),
        TaskId("event_c"),
        TaskId("event_d"),
        TaskId("event_sp"),
        TaskId("raid"),
        TaskId("raid_daily"),
        TaskId("coalition"),
        TaskId("coalition_sp"),
        TaskId("hospital"),
    }
    assert TaskId("gems_farming") not in disabled
    assert TaskId("maritime_escort") not in disabled


def test_event_time_limit_also_disables_maritime_escort() -> None:
    limits = CampaignLimits(event_deadline_at=_OBSERVED_AT - timedelta(seconds=1))

    result = CampaignTask(
        _Workflow(_report(CampaignStopReason.EVENT_TIME_LIMIT)),
        _spec("event2", limits=limits),
    ).run(_context("event2"))

    assert result.outcome == Deferred("event time limit was reached")
    assert DisableTask(TaskId("maritime_escort")) in result.effects


def test_unavailable_event_is_blocked_and_disables_the_full_event_group() -> None:
    result = CampaignTask(
        _Workflow(_report(CampaignStopReason.EVENT_UNAVAILABLE)),
        _spec("event_sp"),
    ).run(_context("event_sp"))

    assert result.outcome == Blocked("event entrance is unavailable")
    assert DisableTask(TaskId("event_sp")) in result.effects
    assert DisableTask(TaskId("maritime_escort")) in result.effects


@pytest.mark.parametrize(
    ("task_id", "reason"),
    [
        ("event_a", CampaignStopReason.NO_ELIGIBLE_STAGE),
        ("event_sp", CampaignStopReason.CONTENT_UNAVAILABLE),
    ],
)
def test_missing_daily_content_blocks_and_disables_only_the_current_task(
    task_id: str,
    reason: CampaignStopReason,
) -> None:
    workflow = _Workflow(_report(reason))
    result = CampaignTask(workflow, _spec(task_id, sessions=())).run(_context(task_id))

    assert workflow.calls == 0
    assert result == TaskResult(
        outcome=Blocked("campaign content is unavailable"),
        effects=(DisableTask(TaskId(task_id)),),
        state_effects=(_delete_effect(task_id),),
    )


def test_war_archives_data_keys_wait_for_server_update() -> None:
    result = CampaignTask(
        _Workflow(_report(CampaignStopReason.DATA_KEYS_EXHAUSTED)),
        _spec("war_archives"),
    ).run(_context("war_archives"))

    assert result == TaskResult(
        outcome=Deferred("war archives data keys are exhausted"),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(_delete_effect("war_archives"),),
    )


def test_task_balancer_delays_campaign_and_forces_the_configured_target() -> None:
    policy = TaskBalancerPolicy(TaskId("commission"), coin_limit=20_000)

    result = CampaignTask(
        _Workflow(_report(CampaignStopReason.COIN_LIMIT, runs_completed=1)),
        _spec(task_balancer=policy),
    ).run(_context("main"))

    assert result == TaskResult(
        outcome=Deferred("campaign coin limit was reached"),
        effects=(
            RescheduleSelf(_OBSERVED_AT + timedelta(minutes=5)),
            WakeTask(TaskId("commission"), _OBSERVED_AT, WakePolicy.FORCE_ENABLE),
        ),
        state_effects=(_delete_effect(),),
    )


def test_emotion_bug_requests_an_app_restart_without_hidden_task_call() -> None:
    result = CampaignTask(_Workflow(_report(CampaignStopReason.EMOTION_BUG)), _spec()).run(_context("main"))

    reason = "campaign detected the emotion calculation bug"
    assert result == TaskResult(
        outcome=Deferred(reason),
        effects=(RescheduleSelf(_OBSERVED_AT), RequestAppRestart(reason)),
        state_effects=(_delete_effect(),),
    )


@pytest.mark.parametrize(
    "reason",
    [CampaignStopReason.ONE_TIME_STAGE, CampaignStopReason.LOOP_STAGE_SWITCH],
)
def test_completion_transitions_wait_for_the_next_daily_trigger(reason: CampaignStopReason) -> None:
    result = CampaignTask(_Workflow(_report(reason)), _spec()).run(_context("main"))

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(_delete_effect(),),
    )


@pytest.mark.parametrize(
    "reason",
    [
        CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
        CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED,
    ],
)
def test_gems_farming_fleet_replacement_failure_retries_after_thirty_minutes(
    reason: CampaignStopReason,
) -> None:
    job = _spec("gems_farming")
    trigger = (
        GemsFleetReplacementTrigger.LEVEL
        if reason is CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED
        else GemsFleetReplacementTrigger.EMOTION
    )
    replacement = GemsFleetReplacementRequest(trigger, GemsFleetReplacementBoundary.POST_MAP)

    result = CampaignTask(
        _Workflow(
            _report(
                reason,
                runs_completed=1,
                session=job.sessions[0],
                gems_replacement=replacement,
            )
        ),
        job,
    ).run(_context("gems_farming"))

    policy = cast("GemsFarmingPolicy", job.gems_farming)
    assert policy.fallback_session.definition.ref == StageRef("campaign_main", "2-4")
    assert policy.level_cap == 32
    assert policy.emotion_after_replacement == 150
    assert result == TaskResult(
        outcome=Retryable("gems farming fleet replacement failed"),
        effects=(RescheduleSelf(_OBSERVED_AT + timedelta(minutes=30)),),
        state_effects=(
            _progress_effect(
                _progress(
                    session=job.sessions[0],
                    runs_completed=1,
                    pending_gems_replacement=replacement,
                ),
                "gems_farming",
            ),
        ),
    )


def test_gems_replacement_failure_rejects_a_battle_free_report() -> None:
    job = _spec("gems_farming")

    with pytest.raises(ValueError, match="post_map confirmed 0 battle units"):
        CampaignTask(
            _Workflow(
                _report(
                    CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED,
                    session=job.sessions[0],
                    gems_replacement=GemsFleetReplacementRequest(
                        GemsFleetReplacementTrigger.LEVEL,
                        GemsFleetReplacementBoundary.POST_MAP,
                    ),
                )
            ),
            job,
        ).run(_context("gems_farming"))


def test_successful_retry_clears_pending_gems_replacement_without_losing_run_count() -> None:
    base = _spec("gems_farming")
    session = base.sessions[0]
    pending = GemsFleetReplacementRequest(
        GemsFleetReplacementTrigger.LEVEL,
        GemsFleetReplacementBoundary.POST_MAP,
    )
    progress = _progress(
        session=session,
        runs_completed=2,
        pending_gems_replacement=pending,
    )
    job = replace(base, progress=progress)
    report = _report(
        CampaignStopReason.GEMS_FLEET_REPLACED,
        session=session,
        gems_replacement=pending,
    )

    result = CampaignTask(_Workflow(report), job).run(_context("gems_farming"))

    assert result == TaskResult(
        outcome=Deferred("gems farming fleet replacement completed at a map boundary"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(
            _progress_effect(
                _progress(session=session, runs_completed=2),
                "gems_farming",
            ),
        ),
    )


def test_gems_workflow_must_absorb_event_end_and_switch_to_fallback() -> None:
    job = _spec(
        "gems_farming",
        limits=CampaignLimits(event_deadline_at=_OBSERVED_AT - timedelta(minutes=1)),
    )

    with pytest.raises(ValueError, match="must switch to its fallback session"):
        CampaignTask(
            _Workflow(_report(CampaignStopReason.EVENT_TIME_LIMIT, session=job.sessions[0])),
            job,
        ).run(_context("gems_farming"))


def test_gems_event_fallback_checkpoints_the_exact_normal_session() -> None:
    job = _spec("gems_farming")
    policy = cast("GemsFarmingPolicy", job.gems_farming)
    fallback = job.session_for(policy.fallback_session.definition.ref, CampaignRunVariant.NORMAL)
    assert fallback is not None

    result = CampaignTask(
        _Workflow(_report(CampaignStopReason.GEMS_EVENT_FALLBACK, session=fallback)),
        job,
    ).run(_context("gems_farming"))

    assert result == TaskResult(
        outcome=Deferred("gems farming switched to its configured fallback stage"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_progress_effect(_progress(session=fallback), "gems_farming"),),
    )


def test_gems_event_fallback_rejects_a_main_stage_as_its_source_boundary() -> None:
    job = _spec("gems_farming", sessions=(_session("campaign_main", "1-1"),))
    policy = cast("GemsFarmingPolicy", job.gems_farming)
    fallback = job.session_for(policy.fallback_session.definition.ref, CampaignRunVariant.NORMAL)
    assert fallback is not None

    with pytest.raises(ValueError, match="requires an event-stage map boundary"):
        CampaignTask(
            _Workflow(_report(CampaignStopReason.GEMS_EVENT_FALLBACK, session=fallback)),
            job,
        ).run(_context("gems_farming"))


def test_controlled_workflow_failure_uses_failure_retry() -> None:
    result = CampaignTask(_Workflow(_report(CampaignStopReason.FAILED)), _spec()).run(_context("main"))

    assert result == TaskResult(
        outcome=Retryable("campaign workflow did not complete"),
        effects=(RescheduleSelf(_OBSERVED_AT + _FAILURE_RETRY),),
        state_effects=(_delete_effect(),),
    )


def test_workflow_preemption_report_reschedules_at_the_safe_point() -> None:
    result = CampaignTask(_Workflow(_report(CampaignStopReason.PREEMPTED)), _spec()).run(_context("main"))

    assert result == TaskResult(
        outcome=Deferred("campaign yielded at a safe point"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(_progress_effect(_progress()),),
    )


def test_preemption_before_scheduled_workflow_reschedules_at_the_run_start() -> None:
    preemption = PreemptionRequest()
    preemption.request("higher priority task")
    workflow = _Workflow(_report(CampaignStopReason.COMPLETED))

    result = CampaignTask(workflow, _spec()).run(_context("main", preemption=preemption))

    assert workflow.calls == 0
    assert result == TaskResult(
        outcome=Deferred("campaign yielded at a safe point"),
        effects=(RescheduleSelf(_STARTED_AT),),
    )


@pytest.mark.parametrize("mode", [ExecutionMode.DIRECT_COMMAND, ExecutionMode.ASSIST_SESSION])
def test_preemption_before_non_scheduled_workflow_has_no_schedule_effects(mode: ExecutionMode) -> None:
    preemption = PreemptionRequest()
    preemption.request("higher priority task")
    workflow = _Workflow(_report(CampaignStopReason.COMPLETED))

    result = CampaignTask(workflow, _spec()).run(_context("main", mode=mode, preemption=preemption))

    assert workflow.calls == 0
    assert result == TaskResult(outcome=Deferred("campaign yielded at a safe point"))


@pytest.mark.parametrize("reason", list(CampaignStopReason))
def test_every_stop_reason_advances_its_scheduled_campaign(reason: CampaignStopReason) -> None:
    task_id, job, report = _case_for_stop_reason(reason)

    result = CampaignTask(_Workflow(report), job).run(_context(task_id))

    assert any(
        isinstance(effect, RescheduleSelf) or (isinstance(effect, DisableTask) and effect.task_id == TaskId(task_id))
        for effect in result.effects
    )


@pytest.mark.parametrize("mode", [ExecutionMode.DIRECT_COMMAND, ExecutionMode.ASSIST_SESSION])
@pytest.mark.parametrize("reason", list(CampaignStopReason))
def test_non_scheduled_campaigns_do_not_mutate_schedules(
    reason: CampaignStopReason,
    mode: ExecutionMode,
) -> None:
    task_id, job, report = _case_for_stop_reason(reason)

    result = CampaignTask(_Workflow(report), job).run(_context(task_id, mode=mode))

    assert all(isinstance(effect, RequestAppRestart) for effect in result.effects)
    if reason is CampaignStopReason.EMOTION_BUG:
        assert len(result.effects) == 1
    else:
        assert result.effects == ()


@pytest.mark.parametrize("mode", [ExecutionMode.DIRECT_COMMAND, ExecutionMode.ASSIST_SESSION])
def test_missing_content_does_not_disable_a_non_scheduled_campaign(mode: ExecutionMode) -> None:
    workflow = _Workflow(_report(CampaignStopReason.CONTENT_UNAVAILABLE))

    result = CampaignTask(workflow, _spec("event_sp", sessions=())).run(_context("event_sp", mode=mode))

    assert workflow.calls == 0
    assert result == TaskResult(
        outcome=Blocked("campaign content is unavailable"),
        state_effects=(_delete_effect("event_sp"),),
    )


def test_abort_before_workflow_prevents_game_actions() -> None:
    abort = AbortToken()
    abort.request("manual stop")
    workflow = _Workflow(_report(CampaignStopReason.COMPLETED))

    with pytest.raises(AbortRequested, match="manual stop"):
        CampaignTask(workflow, _spec()).run(_context("main", abort=abort))

    assert workflow.calls == 0


def test_abort_after_safe_workflow_return_preserves_confirmed_checkpoint_effects() -> None:
    abort = AbortToken()

    def request_abort() -> None:
        abort.request("stop after battle settlement")

    workflow = _Workflow(
        _report(CampaignStopReason.FAILED),
        on_execute=request_abort,
    )

    result = CampaignTask(workflow, _spec()).run(_context("main", abort=abort))

    assert workflow.calls == 1
    assert result == TaskResult(
        outcome=Retryable("campaign workflow did not complete"),
        effects=(RescheduleSelf(_OBSERVED_AT + _FAILURE_RETRY),),
        state_effects=(_delete_effect(),),
    )


def test_campaign_task_rejects_invalid_workflow_report() -> None:
    workflow = cast("CampaignWorkflow", _Workflow(object()))

    with pytest.raises(TypeError, match=r"CampaignWorkflow.execute\(\) must return"):
        CampaignTask(workflow, _spec()).run(_context("main"))


def test_context_task_id_must_match_the_resolved_job() -> None:
    workflow = _Workflow(_report(CampaignStopReason.COMPLETED))

    with pytest.raises(ValueError, match="must match"):
        CampaignTask(workflow, _spec()).run(_context("main2"))

    assert workflow.calls == 0


def test_run_count_stop_requires_the_accumulated_budget_to_be_exhausted() -> None:
    session = _session()
    report = _report(CampaignStopReason.RUN_COUNT_LIMIT, session=session)

    with pytest.raises(ValueError, match="budget to be exhausted"):
        CampaignTask(
            _Workflow(report),
            _spec(
                sessions=(session,),
                limits=CampaignLimits(run_count=2),
                progress=_progress(session=session, runs_completed=1),
            ),
        ).run(_context("main"))


def test_exhausted_run_budget_cannot_skip_the_disabling_stop_reason() -> None:
    session = _session()
    report = _report(CampaignStopReason.COMPLETED, runs_completed=1, session=session)

    with pytest.raises(ValueError, match="must report the run-count stop"):
        CampaignTask(
            _Workflow(report),
            _spec(
                sessions=(session,),
                limits=CampaignLimits(run_count=2),
                progress=_progress(session=session, runs_completed=1),
            ),
        ).run(_context("main"))


def test_event_time_stop_requires_an_expired_aware_deadline() -> None:
    limits = CampaignLimits(event_deadline_at=_OBSERVED_AT + timedelta(minutes=1))

    with pytest.raises(ValueError, match="expired event deadline"):
        CampaignTask(
            _Workflow(_report(CampaignStopReason.EVENT_TIME_LIMIT)),
            _spec("event", limits=limits),
        ).run(_context("event"))


def test_report_session_state_must_use_a_job_variant() -> None:
    loop_session = _session(stage_id="1-2", variant=CampaignRunVariant.LOOP)
    report = CampaignRunReport(
        stage_ref=loop_session.definition.ref,
        observed_at=_OBSERVED_AT,
        stop_reason=CampaignStopReason.BLOCKED,
        session_state=loop_session.initial_state(),
    )

    with pytest.raises(ValueError, match="stage and variant do not belong"):
        CampaignTask(_Workflow(report), _spec()).run(_context("main"))


def test_campaign_specs_require_compiled_content_and_valid_specialization() -> None:
    with pytest.raises(ValueError, match="unsupported campaign task"):
        _spec("unknown")
    with pytest.raises(TypeError, match="require GemsFarmingPolicy"):
        CampaignJobSpec(
            task_id=TaskId("gems_farming"),
            sessions=(
                _session("event", "d3"),
                _session("event", "d3", CampaignRunVariant.LOOP),
            ),
            difficulty=CampaignDifficulty.NORMAL,
            execution=_execution(),
            schedule=_DAILY_SCHEDULE,
            failure_retry_delay=_FAILURE_RETRY_RANGE,
            resource_retry_delay=_RESOURCE_RETRY,
        )
    with pytest.raises(ValueError, match="exactly one primary session"):
        _spec(sessions=(_session(stage_id="1-1"), _session(stage_id="1-2")))


def test_campaign_datetimes_must_be_timezone_aware() -> None:
    naive = datetime(2026, 7, 13, 12)

    with pytest.raises(ValueError, match="timezone-aware"):
        CampaignRunReport(
            stage_ref=StageRef("campaign_main", "1-1"),
            observed_at=naive,
            stop_reason=CampaignStopReason.COMPLETED,
            session_state=_session().initial_state(),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        CampaignLimits(event_deadline_at=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_execution().emotion.fleet1, recorded_at=naive)


def test_campaign_specs_require_a_daily_schedule() -> None:
    with pytest.raises(TypeError, match="schedule must be DailySchedule"):
        CampaignJobSpec(
            task_id=TaskId("main"),
            sessions=(_session(), _session(variant=CampaignRunVariant.LOOP)),
            difficulty=CampaignDifficulty.NORMAL,
            execution=_execution(),
            schedule=cast("DailySchedule", object()),
            failure_retry_delay=_FAILURE_RETRY_RANGE,
            resource_retry_delay=_RESOURCE_RETRY,
        )


def test_campaign_specs_require_typed_execution_settings() -> None:
    with pytest.raises(TypeError, match="execution must be CampaignExecutionSettings"):
        CampaignJobSpec(
            task_id=TaskId("main"),
            sessions=(_session(), _session(variant=CampaignRunVariant.LOOP)),
            difficulty=CampaignDifficulty.NORMAL,
            execution=cast("CampaignExecutionSettings", object()),
            schedule=_DAILY_SCHEDULE,
            failure_retry_delay=_FAILURE_RETRY_RANGE,
            resource_retry_delay=_RESOURCE_RETRY,
        )


def test_campaign_settings_reject_invalid_resource_and_count_values() -> None:
    with pytest.raises(ValueError, match="between 120 and 240"):
        CampaignJobSpec(
            task_id=TaskId("main"),
            sessions=(_session(), _session(variant=CampaignRunVariant.LOOP)),
            difficulty=CampaignDifficulty.NORMAL,
            execution=_execution(),
            schedule=_DAILY_SCHEDULE,
            failure_retry_delay=_FAILURE_RETRY_RANGE,
            resource_retry_delay=timedelta(minutes=119),
        )
    with pytest.raises(ValueError, match="non-negative"):
        CampaignLimits(run_count=-1)
    assert CampaignLimits(oil=0).effective_oil_limit == 500
    assert CampaignLimits(oil=1_200).effective_oil_limit == 1_200
