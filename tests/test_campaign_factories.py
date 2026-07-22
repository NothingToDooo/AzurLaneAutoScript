from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortToken,
    Blocked,
    DailySchedule,
    Deferred,
    DelayRange,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
    RescheduleSelf,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.content.battle_policy import BattlePolicy
from module.content.battle_program import PickedMapItem, VisitedFixedTarget
from module.content.campaign_session import CampaignRunVariant, CampaignSession
from module.content.campaign_session_source import CampaignStageSelection
from module.content.mechanic_rules import MapItemKind
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
from module.gameplay.campaign import (
    CampaignAutomationSettings,
    CampaignDifficulty,
    CampaignEnemyPrioritySettings,
    CampaignExecutionSettings,
    CampaignFleetSettings,
    CampaignHpControlSettings,
    CampaignJobSettings,
    CampaignJobSpec,
    CampaignLimits,
    CampaignMapAchievement,
    CampaignProgress,
    CampaignRunReport,
    CampaignStopReason,
    CampaignSubmarineSettings,
    CampaignWorkflow,
    EnemyPriorityMode,
    FleetMode,
    FleetOrder,
    GemsCommonCarrier,
    GemsCommonDestroyer,
    GemsFarmingSettings,
    GemsFlagshipChange,
    GemsVanguardChange,
    SubmarineAutoSearchMode,
    SubmarineDistanceToBoss,
    SubmarineMode,
    TaskBalancerPolicy,
)
from module.gameplay.campaign_factories import (
    CampaignFactoryDependencies,
    CampaignSessionSource,
    build_campaign_factories,
)
from module.gameplay.emotion import (
    EmotionControl,
    EmotionMode,
    EmotionRecoverLocation,
    EmotionSettings,
    FleetEmotionSettings,
)
from module.runtime import (
    FrozenJsonValue,
    TaskBuildContext,
    TaskStateDocument,
    TaskStateDocumentError,
    TaskStateEntry,
)
from module.task_registry import TASK_SPECS

if TYPE_CHECKING:
    from module.application import CancellationSource


_OBSERVED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)


def _session(ref: StageRef, variant: CampaignRunVariant) -> CampaignSession:
    cells = (CellSpec(CellId(0, 0), "MB", 1.0),)
    run_variant = RunVariant(cells=cells, spawn_waves=(SpawnWave(battle=0, boss=1),))
    definition = CampaignStageDefinition(
        ref=ref,
        map=MapDefinition(
            name=ref.stage_id,
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
        battle_policies={0: BattlePolicy("fleet_boss")},
    )
    return CampaignSession(definition, variant)


class _SessionSource:
    def __init__(self) -> None:
        self.calls: list[tuple[StageRef, CampaignRunVariant]] = []

    def resolve(self, ref: StageRef, variant: CampaignRunVariant) -> CampaignSession:
        self.calls.append((ref, variant))
        return _session(ref, variant)

    @staticmethod
    def select(
        ref: StageRef,
        *,
        remaining_runs: int,
        preferred_ref: StageRef | None = None,
    ) -> CampaignStageSelection:
        del remaining_runs, preferred_ref
        return CampaignStageSelection(ref, ref)


class _SelectingSource(_SessionSource):
    def __init__(self) -> None:
        super().__init__()
        self.selection_calls: list[tuple[StageRef, int, StageRef | None]] = []

    def select(
        self,
        ref: StageRef,
        *,
        remaining_runs: int,
        preferred_ref: StageRef | None = None,
    ) -> CampaignStageSelection:
        self.selection_calls.append((ref, remaining_runs, preferred_ref))
        selected_ref = StageRef(ref.pack_id, "th4") if preferred_ref is None else preferred_ref
        return CampaignStageSelection(
            requested_ref=ref,
            selected_ref=selected_ref,
            loop_stage_switch=True,
        )


class _Workflow:
    def __init__(self) -> None:
        self.calls = 0
        self.last_job: CampaignJobSpec | None = None

    def discard_checkpoint(self) -> None:
        pass

    def execute(
        self,
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> CampaignRunReport:
        cancellation.raise_if_requested()
        self.calls += 1
        self.last_job = job
        session = job.sessions[0]
        return CampaignRunReport(
            stage_ref=session.definition.ref,
            observed_at=_OBSERVED_AT,
            stop_reason=CampaignStopReason.COMPLETED,
            session_state=(session.initial_state() if job.progress is None else job.progress.session_state),
        )


def _dependencies(
    *,
    workflow: _Workflow | None = None,
    sessions: _SessionSource | None = None,
) -> CampaignFactoryDependencies:
    return CampaignFactoryDependencies(
        workflow=_Workflow() if workflow is None else workflow,
        sessions=_SessionSource() if sessions is None else sessions,
    )


def _stage_refs(command: str) -> tuple[StageRef, ...]:
    if command in {"event_a", "event_b", "event_c", "event_d"}:
        return tuple(StageRef("event_20260625_cn", stage_id) for stage_id in ("a1", "a2"))
    if command == "event_sp":
        return (StageRef("event_20260625_cn", "sp"),)
    if command in {"event", "event2", "gems_farming"}:
        return (StageRef("event_20260625_cn", "d3"),)
    if command == "war_archives":
        return (StageRef("campaign_war_archives", "d3"),)
    return (StageRef("campaign_main", "12-4"),)


_EXECUTION = CampaignExecutionSettings(
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
        fleet2_mode=FleetMode.COMBAT_MANUAL,
        fleet2_step=2,
        order=FleetOrder.FLEET1_MOB_FLEET2_BOSS,
    ),
    submarine=CampaignSubmarineSettings(
        fleet=1,
        mode=SubmarineMode.BOSS_ONLY,
        auto_search_mode=SubmarineAutoSearchMode.AUTO_CALL,
        distance_to_boss=SubmarineDistanceToBoss.TWO_GRIDS_TO_BOSS,
    ),
    emotion=EmotionSettings(
        mode=EmotionMode.CALCULATE,
        fleet1=FleetEmotionSettings(
            control=EmotionControl.PREVENT_GREEN_FACE,
            recover=EmotionRecoverLocation.NOT_IN_DORMITORY,
            oath=False,
        ),
        fleet2=FleetEmotionSettings(
            control=EmotionControl.KEEP_EXP_BONUS,
            recover=EmotionRecoverLocation.DORMITORY_FLOOR_1,
            oath=True,
        ),
    ),
    hp_control=CampaignHpControlSettings(
        use_hp_balance=True,
        use_emergency_repair=False,
        use_low_hp_retreat=True,
        hp_balance_threshold=0.2,
        hp_balance_weight=(1_000, 900, 800),
        repair_use_single_threshold=0.3,
        repair_use_multi_threshold=0.6,
        low_hp_retreat_threshold=0.3,
    ),
    enemy_priority=CampaignEnemyPrioritySettings(
        scale_balance_weight=EnemyPriorityMode.LARGE_ENEMY_FIRST,
    ),
)


def _valid_settings(command: str) -> CampaignJobSettings:
    gems_farming = None
    if command == "gems_farming":
        gems_farming = GemsFarmingSettings(
            fallback_ref=StageRef("campaign_main", "2-4"),
            flagship_change=GemsFlagshipChange.SHIP_AND_EQUIPMENT,
            common_carrier=GemsCommonCarrier.LANGLEY,
            vanguard_change=GemsVanguardChange.SHIP_AND_EQUIPMENT,
            common_destroyer=GemsCommonDestroyer.Z20_OR_Z21,
            replacement_retry_delay=timedelta(minutes=30),
        )
    return CampaignJobSettings(
        task_id=TaskId(command),
        stage_refs=_stage_refs(command),
        difficulty=CampaignDifficulty.NORMAL,
        execution=_EXECUTION,
        schedule=DailySchedule("Asia/Hong_Kong", (time(4),)),
        failure_retry_delay=DelayRange(1_800, 1_800),
        resource_retry_delay=timedelta(hours=3),
        limits=CampaignLimits(
            run_count=0,
            reach_level=0,
            oil=1_000,
            stop_on_new_ship=False,
            event_points=0,
            event_deadline_at=None,
            map_achievement=CampaignMapAchievement.NON_STOP,
            stage_increase=False,
        ),
        task_balancer=None,
        gems_farming=gems_farming,
    )


def _context(
    command: str,
    settings: object,
    *,
    content_revision: str = "content-1",
    task_state: TaskStateDocument | None = None,
) -> TaskBuildContext:
    return TaskBuildContext(
        spec=TASK_SPECS[command],
        settings_revision=3,
        content_revision=content_revision,
        settings=settings,
        task_state=TaskStateDocument.empty(command) if task_state is None else task_state,
    )


def _task_context(command: str) -> TaskContext:
    return TaskContext(
        task_id=TaskId(command),
        started_at=_OBSERVED_AT,
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=3, content_revision="content-1"),
        abort=AbortToken(),
    )


def _progress_payload(
    *,
    settings_revision: int = 3,
    pending: FrozenJsonValue = None,
    next_attempt_id: int = 0,
    program_state_initialized: bool = False,
    program_markers: tuple[str, ...] = (),
) -> dict[str, FrozenJsonValue]:
    variant = "normal"
    return {
        "stage_ref": {"pack_id": "campaign_main", "stage_id": "12-4"},
        "variant": variant,
        "session_state": {
            "variant": variant,
            "status": "active",
            "battle_index": 0,
            "remaining": {"enemy": 0, "siren": 0, "mystery": 0, "boss": 1},
            "next_attempt_id": next_attempt_id,
            "next_intent_index": 0,
            "pending": pending,
            "reason": None,
            "program_state_initialized": program_state_initialized,
            "program_flags": (),
            "program_markers": program_markers,
        },
        "runs_completed": 2,
        "settings_revision": settings_revision,
        "content_revision": "content-1",
        "pending_gems_replacement": None,
    }


def _task_state(
    command: str,
    payload: FrozenJsonValue,
    *,
    key: str = "progress",
    schema_version: int = 4,
) -> TaskStateDocument:
    return TaskStateDocument(
        namespace=command,
        entries={
            key: TaskStateEntry(
                schema_version=schema_version,
                payload=payload,
                updated_at=_OBSERVED_AT,
            )
        },
    )


def test_campaign_factory_decodes_complete_typed_execution_settings() -> None:
    workflow = _Workflow()
    task = build_campaign_factories(_dependencies(workflow=workflow))["main"].build(
        _context("main", _valid_settings("main"))
    )

    task.run(_task_context("main"))

    execution = cast("CampaignJobSpec", workflow.last_job).execution
    assert isinstance(execution, CampaignExecutionSettings)
    assert execution.automation.use_auto_search
    assert execution.fleets.fleet2_mode.value == "combat_manual"
    assert execution.submarine.mode.value == "boss_only"
    assert execution.emotion.fleet2.control.value == "keep_exp_bonus"
    assert execution.hp_control.hp_balance_weight == (1_000, 900, 800)
    assert execution.enemy_priority.scale_balance_weight.value == "S3_enemy_first"


def test_campaign_factory_restores_a_strongly_typed_progress_checkpoint() -> None:
    workflow = _Workflow()
    task_state = _task_state("main", _progress_payload())
    task = build_campaign_factories(_dependencies(workflow=workflow))["main"].build(
        _context("main", _valid_settings("main"), task_state=task_state)
    )

    task.run(_task_context("main"))

    progress = cast("CampaignProgress", cast("CampaignJobSpec", workflow.last_job).progress)
    assert progress.stage_ref == StageRef("campaign_main", "12-4")
    assert progress.variant is CampaignRunVariant.NORMAL
    assert progress.session_state == _session(progress.stage_ref, progress.variant).initial_state()
    assert progress.runs_completed == 2
    assert progress.settings_revision == 3
    assert progress.content_revision == "content-1"


def test_campaign_factory_restores_typed_program_facts_from_checkpoint() -> None:
    workflow = _Workflow()
    task_state = _task_state(
        "main",
        _progress_payload(
            program_state_initialized=True,
            program_markers=(
                "picked_map_item:flare:7:6",
                "visited_fixed_target:6:2",
            ),
        ),
    )
    task = build_campaign_factories(_dependencies(workflow=workflow))["main"].build(
        _context("main", _valid_settings("main"), task_state=task_state)
    )

    task.run(_task_context("main"))

    state = cast("CampaignProgress", cast("CampaignJobSpec", workflow.last_job).progress).session_state
    assert state.program_markers == frozenset(
        {
            PickedMapItem(MapItemKind.FLARE, CellId(7, 6)),
            VisitedFixedTarget(CellId(6, 2)),
        }
    )


def test_valid_but_stale_campaign_checkpoint_is_deleted_by_the_task_before_workflow() -> None:
    workflow = _Workflow()
    task_state = _task_state("main", _progress_payload(settings_revision=2))
    task = build_campaign_factories(_dependencies(workflow=workflow))["main"].build(
        _context("main", _valid_settings("main"), task_state=task_state)
    )

    result = task.run(_task_context("main"))

    assert workflow.calls == 0
    assert result == TaskResult(
        outcome=Deferred("stale campaign progress was discarded"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(DeleteTaskState("main", "progress"),),
    )


@pytest.mark.parametrize(
    ("task_state", "message"),
    [
        (_task_state("main", _progress_payload(), schema_version=1), "schema version"),
        (_task_state("main", ()), "must be an object"),
        (_task_state("main", _progress_payload() | {"legacy": True}), "unknown settings"),
        (_task_state("main", {}, key="legacy"), "unknown campaign task state keys"),
    ],
)
def test_campaign_factory_rejects_unknown_schema_or_malformed_progress(
    task_state: TaskStateDocument,
    message: str,
) -> None:
    with pytest.raises(TaskStateDocumentError, match=message):
        build_campaign_factories(_dependencies())["main"].build(
            _context("main", _valid_settings("main"), task_state=task_state)
        )


@pytest.mark.parametrize("attempt_id", [0, 1])
def test_campaign_factory_never_hydrates_a_pending_battle_attempt(attempt_id: int) -> None:
    pending: dict[str, FrozenJsonValue] = {
        "battle_index": 0,
        "attempt_id": attempt_id,
        "intent_index": 0,
        "intent": {"kind": "clear_boss"},
    }
    payload = _progress_payload(pending=pending, next_attempt_id=1)

    with pytest.raises(TaskStateDocumentError, match="pending"):
        build_campaign_factories(_dependencies())["main"].build(
            _context("main", _valid_settings("main"), task_state=_task_state("main", payload))
        )


def test_campaign_factory_rejects_pending_before_decoding_its_legacy_intent_tag() -> None:
    pending: dict[str, FrozenJsonValue] = {
        "battle_index": 0,
        "attempt_id": 0,
        "intent_index": 0,
        "intent": {"kind": "legacy_dynamic_battle"},
    }
    payload = _progress_payload(pending=pending, next_attempt_id=1)

    with pytest.raises(TaskStateDocumentError, match="pending"):
        build_campaign_factories(_dependencies())["main"].build(
            _context("main", _valid_settings("main"), task_state=_task_state("main", payload))
        )


def test_gems_factory_resolves_explicit_primary_and_fallback_sessions() -> None:
    source = _SessionSource()
    workflow = _Workflow()
    factories = build_campaign_factories(_dependencies(workflow=workflow, sessions=source))

    task = factories["gems_farming"].build(_context("gems_farming", _valid_settings("gems_farming")))
    result = task.run(_task_context("gems_farming"))

    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(datetime(2026, 7, 13, 20, tzinfo=UTC)),),
        state_effects=(DeleteTaskState("gems_farming", "progress"),),
    )
    assert source.calls == [
        (StageRef("event_20260625_cn", "d3"), CampaignRunVariant.NORMAL),
        (StageRef("event_20260625_cn", "d3"), CampaignRunVariant.LOOP),
        (StageRef("campaign_main", "2-4"), CampaignRunVariant.NORMAL),
    ]
    job = cast("CampaignJobSpec", workflow.last_job)
    assert job.stage_refs == (StageRef("event_20260625_cn", "d3"),)
    assert job.schedule == DailySchedule("Asia/Hong_Kong", (time(4),))
    assert job.gems_farming is not None
    assert job.gems_farming.fallback_session.definition.ref == StageRef("campaign_main", "2-4")
    assert job.gems_farming.transfers_flagship_equipment
    assert job.gems_farming.changes_vanguard
    assert job.gems_farming.transfers_vanguard_equipment


@pytest.mark.parametrize("command", ["event_sp", "event_a"])
def test_missing_daily_content_is_explicit_and_does_not_query_a_legacy_fallback(command: str) -> None:
    source = _SessionSource()
    workflow = _Workflow()
    settings = replace(_valid_settings(command), stage_refs=())
    task = build_campaign_factories(_dependencies(workflow=workflow, sessions=source))[command].build(
        _context(command, settings)
    )

    result = task.run(_task_context(command))

    assert source.calls == []
    assert workflow.calls == 0
    assert result == TaskResult(
        outcome=Blocked("campaign content is unavailable"),
        effects=(DisableTask(TaskId(command)),),
        state_effects=(DeleteTaskState(command, "progress"),),
    )


def test_factory_rejects_untyped_or_mismatched_campaign_settings() -> None:
    factory = build_campaign_factories(_dependencies())["main"]
    with pytest.raises(TypeError, match="main settings must be CampaignJobSettings"):
        factory.build(_context("main", object()))
    with pytest.raises(ValueError, match="settings task_id must match 'main'"):
        factory.build(_context("main", _valid_settings("main2")))


def test_gems_fallback_must_differ_from_the_primary_stage() -> None:
    settings = _valid_settings("gems_farming")
    assert settings.gems_farming is not None
    settings = replace(
        settings,
        gems_farming=replace(settings.gems_farming, fallback_ref=settings.stage_refs[0]),
    )

    with pytest.raises(ValueError, match="fallback stage must differ"):
        build_campaign_factories(_dependencies())["gems_farming"].build(_context("gems_farming", settings))


def test_task_balancer_passes_an_explicit_main_target() -> None:
    workflow = _Workflow()
    settings = replace(
        _valid_settings("main"),
        task_balancer=TaskBalancerPolicy(TaskId("main2"), 10_000),
    )
    task = build_campaign_factories(_dependencies(workflow=workflow))["main"].build(_context("main", settings))

    task.run(_task_context("main"))

    job = cast("CampaignJobSpec", workflow.last_job)
    assert job.task_balancer is not None
    assert job.task_balancer.target_task_id == TaskId("main2")
    assert job.task_balancer.coin_limit == 10_000


def test_difficulty_is_independent_from_both_compiled_map_variants() -> None:
    source = _SessionSource()
    settings = replace(_valid_settings("main"), difficulty=CampaignDifficulty.HARD)

    workflow = _Workflow()
    task = build_campaign_factories(_dependencies(workflow=workflow, sessions=source))["main"].build(
        _context("main", settings)
    )
    task.run(_task_context("main"))

    assert source.calls == [
        (StageRef("campaign_main", "12-4"), CampaignRunVariant.NORMAL),
        (StageRef("campaign_main", "12-4"), CampaignRunVariant.LOOP),
    ]
    assert cast("CampaignJobSpec", workflow.last_job).difficulty.value == "hard"


def test_factory_selects_a_loop_alias_once_and_resolves_both_variants_from_the_canonical_stage() -> None:
    source = _SelectingSource()
    workflow = _Workflow()
    baseline = _valid_settings("main")
    settings = replace(
        baseline,
        stage_refs=(StageRef("event_20221124_cn", "th"),),
        limits=replace(baseline.limits, run_count=2),
    )

    task = build_campaign_factories(_dependencies(workflow=workflow, sessions=source))["main"].build(
        _context("main", settings)
    )
    task.run(_task_context("main"))

    requested = StageRef("event_20221124_cn", "th")
    selected = StageRef("event_20221124_cn", "th4")
    assert source.selection_calls == [(requested, 2, None)]
    assert source.calls == [
        (selected, CampaignRunVariant.NORMAL),
        (selected, CampaignRunVariant.LOOP),
    ]
    job = cast("CampaignJobSpec", workflow.last_job)
    assert job.stage_refs == (selected,)
    assert job.stage_selections == (CampaignStageSelection(requested, selected, loop_stage_switch=True),)


def test_factory_keeps_the_selected_loop_stage_while_resuming_the_same_settings_revision() -> None:
    source = _SelectingSource()
    workflow = _Workflow()
    settings = replace(
        _valid_settings("main"),
        stage_refs=(StageRef("event_20221124_cn", "th"),),
    )
    resumed_ref = StageRef("event_20221124_cn", "th2")
    payload = _progress_payload()
    payload["stage_ref"] = {"pack_id": resumed_ref.pack_id, "stage_id": resumed_ref.stage_id}

    task = build_campaign_factories(_dependencies(workflow=workflow, sessions=source))["main"].build(
        _context("main", settings, task_state=_task_state("main", payload))
    )
    task.run(_task_context("main"))

    requested = StageRef("event_20221124_cn", "th")
    assert source.selection_calls == [(requested, 0, resumed_ref)]
    assert cast("CampaignJobSpec", workflow.last_job).stage_refs == (resumed_ref,)


def test_factory_does_not_resolve_a_stale_stage_from_an_old_content_revision() -> None:
    source = _SelectingSource()
    workflow = _Workflow()
    settings = replace(
        _valid_settings("main"),
        stage_refs=(StageRef("event_20221124_cn", "th"),),
    )
    payload = _progress_payload()
    payload["content_revision"] = "content-old"
    payload["stage_ref"] = {"pack_id": "event_20221124_cn", "stage_id": "removed"}

    task = build_campaign_factories(_dependencies(workflow=workflow, sessions=source))["main"].build(
        _context("main", settings, task_state=_task_state("main", payload))
    )
    result = task.run(_task_context("main"))

    assert source.selection_calls == [(StageRef("event_20221124_cn", "th"), 0, None)]
    assert workflow.calls == 0
    assert result == TaskResult(
        outcome=Deferred("stale campaign progress was discarded"),
        effects=(RescheduleSelf(_OBSERVED_AT),),
        state_effects=(DeleteTaskState("main", "progress"),),
    )


class _WrongSessionSource:
    @staticmethod
    def select(
        ref: StageRef,
        *,
        remaining_runs: int,
        preferred_ref: StageRef | None = None,
    ) -> CampaignStageSelection:
        del remaining_runs, preferred_ref
        return CampaignStageSelection(ref, ref)

    @staticmethod
    def resolve(ref: StageRef, variant: CampaignRunVariant) -> CampaignSession:
        _ = (ref, variant)
        return _session(StageRef("campaign_main", "wrong"), CampaignRunVariant.NORMAL)


class _InvalidSessionSource:
    @staticmethod
    def select(
        ref: StageRef,
        *,
        remaining_runs: int,
        preferred_ref: StageRef | None = None,
    ) -> CampaignStageSelection:
        del remaining_runs, preferred_ref
        return CampaignStageSelection(ref, ref)

    @staticmethod
    def resolve(ref: StageRef, variant: CampaignRunVariant) -> object:
        _ = (ref, variant)
        return object()


def test_session_source_must_return_the_exact_requested_content() -> None:
    wrong_dependencies = CampaignFactoryDependencies(_Workflow(), _WrongSessionSource())
    with pytest.raises(ValueError, match="different StageRef"):
        build_campaign_factories(wrong_dependencies)["main"].build(_context("main", _valid_settings("main")))

    invalid_dependencies = CampaignFactoryDependencies(
        _Workflow(),
        cast("CampaignSessionSource", _InvalidSessionSource()),
    )
    with pytest.raises(TypeError, match="must return a CampaignSession"):
        build_campaign_factories(invalid_dependencies)["main"].build(_context("main", _valid_settings("main")))


def test_factory_dependencies_fail_fast_for_missing_ports() -> None:
    with pytest.raises(TypeError, match=r"workflow must implement execute\(\)"):
        CampaignFactoryDependencies(
            cast("CampaignWorkflow", object()),
            _SessionSource(),
        )

    class _ExecuteOnlyWorkflow:
        @staticmethod
        def execute(*args: object) -> object:
            del args
            return object()

    with pytest.raises(TypeError, match=r"workflow must implement discard_checkpoint\(\)"):
        CampaignFactoryDependencies(
            cast("CampaignWorkflow", _ExecuteOnlyWorkflow()),
            _SessionSource(),
        )
    with pytest.raises(TypeError, match=r"sessions must implement resolve\(\)"):
        CampaignFactoryDependencies(
            _Workflow(),
            cast("CampaignSessionSource", object()),
        )
    with pytest.raises(TypeError, match="dependencies must be CampaignFactoryDependencies"):
        build_campaign_factories(cast("CampaignFactoryDependencies", object()))
