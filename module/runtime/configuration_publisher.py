from typing import TYPE_CHECKING, Protocol

from module.runtime.errors import ConfigurationDocumentError
from module.runtime.factories import TaskFactoryRegistry
from module.runtime.settings import TaskSettingsDocument
from module.state import (
    ConfigurationPublication,
    ConfigurationUpdate,
    JsonValue,
    ScheduleMutation,
    SettingsSnapshot,
)
from module.task_registry import LaunchSurface

if TYPE_CHECKING:
    from datetime import datetime


class ConfigurationClock(Protocol):
    def now(self) -> datetime: ...


class ConfigurationWriteStore(Protocol):
    def publish_configuration(
        self,
        command: ConfigurationPublication,
    ) -> SettingsSnapshot: ...

    def publish_configuration_update(self, command: ConfigurationUpdate) -> SettingsSnapshot: ...


class ConfigurationPublisher:
    """严格编译完整配置，再以一个 CAS 事务替换 settings 与 schedule。"""

    __slots__ = ("_clock", "_factories", "_store")

    def __init__(
        self,
        *,
        store: ConfigurationWriteStore,
        factories: TaskFactoryRegistry,
        clock: ConfigurationClock,
    ) -> None:
        if isinstance(store, type) or not all(
            callable(getattr(store, method, None))
            for method in ("publish_configuration", "publish_configuration_update")
        ):
            message = "store must implement publish_configuration() and publish_configuration_update()"
            raise TypeError(message)
        if not isinstance(factories, TaskFactoryRegistry):
            message = "factories must be a TaskFactoryRegistry"
            raise TypeError(message)
        if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
            message = "clock must implement now()"
            raise TypeError(message)
        self._store = store
        self._factories = factories
        self._clock = clock

    def publish(
        self,
        payload: JsonValue,
        schedules: tuple[ScheduleMutation, ...],
        *,
        source_revision: str,
        expected_revision: int,
    ) -> SettingsSnapshot:
        self._validate_publication_request(source_revision, expected_revision)
        self._validate_schedules(schedules)

        updated_at = self._clock.now()
        candidate = SettingsSnapshot(
            revision=expected_revision + 1,
            payload=payload,
            updated_at=updated_at,
        )
        document = TaskSettingsDocument.from_snapshot(
            candidate,
            task_ids=self._factories.task_ids,
        )
        schedule_by_task = {mutation.task_id: mutation for mutation in schedules}
        runnable_task_ids = tuple(
            task_id
            for task_id in self._factories.task_ids
            if task_id not in schedule_by_task or schedule_by_task[task_id].enabled
        )
        self._factories.validate_settings(document, task_ids=runnable_task_ids)

        published = self._store.publish_configuration(
            ConfigurationPublication(
                payload=payload,
                schedules=schedules,
                source_revision=source_revision,
                expected_revision=expected_revision,
                updated_at=updated_at,
            )
        )
        if not isinstance(published, SettingsSnapshot):
            message = "ConfigurationWriteStore.publish_configuration() must return a SettingsSnapshot"
            raise TypeError(message)
        if published != candidate:
            message = "configuration store returned an unexpected settings snapshot"
            raise RuntimeError(message)
        return published

    def publish_update(
        self,
        payload: JsonValue,
        schedules: tuple[ScheduleMutation, ...],
        *,
        source_revision: str,
        expected_revision: int,
    ) -> SettingsSnapshot:
        """完整验证新配置，再以 source 差量合并 schedule 并 CAS 发布。"""

        self._validate_publication_request(source_revision, expected_revision)
        self._validate_schedules(schedules)

        updated_at = self._clock.now()
        candidate = SettingsSnapshot(
            revision=expected_revision + 1,
            payload=payload,
            updated_at=updated_at,
        )
        document = TaskSettingsDocument.from_snapshot(
            candidate,
            task_ids=self._factories.task_ids,
        )
        schedule_by_task = {mutation.task_id: mutation for mutation in schedules}
        runnable_task_ids = tuple(
            task_id
            for task_id in self._factories.task_ids
            if task_id not in schedule_by_task or schedule_by_task[task_id].enabled
        )
        self._factories.validate_settings(document, task_ids=runnable_task_ids)

        published = self._store.publish_configuration_update(
            ConfigurationUpdate(
                publication=ConfigurationPublication(
                    payload=payload,
                    schedules=schedules,
                    source_revision=source_revision,
                    expected_revision=expected_revision,
                    updated_at=updated_at,
                ),
            )
        )
        if not isinstance(published, SettingsSnapshot):
            message = "ConfigurationWriteStore.publish_configuration_update() must return a SettingsSnapshot"
            raise TypeError(message)
        if published != candidate:
            message = "configuration store returned an unexpected settings snapshot"
            raise RuntimeError(message)
        return published

    @staticmethod
    def _validate_publication_request(source_revision: str, expected_revision: int) -> None:
        if not isinstance(source_revision, str):
            message = "source_revision must be a string"
            raise TypeError(message)
        if not source_revision or source_revision != source_revision.strip():
            message = "source_revision must be trimmed and non-empty"
            raise ValueError(message)
        if type(expected_revision) is not int or expected_revision < 0:
            message = "expected_revision must be a non-negative integer"
            raise ValueError(message)

    def _validate_schedules(self, schedules: tuple[ScheduleMutation, ...]) -> None:
        if not isinstance(schedules, tuple):
            message = "schedules must be a tuple"
            raise TypeError(message)
        if any(not isinstance(mutation, ScheduleMutation) for mutation in schedules):
            message = "schedules must contain only ScheduleMutation values"
            raise TypeError(message)

        expected = {
            task_id: definition.priority
            for task_id, definition in self._factories.catalog.items()
            if LaunchSurface.SCHEDULER in definition.allowed_launches and definition.priority is not None
        }
        actual = {mutation.task_id: mutation for mutation in schedules}
        if len(actual) != len(schedules):
            message = "configuration schedules must not contain duplicate task ids"
            raise ConfigurationDocumentError(message)
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            unknown = sorted(set(actual) - set(expected))
            message = f"configuration schedule coverage mismatch: missing={missing}, unknown={unknown}"
            raise ConfigurationDocumentError(message)

        for task_id, mutation in actual.items():
            if mutation.priority != expected[task_id]:
                message = f"configuration schedule priority mismatch: {task_id}"
                raise ConfigurationDocumentError(message)
            if mutation.enabled and mutation.due_at is None:
                message = f"enabled configuration schedule requires due_at: {task_id}"
                raise ConfigurationDocumentError(message)
