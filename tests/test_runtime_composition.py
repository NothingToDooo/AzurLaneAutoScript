from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast, override

import pytest

from module.application import ExecutionMode, Succeeded, Task, TaskContext, TaskId, TaskResult
from module.runtime import (
    CatalogTaskResolver,
    ExecutionModeMismatchError,
    FactoryCoverageError,
    FrozenJsonValue,
    InvalidTaskFactoryError,
    MissingSettingsError,
    SettingsDocumentError,
    TaskBuildContext,
    TaskFactory,
    TaskFactoryRegistry,
    TaskResolutionSnapshotSource,
    TaskSettingsDocument,
    TaskStateDocument,
    TaskStateDocumentError,
    UnknownTaskError,
)
from module.state import JsonValue, ScheduleRecord, SettingsSnapshot, TaskResolutionSnapshot, TaskStateRecord
from module.task_registry import LaunchSurface, TaskDefinition, TaskDomain

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)


class _Task(Task):
    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        return TaskResult(outcome=Succeeded())


@dataclass(slots=True)
class _Factory:
    result: Task = field(default_factory=_Task)
    contexts: list[TaskBuildContext] = field(default_factory=list)

    def build(self, context: TaskBuildContext) -> Task:
        self.contexts.append(context)
        return self.result


@dataclass(slots=True)
class _SnapshotSource:
    snapshot: TaskResolutionSnapshot
    reads: int = 0
    requested_task_ids: list[str] = field(default_factory=list)

    def read_task_resolution_snapshot(self, task_id: str) -> TaskResolutionSnapshot:
        self.reads += 1
        self.requested_task_ids.append(task_id)
        return self.snapshot


def _definition(command: str, mode: ExecutionMode, *, priority: int | None) -> TaskDefinition:
    launches = (
        frozenset({LaunchSurface.SCHEDULER}) if mode is ExecutionMode.SCHEDULED_JOB else frozenset({LaunchSurface.TOOL})
    )
    return TaskDefinition(
        command=command,
        config_scopes=(),
        priority=priority,
        domain=TaskDomain.MAINTENANCE,
        execution_mode=mode,
        allowed_launches=launches,
    )


def _catalog() -> dict[str, TaskDefinition]:
    return {
        "restart": _definition("restart", ExecutionMode.SCHEDULED_JOB, priority=0),
        "benchmark": _definition("benchmark", ExecutionMode.DIRECT_COMMAND, priority=None),
    }


class _InvalidSnapshotSource:
    @staticmethod
    def read_task_resolution_snapshot(task_id: str) -> object:
        del task_id
        return {}


class _InvalidFactory:
    @staticmethod
    def build(context: TaskBuildContext) -> object:
        del context
        return object()


def _snapshot(*, payload: JsonValue | None = None) -> SettingsSnapshot:
    if payload is None:
        payload = {
            "schema_version": 1,
            "tasks": {
                "restart": {"nested": {"values": [1, 2]}},
                "benchmark": {"scenes": ["screenshot", "click"]},
            },
        }
    return SettingsSnapshot(revision=7, payload=payload, updated_at=_NOW)


def _registry(*, restart_factory: _Factory | None = None) -> TaskFactoryRegistry:
    restart = restart_factory or _Factory()
    return TaskFactoryRegistry(
        catalog=_catalog(),
        factories={"restart": restart, "benchmark": _Factory()},
        content_revision="content-sha256:abc",
        client_ui_revision="ui-sha256:def",
    )


def test_resolver_reads_one_settings_revision_and_builds_coherent_resolution() -> None:
    factory = _Factory()
    source = _SnapshotSource(
        TaskResolutionSnapshot(
            task_id="restart",
            settings=_snapshot(),
            state_records=(
                TaskStateRecord(
                    namespace="restart",
                    key="checkpoint",
                    version=2,
                    payload={"step": 4},
                    updated_at=_NOW,
                ),
            ),
            schedule_records=(
                ScheduleRecord(
                    task_id="restart",
                    enabled=True,
                    due_at=_NOW,
                    priority=0,
                    updated_at=_NOW,
                ),
            ),
        )
    )
    resolver = CatalogTaskResolver(snapshot_source=source, factories=_registry(restart_factory=factory))

    resolution = resolver.resolve(TaskId("restart"), ExecutionMode.SCHEDULED_JOB)

    assert isinstance(resolution.task, _Task)
    assert resolution.metadata.settings_revision == 7
    assert resolution.metadata.content_revision == "content-sha256:abc"
    assert resolution.metadata.client_ui_revision == "ui-sha256:def"
    assert len(resolution.schedules) == 1
    assert resolution.schedules[0].task_id == TaskId("restart")
    assert resolution.schedules[0].due_at == _NOW
    assert source.reads == 1
    assert source.requested_task_ids == ["restart"]
    assert len(factory.contexts) == 1
    assert factory.contexts[0].definition.command == "restart"
    assert factory.contexts[0].settings_revision == 7
    nested = cast("dict[str, FrozenJsonValue]", factory.contexts[0].settings["nested"])
    assert nested["values"] == (1, 2)
    assert factory.contexts[0].task_state.namespace == "restart"
    checkpoint = factory.contexts[0].task_state.get("checkpoint")
    assert checkpoint is not None
    assert checkpoint.schema_version == 2
    assert checkpoint.payload == {"step": 4}


def test_registry_settings_validation_builds_with_empty_task_state() -> None:
    factory = _Factory()
    registry = _registry(restart_factory=factory)
    document = TaskSettingsDocument.from_snapshot(_snapshot(), task_ids=registry.task_ids)

    registry.validate_settings(document)

    assert len(factory.contexts) == 1
    assert factory.contexts[0].task_state == TaskStateDocument.empty("restart")


def test_settings_document_is_deeply_read_only_and_detached_from_snapshot() -> None:
    snapshot = _snapshot()
    document = TaskSettingsDocument.from_snapshot(snapshot, task_ids=("restart", "benchmark"))
    payload = cast("dict[str, JsonValue]", snapshot.payload)
    raw_tasks = cast("dict[str, JsonValue]", payload["tasks"])
    restart = cast("dict[str, JsonValue]", raw_tasks["restart"])
    raw_nested = cast("dict[str, JsonValue]", restart["nested"])
    cast("list[JsonValue]", raw_nested["values"]).append(3)

    nested = cast("dict[str, FrozenJsonValue]", document.for_task("restart")["nested"])
    assert nested["values"] == (1, 2)
    with pytest.raises(TypeError):
        cast("dict[str, object]", document.tasks)["restart"] = {}
    with pytest.raises(TypeError):
        cast("dict[str, object]", document.for_task("restart"))["new"] = True


def test_task_state_document_is_deeply_read_only_and_detached_from_records() -> None:
    payload: JsonValue = {"cursor": {"visited": ["a", "b"]}}
    record = TaskStateRecord("restart", "checkpoint", 3, payload, _NOW)

    document = TaskStateDocument.from_records("restart", (record,))
    raw_payload = payload
    raw_cursor = cast("dict[str, JsonValue]", raw_payload["cursor"])
    cast("list[JsonValue]", raw_cursor["visited"]).append("c")

    entry = document.get("checkpoint")
    assert entry is not None
    assert entry.schema_version == 3
    assert entry.updated_at == _NOW
    frozen_payload = cast("dict[str, FrozenJsonValue]", entry.payload)
    frozen_cursor = cast("dict[str, FrozenJsonValue]", frozen_payload["cursor"])
    assert frozen_cursor["visited"] == ("a", "b")
    with pytest.raises(TypeError):
        cast("dict[str, object]", document.entries)["new"] = entry
    with pytest.raises(TypeError):
        cast("dict[str, object]", frozen_cursor)["new"] = True


def test_task_state_document_rejects_namespace_duplicates_and_non_json_payloads() -> None:
    valid = TaskStateRecord("restart", "checkpoint", 1, None, _NOW)
    with pytest.raises(TaskStateDocumentError, match="namespace"):
        TaskStateDocument.from_records(
            "restart",
            (TaskStateRecord("benchmark", "checkpoint", 1, None, _NOW),),
        )
    with pytest.raises(TaskStateDocumentError, match="duplicate"):
        TaskStateDocument.from_records("restart", (valid, valid))
    invalid_payload = cast("JsonValue", {"unsupported": object()})
    with pytest.raises(TaskStateDocumentError, match="only JSON"):
        TaskStateDocument.from_records(
            "restart",
            (TaskStateRecord("restart", "checkpoint", 1, invalid_payload, _NOW),),
        )


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"schema_version": 1}, "fields mismatch"),
        ({"schema_version": 2, "tasks": {"restart": {}, "benchmark": {}}}, "schema_version"),
        ({"schema_version": 1, "tasks": {"restart": {}}}, "coverage mismatch"),
        (
            {"schema_version": 1, "tasks": {"restart": {}, "benchmark": {}, "removed": {}}},
            "coverage mismatch",
        ),
        ({"schema_version": 1, "tasks": {"restart": [], "benchmark": {}}}, "must be an object"),
    ],
)
def test_settings_document_rejects_schema_drift(payload: JsonValue, match: str) -> None:
    with pytest.raises(SettingsDocumentError, match=match):
        TaskSettingsDocument.from_snapshot(_snapshot(payload=payload), task_ids=("restart", "benchmark"))


def test_registry_requires_exact_factory_coverage_and_coherent_catalog_keys() -> None:
    with pytest.raises(FactoryCoverageError, match="coverage mismatch"):
        TaskFactoryRegistry(
            catalog=_catalog(),
            factories={"restart": _Factory()},
            content_revision="content:1",
            client_ui_revision="ui:1",
        )
    with pytest.raises(FactoryCoverageError, match="keys must match"):
        TaskFactoryRegistry(
            catalog={"renamed": _definition("restart", ExecutionMode.SCHEDULED_JOB, priority=0)},
            factories={"renamed": _Factory()},
            content_revision="content:1",
            client_ui_revision="ui:1",
        )


def test_unknown_task_and_mode_mismatch_fail_before_settings_read() -> None:
    source = _SnapshotSource(TaskResolutionSnapshot("restart", _snapshot(), ()))
    resolver = CatalogTaskResolver(snapshot_source=source, factories=_registry())

    with pytest.raises(UnknownTaskError, match="unknown task"):
        resolver.resolve(TaskId("removed"), ExecutionMode.SCHEDULED_JOB)
    with pytest.raises(ExecutionModeMismatchError, match="requires direct_command"):
        resolver.resolve(TaskId("benchmark"), ExecutionMode.SCHEDULED_JOB)
    assert source.reads == 0


def test_resolver_rejects_missing_or_invalid_snapshot_and_invalid_factory_result() -> None:
    with pytest.raises(MissingSettingsError, match="not been published"):
        CatalogTaskResolver(
            snapshot_source=_SnapshotSource(TaskResolutionSnapshot("restart", None, ())),
            factories=_registry(),
        ).resolve(
            TaskId("restart"),
            ExecutionMode.SCHEDULED_JOB,
        )
    with pytest.raises(TypeError, match="must return a TaskResolutionSnapshot"):
        CatalogTaskResolver(
            snapshot_source=cast("TaskResolutionSnapshotSource", _InvalidSnapshotSource()),
            factories=_registry(),
        ).resolve(
            TaskId("restart"),
            ExecutionMode.SCHEDULED_JOB,
        )

    with pytest.raises(ValueError, match="must match the requested task"):
        CatalogTaskResolver(
            snapshot_source=_SnapshotSource(TaskResolutionSnapshot("benchmark", _snapshot(), ())),
            factories=_registry(),
        ).resolve(TaskId("restart"), ExecutionMode.SCHEDULED_JOB)

    factories = _registry()
    invalid_registry = TaskFactoryRegistry(
        catalog=_catalog(),
        factories={
            "restart": cast("TaskFactory", _InvalidFactory()),
            "benchmark": factories.factory("benchmark"),
        },
        content_revision="content-sha256:abc",
        client_ui_revision="ui-sha256:def",
    )
    resolver = CatalogTaskResolver(
        snapshot_source=_SnapshotSource(TaskResolutionSnapshot("restart", _snapshot(), ())),
        factories=invalid_registry,
    )
    with pytest.raises(InvalidTaskFactoryError, match="must return a Task"):
        resolver.resolve(TaskId("restart"), ExecutionMode.SCHEDULED_JOB)
