import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, override

import pytest

from module.application import ExecutionMode, Succeeded, Task, TaskContext, TaskId, TaskResult
from module.runtime import (
    CatalogTaskResolver,
    ConfigurationDocumentError,
    ConfigurationPublisher,
    SettingsDecoder,
    SettingsDocumentError,
    TaskFactoryRegistry,
    TypedTaskFactory,
)
from module.state import JsonValue, RevisionConflictError, ScheduleMutation, SQLiteStateStore
from module.task_registry import LaunchSurface, TaskDefinition, TaskDomain


def test_publisher_requires_both_initial_and_update_store_contracts() -> None:
    class _InitialOnlyStore:
        @staticmethod
        def publish_configuration(*args: object, **kwargs: object) -> None:
            del args, kwargs

    with pytest.raises(TypeError, match="publish_configuration_update"):
        ConfigurationPublisher(
            store=cast("ConfigurationWriteStore", _InitialOnlyStore()),
            factories=_registry(),
            clock=_Clock(),
        )


if TYPE_CHECKING:
    from pathlib import Path

    from module.runtime import ConfigurationWriteStore

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)
_SOURCE_REVISION = "sha256:" + "0" * 64


@dataclass(frozen=True, slots=True)
class _Settings:
    enabled: bool


class _Task(Task):
    def __init__(self, settings: _Settings) -> None:
        self.settings = settings

    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        return TaskResult(Succeeded())


class _Clock:
    @staticmethod
    def now() -> datetime:
        return _NOW


def _decode(decoder: SettingsDecoder) -> _Settings:
    return _Settings(enabled=decoder.boolean("enabled"))


def _registry() -> TaskFactoryRegistry:
    definition = TaskDefinition(
        command="restart",
        config_scopes=(),
        priority=0,
        domain=TaskDomain.MAINTENANCE,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        allowed_launches=frozenset({LaunchSurface.SCHEDULER}),
    )
    return TaskFactoryRegistry(
        catalog={"restart": definition},
        factories={"restart": TypedTaskFactory(_decode, _Task)},
        content_revision="content:current",
        client_ui_revision="ui:current",
    )


def _payload(*, enabled: bool = True) -> JsonValue:
    return {"schema_version": 1, "tasks": {"restart": {"enabled": enabled}}}


def _schedules(*, enabled: bool = True) -> tuple[ScheduleMutation, ...]:
    return (
        ScheduleMutation(
            task_id="restart",
            enabled=enabled,
            due_at=_NOW if enabled else None,
            priority=0,
        ),
    )


def test_publisher_atomically_publishes_settings_and_schedule_for_runtime(tmp_path: Path) -> None:
    registry = _registry()
    with SQLiteStateStore(tmp_path / "state.sqlite3") as store:
        store.upsert_schedule(
            ScheduleMutation(task_id="stale", enabled=False, due_at=None, priority=99),
            updated_at=_NOW,
        )
        published = ConfigurationPublisher(store=store, factories=registry, clock=_Clock()).publish(
            _payload(),
            _schedules(),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )
        resolution = CatalogTaskResolver(snapshot_source=store, factories=registry).resolve(
            TaskId("restart"),
            ExecutionMode.SCHEDULED_JOB,
        )
        schedule = store.get_schedule("restart")
        schedules = store.list_schedules()

    assert published.revision == 1
    assert published.updated_at == _NOW
    assert resolution.metadata.settings_revision == 1
    assert isinstance(resolution.task, _Task)
    assert resolution.task.settings == _Settings(enabled=True)
    assert schedule is not None
    assert schedule.enabled
    assert schedule.due_at == _NOW
    assert tuple(record.task_id for record in schedules) == ("restart",)


def test_invalid_typed_settings_never_reach_store(tmp_path: Path) -> None:
    registry = _registry()
    invalid: JsonValue = {"schema_version": 1, "tasks": {"restart": {"enabled": 1}}}
    with SQLiteStateStore(tmp_path / "state.sqlite3") as store:
        with pytest.raises(SettingsDocumentError, match="must be a boolean"):
            ConfigurationPublisher(store=store, factories=registry, clock=_Clock()).publish(
                invalid,
                _schedules(),
                source_revision=_SOURCE_REVISION,
                expected_revision=0,
            )
        assert store.read_settings() is None
        assert store.list_schedules() == ()


def test_disabled_task_settings_are_published_but_validated_when_the_task_becomes_runnable(tmp_path: Path) -> None:
    registry = _registry()
    invalid: JsonValue = {"schema_version": 1, "tasks": {"restart": {"enabled": 1}}}
    with SQLiteStateStore(tmp_path / "state.sqlite3") as store:
        published = ConfigurationPublisher(store=store, factories=registry, clock=_Clock()).publish(
            invalid,
            _schedules(enabled=False),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )

        assert published.payload == invalid
        with pytest.raises(SettingsDocumentError, match="must be a boolean"):
            CatalogTaskResolver(snapshot_source=store, factories=registry).resolve(
                TaskId("restart"),
                ExecutionMode.SCHEDULED_JOB,
            )


@pytest.mark.parametrize(
    ("schedules", "error"),
    [
        ((), "coverage mismatch"),
        (
            (
                ScheduleMutation(
                    task_id="restart",
                    enabled=False,
                    due_at=None,
                    priority=1,
                ),
            ),
            "priority mismatch",
        ),
    ],
)
def test_invalid_schedule_document_never_reaches_store(
    tmp_path: Path,
    schedules: tuple[ScheduleMutation, ...],
    error: str,
) -> None:
    with SQLiteStateStore(tmp_path / "state.sqlite3") as store:
        publisher = ConfigurationPublisher(store=store, factories=_registry(), clock=_Clock())
        with pytest.raises(ConfigurationDocumentError, match=error):
            publisher.publish(
                _payload(),
                schedules,
                source_revision=_SOURCE_REVISION,
                expected_revision=0,
            )
        assert store.read_settings() is None


def test_publisher_preserves_store_cas_conflicts_without_replacing_schedule(tmp_path: Path) -> None:
    registry = _registry()
    with SQLiteStateStore(tmp_path / "state.sqlite3") as store:
        publisher = ConfigurationPublisher(store=store, factories=registry, clock=_Clock())
        publisher.publish(
            _payload(),
            _schedules(),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )

        with pytest.raises(RevisionConflictError):
            publisher.publish(
                _payload(enabled=False),
                _schedules(enabled=False),
                source_revision="sha256:" + "1" * 64,
                expected_revision=0,
            )

        snapshot = store.read_settings()
        schedule = store.get_schedule("restart")
    assert snapshot is not None
    assert snapshot.payload == _payload()
    assert schedule is not None
    assert schedule.enabled


def test_update_publisher_preserves_runtime_schedule_on_cas_conflict(tmp_path: Path) -> None:
    registry = _registry()
    runtime_due = _NOW.replace(hour=12)
    with SQLiteStateStore(tmp_path / "state.sqlite3") as store:
        publisher = ConfigurationPublisher(store=store, factories=registry, clock=_Clock())
        publisher.publish(
            _payload(),
            _schedules(),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )
        store.upsert_schedule(
            ScheduleMutation(task_id="restart", enabled=False, due_at=runtime_due, priority=0),
            updated_at=_NOW,
        )

        with pytest.raises(RevisionConflictError):
            publisher.publish_update(
                _payload(enabled=False),
                _schedules(),
                _schedules(),
                source_revision="sha256:" + "1" * 64,
                expected_revision=0,
            )

        snapshot = store.read_settings()
        schedule = store.get_schedule("restart")
    assert snapshot is not None
    assert snapshot.revision == 1
    assert schedule is not None
    assert not schedule.enabled
    assert schedule.due_at == runtime_due


def test_store_rolls_back_settings_when_schedule_replacement_fails(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"
    with SQLiteStateStore(state_path) as store:
        with sqlite3.connect(state_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_schedule
                BEFORE INSERT ON schedule
                BEGIN
                    SELECT RAISE(ABORT, 'schedule rejected');
                END
                """
            )

        publisher = ConfigurationPublisher(store=store, factories=_registry(), clock=_Clock())
        with pytest.raises(sqlite3.IntegrityError, match="schedule rejected"):
            publisher.publish(
                _payload(),
                _schedules(),
                source_revision=_SOURCE_REVISION,
                expected_revision=0,
            )

        assert store.read_settings() is None
        assert store.list_schedules() == ()
