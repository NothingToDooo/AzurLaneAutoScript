from typing import Protocol

from module.application import ExecutionMode, RunMetadata, ScheduleItem, TaskId
from module.runtime.errors import ExecutionModeMismatchError, MissingSettingsError
from module.runtime.factories import TaskFactoryRegistry
from module.runtime.settings import TaskSettingsDocument
from module.runtime.task_state import TaskStateDocument
from module.state import TaskResolutionSnapshot
from module.supervisor.instance_agent import TaskResolution


class TaskResolutionSnapshotSource(Protocol):
    def read_task_resolution_snapshot(self, task_id: str) -> TaskResolutionSnapshot: ...


class CatalogTaskResolver:
    """从一次 settings 读取与 revision-bound factory 集构造原子 TaskResolution。"""

    __slots__ = ("_factories", "_snapshot_source")

    def __init__(self, *, snapshot_source: TaskResolutionSnapshotSource, factories: TaskFactoryRegistry) -> None:
        if isinstance(snapshot_source, type) or not callable(
            getattr(snapshot_source, "read_task_resolution_snapshot", None)
        ):
            message = "snapshot_source must implement read_task_resolution_snapshot()"
            raise TypeError(message)
        if not isinstance(factories, TaskFactoryRegistry):
            message = "factories must be a TaskFactoryRegistry"
            raise TypeError(message)
        self._snapshot_source = snapshot_source
        self._factories = factories

    def resolve(self, task_id: TaskId, mode: ExecutionMode) -> TaskResolution:
        if not isinstance(task_id, TaskId):
            message = "task_id must be a TaskId"
            raise TypeError(message)
        if not isinstance(mode, ExecutionMode):
            message = "mode must be an ExecutionMode"
            raise TypeError(message)

        definition = self._factories.definition(task_id.value)
        if definition.execution_mode is not mode:
            message = f"task {task_id.value!r} requires {definition.execution_mode.value}, not {mode.value}"
            raise ExecutionModeMismatchError(message)

        snapshot = self._snapshot_source.read_task_resolution_snapshot(task_id.value)
        if not isinstance(snapshot, TaskResolutionSnapshot):
            message = (
                "TaskResolutionSnapshotSource.read_task_resolution_snapshot() must return a TaskResolutionSnapshot"
            )
            raise TypeError(message)
        if snapshot.task_id != task_id.value:
            message = "task resolution snapshot task_id must match the requested task"
            raise ValueError(message)
        if snapshot.settings is None:
            message = "settings snapshot has not been published"
            raise MissingSettingsError(message)
        document = TaskSettingsDocument.from_snapshot(snapshot.settings, task_ids=self._factories.task_ids)
        task_state = TaskStateDocument.from_records(task_id.value, snapshot.state_records)
        task = self._factories.build(task_id.value, document, task_state)

        metadata = RunMetadata(
            settings_revision=document.revision,
            content_revision=self._factories.content_revision,
            client_ui_revision=self._factories.client_ui_revision,
        )
        schedules = tuple(
            ScheduleItem(
                task_id=TaskId(record.task_id),
                enabled=record.enabled,
                due_at=record.due_at,
                priority=record.priority,
            )
            for record in snapshot.schedule_records
        )
        return TaskResolution(task=task, metadata=metadata, schedules=schedules)
