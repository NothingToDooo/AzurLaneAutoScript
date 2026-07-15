import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast, override

import pytest

from module.application import ExecutionMode, Succeeded, Task, TaskContext, TaskResult
from module.bootstrap.assembly_source import ConfigurationFileSignal
from module.runtime import (
    RuntimeConfigurationControl,
    RuntimeConfigurationSnapshot,
    RuntimeRestartRequiredError,
    SettingsDecoder,
    SettingsDocumentError,
    TaskFactoryRegistry,
    TypedTaskFactory,
)
from module.state import ConfigurationPublication, ConfigurationUpdate, ScheduleMutation, SQLiteStateStore
from module.task_registry import LaunchSurface, TaskDefinition, TaskDomain

if TYPE_CHECKING:
    from pathlib import Path

    from module.state import ConfigurationSourceSnapshot, JsonValue

_NOW = datetime(2026, 7, 14, 8, tzinfo=UTC)
_DUE = _NOW + timedelta(hours=1)
_SERIAL = "127.0.0.1:16384"
_ASSEMBLY_REVISION = "sha256:" + "a" * 64


def _source_revision(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class _Settings:
    flag: bool


class _Task(Task):
    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        return TaskResult(Succeeded())


def _decode(decoder: SettingsDecoder) -> _Settings:
    return _Settings(flag=decoder.boolean("flag"))


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
        factories={"restart": TypedTaskFactory(_decode, lambda _settings: _Task())},
        content_revision="content:current",
        client_ui_revision="ui:current",
    )


def _snapshot(
    revision: str,
    *,
    assembly_revision: str = _ASSEMBLY_REVISION,
    flag: object = True,
    enabled: bool = True,
    due_at: datetime = _DUE,
) -> RuntimeConfigurationSnapshot:
    return RuntimeConfigurationSnapshot(
        payload=cast("JsonValue", {"schema_version": 1, "tasks": {"restart": {"flag": flag}}}),
        schedules=(ScheduleMutation("restart", enabled, due_at, 0),),
        source_revision=_source_revision(revision),
        assembly_revision=assembly_revision,
        device_serial=_SERIAL,
    )


class _Clock:
    @staticmethod
    def now() -> datetime:
        return _NOW


class _Signal:
    def __init__(self) -> None:
        self.requested = False

    def set(self) -> None:
        self.requested = True

    def wait(self, timeout: float) -> bool:
        del timeout
        return self.requested

    def clear(self) -> None:
        self.requested = False


class _Source:
    def __init__(self, current: RuntimeConfigurationSnapshot) -> None:
        self.current = current
        self.loads = 0

    def load(self) -> RuntimeConfigurationSnapshot:
        self.loads += 1
        return self.current


def _control(
    path: Path,
    source: _Source,
    signal: _Signal | ConfigurationFileSignal,
    initial: RuntimeConfigurationSnapshot,
    errors: list[Exception],
) -> RuntimeConfigurationControl:
    return RuntimeConfigurationControl(
        state_path=path,
        factories=_registry(),
        clock=_Clock(),
        source=source,
        signal=signal,
        initial=initial,
        error_reporter=errors.append,
    )


def test_initial_publish_failure_closes_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed_stores: list[SQLiteStateStore] = []
    original_close = SQLiteStateStore.close

    def record_close(store: SQLiteStateStore) -> None:
        closed_stores.append(store)
        original_close(store)

    monkeypatch.setattr(SQLiteStateStore, "close", record_close)

    with pytest.raises(SettingsDocumentError, match="must be a boolean"):
        _control(
            tmp_path / "state.sqlite3",
            _Source(_snapshot("source:next")),
            _Signal(),
            _snapshot("source:invalid", flag=1),
            [],
        )

    assert len(closed_stores) == 1


def test_control_rejects_an_untyped_initial_snapshot_before_opening_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"

    with pytest.raises(TypeError, match="initial must be a RuntimeConfigurationSnapshot"):
        RuntimeConfigurationControl(
            state_path=state_path,
            factories=_registry(),
            clock=_Clock(),
            source=_Source(_snapshot("source:next")),
            signal=_Signal(),
            initial=cast("RuntimeConfigurationSnapshot", object()),
            error_reporter=lambda _error: None,
        )

    assert not state_path.exists()


def test_unrelated_source_update_preserves_runtime_schedule(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"
    initial = _snapshot("source:1")
    source = _Source(_snapshot("source:2", flag=False))
    signal = _Signal()
    errors: list[Exception] = []
    control = _control(state_path, source, signal, initial, errors)
    runtime_due = _DUE + timedelta(hours=4)
    try:
        with SQLiteStateStore(state_path) as store:
            store.upsert_schedule(
                ScheduleMutation(task_id="restart", enabled=False, due_at=runtime_due, priority=0),
                updated_at=_NOW + timedelta(minutes=1),
            )
        signal.set()

        assert control.refresh_if_changed()

        with SQLiteStateStore(state_path) as store:
            settings = store.read_settings()
            schedule = store.get_schedule("restart")
            source_snapshot = store.read_configuration_source()
        assert settings is not None
        assert settings.revision == 2
        assert settings.payload == source.current.payload
        assert schedule is not None
        assert not schedule.enabled
        assert schedule.due_at == runtime_due
        assert source_snapshot is not None
        assert source_snapshot.source_schedules == initial.schedules
        assert errors == []
    finally:
        control.close()


def test_only_changed_source_schedule_fields_override_runtime_values(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"
    initial = _snapshot("source:1")
    changed_due = _DUE + timedelta(minutes=20)
    source = _Source(_snapshot("source:2", enabled=False, due_at=changed_due))
    signal = _Signal()
    control = _control(state_path, source, signal, initial, [])
    try:
        with SQLiteStateStore(state_path) as store:
            store.upsert_schedule(
                ScheduleMutation(
                    task_id="restart",
                    enabled=True,
                    due_at=_DUE + timedelta(hours=5),
                    priority=0,
                ),
                updated_at=_NOW + timedelta(minutes=1),
            )
        signal.set()

        assert control.refresh_if_changed()

        with SQLiteStateStore(state_path) as store:
            schedule = store.get_schedule("restart")
        assert schedule is not None
        assert not schedule.enabled
        assert schedule.due_at == changed_due
    finally:
        control.close()


def test_invalid_candidate_is_reported_once_and_keeps_last_known_good(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"
    initial = _snapshot("source:1")
    source = _Source(_snapshot("source:invalid", flag=1))
    signal = _Signal()
    errors: list[Exception] = []
    control = _control(state_path, source, signal, initial, errors)
    try:
        signal.set()
        assert not control.refresh_if_changed()
        assert not control.refresh_if_changed()

        with SQLiteStateStore(state_path) as store:
            settings = store.read_settings()
            source_snapshot = store.read_configuration_source()
        assert settings is not None
        assert settings.revision == 1
        assert settings.payload == initial.payload
        assert source_snapshot is not None
        assert source_snapshot.source_revision == initial.source_revision
        assert source.loads == 1
        assert len(errors) == 1
        assert "boolean" in str(errors[0])
    finally:
        control.close()


def test_assembly_bound_change_requires_restart_and_keeps_last_known_good(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"
    initial = _snapshot("source:1")
    source = _Source(
        _snapshot(
            "source:2",
            assembly_revision="sha256:" + "b" * 64,
            flag=False,
        )
    )
    signal = _Signal()
    errors: list[Exception] = []
    control = _control(state_path, source, signal, initial, errors)
    try:
        signal.set()

        assert not control.refresh_if_changed()
        assert not control.refresh_if_changed()

        with SQLiteStateStore(state_path) as store:
            settings = store.read_settings()
            source_snapshot = store.read_configuration_source()
        assert settings is not None
        assert settings.revision == 1
        assert settings.payload == initial.payload
        assert source_snapshot is not None
        assert source_snapshot.source_revision == initial.source_revision
        assert source.loads == 1
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeRestartRequiredError)
        assert "restart" in str(errors[0])
    finally:
        control.close()


def test_refresh_retries_instead_of_splicing_old_source_baseline_with_new_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "state.sqlite3"
    initial = _snapshot("source:initial")
    candidate = _snapshot("source:candidate", flag=False)
    competing_due = _DUE + timedelta(hours=2)
    competing = _snapshot("source:competing", enabled=False, due_at=competing_due)
    source = _Source(candidate)
    signal = _Signal()
    errors: list[Exception] = []
    control = _control(state_path, source, signal, initial, errors)
    original_read = control._store.read_configuration_source  # noqa: SLF001
    interleaved = False

    def read_with_competing_publish() -> ConfigurationSourceSnapshot | None:
        nonlocal interleaved
        snapshot = original_read()
        if not interleaved:
            interleaved = True
            with SQLiteStateStore(state_path) as writer:
                writer.publish_configuration_update(
                    ConfigurationUpdate(
                        publication=ConfigurationPublication(
                            payload=competing.payload,
                            schedules=competing.schedules,
                            source_revision=competing.source_revision,
                            expected_revision=1,
                            updated_at=_NOW + timedelta(minutes=1),
                        ),
                    )
                )
        return snapshot

    monkeypatch.setattr(control._store, "read_configuration_source", read_with_competing_publish)  # noqa: SLF001
    try:
        signal.set()

        assert control.refresh_if_changed()

        with SQLiteStateStore(state_path) as store:
            settings = store.read_settings()
            schedule = store.get_schedule("restart")
            source_snapshot = store.read_configuration_source()
        assert interleaved
        assert errors == []
        assert settings is not None
        assert settings.revision == 3
        assert settings.payload == candidate.payload
        assert schedule is not None
        assert schedule.enabled is candidate.schedules[0].enabled
        assert schedule.due_at == candidate.schedules[0].due_at
        assert source_snapshot is not None
        assert source_snapshot.source_revision == candidate.source_revision
        assert source_snapshot.source_schedules == candidate.schedules
    finally:
        control.close()


def test_change_between_signal_creation_and_initial_publish_is_not_lost(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"
    config_path = tmp_path / "alas.json"
    config_path.write_text("old", encoding="utf-8")
    signal = ConfigurationFileSignal((config_path,))
    initial = _snapshot("source:1")
    latest = _snapshot("source:2", flag=False)
    source = _Source(latest)
    config_path.write_text("new content", encoding="utf-8")
    control = _control(state_path, source, signal, initial, [])
    try:
        assert control.refresh_if_changed()

        with SQLiteStateStore(state_path) as store:
            settings = store.read_settings()
        assert settings is not None
        assert settings.payload == latest.payload
    finally:
        control.close()
