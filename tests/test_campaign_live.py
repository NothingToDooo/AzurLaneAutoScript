from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_live import (
    CampaignActionInterrupted,
    CampaignMapAdapterError,
    CampaignMapRuntime,
    CommittedCampaignUnit,
    ExistingCampaignMapAdapter,
)
from module.application import AbortRequested, AbortToken, DailySchedule, DelayRange, TaskId
from module.content.battle_policy import (
    BattleFlag,
    BossStrategy,
    ClearAnyEnemy,
    ClearBoss,
    ClearBossRoadblock,
    ClearFilteredEnemy,
    ClearSiren,
    DefaultBattle,
    StagePolicy,
)
from module.content.battle_program import (
    BattleProgram,
    BattleProgramDelegation,
    BattleProgramMode,
    DelegateBattle,
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
    AutoSearchBattle,
    BattleAttempt,
    BattleFailed,
    BattlefieldObservation,
    BattleInterrupted,
    BattleInterruptionReason,
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
    OneTimeCompletion,
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
    GemsCommonCarrier,
    GemsCommonDestroyer,
    GemsFarmingPolicy,
    GemsFlagshipChange,
    GemsFleetReplacementBoundary,
    GemsFleetReplacementRequest,
    GemsVanguardChange,
    SubmarineAutoSearchMode,
    SubmarineDistanceToBoss,
    SubmarineMode,
    TaskBalancerPolicy,
)
from module.gameplay.campaign_live import (
    CampaignCheckpointUnavailable,
    CampaignGemsReplacementFailed,
    CampaignGuardDecision,
    CampaignGuardEvidence,
    CampaignGuardPhase,
    CampaignGuardPolicy,
    CampaignLiveServices,
    CampaignMapAchievementReached,
    GemsFleetReplacementCompleted,
    GemsFleetReplacementFailed,
    GemsFleetReplacementTrigger,
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
    import builtins
    from collections.abc import Callable, Iterable

    from module.application import CancellationSource
    from module.gameplay.campaign_live import CampaignRuntimeLifecycle


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
    task_balancer: TaskBalancerPolicy | None = None,
    gems_farming: GemsFarmingPolicy | None = None,
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
        task_balancer=task_balancer,
        gems_farming=gems_farming,
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
        self.calls: list[BattleAttempt] = []

    def issue_and_confirm(
        self,
        session: CampaignSession,
        attempt: BattleAttempt,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        del session
        cancellation.raise_if_requested()
        self.calls.append(attempt)
        return self.outcome(attempt)


class _UnavailableActivator:
    @staticmethod
    def activate(
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> CampaignCheckpointUnavailable:
        del job
        cancellation.raise_if_requested()
        return CampaignCheckpointUnavailable("client is no longer inside the checkpoint map")


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


class _GemsFailureActivator:
    def __init__(self, failure: CampaignGemsReplacementFailed) -> None:
        self.failure = failure

    def activate(
        self,
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> CampaignGemsReplacementFailed:
        del job
        cancellation.raise_if_requested()
        return self.failure


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


def test_live_workflow_delegates_to_the_current_modes_default_program_once() -> None:
    stage_program = BattleProgram(
        0,
        frozenset({BattleProgramMode.CLEAR_ALL}),
        (DelegateBattle(BattleProgramDelegation.DEFAULT_MODE),),
    )
    session = _program_session(
        stage_program,
        waves=(SpawnWave(battle=0, enemy=1), SpawnWave(battle=1, boss=1)),
    )
    programs = _ProgramExecutor(
        (
            BattleProgramExecution(
                ProgramDelegated(BattleProgramDelegation.DEFAULT_MODE),
                frozenset(),
            ),
            BattleProgramExecution(
                ProgramBattleSettled(ProgramBattleTarget.ENEMY),
                frozenset(),
            ),
        ),
        mode=BattleProgramMode.CLEAR_ALL,
    )

    report = _program_workflow(
        programs,
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(NoBattleTarget),
    ).execute(_job(session), AbortToken())

    assert report.stop_reason is CampaignStopReason.IN_PROGRESS
    assert report.session_state.battle_index == 1
    assert len(programs.calls) == 2
    assert programs.calls[0][0] is stage_program
    assert programs.calls[1][0].activation_modes == frozenset({BattleProgramMode.CLEAR_ALL})


def test_live_workflow_rejects_recursive_default_mode_delegation() -> None:
    stage_program = BattleProgram(
        0,
        frozenset({BattleProgramMode.CLEAR_ALL}),
        (DelegateBattle(BattleProgramDelegation.DEFAULT_MODE),),
    )
    session = _program_session(stage_program)
    delegated = BattleProgramExecution(
        ProgramDelegated(BattleProgramDelegation.DEFAULT_MODE),
        frozenset(),
    )
    programs = _ProgramExecutor(
        (delegated, delegated),
        mode=BattleProgramMode.CLEAR_ALL,
    )

    with pytest.raises(ValueError, match="cannot delegate to itself"):
        _program_workflow(
            programs,
            _Observer(BattlefieldObservation(0, enemy=1)),
            _Driver(NoBattleTarget),
        ).execute(_job(session), AbortToken())


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


def test_live_workflow_rejects_unmet_map_achievement_evidence() -> None:
    session = _session()
    activator = _AchievementActivator(
        CampaignMapAchievementReached(full_clear=False, three_stars=False, threat_safe=False)
    )
    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(NoBattleTarget),
        _Clock(),
        services=CampaignLiveServices(activator=activator),
    )

    with pytest.raises(ValueError, match="unmet map achievement"):
        workflow.execute(
            _job(
                session,
                limits=CampaignLimits(map_achievement=CampaignMapAchievement.THREAT_SAFE),
            ),
            AbortToken(),
        )


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


def test_live_workflow_retains_program_checkpoint_through_the_same_lifecycle_boundary() -> None:
    session = _program_session()
    lifecycle = _RuntimeLifecycle()
    programs = _ProgramExecutor(BattleProgramExecution(ProgramContinue(), frozenset()))
    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(battle_index=0, enemy=1)),
        _Driver(NoBattleTarget),
        _Clock(),
        services=CampaignLiveServices(programs=programs, lifecycle=lifecycle),
    )

    report = workflow.execute(_job(session), AbortToken())

    assert report.stop_reason is CampaignStopReason.PROGRAM_CONTINUE
    assert lifecycle.calls == [(session, report.session_state, CampaignStopReason.PROGRAM_CONTINUE)]


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


def test_live_workflow_preserves_execution_and_lifecycle_cleanup_failures() -> None:
    session = _session()
    execution_error = RuntimeError("observation failed")
    cleanup_error = OSError("runtime cleanup failed")

    class _FailingLifecycle(_RuntimeLifecycle):
        def finish(
            self,
            session: CampaignSession,
            state: CampaignSessionState,
            stop_reason: CampaignStopReason,
        ) -> None:
            super().finish(session, state, stop_reason)
            raise cleanup_error

    def fail_observation() -> None:
        raise execution_error

    lifecycle = _FailingLifecycle()
    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(battle_index=0, enemy=1), fail_observation),
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(lifecycle=lifecycle),
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        workflow.execute(_job(session), AbortToken())

    assert raised.value.exceptions == (execution_error, cleanup_error)
    assert lifecycle.calls == [(session, session.initial_state(), CampaignStopReason.FAILED)]


def test_campaign_live_services_reject_an_invalid_runtime_lifecycle() -> None:
    with pytest.raises(TypeError, match=r"lifecycle must implement finish\(\)"):
        CampaignLiveServices(lifecycle=cast("CampaignRuntimeLifecycle", object()))


def test_campaign_live_services_require_checkpoint_discard_lifecycle() -> None:
    class _FinishOnlyLifecycle:
        @staticmethod
        def finish(
            session: CampaignSession,
            state: CampaignSessionState,
            stop_reason: CampaignStopReason,
        ) -> None:
            del session, state, stop_reason

    with pytest.raises(TypeError, match=r"lifecycle must implement discard_checkpoint\(\)"):
        CampaignLiveServices(lifecycle=cast("CampaignRuntimeLifecycle", _FinishOnlyLifecycle()))


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


def test_live_workflow_reports_a_physically_unavailable_checkpoint_without_io() -> None:
    session = _session()
    progress = CampaignProgress(
        stage_ref=session.definition.ref,
        variant=session.variant,
        session_state=session.initial_state(),
        runs_completed=2,
        settings_revision=1,
        content_revision="content-1",
    )
    observer = _Observer(BattlefieldObservation(battle_index=0, enemy=1))
    driver = _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY))
    workflow = LiveCampaignWorkflow(
        observer,
        driver,
        _Clock(),
        services=CampaignLiveServices(activator=_UnavailableActivator()),
    )

    report = workflow.execute(_job(session, progress=progress), AbortToken())

    assert report.stop_reason is CampaignStopReason.CHECKPOINT_UNAVAILABLE
    assert report.session_state == progress.session_state
    assert observer.calls == []
    assert driver.calls == []


class _GuardSource:
    def __init__(
        self,
        *,
        before: CampaignGuardEvidence | None = None,
        after: CampaignGuardEvidence | None = None,
    ) -> None:
        self.before = CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY) if before is None else before
        self.after = CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE) if after is None else after
        self.calls: list[CampaignGuardPhase] = []

    def before_entry(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> CampaignGuardEvidence:
        del job, session, state
        cancellation.raise_if_requested()
        self.calls.append(CampaignGuardPhase.PRE_ENTRY)
        return self.before

    def after_battle(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
    ) -> CampaignGuardEvidence:
        del job, session, state
        self.calls.append(CampaignGuardPhase.POST_BATTLE)
        return self.after


class _GemsFleetExecutor:
    def __init__(self, result: GemsFleetReplacementCompleted | GemsFleetReplacementFailed) -> None:
        self.result = result
        self.calls: list[tuple[CampaignJobSpec, CampaignSession, GemsFleetReplacementTrigger]] = []

    def replace(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        trigger: GemsFleetReplacementTrigger,
        cancellation: CancellationSource,
    ) -> GemsFleetReplacementCompleted | GemsFleetReplacementFailed:
        cancellation.raise_if_requested()
        self.calls.append((job, session, trigger))
        return self.result


def _guard_decision(
    job: CampaignJobSpec,
    evidence: CampaignGuardEvidence,
    *,
    state: CampaignSessionState | None = None,
) -> CampaignGuardDecision:
    session = job.sessions[0]
    selected_state = session.initial_state() if state is None else state
    return CampaignGuardPolicy.evaluate(job, session, selected_state, evidence, _NOW)


def _completed(session: CampaignSession) -> CampaignSessionState:
    decision = session.decide(session.initial_state(), BattlefieldObservation(0, enemy=1))
    assert decision.command is not None
    return session.reduce(decision.state, BattleSucceeded(decision.command, BattleTarget.ENEMY))


@pytest.mark.parametrize(
    ("job", "evidence", "reason"),
    [
        (
            _job(_session(), limits=CampaignLimits(oil=1_000)),
            CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY, oil=999),
            CampaignStopReason.OIL_LIMIT,
        ),
        (
            _job(
                _session(ref=StageRef("event_test", "d3")),
                task_id="event",
                limits=CampaignLimits(event_deadline_at=_NOW - timedelta(seconds=1)),
            ),
            CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY),
            CampaignStopReason.EVENT_TIME_LIMIT,
        ),
        (
            _job(_session(ref=StageRef("event_test", "d3")), task_id="event"),
            CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY, event_available=False),
            CampaignStopReason.EVENT_UNAVAILABLE,
        ),
        (
            _job(
                _session(ref=StageRef("event_test", "d3")),
                task_id="event",
                limits=CampaignLimits(event_points=100_000),
            ),
            CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY, event_points=100_000),
            CampaignStopReason.EVENT_POINT_LIMIT,
        ),
        (
            _job(_session(ref=StageRef("war_archives_test", "1-1")), task_id="war_archives"),
            CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY, data_keys_remaining=0),
            CampaignStopReason.DATA_KEYS_EXHAUSTED,
        ),
    ],
)
def test_pre_entry_guard_policy_maps_typed_evidence_to_stop_reasons(
    job: CampaignJobSpec,
    evidence: CampaignGuardEvidence,
    reason: CampaignStopReason,
) -> None:
    assert _guard_decision(job, evidence).stop_reason is reason


def test_coin_guard_requires_a_completed_run_and_ignores_ocr_zero() -> None:
    session = _session()
    progress = CampaignProgress(
        stage_ref=session.definition.ref,
        variant=session.variant,
        session_state=session.initial_state(),
        runs_completed=1,
        settings_revision=1,
        content_revision="content-1",
    )
    policy = TaskBalancerPolicy(TaskId("commission"), coin_limit=20_000)
    job = _job(session, progress=progress, task_balancer=policy)

    assert _guard_decision(job, CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY, coin=0)).stop_reason is None
    assert (
        _guard_decision(job, CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY, coin=19_999)).stop_reason
        is CampaignStopReason.COIN_LIMIT
    )


@pytest.mark.parametrize(
    ("limits", "evidence", "reason"),
    [
        (
            CampaignLimits(reach_level=120),
            CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, reach_level_limit=True),
            CampaignStopReason.REACH_LEVEL_LIMIT,
        ),
        (
            CampaignLimits(),
            CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, auto_search_oil_limit=True),
            CampaignStopReason.AUTO_SEARCH_OIL_LIMIT,
        ),
        (
            CampaignLimits(stop_on_new_ship=True),
            CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, new_ship=True),
            CampaignStopReason.NEW_SHIP,
        ),
        (
            CampaignLimits(),
            CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, emotion_bug=True),
            CampaignStopReason.EMOTION_BUG,
        ),
    ],
)
def test_post_battle_guard_policy_uses_only_completed_map_facts(
    limits: CampaignLimits,
    evidence: CampaignGuardEvidence,
    reason: CampaignStopReason,
) -> None:
    session = _session()
    completed = _completed(session)
    assert _guard_decision(_job(session, limits=limits), evidence, state=completed).stop_reason is reason


def test_live_workflow_stops_before_entry_without_observer_or_driver_io() -> None:
    session = _session()
    observer = _Observer(BattlefieldObservation(battle_index=0, enemy=1))
    driver = _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY))
    guards = _GuardSource(before=CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY, oil=499))
    workflow = LiveCampaignWorkflow(
        observer,
        driver,
        _Clock(),
        services=CampaignLiveServices(guards=guards),
    )

    report = workflow.execute(_job(session), AbortToken())

    assert report.stop_reason is CampaignStopReason.OIL_LIMIT
    assert observer.calls == []
    assert driver.calls == []


def test_one_time_and_explicit_loop_selection_stop_after_a_completed_map() -> None:
    one_time = _session(completion=OneTimeCompletion(StarRequirements()))
    loop = _session(ref=StageRef("campaign_main", "7-2"))
    loop_selection = CampaignStageSelection(
        requested_ref=StageRef("campaign_main", "loop_alias"),
        selected_ref=loop.definition.ref,
        loop_stage_switch=True,
    )
    completed_one_time = _completed(one_time)
    completed_loop = _completed(loop)
    evidence = CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE)

    assert (
        _guard_decision(_job(one_time), evidence, state=completed_one_time).stop_reason
        is CampaignStopReason.ONE_TIME_STAGE
    )
    assert (
        _guard_decision(
            _job(loop, stage_selections=(loop_selection,)),
            evidence,
            state=completed_loop,
        ).stop_reason
        is CampaignStopReason.LOOP_STAGE_SWITCH
    )


def test_gems_event_guard_switches_to_typed_fallback_without_entering_map() -> None:
    primary = _session(ref=StageRef("event_test", "d3"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    job = _job(
        primary,
        task_id="gems_farming",
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.SHIP,
            GemsCommonDestroyer.ANY,
        ),
    )
    observer = _Observer(BattlefieldObservation(battle_index=0, enemy=1))
    driver = _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY))
    guards = _GuardSource(
        before=CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY, event_available=False),
    )
    lifecycle = _RuntimeLifecycle()

    report = LiveCampaignWorkflow(
        observer,
        driver,
        _Clock(),
        services=CampaignLiveServices(guards=guards, lifecycle=lifecycle),
    ).execute(
        job,
        AbortToken(),
    )

    assert report.stop_reason is CampaignStopReason.GEMS_EVENT_FALLBACK
    assert report.stage_ref == fallback.definition.ref
    assert report.session_state.variant is CampaignRunVariant.NORMAL
    assert observer.calls == []
    assert lifecycle.calls == [(fallback, report.session_state, CampaignStopReason.GEMS_EVENT_FALLBACK)]


def test_gems_replacement_trigger_is_explicit_in_guard_decision() -> None:
    primary = _session(ref=StageRef("event_test", "d3"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    job = _job(
        primary,
        task_id="gems_farming",
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.SHIP,
            GemsCommonDestroyer.ANY,
        ),
    )
    completed = _completed(primary)

    decision = _guard_decision(
        job,
        CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, gems_level_limit=True),
        state=completed,
    )

    assert decision.gems_replacement is GemsFleetReplacementTrigger.LEVEL
    assert decision.stop_reason is None


@pytest.mark.parametrize(
    ("evidence", "trigger"),
    [
        (
            CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, gems_level_limit=True),
            GemsFleetReplacementTrigger.LEVEL,
        ),
        (
            CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, gems_emotion_limit=True),
            GemsFleetReplacementTrigger.EMOTION,
        ),
    ],
)
def test_gems_workflow_replaces_fleet_and_checkpoints_completed_map(
    evidence: CampaignGuardEvidence,
    trigger: GemsFleetReplacementTrigger,
) -> None:
    primary = _session(ref=StageRef("event_test", "d3"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    job = _job(
        primary,
        task_id="gems_farming",
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.SHIP,
            GemsCommonDestroyer.ANY,
        ),
    )
    fleets = _GemsFleetExecutor(GemsFleetReplacementCompleted())
    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(
            guards=_GuardSource(after=evidence),
            gems_fleets=fleets,
        ),
    )

    report = workflow.execute(job, AbortToken())

    assert report.stop_reason is CampaignStopReason.IN_PROGRESS
    assert report.session_state.status is CampaignSessionStatus.COMPLETED
    assert fleets.calls == [(job, primary, trigger)]


def test_gems_workflow_reports_real_replacement_failure() -> None:
    primary = _session(ref=StageRef("event_test", "d3"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    job = _job(
        primary,
        task_id="gems_farming",
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.DISABLED,
            GemsCommonDestroyer.ANY,
        ),
    )
    fleets = _GemsFleetExecutor(GemsFleetReplacementFailed("no eligible carrier"))
    workflow = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(
            guards=_GuardSource(after=CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, gems_level_limit=True)),
            gems_fleets=fleets,
        ),
    )

    report = workflow.execute(job, AbortToken())

    assert report.stop_reason is CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED


def test_gems_pre_entry_emotion_replacement_never_enters_the_map() -> None:
    primary = _session(ref=StageRef("event_test", "d3"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    job = _job(
        primary,
        task_id="gems_farming",
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.SHIP,
            GemsCommonDestroyer.ANY,
        ),
    )
    observer = _Observer(BattlefieldObservation(0, enemy=1))
    fleets = _GemsFleetExecutor(GemsFleetReplacementCompleted())
    report = LiveCampaignWorkflow(
        observer,
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(
            guards=_GuardSource(
                before=CampaignGuardEvidence(
                    CampaignGuardPhase.PRE_ENTRY,
                    gems_emotion_limit=True,
                )
            ),
            gems_fleets=fleets,
        ),
    ).execute(job, AbortToken())

    assert report.stop_reason is CampaignStopReason.GEMS_FLEET_REPLACED
    assert report.gems_replacement == GemsFleetReplacementRequest(
        GemsFleetReplacementTrigger.EMOTION,
        GemsFleetReplacementBoundary.PRE_ENTRY,
    )
    assert observer.calls == []


def test_pending_gems_replacement_is_consumed_before_any_map_io() -> None:
    primary = _session(ref=StageRef("event_test", "d3"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    pending = GemsFleetReplacementRequest(
        GemsFleetReplacementTrigger.LEVEL,
        GemsFleetReplacementBoundary.POST_MAP,
    )
    progress = CampaignProgress(
        primary.definition.ref,
        primary.variant,
        primary.initial_state(),
        2,
        1,
        "content-1",
        pending,
    )
    job = _job(
        primary,
        task_id="gems_farming",
        progress=progress,
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.SHIP,
            GemsCommonDestroyer.ANY,
        ),
    )
    observer = _Observer(BattlefieldObservation(0, enemy=1))
    fleets = _GemsFleetExecutor(GemsFleetReplacementCompleted())
    report = LiveCampaignWorkflow(
        observer,
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(
            guards=_GuardSource(),
            gems_fleets=fleets,
        ),
    ).execute(job, AbortToken())

    assert report.stop_reason is CampaignStopReason.GEMS_FLEET_REPLACED
    assert report.gems_replacement == pending
    assert observer.calls == []


def test_gems_low_emotion_interruption_resets_the_withdrawn_map() -> None:
    primary = _session(ref=StageRef("event_test", "d3"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    job = _job(
        primary,
        task_id="gems_farming",
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.SHIP,
            GemsCommonDestroyer.ANY,
        ),
    )
    fleets = _GemsFleetExecutor(GemsFleetReplacementCompleted())
    report = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(lambda attempt: BattleInterrupted(attempt, BattleInterruptionReason.GEMS_LOW_EMOTION)),
        _Clock(),
        services=CampaignLiveServices(guards=_GuardSource(), gems_fleets=fleets),
    ).execute(job, AbortToken())

    assert report.stop_reason is CampaignStopReason.GEMS_FLEET_REPLACED
    assert report.session_state == primary.initial_state()
    assert report.runs_completed == 0
    assert report.gems_replacement == GemsFleetReplacementRequest(
        GemsFleetReplacementTrigger.EMOTION,
        GemsFleetReplacementBoundary.MAP_WITHDRAWN,
    )


def test_gems_final_run_attempts_replacement_before_run_count_stop() -> None:
    primary = _session(ref=StageRef("event_test", "d3"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    job = _job(
        primary,
        task_id="gems_farming",
        limits=CampaignLimits(run_count=1),
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.SHIP,
            GemsCommonDestroyer.ANY,
        ),
    )
    fleets = _GemsFleetExecutor(GemsFleetReplacementFailed("no eligible carrier"))
    report = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(
            guards=_GuardSource(after=CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE, gems_level_limit=True)),
            gems_fleets=fleets,
        ),
    ).execute(job, AbortToken())

    assert report.stop_reason is CampaignStopReason.RUN_COUNT_LIMIT
    assert report.runs_completed == 1
    assert len(fleets.calls) == 1


def test_hard_gems_preparation_failure_becomes_a_persistable_request() -> None:
    primary = _session(ref=StageRef("campaign_main", "12-4"))
    fallback = _session(ref=StageRef("campaign_main", "2-4"))
    request = GemsFleetReplacementRequest(
        GemsFleetReplacementTrigger.HARD_PREPARATION,
        GemsFleetReplacementBoundary.PRE_ENTRY,
    )
    job = _job(
        primary,
        task_id="gems_farming",
        gems_farming=GemsFarmingPolicy(
            fallback,
            GemsFlagshipChange.SHIP,
            GemsCommonCarrier.ANY,
            GemsVanguardChange.SHIP,
            GemsCommonDestroyer.ANY,
        ),
    )
    report = LiveCampaignWorkflow(
        _Observer(BattlefieldObservation(0, enemy=1)),
        _Driver(lambda attempt: BattleSucceeded(attempt, BattleTarget.ENEMY)),
        _Clock(),
        services=CampaignLiveServices(
            activator=_GemsFailureActivator(CampaignGemsReplacementFailed(request, "no hard fleet candidate"))
        ),
    ).execute(job, AbortToken())

    assert report.stop_reason is CampaignStopReason.GEMS_HARD_PREPARATION_FAILED
    assert report.gems_replacement == request
    assert report.session_state == primary.initial_state()


@dataclass(slots=True)
class _Grid:
    label: builtins.str
    is_enemy: bool = False
    is_siren: bool = False
    is_boss: bool = False
    is_accessible: bool = True
    may_siren: bool = False
    enemy_scale: int = 1
    enemy_genre: builtins.str | None = "Enemy"
    location: tuple[int, int] | None = None
    weight: float = 50
    cost: float = 1
    cost_1: float = 1
    cost_2: float = 1

    @property
    def str(self) -> builtins.str:
        return self.label

    def __str__(self) -> builtins.str:
        return self.label


class _Fleet:
    def __init__(self, runtime: _Runtime, name: str) -> None:
        self.runtime = runtime
        self.name = name

    def clear_chosen_enemy(self, grid: _Grid, expected: str = "") -> object:
        return self.runtime.clear(self.name, grid, expected)


class _Runtime:
    def __init__(self, grids: Iterable[_Grid], *, confirmed_delta: int = 1) -> None:
        self.map = list(grids)
        self.battle_count = 0
        self.confirmed_delta = confirmed_delta
        self.action_error: Exception | None = None
        self.roadblocks: list[_Grid] = []
        self.calls: list[object] = []
        self._fleet_1 = _Fleet(self, "fleet_1")
        self._fleet_boss = _Fleet(self, "fleet_boss")

    @property
    def fleet_1(self) -> _Fleet:
        self.calls.append("select_fleet_1")
        return self._fleet_1

    @property
    def fleet_boss(self) -> _Fleet:
        self.calls.append("select_fleet_boss")
        return self._fleet_boss

    @property
    def fleet_boss_index(self) -> int:
        return 2

    def full_scan(self) -> None:
        self.calls.append("full_scan")

    def find_path_initial(self) -> None:
        self.calls.append("find_path_initial")

    def read_battle_flag(self, flag: BattleFlag) -> bool:
        self.calls.append(("flag", flag.value))
        return False

    def execute_auto_search_battle(
        self,
        battle_index: int,
        cancellation: CancellationSource,
    ) -> BattleTarget:
        cancellation.raise_if_requested()
        self.calls.append(("auto_search", battle_index))
        self.battle_count += self.confirmed_delta
        return BattleTarget.ENEMY

    def brute_find_roadblocks(self, grid: _Grid, fleet: int | None = None) -> list[_Grid]:
        self.calls.append(("roadblocks", grid.label, fleet))
        return self.roadblocks

    def clear_chosen_enemy(self, grid: _Grid, expected: str = "") -> object:
        return self.clear("map", grid, expected)

    def clear(self, executor: str, grid: _Grid, expected: str) -> object:
        self.calls.append(("clear", executor, grid.label, expected))
        self.battle_count += self.confirmed_delta
        if self.action_error is not None:
            raise self.action_error
        return True


class _RuntimeSource:
    def __init__(self, runtime: _Runtime) -> None:
        self.runtime = runtime
        self.calls = 0
        self.commits = 0

    def active_runtime(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CampaignMapRuntime:
        del session
        cancellation.raise_if_requested()
        self.calls += 1
        return cast("CampaignMapRuntime", self.runtime)

    def commit_active_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CommittedCampaignUnit:
        del session
        cancellation.raise_if_requested()
        self.commits += 1
        return CommittedCampaignUnit(cast("CampaignMapRuntime", self.runtime), cancellation)


def _attempt(intent: object) -> BattleAttempt:
    battle_intent = cast(
        "ClearSiren | ClearFilteredEnemy | DefaultBattle | ClearBossRoadblock | ClearBoss",
        intent,
    )
    return BattleAttempt(0, 0, 0, battle_intent)


def test_map_adapter_observes_real_map_flags() -> None:
    runtime = _Runtime(
        (
            _Grid("1L", is_enemy=True),
            _Grid("S", is_enemy=True, is_siren=True),
            _Grid("B", is_enemy=True, is_boss=True, is_accessible=False),
        )
    )
    session = _session()

    observation = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).observe(
        session,
        session.initial_state(),
        AbortToken(),
    )

    assert observation == BattlefieldObservation(battle_index=0, enemy=1, siren=1, boss=1)
    assert runtime.calls[:2] == ["full_scan", "find_path_initial"]


def test_map_adapter_filtered_enemy_preserves_priority_prefix_and_confirms_action() -> None:
    runtime = _Runtime(
        (
            _Grid("3L", is_enemy=True),
            _Grid("1L", is_enemy=True),
            _Grid("2L", is_enemy=True),
        )
    )
    session = _session()
    attempt = _attempt(ClearFilteredEnemy(preserve=1))

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        session,
        attempt,
        AbortToken(),
    )

    assert outcome == BattleSucceeded(attempt, BattleTarget.ENEMY)
    assert ("clear", "map", "2L", "") in runtime.calls


def test_map_adapter_applies_siren_genre_and_hidden_candidate_contract() -> None:
    runtime = _Runtime(
        (
            _Grid("DD", is_siren=True, enemy_genre="DD", weight=1),
            _Grid("CL", is_siren=True, enemy_genre="CL", weight=9),
            _Grid("candidate"),
        )
    )
    attempt = _attempt(ClearSiren(("CL",), include_hidden_candidates=True))

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        _session(),
        attempt,
        AbortToken(),
    )

    assert outcome == BattleSucceeded(attempt, BattleTarget.SIREN)
    assert ("clear", "map", "CL", "siren") in runtime.calls
    assert all(grid.may_siren for grid in runtime.map)


def test_map_adapter_honors_declared_enemy_sort_order() -> None:
    runtime = _Runtime(
        (
            _Grid("near-fleet-1", is_enemy=True, cost_1=1, cost_2=8),
            _Grid("near-fleet-2", is_enemy=True, cost_1=9, cost_2=2),
        )
    )
    attempt = _attempt(ClearAnyEnemy(sort=("cost_2",)))

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        _session(),
        attempt,
        AbortToken(),
    )

    assert outcome == BattleSucceeded(attempt, BattleTarget.ENEMY)
    assert ("clear", "map", "near-fleet-2", "") in runtime.calls


def test_map_adapter_calls_explicit_auto_search_port() -> None:
    runtime = _Runtime((_Grid("enemy", is_enemy=True),))
    attempt = BattleAttempt(0, 0, 0, AutoSearchBattle())

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        _session(),
        attempt,
        AbortToken(),
    )

    assert outcome == BattleSucceeded(attempt, BattleTarget.ENEMY)
    assert ("auto_search", 0) in runtime.calls


def test_map_adapter_returns_no_target_without_issuing_action() -> None:
    runtime = _Runtime((_Grid("1L", is_enemy=True, is_accessible=False),))
    session = _session()
    attempt = _attempt(DefaultBattle())

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        session,
        attempt,
        AbortToken(),
    )

    assert outcome == NoBattleTarget(attempt)
    assert not any(isinstance(call, tuple) and call[0] == "clear" for call in runtime.calls)


def test_map_adapter_does_not_fabricate_success_without_confirmation() -> None:
    runtime = _Runtime((_Grid("1L", is_enemy=True),), confirmed_delta=0)
    session = _session()
    attempt = _attempt(DefaultBattle())

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        session,
        attempt,
        AbortToken(),
    )

    assert isinstance(outcome, BattleFailed)
    assert outcome.attempt == attempt


def test_map_adapter_accepts_one_confirmation_even_when_action_raises() -> None:
    runtime = _Runtime((_Grid("1L", is_enemy=True),))
    runtime.action_error = RuntimeError("action failed after battle confirmation")
    attempt = _attempt(DefaultBattle())

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        _session(),
        attempt,
        AbortToken(),
    )

    assert outcome == BattleSucceeded(attempt, BattleTarget.ENEMY)
    assert runtime.battle_count == 1


def test_map_adapter_converts_closed_low_emotion_withdrawal_to_typed_interruption() -> None:
    runtime = _Runtime((_Grid("1L", is_enemy=True),), confirmed_delta=0)
    runtime.action_error = CampaignActionInterrupted(BattleInterruptionReason.GEMS_LOW_EMOTION)
    source = _RuntimeSource(runtime)
    attempt = _attempt(DefaultBattle())

    outcome = ExistingCampaignMapAdapter(source).issue_and_confirm(
        _session(),
        attempt,
        AbortToken(),
    )

    assert outcome == BattleInterrupted(attempt, BattleInterruptionReason.GEMS_LOW_EMOTION)
    assert source.commits == 1


def test_map_adapter_rejects_more_than_one_confirmation() -> None:
    runtime = _Runtime((_Grid("1L", is_enemy=True),), confirmed_delta=2)
    adapter = ExistingCampaignMapAdapter(_RuntimeSource(runtime))

    with pytest.raises(CampaignMapAdapterError, match="changed battle_count by 2"):
        adapter.issue_and_confirm(_session(), _attempt(DefaultBattle()), AbortToken())


@pytest.mark.parametrize(
    ("strategy", "executor"),
    [
        (BossStrategy.FLEET_BOSS, "fleet_boss"),
        (BossStrategy.FLEET_1, "fleet_1"),
        (BossStrategy.MAP_SEARCH, "map"),
        (BossStrategy.BRUTE_FORCE, "fleet_boss"),
    ],
)
def test_map_adapter_dispatches_every_boss_strategy_explicitly(
    strategy: BossStrategy,
    executor: str,
) -> None:
    runtime = _Runtime((_Grid("B", is_boss=True),))
    attempt = _attempt(ClearBoss(strategy))

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        _session(),
        attempt,
        AbortToken(),
    )

    assert outcome == BattleSucceeded(attempt, BattleTarget.BOSS)
    assert ("clear", executor, "B", "boss") in runtime.calls


def test_map_adapter_issues_boss_roadblock_as_enemy_not_boss() -> None:
    runtime = _Runtime((_Grid("B", is_boss=True, is_accessible=False), _Grid("1L", is_enemy=True)))
    runtime.roadblocks = [runtime.map[1]]
    attempt = _attempt(ClearBossRoadblock(BossStrategy.BRUTE_FORCE))

    outcome = ExistingCampaignMapAdapter(_RuntimeSource(runtime)).issue_and_confirm(
        _session(),
        attempt,
        AbortToken(),
    )

    assert outcome == BattleSucceeded(attempt, BattleTarget.ENEMY)
    assert ("clear", "map", "1L", "") in runtime.calls


def test_map_adapter_checks_cancellation_before_observer_io() -> None:
    runtime = _Runtime((_Grid("1L", is_enemy=True),))
    cancellation = AbortToken()
    cancellation.request("stop before scan")

    with pytest.raises(AbortRequested, match="stop before scan"):
        ExistingCampaignMapAdapter(_RuntimeSource(runtime)).observe(
            _session(),
            _session().initial_state(),
            cancellation,
        )

    assert runtime.calls == []
