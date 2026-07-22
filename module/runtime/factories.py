from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from module.application import TaskId
from module.runtime.errors import FactoryCoverageError, InvalidTaskFactoryError
from module.runtime.task_state import TaskStateDocument
from module.task_registry import TaskSpec

if TYPE_CHECKING:
    from module.application import Task
    from module.runtime.settings import FrozenTaskSettings


class TaskFactory(Protocol):
    def build(self, context: TaskBuildContext) -> Task: ...


class TaskBuilder(Protocol):
    def __call__(
        self,
        spec: TaskSpec,
        settings_revision: int,
        content_revision: str,
        task_state: TaskStateDocument,
    ) -> Task: ...


@dataclass(frozen=True, slots=True)
class TaskBuildContext:
    spec: TaskSpec
    settings_revision: int
    content_revision: str
    settings: FrozenTaskSettings
    task_state: TaskStateDocument

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TaskSpec):
            message = "spec must be a TaskSpec"
            raise TypeError(message)
        if type(self.settings_revision) is not int or self.settings_revision <= 0:
            message = "settings_revision must be a positive integer"
            raise ValueError(message)
        _validate_revision(self.content_revision, field_name="content_revision")
        if not isinstance(self.settings, Mapping):
            message = "settings must be a mapping"
            raise TypeError(message)
        if not isinstance(self.task_state, TaskStateDocument):
            message = "task_state must be a TaskStateDocument"
            raise TypeError(message)
        if self.task_state.namespace != self.spec.command:
            message = "task_state namespace must match spec command"
            raise ValueError(message)


def _validate_revision(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class TaskBinding:
    """持有一次运行构造 Task 所需的全部不可变输入。"""

    spec: TaskSpec
    settings_revision: int
    content_revision: str
    builder: TaskBuilder

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TaskSpec):
            message = "binding spec must be a TaskSpec"
            raise TypeError(message)
        if type(self.settings_revision) is not int or self.settings_revision <= 0:
            message = "binding settings_revision must be a positive integer"
            raise ValueError(message)
        _validate_revision(self.content_revision, field_name="binding content_revision")
        if not callable(self.builder):
            message = "binding builder must be callable"
            raise TypeError(message)

    def build(self, task_state: TaskStateDocument) -> Task:
        if not isinstance(task_state, TaskStateDocument):
            message = "task_state must be a TaskStateDocument"
            raise TypeError(message)
        if task_state.namespace != self.spec.command:
            message = "task_state namespace must match binding spec"
            raise ValueError(message)
        task = self.builder(
            self.spec,
            self.settings_revision,
            self.content_revision,
            task_state,
        )
        if isinstance(task, type) or not callable(getattr(task, "run", None)):
            message = f"factory for {self.spec.command!r} must return a Task"
            raise InvalidTaskFactoryError(message)
        return task


@dataclass(frozen=True, slots=True)
class _FrozenSettingsTaskBuilder:
    factory: TaskFactory
    settings: FrozenTaskSettings

    def __call__(
        self,
        spec: TaskSpec,
        settings_revision: int,
        content_revision: str,
        task_state: TaskStateDocument,
    ) -> Task:
        return self.factory.build(
            TaskBuildContext(
                spec=spec,
                settings_revision=settings_revision,
                content_revision=content_revision,
                settings=self.settings,
                task_state=task_state,
            )
        )


def bind_tasks(
    *,
    specs: Mapping[str, TaskSpec],
    factories: Mapping[str, TaskFactory],
    settings: Mapping[str, FrozenTaskSettings],
    settings_revisions: Mapping[str, int],
    content_revisions: Mapping[str, str],
) -> Mapping[TaskId, TaskBinding]:
    """把静态 spec、运行依赖和已编译配置收敛成唯一 binding 表。"""

    for field_name, value in (
        ("specs", specs),
        ("factories", factories),
        ("settings", settings),
        ("settings_revisions", settings_revisions),
        ("content_revisions", content_revisions),
    ):
        if not isinstance(value, Mapping):
            message = f"{field_name} must be a mapping"
            raise TypeError(message)

    spec_copy = dict(specs)
    if any(not isinstance(key, str) or not isinstance(spec, TaskSpec) for key, spec in spec_copy.items()):
        message = "specs must map task id strings to TaskSpec values"
        raise TypeError(message)
    incoherent = sorted(key for key, spec in spec_copy.items() if key != spec.command)
    if incoherent:
        message = f"spec keys must match commands: {incoherent}"
        raise FactoryCoverageError(message)

    factory_copy = dict(factories)
    invalid_factories = sorted(
        key
        for key, factory in factory_copy.items()
        if not isinstance(key, str) or isinstance(factory, type) or not callable(getattr(factory, "build", None))
    )
    if invalid_factories:
        message = f"factories must implement build(): {invalid_factories}"
        raise TypeError(message)

    required = set(spec_copy)
    for field_name, keys in (
        ("factory", set(factory_copy)),
        ("content revision", set(content_revisions)),
    ):
        if keys != required:
            missing = sorted(required - keys)
            unknown = sorted(keys - required)
            message = f"{field_name} coverage mismatch: missing={missing}, unknown={unknown}"
            raise FactoryCoverageError(message)
    missing_settings = sorted(required - set(settings))
    missing_revisions = sorted(required - set(settings_revisions))
    if missing_settings or missing_revisions:
        message = (
            "task settings coverage mismatch: "
            f"missing_settings={missing_settings}, missing_revisions={missing_revisions}"
        )
        raise FactoryCoverageError(message)

    bindings = {
        TaskId(task_id): TaskBinding(
            spec=spec,
            settings_revision=settings_revisions[task_id],
            content_revision=content_revisions[task_id],
            builder=_FrozenSettingsTaskBuilder(
                factory=factory_copy[task_id],
                settings=settings[task_id],
            ),
        )
        for task_id, spec in spec_copy.items()
    }
    return MappingProxyType(bindings)


def validate_task_bindings(bindings: Mapping[TaskId, TaskBinding]) -> None:
    if not isinstance(bindings, Mapping):
        message = "bindings must be a mapping"
        raise TypeError(message)
    for task_id, binding in bindings.items():
        if not isinstance(task_id, TaskId) or not isinstance(binding, TaskBinding):
            message = "bindings must map TaskId values to TaskBinding values"
            raise TypeError(message)
        if binding.spec.command != task_id.value:
            message = f"binding key must match spec command: {task_id.value}"
            raise FactoryCoverageError(message)
        binding.build(TaskStateDocument.empty(task_id.value))
