from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.application import TaskId
from module.content.activity_catalog import ActivityCatalog
from module.content.activity_profile import CoalitionStageId
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
    CoalitionFleetMode,
    CoalitionOptions,
    DaemonOptions,
    EncounterBalancerPolicy,
    EncounterCommand,
    EncounterPolicy,
    EncounterProgress,
    EncounterSpec,
    EncounterTask,
    HospitalOptions,
    MaritimeEscortOptions,
    MinigameKind,
    MinigameProgress,
    OpsiDaemonOptions,
    RaidDailyOptions,
    RaidMode,
    RaidOptions,
)
from module.gameplay.emotion import (
    EmotionControl,
    EmotionMode,
    EmotionRecoverLocation,
    EmotionSettings,
    FleetEmotionSettings,
)
from module.runtime import (
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocumentError,
    TypedTaskFactory,
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


def _minigame_spec(decoder: SettingsDecoder, progress: MinigameProgress | None = None) -> ActivitySpec:
    return ActivitySpec.minigame(
        schedule=decoder.daily_schedule("schedule"),
        operation_limit=decoder.integer("operation_limit", minimum=1),
        kind=decoder.enum("game", MinigameKind),
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
        decoder = SettingsDecoder(context.settings, path="$.tasks.minigame")
        spec = _minigame_spec(decoder, _minigame_progress(context))
        decoder.finish()
        return ActivityTask(self._workflow, spec)


def _resolve_activity[T](resolver: Callable[[str], T], event: str, *, path: str) -> T:
    try:
        return resolver(event)
    except (LookupError, ContentValidationError) as error:
        message = f"{path}.event: {error}"
        raise SettingsDocumentError(message) from error


def _event_story_spec(decoder: SettingsDecoder, catalog: ActivityCatalog) -> ActivitySpec:
    event = decoder.string("event")
    return ActivitySpec.event_story(
        activity=_resolve_activity(catalog.resolve_event_story, event, path="$.tasks.event_story"),
        skip_battle=decoder.boolean("skip_battle"),
    )


def _fleet_emotion(decoder: SettingsDecoder) -> FleetEmotionSettings:
    settings = FleetEmotionSettings(
        control=decoder.enum("control", EmotionControl),
        recover=decoder.enum("recover", EmotionRecoverLocation),
        oath=decoder.boolean("oath"),
    )
    decoder.finish()
    return settings


def _emotion_settings(decoder: SettingsDecoder | None) -> EmotionSettings | None:
    if decoder is None:
        return None
    settings = EmotionSettings(
        mode=decoder.enum("mode", EmotionMode),
        fleet1=_fleet_emotion(decoder.object("fleet1")),
        fleet2=_fleet_emotion(decoder.object("fleet2")),
    )
    decoder.finish()
    return settings


def _encounter_policy(decoder: SettingsDecoder) -> EncounterPolicy:
    deadline = decoder.nullable_object("event_deadline")
    deadline_at = None
    if deadline is not None:
        deadline_at = deadline.datetime("at")
        deadline.finish()
    policy = EncounterPolicy(
        failure_retry_delay=decoder.delay_range("failure_retry_seconds"),
        resource_retry_delay=timedelta(seconds=decoder.integer("resource_retry_seconds", minimum=1)),
        oil_limit=decoder.integer("oil_limit", minimum=0),
        event_point_limit=decoder.integer("event_point_limit", minimum=0),
        event_deadline_at=deadline_at,
        use_2x_book=decoder.boolean("use_2x_book"),
        emotion=_emotion_settings(decoder.nullable_object("emotion")),
    )
    decoder.finish()
    return policy


def _balancer_policy(decoder: SettingsDecoder) -> EncounterBalancerPolicy | None:
    value = decoder.nullable_object("balancer")
    if value is None:
        return None
    policy = EncounterBalancerPolicy(
        target_task_id=TaskId(value.string("target_task_id")),
        coin_limit=value.integer("coin_limit", minimum=0),
        retry_delay=timedelta(seconds=value.integer("retry_seconds", minimum=1)),
    )
    value.finish()
    return policy


def _raid_modes(decoder: SettingsDecoder, name: str) -> tuple[RaidMode, ...]:
    raw_modes = decoder.string_tuple(name, allow_empty=False)
    try:
        return tuple(RaidMode(raw) for raw in raw_modes)
    except ValueError as error:
        allowed = sorted(mode.value for mode in RaidMode)
        message = f"$.tasks.raid_daily.{name} must contain only {allowed}"
        raise SettingsDocumentError(message) from error


def _raid_daily_spec(
    decoder: SettingsDecoder,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    event = decoder.string("event")
    options = RaidDailyOptions(
        activity=_resolve_activity(catalog.resolve_raid, event, path="$.tasks.raid_daily"),
        stages=_raid_modes(decoder, "stages"),
        use_ticket=decoder.boolean("use_ticket"),
        collect_daily_mission=decoder.boolean("collect_daily_mission"),
        policy=_encounter_policy(decoder.object("policy")),
    )
    return EncounterSpec(
        command=EncounterCommand.RAID_DAILY,
        options=options,
        schedule=decoder.daily_schedule("schedule"),
        progress=progress,
    )


def _maritime_escort_spec(
    decoder: SettingsDecoder,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    del catalog
    return EncounterSpec(
        command=EncounterCommand.MARITIME_ESCORT,
        options=MaritimeEscortOptions(policy=_encounter_policy(decoder.object("policy"))),
        schedule=decoder.daily_schedule("schedule"),
        progress=progress,
    )


def _raid_spec(
    decoder: SettingsDecoder,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    event = decoder.string("event")
    options = RaidOptions(
        activity=_resolve_activity(catalog.resolve_raid, event, path="$.tasks.raid"),
        mode=decoder.enum("mode", RaidMode),
        use_ticket=decoder.boolean("use_ticket"),
        policy=_encounter_policy(decoder.object("policy")),
    )
    return EncounterSpec(
        command=EncounterCommand.RAID,
        options=options,
        run_limit=decoder.nullable_integer("run_limit", minimum=1),
        balancer=_balancer_policy(decoder),
        progress=progress,
    )


def _hospital_spec(
    decoder: SettingsDecoder,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    del catalog
    options = HospitalOptions(
        use_recommended_fleet=decoder.boolean("use_recommended_fleet"),
        policy=_encounter_policy(decoder.object("policy")),
    )
    return EncounterSpec(
        command=EncounterCommand.HOSPITAL,
        options=options,
        schedule=decoder.daily_schedule("schedule"),
        progress=progress,
    )


def _coalition_options(
    decoder: SettingsDecoder,
    catalog: ActivityCatalog,
    *,
    path: str,
) -> CoalitionOptions:
    event = decoder.string("event")
    return CoalitionOptions(
        activity=_resolve_activity(catalog.resolve_coalition, event, path=path),
        stage=CoalitionStageId(decoder.string("stage")),
        fleet=decoder.enum("fleet", CoalitionFleetMode),
        policy=_encounter_policy(decoder.object("policy")),
    )


def _coalition_spec(
    decoder: SettingsDecoder,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    return EncounterSpec(
        command=EncounterCommand.COALITION,
        options=_coalition_options(decoder, catalog, path="$.tasks.coalition"),
        run_limit=decoder.nullable_integer("run_limit", minimum=1),
        balancer=_balancer_policy(decoder),
        progress=progress,
    )


def _coalition_sp_spec(
    decoder: SettingsDecoder,
    progress: EncounterProgress | None,
    catalog: ActivityCatalog,
) -> EncounterSpec:
    return EncounterSpec(
        command=EncounterCommand.COALITION_SP,
        options=_coalition_options(decoder, catalog, path="$.tasks.coalition_sp"),
        schedule=decoder.daily_schedule("schedule"),
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


type _EncounterSpecBuilder = Callable[[SettingsDecoder, EncounterProgress | None, ActivityCatalog], EncounterSpec]


class _EncounterTaskFactory:
    __slots__ = ("_builder", "_catalog", "_command", "_workflow")

    def __init__(
        self,
        workflow: EncounterWorkflow,
        command: EncounterCommand,
        builder: _EncounterSpecBuilder,
        catalog: ActivityCatalog,
    ) -> None:
        self._workflow = workflow
        self._command = command
        self._builder = builder
        self._catalog = catalog

    def build(self, context: TaskBuildContext) -> EncounterTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.spec.command != self._command.value:
            message = f"encounter factory requires the {self._command.value} task definition"
            raise ValueError(message)
        decoder = SettingsDecoder(context.settings, path=f"$.tasks.{self._command.value}")
        spec = self._builder(decoder, _encounter_progress(context), self._catalog)
        decoder.finish()
        return EncounterTask(self._workflow, spec)


def _daemon_spec(decoder: SettingsDecoder) -> AssistSessionSpec:
    return AssistSessionSpec(
        command=AssistSessionCommand.DAEMON,
        options=DaemonOptions(enter_map=decoder.boolean("enter_map")),
    )


def _opsi_daemon_spec(decoder: SettingsDecoder) -> AssistSessionSpec:
    return AssistSessionSpec(
        command=AssistSessionCommand.OPSI_DAEMON,
        options=OpsiDaemonOptions(
            repair_ship=decoder.boolean("repair_ship"),
            select_enemy=decoder.boolean("select_enemy"),
        ),
    )


def build_activity_factories(dependencies: ActivityFactoryDependencies) -> Mapping[str, TaskFactory]:
    if not isinstance(dependencies, ActivityFactoryDependencies):
        message = "dependencies must be ActivityFactoryDependencies"
        raise TypeError(message)
    workflows = dependencies.workflows
    catalog = dependencies.catalog
    factories: dict[str, TaskFactory] = {
        "minigame": _MinigameTaskFactory(workflows.minigame),
        "event_story": TypedTaskFactory(
            lambda decoder: _event_story_spec(decoder, catalog),
            lambda spec: ActivityTask(workflows.event_story, spec),
        ),
        "raid_daily": _EncounterTaskFactory(
            workflows.raid_daily,
            EncounterCommand.RAID_DAILY,
            _raid_daily_spec,
            catalog,
        ),
        "maritime_escort": _EncounterTaskFactory(
            workflows.maritime_escort,
            EncounterCommand.MARITIME_ESCORT,
            _maritime_escort_spec,
            catalog,
        ),
        "raid": _EncounterTaskFactory(workflows.raid, EncounterCommand.RAID, _raid_spec, catalog),
        "hospital": _EncounterTaskFactory(workflows.hospital, EncounterCommand.HOSPITAL, _hospital_spec, catalog),
        "coalition": _EncounterTaskFactory(
            workflows.coalition,
            EncounterCommand.COALITION,
            _coalition_spec,
            catalog,
        ),
        "coalition_sp": _EncounterTaskFactory(
            workflows.coalition_sp,
            EncounterCommand.COALITION_SP,
            _coalition_sp_spec,
            catalog,
        ),
        "daemon": TypedTaskFactory(
            _daemon_spec,
            lambda spec: AssistSessionTask(workflows.daemon, spec),
        ),
        "opsi_daemon": TypedTaskFactory(
            _opsi_daemon_spec,
            lambda spec: AssistSessionTask(workflows.opsi_daemon, spec),
        ),
    }
    return MappingProxyType(factories)
