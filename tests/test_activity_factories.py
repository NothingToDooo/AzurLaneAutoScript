from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
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
from module.gameplay.activity import (
    GAMEPLAY_COMMAND_PROFILES,
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
    DaemonOptions,
    EncounterBalancerPolicy,
    EncounterCommand,
    EncounterPolicy,
    EncounterProgress,
    EncounterReport,
    EncounterSpec,
    EncounterStopReason,
    MinigameProgress,
    OpsiDaemonOptions,
    RaidMode,
    RaidOptions,
)
from module.gameplay.activity_factories import (
    ActivityFactoryDependencies,
    ActivityWorkflows,
    build_activity_factories,
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
from module.task_registry import TASK_CATALOG

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource


_OBSERVED_AT = datetime(2026, 7, 13, 8, tzinfo=UTC)
_SERVER_UPDATE_AT = datetime(2026, 7, 14, 0, tzinfo=UTC)
_SERVER_UPDATE_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(8),))
_SERVER_UPDATE_SETTINGS: dict[str, FrozenJsonValue] = {
    "timezone": "Asia/Hong_Kong",
    "triggers": ("08:00",),
}
_RESUME_AT = _OBSERVED_AT + timedelta(minutes=5)
_POLICY_SETTINGS: dict[str, FrozenJsonValue] = {
    "failure_retry_seconds": {"lower_seconds": 300, "upper_seconds": 300},
    "resource_retry_seconds": 7_200,
    "oil_limit": 1_000,
    "event_point_limit": 0,
    "event_deadline": None,
    "use_2x_book": False,
    "emotion": None,
}
_ENCOUNTER_POLICY = EncounterPolicy(
    failure_retry_delay=DelayRange(300, 300),
    resource_retry_delay=timedelta(hours=2),
    oil_limit=1_000,
)
_BALANCER_SETTINGS: dict[str, FrozenJsonValue] = {
    "target_task_id": "main",
    "coin_limit": 10_000,
    "retry_seconds": 300,
}
_ACTIVITY_CATALOG = ActivityCatalog(load_event_manifests(Path("content/events")))
_VALID_SETTINGS_BY_COMMAND: dict[str, dict[str, FrozenJsonValue]] = {
    "minigame": {
        "game": "new_year_challenge",
        "operation_limit": 10,
        "schedule": _SERVER_UPDATE_SETTINGS,
    },
    "event_story": {"event": "event_20260625_cn", "skip_battle": True},
    "raid_daily": {
        "event": "raid_20260212",
        "stages": ("hard", "normal", "easy", "ex"),
        "use_ticket": False,
        "collect_daily_mission": True,
        "policy": _POLICY_SETTINGS,
        "schedule": _SERVER_UPDATE_SETTINGS,
    },
    "maritime_escort": {"policy": _POLICY_SETTINGS, "schedule": _SERVER_UPDATE_SETTINGS},
    "raid": {
        "event": "raid_20260212",
        "mode": "hard",
        "use_ticket": False,
        "policy": _POLICY_SETTINGS,
        "run_limit": None,
        "balancer": _BALANCER_SETTINGS,
    },
    "hospital": {
        "use_recommended_fleet": True,
        "policy": _POLICY_SETTINGS,
        "schedule": _SERVER_UPDATE_SETTINGS,
    },
    "coalition": {
        "event": "coalition_20260122",
        "stage": "hard",
        "fleet": "single",
        "policy": _POLICY_SETTINGS,
        "run_limit": None,
        "balancer": _BALANCER_SETTINGS,
    },
    "coalition_sp": {
        "event": "coalition_20260122",
        "stage": "sp",
        "fleet": "multi",
        "policy": _POLICY_SETTINGS,
        "schedule": _SERVER_UPDATE_SETTINGS,
    },
    "daemon": {"enter_map": True},
    "opsi_daemon": {"repair_ship": True, "select_enemy": False},
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
    settings: dict[str, FrozenJsonValue],
    *,
    task_state: TaskStateDocument | None = None,
) -> TaskBuildContext:
    return TaskBuildContext(
        definition=TASK_CATALOG[command],
        settings_revision=3,
        content_revision="content-1",
        settings=MappingProxyType(settings),
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
        mode=GAMEPLAY_COMMAND_PROFILES[command].execution_mode,
        metadata=RunMetadata(settings_revision=3, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def _valid_settings(command: str) -> dict[str, FrozenJsonValue]:
    return dict(_VALID_SETTINGS_BY_COMMAND.get(command, {}))


def test_minigame_factory_preserves_the_source_run_cap_and_decodes_the_schedule() -> None:
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


def test_continuous_encounter_factory_decodes_nullable_limit_and_typed_balancer_target() -> None:
    workflow = _EncounterWorkflow()
    factory = _factories(replace(_workflows(), raid=workflow))["raid"]
    settings = _valid_settings("raid")
    settings["run_limit"] = 3
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


def test_continuous_encounter_factory_restores_typed_progress_checkpoint() -> None:
    workflow = _EncounterWorkflow()
    factory = _factories(replace(_workflows(), raid=workflow))["raid"]
    settings = _valid_settings("raid")
    settings["run_limit"] = 3
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


def test_assist_factories_decode_command_specific_options() -> None:
    daemon_workflow = _AssistWorkflow(AssistSessionState.COMPLETED)
    abort = AbortToken()
    opsi_workflow = _AssistWorkflow(
        AssistSessionState.CONTINUE,
        on_advance=lambda: _request_abort(abort),
    )
    factories = _factories(replace(_workflows(), daemon=daemon_workflow, opsi_daemon=opsi_workflow))

    daemon = factories["daemon"].build(_build_context("daemon", {"enter_map": False}))
    opsi_daemon = factories["opsi_daemon"].build(
        _build_context("opsi_daemon", {"repair_ship": True, "select_enemy": False})
    )

    assert daemon.run(_task_context("daemon")) == TaskResult(outcome=Succeeded())
    assert opsi_daemon.run(_task_context("opsi_daemon", abort=abort)) == TaskResult(outcome=Cancelled("operator stop"))
    assert daemon_workflow.specs == [AssistSessionSpec(AssistSessionCommand.DAEMON, DaemonOptions(enter_map=False))]
    assert opsi_workflow.specs == [
        AssistSessionSpec(
            AssistSessionCommand.OPSI_DAEMON,
            OpsiDaemonOptions(repair_ship=True, select_enemy=False),
        )
    ]


def _settings_with(command: str, name: str, value: FrozenJsonValue) -> dict[str, FrozenJsonValue]:
    settings = _valid_settings(command)
    settings[name] = value
    return settings


@pytest.mark.parametrize(
    ("command", "settings", "message"),
    [
        ("minigame", {}, "missing required setting"),
        (
            "event_story",
            _settings_with("event_story", "removed", value=True),
            "unknown settings",
        ),
        ("minigame", _settings_with("minigame", "removed", value=True), "unknown settings"),
        ("raid", _settings_with("raid", "run_limit", 0), "must be at least 1"),
        (
            "raid",
            _settings_with(
                "raid",
                "balancer",
                {"target_task_id": "", "coin_limit": 10_000, "retry_seconds": 300},
            ),
            "trimmed non-empty string",
        ),
        ("daemon", {"enter_map": 1}, "must be a boolean"),
        (
            "hospital",
            _settings_with(
                "hospital",
                "schedule",
                {"timezone": "UTC", "triggers": ("00:00:00",)},
            ),
            "must be HH:MM",
        ),
    ],
)
def test_activity_factories_reject_missing_unknown_and_invalid_settings(
    command: str,
    settings: dict[str, FrozenJsonValue],
    message: str,
) -> None:
    factory = _factories()[command]

    with pytest.raises(SettingsDocumentError, match=message):
        factory.build(_build_context(command, settings))


@pytest.mark.parametrize(
    ("command", "event", "message"),
    [
        ("event_story", "campaign_main", "expected event_story"),
        ("raid", "event_20260625_cn", "expected raid"),
        ("coalition", "raid_20260212", "expected coalition"),
    ],
)
def test_activity_factories_reject_wrong_content_kind_before_workflow_entry(
    command: str,
    event: str,
    message: str,
) -> None:
    settings = _valid_settings(command)
    settings["event"] = event

    with pytest.raises(SettingsDocumentError, match=message):
        _factories()[command].build(_build_context(command, settings))


def test_activity_workflow_bundle_rejects_missing_ports() -> None:
    with pytest.raises(TypeError, match=r"minigame must implement execute\(\)"):
        replace(_workflows(), minigame=cast("ActivityWorkflow", object()))
    with pytest.raises(TypeError, match=r"opsi_daemon must implement advance_to_safe_point\(\)"):
        replace(_workflows(), opsi_daemon=cast("AssistSessionWorkflow", object()))
    with pytest.raises(TypeError, match="dependencies must be ActivityFactoryDependencies"):
        build_activity_factories(cast("ActivityFactoryDependencies", object()))
