from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from module.application import TaskId
from module.content.battle_program import ProgramFlag, ProgramMarker
from module.content.campaign_session import (
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
    CampaignSessionStatus,
    RemainingSpawns,
)
from module.content.campaign_session_source import CampaignStageSelection
from module.content.models import StageRef
from module.gameplay.campaign import (
    CAMPAIGN_JOB_KINDS,
    CAMPAIGN_PROGRESS_KEY,
    CAMPAIGN_PROGRESS_SCHEMA_VERSION,
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
    SubmarineAutoSearchMode,
    SubmarineDistanceToBoss,
    SubmarineMode,
    TaskBalancerPolicy,
)
from module.runtime import (
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocumentError,
)

if TYPE_CHECKING:
    from module.runtime import FrozenTaskSettings, TaskFactory


@runtime_checkable
class CampaignSessionSource(Protocol):
    def resolve(self, ref: StageRef, variant: CampaignRunVariant) -> CampaignSession: ...

    def select(
        self,
        ref: StageRef,
        *,
        remaining_runs: int,
        preferred_ref: StageRef | None = None,
    ) -> CampaignStageSelection: ...


@runtime_checkable
class HardCampaignSessionSource(CampaignSessionSource, Protocol):
    def resolve_hard_stage_ref(self, stage_id: str) -> StageRef: ...


def _require_method(value: object, method_name: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method_name, None)):
        message = f"{field_name} must implement {method_name}()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CampaignFactoryDependencies:
    workflow: CampaignWorkflow
    sessions: CampaignSessionSource

    def __post_init__(self) -> None:
        _require_method(self.workflow, "execute", field_name="workflow")
        _require_method(self.workflow, "discard_checkpoint", field_name="workflow")
        _require_method(self.sessions, "resolve", field_name="sessions")
        _require_method(self.sessions, "select", field_name="sessions")


class _BalancerTarget(StrEnum):
    MAIN = "main"
    MAIN2 = "main2"
    MAIN3 = "main3"


def _session_state(decoder: SettingsDecoder) -> CampaignSessionState:
    remaining_decoder = decoder.object("remaining")
    remaining = RemainingSpawns(
        enemy=remaining_decoder.integer("enemy", minimum=0),
        siren=remaining_decoder.integer("siren", minimum=0),
        mystery=remaining_decoder.integer("mystery", minimum=0),
        boss=remaining_decoder.integer("boss", minimum=0),
    )
    remaining_decoder.finish()
    pending_decoder = decoder.nullable_object("pending")
    if pending_decoder is not None:
        message = "campaign progress must not contain a pending battle attempt"
        raise ValueError(message)
    raw_program_flags = decoder.string_tuple("program_flags")
    program_flags = frozenset(ProgramFlag(value) for value in raw_program_flags)
    if len(program_flags) != len(raw_program_flags):
        message = "campaign progress program_flags must not contain duplicates"
        raise ValueError(message)
    raw_program_markers = decoder.string_tuple("program_markers")
    program_markers = frozenset(ProgramMarker.parse(value) for value in raw_program_markers)
    if len(program_markers) != len(raw_program_markers):
        message = "campaign progress program_markers must not contain duplicates"
        raise ValueError(message)
    state = CampaignSessionState(
        variant=decoder.enum("variant", CampaignRunVariant),
        status=decoder.enum("status", CampaignSessionStatus),
        battle_index=decoder.integer("battle_index", minimum=0),
        remaining=remaining,
        next_attempt_id=decoder.integer("next_attempt_id", minimum=0),
        next_intent_index=decoder.integer("next_intent_index", minimum=0),
        pending=None,
        reason=decoder.nullable_string("reason"),
        program_state_initialized=decoder.boolean("program_state_initialized"),
        program_flags=program_flags,
        program_markers=program_markers,
    )
    decoder.finish()
    return state


def _campaign_progress(context: TaskBuildContext) -> CampaignProgress | None:
    unknown = sorted(set(context.task_state.entries) - {CAMPAIGN_PROGRESS_KEY})
    if unknown:
        message = f"unknown campaign task state keys: {unknown}"
        raise TaskStateDocumentError(message)
    entry = context.task_state.get(CAMPAIGN_PROGRESS_KEY)
    if entry is None:
        return None
    if entry.schema_version != CAMPAIGN_PROGRESS_SCHEMA_VERSION:
        message = f"$.task_state.{CAMPAIGN_PROGRESS_KEY} schema version must be {CAMPAIGN_PROGRESS_SCHEMA_VERSION}"
        raise TaskStateDocumentError(message)
    if not isinstance(entry.payload, Mapping):
        message = f"$.task_state.{CAMPAIGN_PROGRESS_KEY} must be an object"
        raise TaskStateDocumentError(message)

    try:
        decoder = SettingsDecoder(
            cast("FrozenTaskSettings", entry.payload),
            path=f"$.task_state.{CAMPAIGN_PROGRESS_KEY}",
        )
        stage_decoder = decoder.object("stage_ref")
        stage_ref = StageRef(
            stage_decoder.string("pack_id"),
            stage_decoder.string("stage_id"),
        )
        stage_decoder.finish()
        replacement_decoder = decoder.nullable_object("pending_gems_replacement")
        pending_replacement = None
        if replacement_decoder is not None:
            pending_replacement = GemsFleetReplacementRequest(
                replacement_decoder.enum("trigger", GemsFleetReplacementTrigger),
                replacement_decoder.enum("boundary", GemsFleetReplacementBoundary),
            )
            replacement_decoder.finish()
        progress = CampaignProgress(
            stage_ref=stage_ref,
            variant=decoder.enum("variant", CampaignRunVariant),
            session_state=_session_state(decoder.object("session_state")),
            runs_completed=decoder.integer("runs_completed", minimum=0),
            settings_revision=decoder.integer("settings_revision", minimum=1),
            content_revision=decoder.string("content_revision"),
            pending_gems_replacement=pending_replacement,
        )
        decoder.finish()
    except (SettingsDocumentError, TypeError, ValueError) as error:
        message = f"invalid campaign progress checkpoint: {error}"
        raise TaskStateDocumentError(message) from error
    return progress


def _duration(
    decoder: SettingsDecoder,
    name: str,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> timedelta:
    return timedelta(seconds=decoder.integer(name, minimum=minimum, maximum=maximum))


def _limits(decoder: SettingsDecoder) -> CampaignLimits:
    deadline_decoder = decoder.nullable_object("event_deadline")
    deadline_at = None
    if deadline_decoder is not None:
        deadline_at = deadline_decoder.datetime("at")
        deadline_decoder.finish()
    limits = CampaignLimits(
        run_count=decoder.integer("run_count", minimum=0),
        reach_level=decoder.integer("reach_level", minimum=0),
        oil=decoder.integer("oil", minimum=0),
        stop_on_new_ship=decoder.boolean("stop_on_new_ship"),
        event_points=decoder.integer("event_points", minimum=0),
        event_deadline_at=deadline_at,
        map_achievement=decoder.enum("map_achievement", CampaignMapAchievement),
        stage_increase=decoder.boolean("stage_increase"),
    )
    decoder.finish()
    return limits


def _automation(decoder: SettingsDecoder) -> CampaignAutomationSettings:
    settings = CampaignAutomationSettings(
        ambush_evade=decoder.boolean("ambush_evade"),
        use_2x_book=decoder.boolean("use_2x_book"),
        use_auto_search=decoder.boolean("use_auto_search"),
        use_clear_mode=decoder.boolean("use_clear_mode"),
        use_fleet_lock=decoder.boolean("use_fleet_lock"),
    )
    decoder.finish()
    return settings


def _fleets(decoder: SettingsDecoder) -> CampaignFleetSettings:
    settings = CampaignFleetSettings(
        fleet1=decoder.integer("fleet1", minimum=1, maximum=6),
        fleet1_mode=decoder.enum("fleet1_mode", FleetMode),
        fleet1_step=decoder.integer("fleet1_step", minimum=2, maximum=5),
        fleet2=decoder.integer("fleet2", minimum=0, maximum=6),
        fleet2_mode=decoder.enum("fleet2_mode", FleetMode),
        fleet2_step=decoder.integer("fleet2_step", minimum=2, maximum=5),
        order=decoder.enum("order", FleetOrder),
    )
    decoder.finish()
    return settings


def _submarine(decoder: SettingsDecoder) -> CampaignSubmarineSettings:
    settings = CampaignSubmarineSettings(
        fleet=decoder.integer("fleet", minimum=0, maximum=2),
        mode=decoder.enum("mode", SubmarineMode),
        auto_search_mode=decoder.enum("auto_search_mode", SubmarineAutoSearchMode),
        distance_to_boss=decoder.enum("distance_to_boss", SubmarineDistanceToBoss),
    )
    decoder.finish()
    return settings


def _fleet_emotion(decoder: SettingsDecoder) -> CampaignFleetEmotionSettings:
    settings = CampaignFleetEmotionSettings(
        value=decoder.integer("value", minimum=0, maximum=150),
        recorded_at=decoder.datetime("recorded_at"),
        control=decoder.enum("control", EmotionControl),
        recover=decoder.enum("recover", EmotionRecoverLocation),
        oath=decoder.boolean("oath"),
    )
    decoder.finish()
    return settings


def _emotion(decoder: SettingsDecoder) -> CampaignEmotionSettings:
    settings = CampaignEmotionSettings(
        mode=decoder.enum("mode", EmotionMode),
        fleet1=_fleet_emotion(decoder.object("fleet1")),
        fleet2=_fleet_emotion(decoder.object("fleet2")),
    )
    decoder.finish()
    return settings


def _hp_control(decoder: SettingsDecoder) -> CampaignHpControlSettings:
    settings = CampaignHpControlSettings(
        use_hp_balance=decoder.boolean("use_hp_balance"),
        use_emergency_repair=decoder.boolean("use_emergency_repair"),
        use_low_hp_retreat=decoder.boolean("use_low_hp_retreat"),
        hp_balance_threshold=decoder.number("hp_balance_threshold", minimum=0.0, maximum=1.0),
        hp_balance_weight=cast(
            "tuple[int, int, int]",
            decoder.integer_tuple("hp_balance_weight", length=3, minimum=1),
        ),
        repair_use_single_threshold=decoder.number(
            "repair_use_single_threshold",
            minimum=0.0,
            maximum=1.0,
        ),
        repair_use_multi_threshold=decoder.number(
            "repair_use_multi_threshold",
            minimum=0.0,
            maximum=1.0,
        ),
        low_hp_retreat_threshold=decoder.number(
            "low_hp_retreat_threshold",
            minimum=0.0,
            maximum=1.0,
        ),
    )
    decoder.finish()
    return settings


def _enemy_priority(decoder: SettingsDecoder) -> CampaignEnemyPrioritySettings:
    settings = CampaignEnemyPrioritySettings(
        scale_balance_weight=decoder.enum("scale_balance_weight", EnemyPriorityMode),
    )
    decoder.finish()
    return settings


def _execution(decoder: SettingsDecoder) -> CampaignExecutionSettings:
    settings = CampaignExecutionSettings(
        automation=_automation(decoder.object("automation")),
        fleets=_fleets(decoder.object("fleets")),
        submarine=_submarine(decoder.object("submarine")),
        emotion=_emotion(decoder.object("emotion")),
        hp_control=_hp_control(decoder.object("hp_control")),
        enemy_priority=_enemy_priority(decoder.object("enemy_priority")),
    )
    decoder.finish()
    return settings


def _task_balancer(decoder: SettingsDecoder) -> TaskBalancerPolicy | None:
    balancer = decoder.nullable_object("task_balancer")
    if balancer is None:
        return None
    target = balancer.enum("target_task_id", _BalancerTarget)
    policy = TaskBalancerPolicy(
        target_task_id=TaskId(target.value),
        coin_limit=balancer.integer("coin_limit", minimum=0),
    )
    balancer.finish()
    return policy


def _stage_refs(
    *,
    command: str,
    kind: CampaignJobKind,
    pack_id: str,
    stage_ids: tuple[str, ...],
) -> tuple[StageRef, ...]:
    if len(set(stage_ids)) != len(stage_ids):
        message = f"$.tasks.{command}.stage_ids must not contain duplicates"
        raise SettingsDocumentError(message)
    if kind is CampaignJobKind.EVENT_SP:
        if len(stage_ids) > 1:
            message = f"$.tasks.{command}.stage_ids must contain at most one stage"
            raise SettingsDocumentError(message)
    elif kind is not CampaignJobKind.EVENT_DAILY and len(stage_ids) != 1:
        message = f"$.tasks.{command}.stage_ids must contain exactly one stage"
        raise SettingsDocumentError(message)
    return tuple(StageRef(pack_id, stage_id) for stage_id in stage_ids)


def _resolve_session(
    source: CampaignSessionSource,
    ref: StageRef,
    variant: CampaignRunVariant,
    *,
    field_name: str,
) -> CampaignSession:
    session = source.resolve(ref, variant)
    if not isinstance(session, CampaignSession):
        message = f"{field_name} source must return a CampaignSession"
        raise TypeError(message)
    if session.definition.ref != ref:
        message = f"{field_name} source returned a different StageRef"
        raise ValueError(message)
    if session.variant is not variant:
        message = f"{field_name} source returned a different run variant"
        raise ValueError(message)
    return session


def _select_stage(
    source: CampaignSessionSource,
    ref: StageRef,
    *,
    remaining_runs: int,
    preferred_ref: StageRef | None,
    field_name: str,
) -> CampaignStageSelection:
    selection = source.select(
        ref,
        remaining_runs=remaining_runs,
        preferred_ref=preferred_ref,
    )
    if not isinstance(selection, CampaignStageSelection):
        message = f"{field_name} source must return a CampaignStageSelection"
        raise TypeError(message)
    if selection.requested_ref != ref:
        message = f"{field_name} source returned a selection for a different requested StageRef"
        raise ValueError(message)
    return selection


def _gems_policy(
    decoder: SettingsDecoder,
    source: CampaignSessionSource,
) -> GemsFarmingPolicy:
    settings = decoder.object("gems_farming")
    fallback = settings.object("fallback")
    fallback_ref = StageRef(
        fallback.string("pack_id"),
        fallback.string("stage_id"),
    )
    fallback.finish()
    policy = GemsFarmingPolicy(
        fallback_session=_resolve_session(
            source,
            fallback_ref,
            CampaignRunVariant.NORMAL,
            field_name="gems_farming.fallback",
        ),
        flagship_change=settings.enum("flagship_change", GemsFlagshipChange),
        common_carrier=settings.enum("common_carrier", GemsCommonCarrier),
        vanguard_change=settings.enum("vanguard_change", GemsVanguardChange),
        common_destroyer=settings.enum("common_destroyer", GemsCommonDestroyer),
        equipment_code_config=settings.string("equipment_code_config"),
        replacement_retry_delay=_duration(settings, "replacement_retry_seconds"),
    )
    settings.finish()
    return policy


def _validate_limit_scope(command: str, kind: CampaignJobKind, limits: CampaignLimits) -> None:
    event_kinds = {
        CampaignJobKind.EVENT,
        CampaignJobKind.EVENT_SP,
        CampaignJobKind.EVENT_DAILY,
        CampaignJobKind.GEMS_FARMING,
    }
    if kind not in event_kinds and (limits.event_points or limits.event_deadline_at is not None):
        message = f"$.tasks.{command}.limits event limits are only valid for event or gems-farming jobs"
        raise SettingsDocumentError(message)


def _decode_job(
    decoder: SettingsDecoder,
    *,
    command: str,
    sessions: CampaignSessionSource,
    settings_revision: int,
    progress: CampaignProgress | None = None,
) -> CampaignJobSpec:
    task_id = TaskId(command)
    kind = CAMPAIGN_JOB_KINDS[task_id]
    pack_id = decoder.string("pack_id")
    stage_ids = decoder.string_tuple("stage_ids")
    difficulty = decoder.enum("difficulty", CampaignDifficulty)
    refs = _stage_refs(command=command, kind=kind, pack_id=pack_id, stage_ids=stage_ids)
    limits = _limits(decoder.object("limits"))
    preferred_ref = (
        progress.stage_ref
        if progress is not None and progress.settings_revision == settings_revision and len(refs) == 1
        else None
    )
    selections = tuple(
        _select_stage(
            sessions,
            ref,
            remaining_runs=limits.run_count,
            preferred_ref=preferred_ref,
            field_name=f"{command}.stage_ids",
        )
        for ref in refs
    )
    selected_refs = tuple(selection.selected_ref for selection in selections)
    if len(set(selected_refs)) != len(selected_refs):
        message = f"$.tasks.{command}.stage_ids must not resolve to duplicate canonical stages"
        raise SettingsDocumentError(message)
    primary_sessions = tuple(
        _resolve_session(sessions, ref, variant, field_name=f"{command}.stage_ids")
        for ref in selected_refs
        for variant in CampaignRunVariant
    )
    transition_refs = tuple(
        dict.fromkeys(
            selection.next_ref
            for selection in selections
            if selection.next_ref is not None and selection.next_ref not in selected_refs
        )
    )
    transition_sessions = tuple(
        _resolve_session(sessions, ref, variant, field_name=f"{command}.stage_ids progression")
        for ref in transition_refs
        for variant in CampaignRunVariant
    )
    _validate_limit_scope(command, kind, limits)
    gems_policy = _gems_policy(decoder, sessions) if kind is CampaignJobKind.GEMS_FARMING else None
    return CampaignJobSpec(
        task_id=task_id,
        sessions=primary_sessions,
        difficulty=difficulty,
        execution=_execution(decoder.object("execution")),
        schedule=decoder.daily_schedule("schedule"),
        failure_retry_delay=decoder.delay_range("failure_retry_seconds"),
        resource_retry_delay=_duration(
            decoder,
            "resource_retry_seconds",
            minimum=7_200,
            maximum=14_400,
        ),
        limits=limits,
        task_balancer=_task_balancer(decoder),
        gems_farming=gems_policy,
        progress=progress,
        stage_selections=selections,
        transition_sessions=transition_sessions,
    )


class _CampaignTaskFactory:
    __slots__ = ("_command", "_dependencies")

    def __init__(self, command: str, dependencies: CampaignFactoryDependencies) -> None:
        self._command = command
        self._dependencies = dependencies

    def build(self, context: TaskBuildContext) -> CampaignTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.definition.command != self._command:
            message = f"campaign factory requires the {self._command!r} task definition"
            raise ValueError(message)
        decoder = SettingsDecoder(context.settings, path=f"$.tasks.{self._command}")
        job = _decode_job(
            decoder,
            command=self._command,
            sessions=self._dependencies.sessions,
            settings_revision=context.settings_revision,
            progress=_campaign_progress(context),
        )
        decoder.finish()
        return CampaignTask(self._dependencies.workflow, job)


def build_campaign_factories(
    dependencies: CampaignFactoryDependencies,
) -> Mapping[str, TaskFactory]:
    if not isinstance(dependencies, CampaignFactoryDependencies):
        message = "dependencies must be CampaignFactoryDependencies"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {}
    for task_id in CAMPAIGN_JOB_KINDS:
        command = task_id.value
        factories[command] = _CampaignTaskFactory(command, dependencies)
    return MappingProxyType(factories)
