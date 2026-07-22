from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest

from module.application import AbortRequested, AbortToken, DailySchedule, DelayRange, TaskId
from module.content.battle_policy import (
    BossStrategy,
    ClearBoss,
    ClearSiren,
    DefaultBattle,
    StagePolicy,
)
from module.content.battle_program import (
    BattleProgram,
    BattleProgramDelegation,
    BattleProgramMode,
    NamedProgramMarker,
    ProgramBattleSettled,
    ProgramBattleTarget,
    ProgramCampaignEnded,
    ProgramContinue,
    ProgramDelegated,
    ProgramNoTarget,
    ReturnProgramContinue,
)
from module.content.campaign_session import (
    BattleAttempt,
    BattleFailed,
    BattlefieldObservation,
    BattleOutcome,
    BattleSucceeded,
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
    CampaignSessionStatus,
    NoBattleTarget,
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
from module.content.stage_rules import (
    MapFeatures,
    RepeatableCompletion,
    StageCompletion,
    StageRules,
    StarRequirements,
)
from module.gameplay.battle_program import BattleProgramExecution
from module.gameplay.campaign import (
    CampaignAutomationSettings,
    CampaignDifficulty,
    CampaignEnemyPrioritySettings,
    CampaignExecutionSettings,
    CampaignFleetSettings,
    CampaignHpControlSettings,
    CampaignJobSpec,
    CampaignLimits,
    CampaignMapAchievement,
    CampaignProgress,
    CampaignStopReason,
    CampaignSubmarineSettings,
    EnemyPriorityMode,
    FleetMode,
    FleetOrder,
    SubmarineAutoSearchMode,
    SubmarineDistanceToBoss,
    SubmarineMode,
)
from module.gameplay.campaign_live import (
    CampaignCheckpointReset,
    CampaignLiveServices,
    CampaignMapAchievementReached,
    LiveCampaignWorkflow,
)
from module.gameplay.emotion import (
    EmotionControl,
    EmotionMode,
    EmotionRecoverLocation,
    EmotionSettings,
    FleetEmotionSettings,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(4),))
_DEFAULT_STAGE_REF = StageRef("campaign_main", "1-1")


def _execution() -> CampaignExecutionSettings:
    fleet_emotion = FleetEmotionSettings(
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
        emotion=EmotionSettings(
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
        enemy_priority=CampaignEnemyPrioritySettings(scale_balance_weight=EnemyPriorityMode.DEFAULT),
    )


def _session(
    *,
    ref: StageRef = _DEFAULT_STAGE_REF,
    waves: tuple[SpawnWave, ...] = (SpawnWave(battle=0, enemy=1),),
    policies: dict[int, StagePolicy] | None = None,
    enemy_filter: str = "1L > 2L > 3L",
    completion: StageCompletion | None = None,
) -> CampaignSession:
    cells = (CellSpec(CellId(0, 0), "MB", 1.0),)
    variant = RunVariant(cells=cells, spawn_waves=waves)
    if policies is None:
        policies = {
            wave.battle: StagePolicy((ClearBoss(BossStrategy.FLEET_BOSS),) if wave.boss else (DefaultBattle(),))
            for wave in waves
        }
    definition = CampaignStageDefinition(
        ref=ref,
        map=MapDefinition(
            name=ref.stage_id,
            shape=GridShape(1, 1),
            camera_data=(),
            camera_data_spawn_point=(),
            normal=variant,
            loop=variant,
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
            completion=RepeatableCompletion(StarRequirements()) if completion is None else completion,
        ),
        enemy_filter=enemy_filter,
        battle_policies=policies,
    )
    return CampaignSession(definition, CampaignRunVariant.NORMAL)


def _job(  # ruff:ignore[too-many-arguments] - 测试构造器需要独立控制各领域维度。
    session: CampaignSession,
    *,
    task_id: str = "main",
    sessions: tuple[CampaignSession, ...] | None = None,
    progress: CampaignProgress | None = None,
    limits: CampaignLimits | None = None,
    stage_selections: tuple[CampaignStageSelection, ...] = (),
) -> CampaignJobSpec:
    selected = (session,) if sessions is None else sessions
    by_ref = {item.definition.ref: item.definition for item in selected}
    complete_sessions = tuple(
        CampaignSession(definition, variant) for definition in by_ref.values() for variant in CampaignRunVariant
    )
    return CampaignJobSpec(
        task_id=TaskId(task_id),
        sessions=complete_sessions,
        difficulty=CampaignDifficulty.NORMAL,
        execution=_execution(),
        schedule=_SCHEDULE,
        failure_retry_delay=DelayRange(1_800, 1_800),
        resource_retry_delay=timedelta(minutes=180),
        progress=progress,
        limits=CampaignLimits() if limits is None else limits,
        stage_selections=stage_selections,
    )


class _Clock:
    @staticmethod
    def now() -> datetime:
        return _NOW


class _Observer:
    def __init__(
        self,
        observation: BattlefieldObservation,
        on_observe: Callable[[], None] | None = None,
    ) -> None:
        self.observation = observation
        self.on_observe = on_observe
        self.calls: list[tuple[CampaignSession, CampaignSessionState]] = []

    def observe(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattlefieldObservation:
        cancellation.raise_if_requested()
        self.calls.append((session, state))
        if self.on_observe is not None:
            self.on_observe()
        return self.observation


class _Driver:
    def __init__(self, outcome: Callable[[BattleAttempt], BattleOutcome]) -> None:
        self.outcome = outcome
        self.calls: list[tuple[BattleAttempt, CampaignSessionState]] = []

    def issue_and_confirm(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        del session
        cancellation.raise_if_requested()
        attempt = state.pending
        assert attempt is not None
        self.calls.append((attempt, state))
        return self.outcome(attempt)


class _ResetActivator:
    @staticmethod
    def activate(
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> CampaignCheckpointReset:
        del job
        cancellation.raise_if_requested()
        return CampaignCheckpointReset("client checkpoint was reset to the map boundary")


class _AchievementActivator:
    def __init__(self, evidence: CampaignMapAchievementReached) -> None:
        self.evidence = evidence
        self.calls = 0

    def activate(
        self,
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> CampaignMapAchievementReached:
        del job
        cancellation.raise_if_requested()
        self.calls += 1
        return self.evidence


class _ProgramExecutor:
    def __init__(
        self,
        execution: BattleProgramExecution | tuple[BattleProgramExecution, ...],
        *,
        mode: BattleProgramMode = BattleProgramMode.NORMAL,
    ) -> None:
        self.executions = list(execution if isinstance(execution, tuple) else (execution,))
        self.selected_mode = mode
        self.calls: list[tuple[BattleProgram, CampaignSession, CampaignSessionState]] = []

    def mode(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleProgramMode:
        del session, state
        cancellation.raise_if_requested()
        return self.selected_mode

    def execute(
        self,
        program: BattleProgram,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleProgramExecution:
        cancellation.raise_if_requested()
        self.calls.append((program, session, state))
        return self.executions.pop(0)


class _RuntimeLifecycle:
    def __init__(self) -> None:
        self.calls: list[tuple[CampaignSession, CampaignSessionState, CampaignStopReason]] = []
        self.discard_calls = 0

    def discard_checkpoint(self) -> None:
        self.discard_calls += 1

    def finish(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        stop_reason: CampaignStopReason,
    ) -> None:
        self.calls.append((session, state, stop_reason))


def _workflow(
    observer: _Observer,
    driver: _Driver,
) -> LiveCampaignWorkflow:
    return LiveCampaignWorkflow(observer, driver, _Clock())


def _program_session(
    result_program: BattleProgram | None = None,
    *,
    waves: tuple[SpawnWave, ...] = (SpawnWave(battle=0, enemy=1),),
) -> CampaignSession:
    base = _session(waves=waves)
    program = (
        BattleProgram(
            0,
            frozenset({BattleProgramMode.NORMAL}),
            (ReturnProgramContinue(),),
        )
        if result_program is None
        else result_program
    )
    return CampaignSession(
        replace(base.definition, battle_programs={0: program}),
        CampaignRunVariant.NORMAL,
    )


def _program_workflow(
    executor: _ProgramExecutor,
    observer: _Observer,
    driver: _Driver,
) -> LiveCampaignWorkflow:
    return LiveCampaignWorkflow(
        observer,
        driver,
        _Clock(),
        services=CampaignLiveServices(programs=executor),
    )


def test_live_workflow_checkpoints_a_battle_free_program_action_and_markers() -> None:
    session = _program_session()
    observer = _Observer(BattlefieldObservation(0, enemy=1))
    driver = _Driver(NoBattleTarget)
    marker = NamedProgramMarker("test.checkpoint")
    execution = BattleProgramExecution(ProgramContinue(), frozenset(), frozenset({marker}))
    programs = _ProgramExecutor(execution)

    report = _program_workflow(programs, observer, driver).execute(
        _job(session),
        AbortToken(),
    )

    assert report.stop_reason is CampaignStopReason.PROGRAM_CONTINUE
    assert report.session_state.program_state_initialized
    assert report.session_state.program_markers == frozenset({marker})
    assert report.session_state.battle_index == 0
    assert len(programs.calls) == 1
    assert observer.calls == []
    assert driver.calls == []


def test_live_workflow_delegates_to_the_stage_policy_without_losing_program_facts() -> None:
    session = _program_session(
        waves=(SpawnWave(battle=0, enemy=1), SpawnWave(battle=1, boss=1)),
    )
    marker = NamedProgramMarker("test.delegated")
    programs = _ProgramExecutor(
        BattleProgramExecution(
            ProgramDelegated(BattleProgramDelegation.STAGE_POLICY),
            frozenset(),
            frozenset({marker}),
        )
    )
    observer = _Observer(BattlefieldObservation(0, enemy=1))
    driver = _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY))

    report = _program_workflow(programs, observer, driver).execute(
        _job(session),
        AbortToken(),
    )

    assert report.stop_reason is CampaignStopReason.IN_PROGRESS
    assert report.session_state.battle_index == 1
    assert report.session_state.program_markers == frozenset({marker})
    assert len(observer.calls) == 1
    assert len(driver.calls) == 1


def test_live_workflow_turns_verified_map_completion_into_a_terminal_achievement() -> None:
    session = _session()
    observer = _Observer(BattlefieldObservation(0, enemy=1))
    driver = _Driver(NoBattleTarget)
    activator = _AchievementActivator(
        CampaignMapAchievementReached(full_clear=True, three_stars=False, threat_safe=False)
    )
    workflow = LiveCampaignWorkflow(
        observer,
        driver,
        _Clock(),
        services=CampaignLiveServices(activator=activator),
    )

    report = workflow.execute(
        _job(
            session,
            limits=CampaignLimits(map_achievement=CampaignMapAchievement.FULL_CLEAR),
        ),
        AbortToken(),
    )

    assert report.stop_reason is CampaignStopReason.MAP_ACHIEVEMENT
    assert report.next_stage_ref is None
    assert report.session_state == session.initial_state()
    assert activator.calls == 1
    assert observer.calls == []
    assert driver.calls == []


def test_live_workflow_advances_only_to_the_content_declared_next_stage() -> None:
    source = _session(ref=StageRef("campaign_main", "1-1"))
    target = _session(ref=StageRef("campaign_main", "1-2"))
    target_sessions = tuple(CampaignSession(target.definition, variant) for variant in CampaignRunVariant)
    selection = CampaignStageSelection(
        requested_ref=source.definition.ref,
        selected_ref=source.definition.ref,
        next_ref=target.definition.ref,
    )
    limits = CampaignLimits(
        map_achievement=CampaignMapAchievement.THREE_STARS,
        stage_increase=True,
    )
    job = replace(
        _job(source, limits=limits),
        stage_selections=(selection,),
        transition_sessions=target_sessions,
    )
    activator = _AchievementActivator(
        CampaignMapAchievementReached(full_clear=True, three_stars=True, threat_safe=False)
    )
    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(NoBattleTarget),
        _Clock(),
        services=CampaignLiveServices(activator=activator),
    )

    report = workflow.execute(job, AbortToken())

    assert report.stop_reason is CampaignStopReason.STAGE_INCREASE
    assert report.next_stage_ref == target.definition.ref
    assert report.session_state == source.initial_state()


def test_live_workflow_reduces_a_program_battle_and_advances_the_static_wave() -> None:
    session = _program_session(
        waves=(SpawnWave(battle=0, enemy=1), SpawnWave(battle=1, boss=1)),
    )
    programs = _ProgramExecutor(
        BattleProgramExecution(
            ProgramBattleSettled(ProgramBattleTarget.ENEMY),
            frozenset(),
        )
    )

    report = _program_workflow(
        programs,
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(NoBattleTarget),
    ).execute(_job(session), AbortToken())

    assert report.stop_reason is CampaignStopReason.IN_PROGRESS
    assert report.session_state.battle_index == 1
    assert report.session_state.remaining.boss == 1
    assert report.session_state.status is CampaignSessionStatus.ACTIVE


def test_live_workflow_keeps_a_dynamic_boss_roadblock_on_the_current_wave() -> None:
    session = _program_session(waves=(SpawnWave(battle=0, boss=1),))
    programs = _ProgramExecutor(
        BattleProgramExecution(
            ProgramBattleSettled(ProgramBattleTarget.ENEMY, advances_wave=False),
            frozenset(),
        )
    )

    report = _program_workflow(
        programs,
        _Observer(BattlefieldObservation(0, boss=1)),
        _Driver(NoBattleTarget),
    ).execute(_job(session), AbortToken())

    assert report.stop_reason is CampaignStopReason.IN_PROGRESS
    assert report.session_state.battle_index == 0
    assert report.session_state.remaining.boss == 1


@pytest.mark.parametrize(
    ("result", "expected_reason", "expected_status"),
    [
        (ProgramNoTarget(), CampaignStopReason.BLOCKED, CampaignSessionStatus.BLOCKED),
        (ProgramCampaignEnded(), CampaignStopReason.ONE_TIME_STAGE, CampaignSessionStatus.ACTIVE),
    ],
)
def test_live_workflow_closes_terminal_program_results(
    result: ProgramNoTarget | ProgramCampaignEnded,
    expected_reason: CampaignStopReason,
    expected_status: CampaignSessionStatus,
) -> None:
    session = _program_session()
    programs = _ProgramExecutor(BattleProgramExecution(result, frozenset()))

    report = _program_workflow(
        programs,
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(NoBattleTarget),
    ).execute(_job(session), AbortToken())

    assert report.stop_reason is expected_reason
    assert report.session_state.status is expected_status


def test_live_workflow_observes_issues_confirms_and_reduces_one_battle() -> None:
    session = _session()
    observer = _Observer(BattlefieldObservation(battle_index=0, enemy=1))
    driver = _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY))

    report = _workflow(observer, driver).execute(
        _job(session),
        AbortToken(),
    )

    assert report.stop_reason is CampaignStopReason.IN_PROGRESS
    assert report.session_state.status is CampaignSessionStatus.COMPLETED
    assert report.session_state.pending is None
    assert report.runs_completed == 1
    assert len(observer.calls) == len(driver.calls) == 1
    attempt, issued_state = driver.calls[0]
    assert issued_state.pending == attempt
    assert issued_state.next_attempt_id == 1


def test_live_workflow_reduces_no_target_without_faking_a_battle() -> None:
    policy = StagePolicy((ClearSiren(), DefaultBattle()))
    session = _session(
        waves=(SpawnWave(battle=0, enemy=1, siren=1),),
        policies={0: policy},
    )
    observer = _Observer(BattlefieldObservation(battle_index=0, enemy=1, siren=1))
    driver = _Driver(NoBattleTarget)

    report = _workflow(observer, driver).execute(_job(session), AbortToken())

    assert report.stop_reason is CampaignStopReason.IN_PROGRESS
    assert report.session_state.status is CampaignSessionStatus.ACTIVE
    assert report.session_state.next_intent_index == 1
    assert report.session_state.pending is None
    assert report.runs_completed == 0


def test_live_workflow_reduces_confirmed_failure() -> None:
    session = _session()
    observer = _Observer(BattlefieldObservation(battle_index=0, enemy=1))
    driver = _Driver(lambda attempt: BattleFailed(attempt, "combat confirmation failed"))

    report = _workflow(observer, driver).execute(_job(session), AbortToken())

    assert report.stop_reason is CampaignStopReason.FAILED
    assert report.session_state.status is CampaignSessionStatus.FAILED
    assert report.session_state.pending is None


def test_live_workflow_finishes_runtime_at_the_report_boundary() -> None:
    session = _session()
    lifecycle = _RuntimeLifecycle()
    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(battle_index=0, enemy=1)),
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(lifecycle=lifecycle),
    )

    report = workflow.execute(_job(session), AbortToken())

    assert lifecycle.calls == [(session, report.session_state, report.stop_reason)]


def test_live_workflow_discards_the_runtime_owned_by_a_stale_checkpoint() -> None:
    lifecycle = _RuntimeLifecycle()
    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(battle_index=0, enemy=1)),
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(lifecycle=lifecycle),
    )

    workflow.discard_checkpoint()

    assert lifecycle.discard_calls == 1


def test_live_workflow_checks_cancellation_before_intent_io() -> None:
    session = _session()
    cancellation = AbortToken()
    lifecycle = _RuntimeLifecycle()

    def request_cancellation() -> None:
        cancellation.request("stop before action")

    observer = _Observer(
        BattlefieldObservation(battle_index=0, enemy=1),
        request_cancellation,
    )
    driver = _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY))

    workflow = LiveCampaignWorkflow(
        observer,
        driver,
        _Clock(),
        services=CampaignLiveServices(lifecycle=lifecycle),
    )

    with pytest.raises(AbortRequested, match="stop before action"):
        workflow.execute(_job(session), cancellation)

    assert driver.calls == []
    assert lifecycle.calls == [(session, session.initial_state(), CampaignStopReason.CANCELLED)]


def test_live_workflow_marks_runtime_failed_when_execution_raises() -> None:
    session = _session()
    lifecycle = _RuntimeLifecycle()

    def fail_observation() -> None:
        message = "observation failed"
        raise RuntimeError(message)

    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(battle_index=0, enemy=1), fail_observation),
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(lifecycle=lifecycle),
    )

    with pytest.raises(RuntimeError, match="observation failed"):
        workflow.execute(_job(session), AbortToken())

    assert lifecycle.calls == [(session, session.initial_state(), CampaignStopReason.FAILED)]


def test_live_workflow_resumes_the_exact_progress_session() -> None:
    first = _session(ref=StageRef("campaign_main", "1-1"))
    second = _session(ref=StageRef("campaign_main", "1-2"))
    progress = CampaignProgress(
        stage_ref=second.definition.ref,
        variant=second.variant,
        session_state=second.initial_state(),
        runs_completed=2,
        settings_revision=1,
        content_revision="content-1",
    )
    observer = _Observer(BattlefieldObservation(battle_index=0, enemy=1))
    driver = _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY))

    report = _workflow(observer, driver).execute(
        _job(second, task_id="event_a", sessions=(first, second), progress=progress),
        AbortToken(),
    )

    assert observer.calls[0][0] == second
    assert report.stage_ref == second.definition.ref


def test_live_workflow_reports_a_checkpoint_reset_without_map_io() -> None:
    session = _session(waves=(SpawnWave(battle=0, enemy=1), SpawnWave(battle=1, boss=1)))
    decision = session.decide(session.initial_state(), BattlefieldObservation(0, enemy=1))
    assert decision.command is not None
    checkpoint = session.reduce(
        decision.state,
        BattleSucceeded(decision.command, BattleTarget.ENEMY),
    )
    progress = CampaignProgress(
        stage_ref=session.definition.ref,
        variant=session.variant,
        session_state=checkpoint,
        runs_completed=2,
        settings_revision=1,
        content_revision="content-1",
    )
    observer = _Observer(BattlefieldObservation(battle_index=0, enemy=1))
    driver = _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY))
    lifecycle = _RuntimeLifecycle()
    workflow = LiveCampaignWorkflow(
        observer,
        driver,
        _Clock(),
        services=CampaignLiveServices(activator=_ResetActivator(), lifecycle=lifecycle),
    )

    report = workflow.execute(_job(session, progress=progress), AbortToken())

    assert report.stop_reason is CampaignStopReason.CHECKPOINT_RESET
    assert report.session_state == session.initial_state()
    assert observer.calls == []
    assert driver.calls == []
    assert lifecycle.calls == [(session, session.initial_state(), CampaignStopReason.CHECKPOINT_RESET)]
