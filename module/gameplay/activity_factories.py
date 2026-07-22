from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.content.activity_catalog import ActivityCatalog
from module.content.errors import ContentValidationError
from module.gameplay.activity import (
    ENCOUNTER_PROGRESS_KEY,
    ENCOUNTER_PROGRESS_SCHEMA_VERSION,
    MINIGAME_PROGRESS_KEY,
    MINIGAME_PROGRESS_SCHEMA_VERSION,
    ActivityCommand,
    ActivitySpec,
    ActivityTask,
    AssistSessionCommand,
    AssistSessionSpec,
    AssistSessionTask,
    CoalitionOptions,
    CoalitionSettings,
    CoalitionSpSettings,
    EncounterCommand,
    EncounterProgress,
    EncounterSpec,
    EncounterTask,
    EventStorySettings,
    HospitalOptions,
    HospitalSettings,
    MaritimeEscortOptions,
    MaritimeEscortSettings,
    MinigameProgress,
    MinigameSettings,
    RaidDailyOptions,
    RaidDailySettings,
    RaidOptions,
    RaidSettings,
)
from module.runtime import (
    ConfiguredTaskFactory,
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocumentError,
    require_task_settings,
)

if TYPE_CHECKING:
    from module.gameplay.activity import ActivityWorkflow, AssistSessionWorkflow, EncounterWorkflow
    from module.runtime import FrozenTaskSettings, TaskFactory


def _require_method(value: object, method_name: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method_name, None)):
        message = f"{field_name} must implement {method_name}()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class ActivityWorkflows:
    minigame: ActivityWorkflow
    event_story: ActivityWorkflow
    raid_daily: EncounterWorkflow
    maritime_escort: EncounterWorkflow
    raid: EncounterWorkflow
    hospital: EncounterWorkflow
    coalition: EncounterWorkflow
    coalition_sp: EncounterWorkflow
    daemon: AssistSessionWorkflow
    opsi_daemon: AssistSessionWorkflow

    def __post_init__(self) -> None:
        for field_name in (
            "minigame",
            "event_story",
            "raid_daily",
            "maritime_escort",
            "raid",
            "hospital",
            "coalition",
            "coalition_sp",
        ):
            _require_method(getattr(self, field_name), "execute", field_name=field_name)
        for field_name in ("daemon", "opsi_daemon"):
            _require_method(
                getattr(self, field_name),
                "advance_to_safe_point",
                field_name=field_name,
            )


@dataclass(frozen=True, slots=True)
class ActivityFactoryDependencies:
    workflows: ActivityWorkflows
    catalog: ActivityCatalog

    def __post_init__(self) -> None:
        if not isinstance(self.workflows, ActivityWorkflows):
            message = "workflows must be an ActivityWorkflows"
            raise TypeError(message)
        if not isinstance(self.catalog, ActivityCatalog):
            message = "catalog must be an ActivityCatalog"
            raise TypeError(message)


def _minigame_spec(settings: MinigameSettings, progress: MinigameProgress | None = None) -> ActivitySpec:
    return ActivitySpec.minigame(
        schedule=settings.schedule,
        operation_limit=settings.operation_limit,
        kind=settings.kind,
        progress=progress,
    )


def _minigame_progress(context: TaskBuildContext) -> MinigameProgress | None:
    entry = context.task_state.get(MINIGAME_PROGRESS_KEY)
    if entry is None:
        return None
    if entry.schema_version != MINIGAME_PROGRESS_SCHEMA_VERSION:
        message = f"$.task_state.{MINIGAME_PROGRESS_KEY} schema version must be {MINIGAME_PROGRESS_SCHEMA_VERSION}"
        raise TaskStateDocumentError(message)
    if not isinstance(entry.payload, Mapping):
        message = f"$.task_state.{MINIGAME_PROGRESS_KEY} must be an object"
        raise TaskStateDocumentError(message)

    try:
        decoder = SettingsDecoder(
            cast("FrozenTaskSettings", entry.payload),
            path=f"$.task_state.{MINIGAME_PROGRESS_KEY}",
        )
        progress = MinigameProgress(
            operations_completed=decoder.integer("operations_completed", minimum=1),
            cycle_ends_at=decoder.datetime("cycle_ends_at"),
            settings_revision=decoder.integer("settings_revision", minimum=1),
            content_revision=decoder.string("content_revision"),
        )
        decoder.finish()
    except (SettingsDocumentError, TypeError, ValueError) as error:
        message = f"invalid minigame progress checkpoint: {error}"
        raise TaskStateDocumentError(message) from error
    return progress


class _MinigameTaskFactory:
    __slots__ = ("_workflow",)

    def __init__(self, workflow: ActivityWorkflow) -> None:
        self._workflow = workflow

    def build(self, context: TaskBuildContext) -> ActivityTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.spec.command != ActivityCommand.MINIGAME.value:
            message = "minigame factory requires the minigame task definition"
            raise ValueError(message)
        settings = require_task_settings(context, MinigameSettings)
        spec = _minigame_spec(settings, _minigame_progress(context))
        return ActivityTask(self._workflow, spec)


def _resolve_activity[T](resolver: Callable[[str], T], content_id: str, *, path: str) -> T:
    try:
        return resolver(content_id)
    except (LookupError, ContentValidationError) as error:
        message = f"{path}.event: {error}"
        raise SettingsDocumentError(message) from error


def _event_story_spec(settings: EventStorySettings, catalog: ActivityCatalog) -> ActivitySpec:
    return ActivitySpec.event_story(
        activity=_resolve_activity(
            catalog.resolve_event_story,
            settings.content_id.value,
            path="$.tasks.event_story",
        ),
        skip_battle=settings.skip_battle,
    )


def _raid_daily_spec(
    settings: RaidDailySettings,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    options = RaidDailyOptions(
        activity=_resolve_activity(
            catalog.resolve_raid,
            settings.content_id.value,
            path="$.tasks.raid_daily",
        ),
        stages=settings.stages,
        use_ticket=settings.use_ticket,
        collect_daily_mission=settings.collect_daily_mission,
        policy=settings.policy,
    )
    return EncounterSpec(
        command=EncounterCommand.RAID_DAILY,
        options=options,
        schedule=settings.schedule,
        progress=progress,
    )


def _maritime_escort_spec(
    settings: MaritimeEscortSettings,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    del catalog
    return EncounterSpec(
        command=EncounterCommand.MARITIME_ESCORT,
        options=MaritimeEscortOptions(policy=settings.policy),
        schedule=settings.schedule,
        progress=progress,
    )


def _raid_spec(
    settings: RaidSettings,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    options = RaidOptions(
        activity=_resolve_activity(
            catalog.resolve_raid,
            settings.content_id.value,
            path="$.tasks.raid",
        ),
        mode=settings.mode,
        use_ticket=settings.use_ticket,
        policy=settings.policy,
    )
    return EncounterSpec(
        command=EncounterCommand.RAID,
        options=options,
        run_limit=settings.run_limit,
        balancer=settings.balancer,
        progress=progress,
    )


def _hospital_spec(
    settings: HospitalSettings,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    del catalog
    options = HospitalOptions(
        use_recommended_fleet=settings.use_recommended_fleet,
        policy=settings.policy,
    )
    return EncounterSpec(
        command=EncounterCommand.HOSPITAL,
        options=options,
        schedule=settings.schedule,
        progress=progress,
    )


def _coalition_options(
    settings: CoalitionSettings | CoalitionSpSettings,
    catalog: ActivityCatalog,
    *,
    path: str,
) -> CoalitionOptions:
    return CoalitionOptions(
        activity=_resolve_activity(
            catalog.resolve_coalition,
            settings.content_id.value,
            path=path,
        ),
        stage=settings.stage,
        fleet=settings.fleet,
        policy=settings.policy,
    )


def _coalition_spec(
    settings: CoalitionSettings,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    return EncounterSpec(
        command=EncounterCommand.COALITION,
        options=_coalition_options(settings, catalog, path="$.tasks.coalition"),
        run_limit=settings.run_limit,
        balancer=settings.balancer,
        progress=progress,
    )


def _coalition_sp_spec(
    settings: CoalitionSpSettings,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    return EncounterSpec(
        command=EncounterCommand.COALITION_SP,
        options=_coalition_options(settings, catalog, path="$.tasks.coalition_sp"),
        schedule=settings.schedule,
        run_limit=1,
        progress=progress,
    )


def _encounter_progress(context: TaskBuildContext) -> EncounterProgress | None:
    entry = context.task_state.get(ENCOUNTER_PROGRESS_KEY)
    if entry is None:
        return None
    if entry.schema_version != ENCOUNTER_PROGRESS_SCHEMA_VERSION:
        message = f"$.task_state.{ENCOUNTER_PROGRESS_KEY} schema version must be {ENCOUNTER_PROGRESS_SCHEMA_VERSION}"
        raise TaskStateDocumentError(message)
    if not isinstance(entry.payload, Mapping):
        message = f"$.task_state.{ENCOUNTER_PROGRESS_KEY} must be an object"
        raise TaskStateDocumentError(message)

    try:
        decoder = SettingsDecoder(
            cast("FrozenTaskSettings", entry.payload),
            path=f"$.task_state.{ENCOUNTER_PROGRESS_KEY}",
        )
        raw_cycle = decoder.nullable_string("cycle_ends_at")
        cycle_ends_at = None if raw_cycle is None else datetime.fromisoformat(raw_cycle)
        progress = EncounterProgress(
            runs_completed=decoder.integer("runs_completed", minimum=1),
            cycle_ends_at=cycle_ends_at,
            settings_revision=decoder.integer("settings_revision", minimum=1),
            content_revision=decoder.string("content_revision"),
        )
        decoder.finish()
    except (SettingsDocumentError, TypeError, ValueError) as error:
        message = f"invalid encounter progress checkpoint: {error}"
        raise TaskStateDocumentError(message) from error
    return progress


type _EncounterSettings = (
    RaidDailySettings
    | MaritimeEscortSettings
    | RaidSettings
    | HospitalSettings
    | CoalitionSettings
    | CoalitionSpSettings
)
type _EncounterSpecBuilder[SettingsT: _EncounterSettings] = Callable[
    [SettingsT, EncounterProgress | None, ActivityCatalog],
    EncounterSpec,
]


class _EncounterTaskFactory[SettingsT: _EncounterSettings]:
    __slots__ = ("_builder", "_catalog", "_command", "_settings_type", "_workflow")

    def __init__(
        self,
        workflow: EncounterWorkflow,
        command: EncounterCommand,
        settings_type: type[SettingsT],
        builder: _EncounterSpecBuilder[SettingsT],
        catalog: ActivityCatalog,
    ) -> None:
        self._workflow = workflow
        self._command = command
        self._settings_type = settings_type
        self._builder = builder
        self._catalog = catalog

    def build(self, context: TaskBuildContext) -> EncounterTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.spec.command != self._command.value:
            message = f"encounter factory requires the {self._command.value} task definition"
            raise ValueError(message)
        settings = require_task_settings(context, self._settings_type)
        spec = self._builder(settings, _encounter_progress(context), self._catalog)
        return EncounterTask(self._workflow, spec)


class _AssistSessionTaskFactory:
    __slots__ = ("_command", "_workflow")

    def __init__(self, workflow: AssistSessionWorkflow, command: AssistSessionCommand) -> None:
        self._workflow = workflow
        self._command = command

    def build(self, context: TaskBuildContext) -> AssistSessionTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.spec.command != self._command.value:
            message = f"assist factory requires the {self._command.value} task definition"
            raise ValueError(message)
        spec = require_task_settings(context, AssistSessionSpec)
        if spec.command is not self._command:
            message = f"{self._command.value} settings command must be {self._command.value}"
            raise ValueError(message)
        return AssistSessionTask(self._workflow, spec)


def build_activity_factories(dependencies: ActivityFactoryDependencies) -> Mapping[str, TaskFactory]:
    if not isinstance(dependencies, ActivityFactoryDependencies):
        message = "dependencies must be ActivityFactoryDependencies"
        raise TypeError(message)
    workflows = dependencies.workflows
    catalog = dependencies.catalog
    factories: dict[str, TaskFactory] = {
        "minigame": _MinigameTaskFactory(workflows.minigame),
        "event_story": ConfiguredTaskFactory(
            EventStorySettings,
            lambda settings: ActivityTask(workflows.event_story, _event_story_spec(settings, catalog)),
        ),
        "raid_daily": _EncounterTaskFactory(
            workflows.raid_daily,
            EncounterCommand.RAID_DAILY,
            RaidDailySettings,
            _raid_daily_spec,
            catalog,
        ),
        "maritime_escort": _EncounterTaskFactory(
            workflows.maritime_escort,
            EncounterCommand.MARITIME_ESCORT,
            MaritimeEscortSettings,
            _maritime_escort_spec,
            catalog,
        ),
        "raid": _EncounterTaskFactory(
            workflows.raid,
            EncounterCommand.RAID,
            RaidSettings,
            _raid_spec,
            catalog,
        ),
        "hospital": _EncounterTaskFactory(
            workflows.hospital,
            EncounterCommand.HOSPITAL,
            HospitalSettings,
            _hospital_spec,
            catalog,
        ),
        "coalition": _EncounterTaskFactory(
            workflows.coalition,
            EncounterCommand.COALITION,
            CoalitionSettings,
            _coalition_spec,
            catalog,
        ),
        "coalition_sp": _EncounterTaskFactory(
            workflows.coalition_sp,
            EncounterCommand.COALITION_SP,
            CoalitionSpSettings,
            _coalition_sp_spec,
            catalog,
        ),
        "daemon": _AssistSessionTaskFactory(
            workflows.daemon,
            AssistSessionCommand.DAEMON,
        ),
        "opsi_daemon": _AssistSessionTaskFactory(
            workflows.opsi_daemon,
            AssistSessionCommand.OPSI_DAEMON,
        ),
    }
    return MappingProxyType(factories)
