from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast, override

import pytest

from module.application import ExecutionMode, Succeeded, Task, TaskContext, TaskId, TaskResult
from module.runtime import (
    TaskBuildContext,
    TaskStateDocument,
    TaskStateEntry,
    bind_tasks,
    compile_task_settings,
)
from module.task_registry import ContentRevisionPolicy, TaskDomain, TaskSpec

_NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)


class _Task(Task):
    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        return TaskResult(Succeeded())


@dataclass(frozen=True, slots=True)
class _Settings:
    values: tuple[int, ...]


@dataclass(slots=True)
class _Factory:
    contexts: list[TaskBuildContext] = field(default_factory=list)

    def build(self, context: TaskBuildContext) -> Task:
        self.contexts.append(context)
        return _Task()


def test_task_binding_owns_all_inputs_needed_to_build_fresh_task() -> None:
    spec = TaskSpec(
        command="restart",
        config_scopes=(),
        priority=0,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        domain=TaskDomain.MAINTENANCE,
        content_revision_policy=ContentRevisionPolicy.BUILTIN,
    )
    settings = compile_task_settings({"restart": _Settings((1, 2))}, task_ids=("restart",))
    factory = _Factory()
    bindings = bind_tasks(
        specs={"restart": spec},
        factories={"restart": factory},
        settings=settings,
        content_revisions={"restart": "builtin-content-v1"},
    )
    binding = bindings[TaskId("restart")]
    state = TaskStateDocument(
        "restart",
        {"checkpoint": TaskStateEntry(schema_version=1, payload={"step": 3}, updated_at=_NOW)},
    )

    first = binding.build(state)
    second = binding.build(state)

    assert first is not second
    assert len(factory.contexts) == 2
    context = factory.contexts[0]
    assert context.spec is spec
    assert context.settings_revision == settings["restart"].revision
    assert context.content_revision == "builtin-content-v1"
    assert context.settings == _Settings((1, 2))
    assert context.task_state.get("checkpoint") == state.get("checkpoint")


def test_task_spec_rejects_untyped_domain_and_content_policy() -> None:
    with pytest.raises(TypeError, match="task domain"):
        TaskSpec(
            command="restart",
            config_scopes=(),
            priority=0,
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            domain=cast("TaskDomain", "maintenance"),
            content_revision_policy=ContentRevisionPolicy.BUILTIN,
        )
    with pytest.raises(TypeError, match="content revision policy"):
        TaskSpec(
            command="restart",
            config_scopes=(),
            priority=0,
            execution_mode=ExecutionMode.SCHEDULED_JOB,
            domain=TaskDomain.MAINTENANCE,
            content_revision_policy=cast("ContentRevisionPolicy", "builtin"),
        )
