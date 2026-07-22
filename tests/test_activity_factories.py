from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortToken,
    Cancelled,
    DailySchedule,
    Deferred,
    DelayRange,
    DeleteTaskState,
    RescheduleSelf,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
    WakePolicy,
    WakeTask,
)
from module.content.activity_catalog import ActivityCatalog
from module.content.activity_profile import CoalitionStageId
from module.content.manifest import load_event_manifests
from module.content.models import ContentId
from module.gameplay.activity import (
    ActivityDisposition,
    ActivityReport,
    ActivitySpec,
    ActivityWorkflow,
    AssistSessionCommand,
    AssistSessionReport,
    AssistSessionSpec,
    AssistSessionState,
    AssistSessionWorkflow,
    CoalitionFleetMode,
    CoalitionOptions,
    CoalitionSettings,
    CoalitionSpSettings,
    DaemonOptions,
    EncounterBalancerPolicy,
    EncounterCommand,
    EncounterPolicy,
    EncounterProgress,
    EncounterReport,
    EncounterSpec,
    EncounterStopReason,
    EventStorySettings,
    HospitalSettings,
    MaritimeEscortSettings,
    MinigameKind,
    MinigameProgress,
    MinigameSettings,
    OpsiDaemonOptions,
    RaidDailySettings,
    RaidMode,
    RaidOptions,
    RaidSettings,
)
from module.gameplay.activity_factories import (
    ActivityFactoryDependencies,
    ActivityWorkflows,
    build_activity_factories,
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
    SettingsDocumentError,
    TaskBuildContext,
    TaskFactory,
    TaskStateDocument,
    TaskStateDocumentError,
    TaskStateEntry,
)
from module.task_registry import TASK_SPECS

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_OBSERVED_AT = datetime(2026, 7, 13, 8, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 14, 0, tzinfo=UTC)
_SERVER_UPDATE_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(8),))
_RESUME_AT = _OBSERVED_AT + timedelta(minutes=5)
_ENCOUNTER_POLICY = EncounterPolicy(
    failure_retry_delay=DelayRange(300, 300),
    resource_retry_delay=timedelta(hours=2),
    oil_limit=1_000,
)
_BALANCER_POLICY = EncounterBalancerPolicy(TaskId("main"), 10_000)
_ACTIVITY_CATALOG = ActivityCatalog(load_event_manifests(Path("content/events")))
_VALID_SETTINGS_BY_COMMAND: dict[str, object] = {
    "minigame": MinigameSettings(
        schedule=_SERVER_UPDATE_SCHEDULE,
        operation_limit=10,
        kind=MinigameKind.NEW_YEAR_CHALLENGE,
    ),
    "event_story": EventStorySettings(ContentId("event_20260625_cn"), skip_battle=True),
    "raid_daily": RaidDailySettings(
        content_id=ContentId("raid_20260212"),
        stages=(RaidMode.HARD, RaidMode.NORMAL, RaidMode.EASY, RaidMode.EX),
        use_ticket=False,
        collect_daily_mission=True,
        policy=_ENCOUNTER_POLICY,
        schedule=_SERVER_UPDATE_SCHEDULE,
    ),
    "maritime_escort": MaritimeEscortSettings(
        policy=_ENCOUNTER_POLICY,
        schedule=_SERVER_UPDATE_SCHEDULE,
    ),
    "raid": RaidSettings(
        content_id=ContentId("raid_20260212"),
        mode=RaidMode.HARD,
        use_ticket=False,
        policy=_ENCOUNTER_POLICY,
        run_limit=None,
        balancer=_BALANCER_POLICY,
    ),
    "hospital": HospitalSettings(
        use_recommended_fleet=True,
        policy=_ENCOUNTER_POLICY,
        schedule=_SERVER_UPDATE_SCHEDULE,
    ),
    "coalition": CoalitionSettings(
        content_id=ContentId("coalition_20260122"),
        stage=CoalitionStageId("hard"),
        fleet=CoalitionFleetMode.SINGLE,
        policy=_ENCOUNTER_POLICY,
        run_limit=None,
        balancer=_BALANCER_POLICY,
    ),
    "coalition_sp": CoalitionSpSettings(
        content_id=ContentId("coalition_20260122"),
        stage=CoalitionStageId("sp"),
        fleet=CoalitionFleetMode.MULTI,
        policy=_ENCOUNTER_POLICY,
        schedule=_SERVER_UPDATE_SCHEDULE,
    ),
    "daemon": AssistSessionSpec(AssistSessionCommand.DAEMON, DaemonOptions(enter_map=True)),
    "opsi_daemon": AssistSessionSpec(
        AssistSessionCommand.OPSI_DAEMON,
        OpsiDaemonOptions(repair_ship=True, select_enemy=False),
    ),
}


def _minigame_state(payload: object, *, schema_version: int = 1) -> TaskStateDocument:
    return TaskStateDocument(
        namespace="minigame",
        entries={
            "progress": TaskStateEntry(
                schema_version=schema_version,
                payload=cast("FrozenJsonValue", payload),
                updated_at=_OBSERVED_AT,
            )
        },
    )


def _encounter_state(command: str, payload: object, *, schema_version: int = 1) -> TaskStateDocument:
    return TaskStateDocument(
        namespace=command,
        entries={
            "progress": TaskStateEntry(
                schema_version=schema_version,
                payload=cast("FrozenJsonValue", payload),
                updated_at=_OBSERVED_AT,
            )
        },
    )


class _ActivityWorkflow:
    def __init__(self) -> None:
        self.specs: list[ActivitySpec] = []

    def execute(
        self,
        spec: ActivitySpec,
        cancellation: CancellationSource,
    ) -> ActivityReport:
        cancellation.raise_if_requested()
        self.specs.append(spec)
        return ActivityReport(
            spec.command,
            ActivityDisposition.COMPLETED,
            observed_at=_OBSERVED_AT,
            operations_completed=0,
        )


class _EncounterWorkflow:
    def __init__(self) -> None:
        self.specs: list[EncounterSpec] = []

    def execute(self, spec: EncounterSpec, cancellation: CancellationSource) -> EncounterReport:
        cancellation.raise_if_requested()
        self.specs.append(spec)
        if spec.command in {EncounterCommand.RAID, EncounterCommand.COALITION}:
            return EncounterReport(
                command=spec.command,
                stop_reason=EncounterStopReason.BALANCER_SWITCH,
                observed_at=_OBSERVED_AT,
                runs_completed=0,
                resume_at=_RESUME_AT,
            )
        return EncounterReport(
            command=spec.command,
            stop_reason=EncounterStopReason.COMPLETED,
            observed_at=_OBSERVED_AT,
            runs_completed=1 if spec.command is EncounterCommand.COALITION_SP else 0,
        )


class _AssistWorkflow:
    def __init__(
        self,
        state: AssistSessionState,
        *,
        on_advance: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self._on_advance = on_advance
        self.specs: list[AssistSessionSpec] = []

    def advance_to_safe_point(
        self,
        spec: AssistSessionSpec,
        cancellation: CancellationSource,
    ) -> AssistSessionReport:
        cancellation.raise_if_requested()
        self.specs.append(spec)
        if self._on_advance is not None:
            self._on_advance()
        return AssistSessionReport(spec.command, self._state)


def _workflows() -> ActivityWorkflows:
    return ActivityWorkflows(
        minigame=_ActivityWorkflow(),
        event_story=_ActivityWorkflow(),
        raid_daily=_EncounterWorkflow(),
        maritime_escort=_EncounterWorkflow(),
        raid=_EncounterWorkflow(),
        hospital=_EncounterWorkflow(),
        coalition=_EncounterWorkflow(),
        coalition_sp=_EncounterWorkflow(),
        daemon=_AssistWorkflow(AssistSessionState.COMPLETED),
        opsi_daemon=_AssistWorkflow(AssistSessionState.CONTINUE),
    )


def _factories(workflows: ActivityWorkflows | None = None) -> dict[str, TaskFactory]:
    selected = _workflows() if workflows is None else workflows
    return dict(build_activity_factories(ActivityFactoryDependencies(selected, _ACTIVITY_CATALOG)))


def _build_context(
    command: str,
    settings: object,
    *,
    task_state: TaskStateDocument | None = None,
) -> TaskBuildContext:
    return TaskBuildContext(
        spec=TASK_SPECS[command],
        settings_revision=3,
        content_revision="content-1",
        settings=settings,
        task_state=TaskStateDocument.empty(command) if task_state is None else task_state,
    )


def _task_context(
    command: str,
    *,
    abort: AbortToken | None = None,
) -> TaskContext:
    return TaskContext(
        task_id=TaskId(command),
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        mode=TASK_SPECS[command].execution_mode,
        metadata=RunMetadata(settings_revision=3, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def _valid_settings(command: str) -> object:
    return _VALID_SETTINGS_BY_COMMAND[command]


def test_minigame_factory_preserves_the_source_run_cap_and_typed_schedule() -> None:
    workflow = _ActivityWorkflow()
    factory = _factories(replace(_workflows(), minigame=workflow))["minigame"]
    task = factory.build(_build_context("minigame", _valid_settings("minigame")))

    result = task.run(_task_context("minigame"))

    assert workflow.specs == [ActivitySpec.minigame(schedule=_SERVER_UPDATE_SCHEDULE, operation_limit=10)]
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(DeleteTaskState("minigame", "progress"),),
    )


def test_minigame_factory_restores_a_strongly_typed_progress_checkpoint() -> None:
    workflow = _ActivityWorkflow()
    factory = _factories(replace(_workflows(), minigame=workflow))["minigame"]
    task_state = _minigame_state(
        {
            "operations_completed": 4,
            "cycle_ends_at": _SERVER_UPDATE_AT.isoformat(),
            "settings_revision": 3,
            "content_revision": "content-1",
        }
    )
    task = factory.build(
        _build_context(
            "minigame",
            _valid_settings("minigame"),
            task_state=task_state,
        )
    )

    result = task.run(_task_context("minigame"))

    assert workflow.specs == [
        ActivitySpec.minigame(
            schedule=_SERVER_UPDATE_SCHEDULE,
            operation_limit=10,
            progress=MinigameProgress(4, _SERVER_UPDATE_AT, 3, "content-1"),
        )
    ]
    assert workflow.specs[0].remaining_operations == 6
    assert result == TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_SERVER_UPDATE_AT),),
        state_effects=(DeleteTaskState("minigame", "progress"),),
    )


@pytest.mark.parametrize(
    ("task_state", "message"),
    [
        (_minigame_state({}, schema_version=2), "schema version must be 1"),
        (_minigame_state(None), "must be an object"),
        (
            _minigame_state(
                {
                    "operations_completed": 1,
                    "cycle_ends_at": _SERVER_UPDATE_AT.isoformat(),
                    "settings_revision": 3,
                }
            ),
            "missing required setting",
        ),
        (
            _minigame_state(
                {
                    "operations_completed": 1,
                    "cycle_ends_at": _SERVER_UPDATE_AT.isoformat(),
                    "settings_revision": 3,
                    "content_revision": "content-1",
                    "removed": True,
                }
            ),
            "unknown settings",
        ),
    ],
)
def test_minigame_factory_rejects_incompatible_or_malformed_progress(
    task_state: TaskStateDocument,
    message: str,
) -> None:
    factory = _factories()["minigame"]

    with pytest.raises(TaskStateDocumentError, match=message):
        factory.build(
            _build_context(
                "minigame",
                _valid_settings("minigame"),
                task_state=task_state,
            )
        )


def test_continuous_encounter_factory_uses_typed_limit_and_balancer_target() -> None:
    workflow = _EncounterWorkflow()
    factory = _factories(replace(_workflows(), raid=workflow))["raid"]
    settings = replace(cast("RaidSettings", _valid_settings("raid")), run_limit=3)
    task = factory.build(
        _build_context(
            "raid",
            settings,
        )
    )

    result = task.run(_task_context("raid"))

    assert workflow.specs == [
        EncounterSpec(
            command=EncounterCommand.RAID,
            options=RaidOptions(
                activity=_ACTIVITY_CATALOG.resolve_raid("raid_20260212"),
                mode=RaidMode.HARD,
                use_ticket=False,
                policy=_ENCOUNTER_POLICY,
            ),
            run_limit=3,
            balancer=EncounterBalancerPolicy(TaskId("main"), 10_000),
        )
    ]
    assert result == TaskResult(
        outcome=Deferred("encounter yielded to the configured balancing task"),
        effects=(
            RescheduleSelf(_RESUME_AT),
            WakeTask(TaskId("main"), _OBSERVED_AT, WakePolicy.FORCE_ENABLE),
        ),
    )


def test_encounter_factory_preserves_typed_emotion_settings() -> None:
    workflow = _EncounterWorkflow()
    factory = _factories(replace(_workflows(), raid=workflow))["raid"]
    source = cast("RaidSettings", _valid_settings("raid"))
    emotion = EmotionSettings(
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
    )
    settings = replace(source, policy=replace(source.policy, emotion=emotion))
    task = factory.build(_build_context("raid", settings))

    task.run(_task_context("raid"))

    options = workflow.specs[0].options
    assert isinstance(options, RaidOptions)
    emotion = options.policy.emotion
    assert type(emotion) is EmotionSettings
    assert type(emotion.fleet1) is FleetEmotionSettings
    assert emotion.mode is EmotionMode.CALCULATE
    assert emotion.fleet2.control is EmotionControl.KEEP_EXP_BONUS
    assert emotion.fleet2.recover is EmotionRecoverLocation.DORMITORY_FLOOR_1
    assert emotion.fleet2.oath is True


def test_continuous_encounter_factory_restores_typed_progress_checkpoint() -> None:
    workflow = _EncounterWorkflow()
    factory = _factories(replace(_workflows(), raid=workflow))["raid"]
    settings = replace(cast("RaidSettings", _valid_settings("raid")), run_limit=3)
    progress = {
        "runs_completed": 2,
        "cycle_ends_at": None,
        "settings_revision": 3,
        "content_revision": "content-1",
    }
    task = factory.build(
        _build_context(
            "raid",
            settings,
            task_state=_encounter_state("raid", progress),
        )
    )

    task.run(_task_context("raid"))

    assert workflow.specs[0].progress == EncounterProgress(
        runs_completed=2,
        cycle_ends_at=None,
        settings_revision=3,
        content_revision="content-1",
    )


def test_coalition_sp_factory_keeps_the_one_run_contract_out_of_settings() -> None:
    workflow = _EncounterWorkflow()
    factory = _factories(replace(_workflows(), coalition_sp=workflow))["coalition_sp"]
    task = factory.build(_build_context("coalition_sp", _valid_settings("coalition_sp")))

    result = task.run(_task_context("coalition_sp"))

    assert workflow.specs == [
        EncounterSpec(
            command=EncounterCommand.COALITION_SP,
            options=CoalitionOptions(
                _ACTIVITY_CATALOG.resolve_coalition("coalition_20260122"),
                CoalitionStageId("sp"),
                CoalitionFleetMode.MULTI,
                _ENCOUNTER_POLICY,
            ),
            schedule=_SERVER_UPDATE_SCHEDULE,
            run_limit=1,
        )
    ]
    assert result == TaskResult(outcome=Succeeded(), effects=(RescheduleSelf(_SERVER_UPDATE_AT),))


def _request_abort(abort: AbortToken) -> None:
    abort.request("operator stop")


def test_assist_factories_use_command_specific_typed_options() -> None:
    daemon_workflow = _AssistWorkflow(AssistSessionState.COMPLETED)
    abort = AbortToken()
    opsi_workflow = _AssistWorkflow(
        AssistSessionState.CONTINUE,
        on_advance=lambda: _request_abort(abort),
    )
    factories = _factories(replace(_workflows(), daemon=daemon_workflow, opsi_daemon=opsi_workflow))

    daemon_spec = AssistSessionSpec(AssistSessionCommand.DAEMON, DaemonOptions(enter_map=False))
    opsi_spec = AssistSessionSpec(
        AssistSessionCommand.OPSI_DAEMON,
        OpsiDaemonOptions(repair_ship=True, select_enemy=False),
    )
    daemon = factories["daemon"].build(_build_context("daemon", daemon_spec))
    opsi_daemon = factories["opsi_daemon"].build(_build_context("opsi_daemon", opsi_spec))

    assert daemon.run(_task_context("daemon")) == TaskResult(outcome=Succeeded())
    assert opsi_daemon.run(_task_context("opsi_daemon", abort=abort)) == TaskResult(outcome=Cancelled("operator stop"))
    assert daemon_workflow.specs == [daemon_spec]
    assert opsi_workflow.specs == [opsi_spec]


@pytest.mark.parametrize(
    ("command", "expected_type"),
    [
        ("minigame", "MinigameSettings"),
        ("event_story", "EventStorySettings"),
        ("raid_daily", "RaidDailySettings"),
        ("maritime_escort", "MaritimeEscortSettings"),
        ("raid", "RaidSettings"),
        ("hospital", "HospitalSettings"),
        ("coalition", "CoalitionSettings"),
        ("coalition_sp", "CoalitionSpSettings"),
        ("daemon", "AssistSessionSpec"),
        ("opsi_daemon", "AssistSessionSpec"),
    ],
)
def test_activity_factories_reject_wrong_settings_type(
    command: str,
    expected_type: str,
) -> None:
    factory = _factories()[command]

    with pytest.raises(TypeError, match=rf"{command} settings must be {expected_type}"):
        factory.build(_build_context(command, object()))


def test_assist_factory_rejects_mismatched_typed_command() -> None:
    wrong_spec = AssistSessionSpec(
        AssistSessionCommand.OPSI_DAEMON,
        OpsiDaemonOptions(repair_ship=True, select_enemy=False),
    )

    with pytest.raises(ValueError, match="daemon settings command must be daemon"):
        _factories()["daemon"].build(_build_context("daemon", wrong_spec))


@pytest.mark.parametrize(
    ("command", "settings", "message"),
    [
        (
            "event_story",
            EventStorySettings(ContentId("campaign_main"), skip_battle=True),
            "expected event_story",
        ),
        (
            "raid",
            replace(
                _VALID_SETTINGS_BY_COMMAND["raid"],
                content_id=ContentId("event_20260625_cn"),
            ),
            "expected raid",
        ),
        (
            "coalition",
            replace(
                _VALID_SETTINGS_BY_COMMAND["coalition"],
                content_id=ContentId("raid_20260212"),
            ),
            "expected coalition",
        ),
    ],
)
def test_activity_factories_reject_wrong_content_kind_before_workflow_entry(
    command: str,
    settings: object,
    message: str,
) -> None:
    with pytest.raises(SettingsDocumentError, match=message):
        _factories()[command].build(_build_context(command, settings))


def test_activity_workflow_bundle_rejects_missing_ports() -> None:
    with pytest.raises(TypeError, match=r"minigame must implement execute\(\)"):
        replace(_workflows(), minigame=cast("ActivityWorkflow", object()))
    with pytest.raises(TypeError, match=r"opsi_daemon must implement advance_to_safe_point\(\)"):
        replace(_workflows(), opsi_daemon=cast("AssistSessionWorkflow", object()))
    with pytest.raises(TypeError, match="dependencies must be ActivityFactoryDependencies"):
        build_activity_factories(cast("ActivityFactoryDependencies", object()))
