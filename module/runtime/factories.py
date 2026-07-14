from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from module.runtime.errors import FactoryCoverageError, InvalidTaskFactoryError, UnknownTaskError
from module.runtime.settings import TaskSettingsDocument
from module.runtime.task_state import TaskStateDocument
from module.task_registry import TaskDefinition

if TYPE_CHECKING:
    from module.application import Task
    from module.runtime.settings import FrozenTaskSettings


class TaskFactory(Protocol):
    def build(self, context: TaskBuildContext) -> Task: ...


@dataclass(frozen=True, slots=True)
class TaskBuildContext:
    definition: TaskDefinition
    settings_revision: int
    settings: FrozenTaskSettings
    task_state: TaskStateDocument

    def __post_init__(self) -> None:
        if not isinstance(self.definition, TaskDefinition):
            message = "definition must be a TaskDefinition"
            raise TypeError(message)
        if type(self.settings_revision) is not int or self.settings_revision <= 0:
            message = "settings_revision must be a positive integer"
            raise ValueError(message)
        if not isinstance(self.settings, Mapping):
            message = "settings must be a mapping"
            raise TypeError(message)
        if not isinstance(self.task_state, TaskStateDocument):
            message = "task_state must be a TaskStateDocument"
            raise TypeError(message)
        if self.task_state.namespace != self.definition.command:
            message = "task_state namespace must match definition command"
            raise ValueError(message)


def _validate_revision(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


class TaskFactoryRegistry:
    """绑定同一 content/UI revision，并精确覆盖 catalog 的不可变 factory 集。"""

    __slots__ = ("_catalog", "_factories", "client_ui_revision", "content_revision")

    def __init__(
        self,
        *,
        catalog: Mapping[str, TaskDefinition],
        factories: Mapping[str, TaskFactory],
        content_revision: str,
        client_ui_revision: str,
    ) -> None:
        if not isinstance(catalog, Mapping):
            message = "catalog must be a mapping"
            raise TypeError(message)
        if not isinstance(factories, Mapping):
            message = "factories must be a mapping"
            raise TypeError(message)
        _validate_revision(content_revision, field_name="content_revision")
        _validate_revision(client_ui_revision, field_name="client_ui_revision")

        catalog_copy = dict(catalog)
        if any(
            not isinstance(key, str) or not isinstance(value, TaskDefinition) for key, value in catalog_copy.items()
        ):
            message = "catalog must map task id strings to TaskDefinition values"
            raise TypeError(message)
        incoherent = sorted(key for key, definition in catalog_copy.items() if definition.command != key)
        if incoherent:
            message = f"catalog keys must match definition commands: {incoherent}"
            raise FactoryCoverageError(message)

        factory_copy = dict(factories)
        invalid = sorted(
            key
            for key, factory in factory_copy.items()
            if not isinstance(key, str) or isinstance(factory, type) or not callable(getattr(factory, "build", None))
        )
        if invalid:
            message = f"factories must implement build(): {invalid}"
            raise TypeError(message)
        if set(factory_copy) != set(catalog_copy):
            missing = sorted(set(catalog_copy) - set(factory_copy))
            unknown = sorted(set(factory_copy) - set(catalog_copy))
            message = f"factory coverage mismatch: missing={missing}, unknown={unknown}"
            raise FactoryCoverageError(message)

        self._catalog = MappingProxyType(catalog_copy)
        self._factories = MappingProxyType(factory_copy)
        self.content_revision = content_revision
        self.client_ui_revision = client_ui_revision

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(self._catalog)

    @property
    def catalog(self) -> Mapping[str, TaskDefinition]:
        return self._catalog

    def definition(self, task_id: str) -> TaskDefinition:
        try:
            return self._catalog[task_id]
        except KeyError:
            message = f"unknown task: {task_id}"
            raise UnknownTaskError(message) from None

    def factory(self, task_id: str) -> TaskFactory:
        try:
            return self._factories[task_id]
        except KeyError:
            message = f"unknown task: {task_id}"
            raise UnknownTaskError(message) from None

    def build(
        self,
        task_id: str,
        document: TaskSettingsDocument,
        task_state: TaskStateDocument,
    ) -> Task:
        if not isinstance(document, TaskSettingsDocument):
            message = "document must be a TaskSettingsDocument"
            raise TypeError(message)
        if not isinstance(task_state, TaskStateDocument):
            message = "task_state must be a TaskStateDocument"
            raise TypeError(message)
        if task_state.namespace != task_id:
            message = "task_state namespace must match task_id"
            raise ValueError(message)
        definition = self.definition(task_id)
        context = TaskBuildContext(
            definition=definition,
            settings_revision=document.revision,
            settings=document.for_task(task_id),
            task_state=task_state,
        )
        task = self.factory(task_id).build(context)
        if isinstance(task, type) or not callable(getattr(task, "run", None)):
            message = f"factory for {task_id!r} must return a Task"
            raise InvalidTaskFactoryError(message)
        return task

    def validate_settings(
        self,
        document: TaskSettingsDocument,
        *,
        task_ids: Iterable[str] | None = None,
    ) -> None:
        if not isinstance(document, TaskSettingsDocument):
            message = "document must be a TaskSettingsDocument"
            raise TypeError(message)
        if set(document.tasks) != set(self._catalog):
            message = "settings document coverage does not match factory registry"
            raise FactoryCoverageError(message)
        if isinstance(task_ids, str):
            message = "task_ids must be an iterable of task id strings"
            raise TypeError(message)
        selected = tuple(self._catalog) if task_ids is None else tuple(task_ids)
        if any(not isinstance(task_id, str) for task_id in selected):
            message = "task_ids must contain strings"
            raise TypeError(message)
        if len(set(selected)) != len(selected):
            message = "task_ids must not contain duplicates"
            raise ValueError(message)
        unknown = sorted(set(selected) - set(self._catalog))
        if unknown:
            message = f"task_ids contain unknown tasks: {unknown}"
            raise UnknownTaskError(message)
        for task_id in selected:
            self.build(task_id, document, TaskStateDocument.empty(task_id))
