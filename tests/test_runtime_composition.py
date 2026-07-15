from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast, override

import pytest

from module.application import ExecutionMode, Succeeded, Task, TaskContext, TaskResult
from module.runtime import (
    FactoryCoverageError,
    FrozenJsonValue,
    InvalidTaskFactoryError,
    JsonValue,
    SettingsDocumentError,
    TaskBuildContext,
    TaskFactory,
    TaskFactoryRegistry,
    TaskSettingsDocument,
    TaskStateDocument,
    TaskStateDocumentError,
    TaskStateEntry,
    UnknownTaskError,
)
from module.task_registry import TaskDefinition

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


class _InvalidFactory:
    @staticmethod
    def build(context: TaskBuildContext) -> object:
        del context
        return object()


def _definition(command: str, mode: ExecutionMode, *, priority: int | None) -> TaskDefinition:
    return TaskDefinition(
        command=command,
        config_scopes=(),
        priority=priority,
        execution_mode=mode,
    )


def _catalog() -> dict[str, TaskDefinition]:
    return {
        "restart": _definition("restart", ExecutionMode.SCHEDULED_JOB, priority=0),
        "benchmark": _definition("benchmark", ExecutionMode.DIRECT_COMMAND, priority=None),
    }


def _payload(*, tasks: JsonValue | None = None) -> JsonValue:
    return {
        "schema_version": 1,
        "tasks": tasks
        if tasks is not None
        else {
            "restart": {"nested": {"values": [1, 2]}},
            "benchmark": {"scenes": ["screenshot", "click"]},
        },
    }


def _document(*, payload: JsonValue | None = None) -> TaskSettingsDocument:
    return TaskSettingsDocument.from_payload(
        _payload() if payload is None else payload,
        revision=7,
        updated_at=_NOW,
        task_ids=("restart", "benchmark"),
    )


def _registry(*, restart_factory: _Factory | None = None) -> TaskFactoryRegistry:
    return TaskFactoryRegistry(
        catalog=_catalog(),
        factories={"restart": restart_factory or _Factory(), "benchmark": _Factory()},
        content_revision="content-sha256:abc",
    )


def test_registry_builds_from_one_settings_revision_and_current_task_state() -> None:
    factory = _Factory()
    registry = _registry(restart_factory=factory)
    task_state = TaskStateDocument(
        "restart",
        {"checkpoint": TaskStateEntry(schema_version=2, payload={"step": 4}, updated_at=_NOW)},
    )

    registry.build("restart", _document(), task_state)

    assert len(factory.contexts) == 1
    context = factory.contexts[0]
    assert context.definition.command == "restart"
    assert context.settings_revision == 7
    nested = cast("dict[str, FrozenJsonValue]", context.settings["nested"])
    assert nested["values"] == (1, 2)
    assert context.task_state.get("checkpoint") == task_state.get("checkpoint")


def test_registry_settings_validation_builds_with_empty_task_state() -> None:
    factory = _Factory()
    registry = _registry(restart_factory=factory)

    registry.validate_settings(_document())

    assert len(factory.contexts) == 1
    assert factory.contexts[0].task_state == TaskStateDocument.empty("restart")


def test_settings_document_is_deeply_read_only_and_detached_from_payload() -> None:
    payload = _payload()
    document = _document(payload=payload)
    root = cast("dict[str, JsonValue]", payload)
    tasks = cast("dict[str, JsonValue]", root["tasks"])
    restart = cast("dict[str, JsonValue]", tasks["restart"])
    raw_nested = cast("dict[str, JsonValue]", restart["nested"])
    cast("list[JsonValue]", raw_nested["values"]).append(3)

    nested = cast("dict[str, FrozenJsonValue]", document.for_task("restart")["nested"])
    assert nested["values"] == (1, 2)
    with pytest.raises(TypeError):
        cast("dict[str, object]", document.tasks)["restart"] = {}
    with pytest.raises(TypeError):
        cast("dict[str, object]", document.for_task("restart"))["new"] = True


def test_task_state_document_is_deeply_read_only_and_detached_from_payload() -> None:
    payload: object = {"cursor": {"visited": ["a", "b"]}}
    entry = TaskStateEntry(schema_version=3, payload=cast("FrozenJsonValue", payload), updated_at=_NOW)
    document = TaskStateDocument("restart", {"checkpoint": entry})
    raw_cursor = cast("dict[str, object]", cast("dict[str, object]", payload)["cursor"])
    cast("list[str]", raw_cursor["visited"]).append("c")

    stored = document.get("checkpoint")
    assert stored is not None
    frozen_payload = cast("dict[str, FrozenJsonValue]", stored.payload)
    frozen_cursor = cast("dict[str, FrozenJsonValue]", frozen_payload["cursor"])
    assert frozen_cursor["visited"] == ("a", "b")
    with pytest.raises(TypeError):
        cast("dict[str, object]", document.entries)["new"] = entry
    with pytest.raises(TypeError):
        cast("dict[str, object]", frozen_cursor)["new"] = True


def test_task_state_document_rejects_invalid_entries_and_non_json_payloads() -> None:
    with pytest.raises(TypeError, match="TaskStateEntry"):
        TaskStateDocument("restart", {"checkpoint": cast("TaskStateEntry", object())})
    with pytest.raises(TaskStateDocumentError, match="only JSON"):
        TaskStateEntry(
            schema_version=1,
            payload=cast("FrozenJsonValue", {"unsupported": object()}),
            updated_at=_NOW,
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
        _document(payload=payload)


def test_settings_document_rejects_invalid_revision_and_timestamp() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        TaskSettingsDocument.from_payload(_payload(), revision=0, updated_at=_NOW, task_ids=_catalog())
    with pytest.raises(ValueError, match="timezone-aware"):
        TaskSettingsDocument.from_payload(
            _payload(),
            revision=1,
            updated_at=datetime(2026, 7, 13),
            task_ids=_catalog(),
        )


def test_registry_requires_exact_factory_coverage_and_coherent_catalog_keys() -> None:
    with pytest.raises(FactoryCoverageError, match="coverage mismatch"):
        TaskFactoryRegistry(
            catalog=_catalog(),
            factories={"restart": _Factory()},
            content_revision="content:1",
        )
    with pytest.raises(FactoryCoverageError, match="keys must match"):
        TaskFactoryRegistry(
            catalog={"renamed": _definition("restart", ExecutionMode.SCHEDULED_JOB, priority=0)},
            factories={"renamed": _Factory()},
            content_revision="content:1",
        )


def test_registry_rejects_unknown_task_and_invalid_factory_result() -> None:
    registry = _registry()
    with pytest.raises(UnknownTaskError, match="unknown task"):
        registry.definition("removed")

    invalid_registry = TaskFactoryRegistry(
        catalog=_catalog(),
        factories={
            "restart": cast("TaskFactory", _InvalidFactory()),
            "benchmark": registry.factory("benchmark"),
        },
        content_revision="content-sha256:abc",
    )
    with pytest.raises(InvalidTaskFactoryError, match="must return a Task"):
        invalid_registry.build("restart", _document(), TaskStateDocument.empty("restart"))
