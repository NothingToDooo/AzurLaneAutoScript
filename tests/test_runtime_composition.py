from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, override

import pytest

from module.application import ExecutionMode, Succeeded, Task, TaskContext, TaskId, TaskResult
from module.runtime import (
    CompiledTaskSettings,
    FactoryCoverageError,
    FrozenJsonValue,
    InvalidTaskFactoryError,
    TaskBinding,
    TaskBuildContext,
    TaskFactory,
    TaskStateDocument,
    TaskStateDocumentError,
    TaskStateEntry,
    bind_tasks,
    compile_task_settings,
    validate_task_bindings,
)
from module.task_registry import ContentRevisionPolicy, TaskDomain, TaskSpec

if TYPE_CHECKING:
    from collections.abc import Mapping

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


@dataclass(frozen=True, slots=True)
class _NestedSettings:
    values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _RestartSettings:
    nested: _NestedSettings


@dataclass(frozen=True, slots=True)
class _BenchmarkSettings:
    scenes: tuple[str, ...]


def _spec(command: str, mode: ExecutionMode, *, priority: int | None) -> TaskSpec:
    return TaskSpec(
        command=command,
        config_scopes=(),
        priority=priority,
        execution_mode=mode,
        domain=TaskDomain.MAINTENANCE,
        content_revision_policy=ContentRevisionPolicy.BUILTIN,
    )


def _specs() -> dict[str, TaskSpec]:
    return {
        "restart": _spec("restart", ExecutionMode.SCHEDULED_JOB, priority=0),
        "benchmark": _spec("benchmark", ExecutionMode.DIRECT_COMMAND, priority=None),
    }


def _settings() -> Mapping[str, CompiledTaskSettings]:
    return compile_task_settings(
        {
            "restart": _RestartSettings(_NestedSettings((1, 2))),
            "benchmark": _BenchmarkSettings(("screenshot", "click")),
        },
        task_ids=("restart", "benchmark"),
    )


def _bindings(*, restart_factory: _Factory | None = None) -> Mapping[TaskId, TaskBinding]:
    return bind_tasks(
        specs=_specs(),
        factories={"restart": restart_factory or _Factory(), "benchmark": _Factory()},
        settings=_settings(),
        content_revisions={"restart": "content-restart", "benchmark": "content-benchmark"},
    )


def test_binding_validation_builds_with_empty_task_state() -> None:
    factory = _Factory()
    bindings = _bindings(restart_factory=factory)

    validate_task_bindings(bindings)

    assert len(factory.contexts) == 1
    assert factory.contexts[0].task_state == TaskStateDocument.empty("restart")


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


def test_bind_tasks_requires_exact_factory_coverage_and_coherent_spec_keys() -> None:
    settings = _settings()
    with pytest.raises(FactoryCoverageError, match="coverage mismatch"):
        bind_tasks(
            specs=_specs(),
            factories={"restart": _Factory()},
            settings=settings,
            content_revisions={"restart": "content:1", "benchmark": "content:1"},
        )
    with pytest.raises(FactoryCoverageError, match="keys must match"):
        bind_tasks(
            specs={"renamed": _spec("restart", ExecutionMode.SCHEDULED_JOB, priority=0)},
            factories={"renamed": _Factory()},
            settings={"renamed": settings["restart"]},
            content_revisions={"renamed": "content:1"},
        )

    with pytest.raises(FactoryCoverageError, match="content revision coverage mismatch"):
        bind_tasks(
            specs=_specs(),
            factories={"restart": _Factory(), "benchmark": _Factory()},
            settings=settings,
            content_revisions={"restart": "content:1"},
        )


def test_binding_rejects_invalid_factory_result() -> None:
    settings = _settings()
    bindings = bind_tasks(
        specs=_specs(),
        factories={
            "restart": cast("TaskFactory", _InvalidFactory()),
            "benchmark": _Factory(),
        },
        settings=settings,
        content_revisions={"restart": "content-restart", "benchmark": "content-benchmark"},
    )
    with pytest.raises(InvalidTaskFactoryError, match="must return a Task"):
        bindings[TaskId("restart")].build(TaskStateDocument.empty("restart"))
