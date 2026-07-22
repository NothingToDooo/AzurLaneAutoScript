from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

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
    CampaignJobSettings,
    CampaignJobSpec,
    CampaignProgress,
    CampaignTask,
    CampaignWorkflow,
    GemsFarmingPolicy,
    GemsFarmingSettings,
    GemsFleetReplacementBoundary,
    GemsFleetReplacementRequest,
    GemsFleetReplacementTrigger,
)
from module.runtime import (
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocumentError,
    require_task_settings,
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
    settings: GemsFarmingSettings,
    source: CampaignSessionSource,
) -> GemsFarmingPolicy:
    return GemsFarmingPolicy(
        fallback_session=_resolve_session(
            source,
            settings.fallback_ref,
            CampaignRunVariant.NORMAL,
            field_name="gems_farming.fallback",
        ),
        flagship_change=settings.flagship_change,
        common_carrier=settings.common_carrier,
        vanguard_change=settings.vanguard_change,
        common_destroyer=settings.common_destroyer,
        replacement_retry_delay=settings.replacement_retry_delay,
    )


def _build_job(
    settings: CampaignJobSettings,
    *,
    command: str,
    sessions: CampaignSessionSource,
    context: TaskBuildContext,
    progress: CampaignProgress | None = None,
) -> CampaignJobSpec:
    refs = settings.stage_refs
    preferred_ref = (
        progress.stage_ref
        if progress is not None
        and progress.settings_revision == context.settings_revision
        and progress.content_revision == context.content_revision
        and len(refs) == 1
        else None
    )
    selections = tuple(
        _select_stage(
            sessions,
            ref,
            remaining_runs=settings.limits.run_count,
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
    gems_policy = _gems_policy(settings.gems_farming, sessions) if settings.gems_farming is not None else None
    return CampaignJobSpec(
        task_id=settings.task_id,
        sessions=primary_sessions,
        difficulty=settings.difficulty,
        execution=settings.execution,
        schedule=settings.schedule,
        failure_retry_delay=settings.failure_retry_delay,
        resource_retry_delay=settings.resource_retry_delay,
        limits=settings.limits,
        task_balancer=settings.task_balancer,
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
        if context.spec.command != self._command:
            message = f"campaign factory requires the {self._command!r} task spec"
            raise ValueError(message)
        settings = require_task_settings(context, CampaignJobSettings)
        if settings.task_id.value != self._command:
            message = f"campaign settings task_id must match {self._command!r}"
            raise ValueError(message)
        job = _build_job(
            settings,
            command=self._command,
            sessions=self._dependencies.sessions,
            context=context,
            progress=_campaign_progress(context),
        )
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
