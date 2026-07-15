import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.state import (
    SCHEMA_VERSION,
    ConfigurationPublication,
    ConfigurationUpdate,
    CorruptStateError,
    DeleteTaskStateMutation,
    JsonValue,
    OutboxClaimRequest,
    OutboxFailureUpdate,
    OutboxManualRetry,
    OutboxMessage,
    OutboxStateError,
    RevisionConflictError,
    RunEvent,
    RunFinalization,
    RunMode,
    RunStartCommand,
    RunStateError,
    RunStatus,
    ScheduleMutation,
    SchemaVersionError,
    SettingsSnapshot,
    SQLiteStateStore,
    UpsertTaskStateMutation,
)

if TYPE_CHECKING:
    from pathlib import Path

_STARTED_AT = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
_FINISHED_AT = _STARTED_AT + timedelta(minutes=5)
_SOURCE_REVISION = "sha256:" + "0" * 64
_WORKER_A = "publisher-a"
_WORKER_B = "publisher-b"
_RECOVERY_WORKER = "publisher-b-recovery"


def _run_start(  # noqa: PLR0913 - 测试工厂显式暴露 run provenance 的独立契约轴。
    run_id: str,
    task_id: str,
    *,
    mode: RunMode = RunMode.SCHEDULED_JOB,
    settings_revision: int = 1,
    content_revision: str = "content-1",
    client_ui_revision: str = "client-ui-1",
    started_at: datetime = _STARTED_AT,
) -> RunStartCommand:
    return RunStartCommand(
        run_id=run_id,
        task_id=task_id,
        mode=mode,
        settings_revision=settings_revision,
        content_revision=content_revision,
        client_ui_revision=client_ui_revision,
        started_at=started_at,
    )


def _publication(
    payload: JsonValue,
    schedules: tuple[ScheduleMutation, ...] = (),
    *,
    source_revision: str = _SOURCE_REVISION,
    expected_revision: int = 0,
    updated_at: datetime = _STARTED_AT,
) -> ConfigurationPublication:
    return ConfigurationPublication(
        payload=payload,
        schedules=schedules,
        source_revision=source_revision,
        expected_revision=expected_revision,
        updated_at=updated_at,
    )


def _claim_request(
    claim_token: str,
    *,
    claimed_at: datetime = _FINISHED_AT,
    limit: int = 32,
) -> OutboxClaimRequest:
    return OutboxClaimRequest(
        claim_token=claim_token,
        claimed_at=claimed_at,
        claim_until=claimed_at + timedelta(minutes=5),
        limit=limit,
    )


def _seed_outbox(store: SQLiteStateStore, *message_ids: str) -> None:
    store.start_run(_run_start("run-outbox-seed", "outbox-seed"))
    store.finalize_run(
        "run-outbox-seed",
        RunFinalization(
            status=RunStatus.SUCCEEDED,
            finished_at=_FINISHED_AT,
            outbox_messages=tuple(
                OutboxMessage(
                    message_id=message_id,
                    topic="test.outbox",
                    payload={"message_id": message_id},
                )
                for message_id in message_ids
            ),
        ),
    )


def test_run_status_preserves_application_outcomes() -> None:
    assert tuple(status.value for status in RunStatus) == (
        "running",
        "succeeded",
        "deferred",
        "retryable",
        "blocked",
        "cancelled",
        "faulted",
    )


def test_state_store_initializes_wal_and_closed_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"

    with SQLiteStateStore(database_path) as store:
        assert store.journal_mode == "wal"
        assert store.schema_version == SCHEMA_VERSION
        assert store.table_names() == frozenset(
            {"settings", "configuration_source", "schedule", "task_state", "runs", "run_events", "outbox"}
        )

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        run_columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(runs)").fetchall())
        assert run_columns == (
            "run_id",
            "task_id",
            "mode",
            "settings_revision",
            "content_revision",
            "client_ui_revision",
            "status",
            "started_at",
            "finished_at",
            "result_payload",
            "error",
        )


def test_start_run_round_trips_required_provenance(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"

    with SQLiteStateStore(database_path) as store:
        for index, mode in enumerate(RunMode):
            started = store.start_run(
                _run_start(
                    f"run-{index}",
                    "commission",
                    mode=mode,
                    settings_revision=index + 1,
                    content_revision=f"content-{index}",
                    client_ui_revision=f"client-ui-{index}",
                )
            )

            assert started.mode is mode
            assert started.settings_revision == index + 1
            assert started.content_revision == f"content-{index}"
            assert started.client_ui_revision == f"client-ui-{index}"
            assert store.get_run(started.run_id) == started

        assert tuple(run.run_id for run in store.list_runs()) == ("run-0", "run-1", "run-2")
        assert tuple(run.run_id for run in store.list_runs(status=RunStatus.RUNNING)) == (
            "run-0",
            "run-1",
            "run-2",
        )
        with pytest.raises(TypeError, match="status must be a RunStatus"):
            store.list_runs(status=cast("RunStatus", "running"))


def test_start_run_rejects_non_enum_mode(tmp_path: Path) -> None:
    with (
        SQLiteStateStore(tmp_path / "instance.sqlite3") as store,
        pytest.raises(TypeError, match="mode"),
    ):
        store.start_run(_run_start("run-invalid-mode", "commission", mode=cast("RunMode", "scheduled_job")))


@pytest.mark.parametrize("settings_revision", [0, -1])
def test_start_run_rejects_non_positive_settings_revision(tmp_path: Path, settings_revision: int) -> None:
    with (
        SQLiteStateStore(tmp_path / "instance.sqlite3") as store,
        pytest.raises(ValueError, match="settings_revision"),
    ):
        store.start_run(
            _run_start(
                "run-invalid-settings",
                "commission",
                settings_revision=settings_revision,
            )
        )


@pytest.mark.parametrize(
    ("field_name", "revision"),
    [
        ("content_revision", ""),
        ("content_revision", " content-1"),
        ("content_revision", "content-1\n"),
        ("client_ui_revision", "\tclient-ui-1"),
        ("client_ui_revision", "client-ui-1 "),
    ],
)
def test_start_run_rejects_empty_or_untrimmed_text_revision(
    tmp_path: Path,
    field_name: str,
    revision: str,
) -> None:
    content_revision = revision if field_name == "content_revision" else "content-1"
    client_ui_revision = revision if field_name == "client_ui_revision" else "client-ui-1"

    with (
        SQLiteStateStore(tmp_path / "instance.sqlite3") as store,
        pytest.raises(ValueError, match=field_name),
    ):
        store.start_run(
            _run_start(
                "run-invalid-text-revision",
                "commission",
                content_revision=content_revision,
                client_ui_revision=client_ui_revision,
            )
        )


def test_settings_update_detects_stale_revision_across_connections(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"
    first = SQLiteStateStore(database_path)
    second = SQLiteStateStore(database_path)
    try:
        created = first.update_settings(
            {"profile": {"server": "cn", "enabled": True}},
            expected_revision=0,
            updated_at=_STARTED_AT,
        )
        stale_snapshot = second.read_settings()

        updated = first.update_settings(
            {"profile": {"server": "cn", "enabled": False}},
            expected_revision=created.revision,
            updated_at=_FINISHED_AT,
        )
        with pytest.raises(RevisionConflictError) as caught:
            second.update_settings(
                {"profile": {"server": "en", "enabled": True}},
                expected_revision=stale_snapshot.revision if stale_snapshot is not None else 0,
                updated_at=_FINISHED_AT,
            )

        assert created.revision == 1
        assert updated.revision == 2
        assert caught.value.expected_revision == 1
        assert caught.value.actual_revision == 2
        assert second.read_settings() == updated
    finally:
        second.close()
        first.close()


def test_configuration_source_tracks_only_the_settings_revision_published_with_it(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        published = store.publish_configuration(_publication({"generation": 1}))

        source = store.read_configuration_source()
        assert source is not None
        assert source.source_revision == _SOURCE_REVISION
        assert source.settings_revision == published.revision
        assert source.updated_at == _STARTED_AT
        assert source.source_schedules == ()

        store.update_settings(
            {"generation": 2},
            expected_revision=published.revision,
            updated_at=_FINISHED_AT,
        )
        assert store.read_configuration_source() is None


def test_configuration_update_merges_against_the_persisted_source_baseline(tmp_path: Path) -> None:
    initial_due_at = _STARTED_AT + timedelta(hours=1)
    runtime_due_at = _STARTED_AT + timedelta(hours=2)
    changed_source_due_at = _STARTED_AT + timedelta(hours=3)
    initial_schedule = ScheduleMutation(
        task_id="research",
        enabled=True,
        due_at=initial_due_at,
        priority=4,
    )

    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        store.publish_configuration(_publication({"generation": 1}, (initial_schedule,)))
        store.upsert_schedule(
            ScheduleMutation(
                task_id="research",
                enabled=False,
                due_at=runtime_due_at,
                priority=4,
            ),
            updated_at=_STARTED_AT + timedelta(minutes=1),
        )

        store.publish_configuration_update(
            ConfigurationUpdate(
                _publication(
                    {"generation": 2},
                    (
                        ScheduleMutation(
                            task_id="research",
                            enabled=True,
                            due_at=changed_source_due_at,
                            priority=4,
                        ),
                    ),
                    source_revision="sha256:" + "1" * 64,
                    expected_revision=1,
                    updated_at=_FINISHED_AT,
                )
            )
        )

        schedule = store.get_schedule("research")
        source = store.read_configuration_source()

    assert schedule is not None
    assert not schedule.enabled
    assert schedule.due_at == changed_source_due_at
    assert source is not None
    assert source.source_schedules[0].due_at == changed_source_due_at


def test_configuration_update_requires_a_persisted_source_baseline(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        original = store.update_settings(
            {"generation": 1},
            expected_revision=0,
            updated_at=_STARTED_AT,
        )

        with pytest.raises(CorruptStateError, match="persisted source baseline"):
            store.publish_configuration_update(
                ConfigurationUpdate(
                    _publication(
                        {"generation": 2},
                        source_revision="sha256:" + "1" * 64,
                        expected_revision=1,
                        updated_at=_FINISHED_AT,
                    )
                )
            )

        assert store.read_settings() == original


def test_stale_configuration_update_reports_revision_conflict_before_missing_baseline(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        initial = store.publish_configuration(_publication({"generation": 1}))
        current = store.update_settings(
            {"generation": 2},
            expected_revision=initial.revision,
            updated_at=_FINISHED_AT,
        )

        with pytest.raises(RevisionConflictError) as caught:
            store.publish_configuration_update(
                ConfigurationUpdate(
                    _publication(
                        {"generation": 3},
                        source_revision="sha256:" + "2" * 64,
                        expected_revision=initial.revision,
                        updated_at=_FINISHED_AT + timedelta(minutes=1),
                    )
                )
            )

        assert caught.value.actual_revision == current.revision


def test_task_resolution_snapshot_reads_settings_schedules_and_only_the_current_namespace(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        settings = store.update_settings(
            {"generation": 1},
            expected_revision=0,
            updated_at=_STARTED_AT,
        )
        store.put_task_state(
            "research",
            "z-last",
            version=2,
            payload={"steps": [1, 2]},
            updated_at=_FINISHED_AT,
        )
        store.put_task_state(
            "research",
            "a-first",
            version=1,
            payload={"cursor": 3},
            updated_at=_STARTED_AT,
        )
        store.upsert_schedule(
            ScheduleMutation(
                task_id="research",
                enabled=True,
                due_at=_STARTED_AT,
                priority=4,
            ),
            updated_at=_STARTED_AT,
        )
        store.put_task_state(
            "other-task",
            "hidden",
            version=1,
            payload={"visible": False},
            updated_at=_STARTED_AT,
        )

        snapshot = store.read_task_resolution_snapshot("research")

    assert snapshot.task_id == "research"
    assert snapshot.settings == settings
    assert tuple(record.key for record in snapshot.state_records) == ("a-first", "z-last")
    assert snapshot.state_records[0].payload == {"cursor": 3}
    assert snapshot.state_records[1].version == 2
    assert tuple(record.task_id for record in snapshot.schedule_records) == ("research",)
    assert snapshot.schedule_records[0].due_at == _STARTED_AT


def test_task_resolution_snapshot_keeps_one_sqlite_read_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "instance.sqlite3"
    reader = SQLiteStateStore(database_path)
    writer = SQLiteStateStore(database_path)
    try:
        reader.update_settings(
            {"generation": 1},
            expected_revision=0,
            updated_at=_STARTED_AT,
        )
        reader.put_task_state(
            "research",
            "checkpoint",
            version=1,
            payload={"generation": 1},
            updated_at=_STARTED_AT,
        )
        reader.upsert_schedule(
            ScheduleMutation(
                task_id="research",
                enabled=True,
                due_at=_STARTED_AT,
                priority=4,
            ),
            updated_at=_STARTED_AT,
        )

        original = SQLiteStateStore._settings_from_row  # noqa: SLF001
        switched = False

        def publish_new_generation(row: sqlite3.Row) -> SettingsSnapshot:
            nonlocal switched
            if not switched:
                switched = True
                writer.update_settings(
                    {"generation": 2},
                    expected_revision=1,
                    updated_at=_FINISHED_AT,
                )
                writer.put_task_state(
                    "research",
                    "checkpoint",
                    version=2,
                    payload={"generation": 2},
                    updated_at=_FINISHED_AT,
                )
                writer.upsert_schedule(
                    ScheduleMutation(
                        task_id="research",
                        enabled=False,
                        due_at=_FINISHED_AT,
                        priority=4,
                    ),
                    updated_at=_FINISHED_AT,
                )
            return original(row)

        monkeypatch.setattr(SQLiteStateStore, "_settings_from_row", staticmethod(publish_new_generation))

        snapshot = reader.read_task_resolution_snapshot("research")
        fresh = reader.read_task_resolution_snapshot("research")
    finally:
        writer.close()
        reader.close()

    assert snapshot.settings is not None
    assert snapshot.settings.revision == 1
    assert snapshot.settings.payload == {"generation": 1}
    assert snapshot.state_records[0].version == 1
    assert snapshot.state_records[0].payload == {"generation": 1}
    assert snapshot.schedule_records[0].enabled
    assert snapshot.schedule_records[0].due_at == _STARTED_AT
    assert fresh.settings is not None
    assert fresh.settings.revision == 2
    assert fresh.state_records[0].version == 2
    assert not fresh.schedule_records[0].enabled
    assert fresh.schedule_records[0].due_at == _FINISHED_AT


def test_finalize_run_atomically_persists_terminal_facts(tmp_path: Path) -> None:
    due_at = _FINISHED_AT + timedelta(hours=2)
    database_path = tmp_path / "instance.sqlite3"

    with SQLiteStateStore(database_path) as store:
        store.put_task_state(
            "event.lifecycle",
            "reset",
            version=1,
            payload={"pending": True},
            updated_at=_STARTED_AT,
        )
        store.start_run(
            _run_start(
                "run-1",
                "commission",
                settings_revision=7,
                content_revision="content-2026-07-13",
                client_ui_revision="client-ui-v2",
            )
        )
        finalization = RunFinalization(
            status=RunStatus.SUCCEEDED,
            finished_at=_FINISHED_AT,
            result_payload={"claimed": 4},
            schedule_mutations=(ScheduleMutation(task_id="commission", enabled=True, due_at=due_at, priority=30),),
            task_state_mutations=(
                UpsertTaskStateMutation(
                    namespace="encounter.progress",
                    key="commission",
                    schema_version=2,
                    payload={"claimed": 4},
                ),
                DeleteTaskStateMutation(namespace="event.lifecycle", key="reset"),
            ),
            events=(RunEvent(kind="commission.claimed", payload={"count": 4}, occurred_at=_FINISHED_AT),),
            outbox_messages=(
                OutboxMessage(
                    message_id="run-1-finished",
                    topic="run.finished",
                    key="commission",
                    payload={"run_id": "run-1", "status": "succeeded"},
                ),
            ),
        )

        finalized = store.finalize_run("run-1", finalization)

        assert finalized.status is RunStatus.SUCCEEDED
        assert finalized.mode is RunMode.SCHEDULED_JOB
        assert finalized.settings_revision == 7
        assert finalized.content_revision == "content-2026-07-13"
        assert finalized.client_ui_revision == "client-ui-v2"
        assert finalized.finished_at == _FINISHED_AT
        assert finalized.result_payload == {"claimed": 4}
        schedule = store.get_schedule("commission")
        assert schedule is not None
        assert schedule == store.list_schedules()[0]
        assert schedule.due_at == due_at
        checkpoint = store.get_task_state("encounter.progress", "commission")
        assert checkpoint is not None
        assert checkpoint.version == 2
        assert checkpoint.payload == {"claimed": 4}
        assert checkpoint.updated_at == _FINISHED_AT
        assert store.get_task_state("event.lifecycle", "reset") is None
        assert store.list_run_events("run-1")[0].payload == {"count": 4}
        assert store.list_outbox()[0].payload == {"run_id": "run-1", "status": "succeeded"}

        with pytest.raises(RunStateError, match="cannot finalize"):
            store.finalize_run("run-1", finalization)


def test_finalize_does_not_overwrite_newer_configuration_mutations(tmp_path: Path) -> None:
    original_due_at = _STARTED_AT + timedelta(hours=1)
    user_due_at = _FINISHED_AT + timedelta(hours=6)
    stale_due_at = _FINISHED_AT + timedelta(minutes=30)

    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        store.publish_configuration(
            _publication(
                {"generation": 1},
                (
                    ScheduleMutation(
                        task_id="research",
                        enabled=True,
                        due_at=original_due_at,
                        priority=4,
                    ),
                ),
            )
        )
        store.start_run(
            _run_start(
                "run-stale-configuration",
                "research",
                client_ui_revision="ui-1",
            )
        )
        store.publish_configuration(
            _publication(
                {"generation": 2},
                (
                    ScheduleMutation(
                        task_id="research",
                        enabled=False,
                        due_at=user_due_at,
                        priority=4,
                    ),
                ),
                source_revision="sha256:" + "1" * 64,
                expected_revision=1,
                updated_at=_FINISHED_AT,
            )
        )

        finalized = store.finalize_run(
            "run-stale-configuration",
            RunFinalization(
                status=RunStatus.SUCCEEDED,
                finished_at=_FINISHED_AT + timedelta(minutes=1),
                schedule_mutations=(
                    ScheduleMutation(
                        task_id="research",
                        enabled=True,
                        due_at=stale_due_at,
                        priority=4,
                    ),
                ),
                task_state_mutations=(
                    UpsertTaskStateMutation(
                        namespace="research",
                        key="progress",
                        schema_version=1,
                        payload={"step": 3},
                    ),
                ),
            ),
        )

        assert finalized.status is RunStatus.SUCCEEDED
        schedule = store.get_schedule("research")
        assert schedule is not None
        assert (schedule.enabled, schedule.due_at) == (False, user_due_at)
        assert store.get_task_state("research", "progress") is None
        events = store.list_run_events("run-stale-configuration")
        assert tuple(event.kind for event in events) == ("run.mutations.skipped",)
        assert events[0].payload == {
            "run_settings_revision": 1,
            "current_settings_revision": 2,
        }


def test_start_run_rejects_a_stale_settings_revision_before_insert(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        store.update_settings(
            {"generation": 1},
            expected_revision=0,
            updated_at=_STARTED_AT,
        )
        store.update_settings(
            {"generation": 2},
            expected_revision=1,
            updated_at=_FINISHED_AT,
        )

        with pytest.raises(RevisionConflictError) as raised:
            store.start_run(
                _run_start(
                    "run-stale-start",
                    "research",
                    settings_revision=1,
                    client_ui_revision="ui-1",
                    started_at=_FINISHED_AT,
                )
            )

        assert raised.value.expected_revision == 1
        assert raised.value.actual_revision == 2
        assert store.get_run("run-stale-start") is None


def test_mark_outbox_published_strictly_transitions_pending_message(tmp_path: Path) -> None:
    published_at = _FINISHED_AT + timedelta(seconds=30)

    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        store.start_run(_run_start("run-outbox", "commission"))
        store.finalize_run(
            "run-outbox",
            RunFinalization(
                status=RunStatus.SUCCEEDED,
                finished_at=_FINISHED_AT,
                outbox_messages=(
                    OutboxMessage(
                        message_id="run-outbox-finished",
                        topic="run.finished",
                        key="commission",
                        payload={"run_id": "run-outbox"},
                    ),
                ),
            ),
        )

        pending = store.list_outbox(pending_only=True)
        assert len(pending) == 1

        claimed = store.claim_ready_outbox(_claim_request(_WORKER_A))
        assert tuple(record.message_id for record in claimed) == ("run-outbox-finished",)
        published = store.mark_outbox_published(
            "run-outbox-finished",
            published_at,
            claim_token=_WORKER_A,
            expected_attempt_count=0,
        )

        assert published == store.list_outbox()[0]
        assert published.message_id == pending[0].message_id
        assert published.run_id == pending[0].run_id
        assert published.topic == pending[0].topic
        assert published.key == pending[0].key
        assert published.payload == pending[0].payload
        assert published.created_at == pending[0].created_at
        assert published.attempt_count == 1
        assert published.last_attempt_at == published_at
        assert published.claim_token is None
        assert published.claim_until is None
        assert published.published_at == published_at
        assert store.list_outbox(pending_only=True) == ()

        with pytest.raises(OutboxStateError, match="already published"):
            store.mark_outbox_published(
                "run-outbox-finished",
                published_at + timedelta(seconds=1),
                claim_token=_WORKER_A,
                expected_attempt_count=0,
            )
        assert store.list_outbox() == (published,)


def test_mark_outbox_published_rejects_unknown_message(tmp_path: Path) -> None:
    with (
        SQLiteStateStore(tmp_path / "instance.sqlite3") as store,
        pytest.raises(OutboxStateError, match="unknown outbox message: missing-message"),
    ):
        store.mark_outbox_published(
            "missing-message",
            _FINISHED_AT,
            claim_token=_WORKER_A,
            expected_attempt_count=0,
        )


def test_mark_outbox_published_validates_inputs(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"
    with SQLiteStateStore(database_path) as store, pytest.raises(ValueError, match="message_id"):
        store.mark_outbox_published(
            " ",
            _FINISHED_AT,
            claim_token=_WORKER_A,
            expected_attempt_count=0,
        )
    with (
        SQLiteStateStore(database_path) as store,
        pytest.raises(
            ValueError,
            match="published_at must be timezone-aware",
        ),
    ):
        store.mark_outbox_published(
            "message-id",
            datetime(2026, 7, 13, 8, 0),
            claim_token=_WORKER_A,
            expected_attempt_count=0,
        )


def test_ready_claim_is_bounded_and_follows_global_sequence(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        _seed_outbox(store, "first", "second", "third")

        first_batch = store.claim_ready_outbox(_claim_request(_WORKER_A, limit=2))
        second_batch = store.claim_ready_outbox(_claim_request(_WORKER_B, limit=2))

        assert tuple(record.message_id for record in first_batch) == ("first", "second")
        assert tuple(record.sequence for record in first_batch) == (1, 2)
        assert tuple(record.message_id for record in second_batch) == ("third",)
        assert tuple(record.sequence for record in second_batch) == (3,)


def test_claim_is_exclusive_across_connections_and_expired_claim_can_be_recovered(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"
    with SQLiteStateStore(database_path) as seed_store:
        _seed_outbox(seed_store, "stable-message-id")

    first_request = _claim_request(_WORKER_A, limit=1)
    with SQLiteStateStore(database_path) as first_store, SQLiteStateStore(database_path) as second_store:
        first_claim = first_store.claim_ready_outbox(first_request)
        blocked_claim = second_store.claim_ready_outbox(_claim_request(_WORKER_B, limit=1))
        recovered_claim = second_store.claim_ready_outbox(
            _claim_request(
                _RECOVERY_WORKER,
                claimed_at=first_request.claim_until,
                limit=1,
            )
        )

        assert tuple(record.message_id for record in first_claim) == ("stable-message-id",)
        assert blocked_claim == ()
        assert tuple(record.message_id for record in recovered_claim) == ("stable-message-id",)
        assert recovered_claim[0].claim_token == _RECOVERY_WORKER

        with pytest.raises(OutboxStateError, match="claim changed"):
            first_store.mark_outbox_published(
                "stable-message-id",
                first_request.claim_until,
                claim_token=_WORKER_A,
                expected_attempt_count=0,
            )

        published = second_store.mark_outbox_published(
            "stable-message-id",
            first_request.claim_until,
            claim_token=_RECOVERY_WORKER,
            expected_attempt_count=0,
        )
        assert published.message_id == "stable-message-id"
        assert published.published_at == first_request.claim_until


def test_dead_letter_is_excluded_from_pending_and_manual_retry_preserves_audit(tmp_path: Path) -> None:
    retry_at = _FINISHED_AT + timedelta(hours=1)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        _seed_outbox(store, "discarded-message")
        claimed = store.claim_ready_outbox(_claim_request(_WORKER_A, limit=1))[0]
        discarded = store.record_outbox_failure(
            OutboxFailureUpdate(
                message_id=claimed.message_id,
                claim_token=_WORKER_A,
                expected_attempt_count=0,
                failed_at=_FINISHED_AT,
                error_type="PermanentPublishError",
                error_message="publisher rejected local payload",
                available_at=None,
            )
        )

        assert discarded.discarded_at == _FINISHED_AT
        assert discarded.attempt_count == 1
        assert store.list_outbox(pending_only=True) == ()

        retried = store.retry_discarded_outbox(OutboxManualRetry(message_id="discarded-message", available_at=retry_at))
        assert retried.discarded_at is None
        assert retried.available_at == retry_at
        assert retried.attempt_count == 1
        assert retried.last_attempt_at == _FINISHED_AT
        assert retried.last_error_type == "PermanentPublishError"
        assert retried.last_error_message == "publisher rejected local payload"
        assert retried.claim_token is None
        assert store.list_outbox(pending_only=True) == (retried,)

        retry_claim = store.claim_ready_outbox(_claim_request(_RECOVERY_WORKER, claimed_at=retry_at, limit=1))[0]
        published = store.mark_outbox_published(
            retry_claim.message_id,
            retry_at,
            claim_token=_RECOVERY_WORKER,
            expected_attempt_count=retry_claim.attempt_count,
        )
        assert published.last_error_type == "PermanentPublishError"
        assert published.last_error_message == "publisher rejected local payload"

        with pytest.raises(OutboxStateError, match="published"):
            store.retry_discarded_outbox(OutboxManualRetry(message_id="discarded-message", available_at=retry_at))


@pytest.mark.parametrize("error_message", ["", " first line\nsecond line "])
def test_outbox_failure_message_round_trips_without_normalization(
    tmp_path: Path,
    error_message: str,
) -> None:
    database_path = tmp_path / "instance.sqlite3"
    with SQLiteStateStore(database_path) as store:
        _seed_outbox(store, "failed-message")
        claimed = store.claim_ready_outbox(_claim_request(_WORKER_A, limit=1))[0]
        store.record_outbox_failure(
            OutboxFailureUpdate(
                message_id=claimed.message_id,
                claim_token=_WORKER_A,
                expected_attempt_count=0,
                failed_at=_FINISHED_AT,
                error_type="RuntimeError",
                error_message=error_message,
                available_at=None,
            )
        )

    with SQLiteStateStore(database_path) as reopened:
        record = reopened.list_outbox()[0]

    assert record.last_error_message == error_message


def _downgrade_outbox_to_v3(database_path: Path) -> None:
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DROP INDEX outbox_ready")
        connection.execute("ALTER TABLE outbox RENAME TO outbox_v4")
        connection.execute(
            """
            CREATE TABLE outbox (
                message_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                topic TEXT NOT NULL,
                message_key TEXT,
                payload TEXT NOT NULL CHECK (json_valid(payload)),
                created_at TEXT NOT NULL,
                published_at TEXT
            ) STRICT
            """
        )
        connection.execute(
            """
            INSERT INTO outbox(message_id, run_id, topic, message_key, payload, created_at, published_at)
            SELECT message_id, run_id, topic, message_key, payload, created_at, NULL
            FROM outbox_v4
            """
        )
        connection.execute(
            "UPDATE outbox SET published_at = ? WHERE message_id = ?",
            (_FINISHED_AT.isoformat(), "m-published"),
        )
        connection.execute("DROP TABLE outbox_v4")
        connection.execute("PRAGMA user_version = 3")
        connection.commit()


def _downgrade_outbox_to_v4(database_path: Path) -> None:
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DROP INDEX outbox_ready")
        connection.execute("ALTER TABLE outbox RENAME TO outbox_v5")
        connection.execute(
            """
            CREATE TABLE outbox (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE,
                run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                topic TEXT NOT NULL,
                message_key TEXT,
                payload TEXT NOT NULL CHECK (json_valid(payload)),
                created_at TEXT NOT NULL,
                available_at TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
                last_attempt_at TEXT,
                last_error_type TEXT CHECK (
                    last_error_type IS NULL
                    OR (length(last_error_type) > 0 AND last_error_type = trim(last_error_type))
                ),
                claim_token TEXT,
                claim_until TEXT,
                published_at TEXT,
                discarded_at TEXT,
                CHECK (published_at IS NULL OR discarded_at IS NULL),
                CHECK ((claim_token IS NULL) = (claim_until IS NULL)),
                CHECK ((published_at IS NULL AND discarded_at IS NULL) OR claim_token IS NULL),
                CHECK (
                    (attempt_count = 0 AND last_attempt_at IS NULL AND last_error_type IS NULL)
                    OR (attempt_count > 0 AND last_attempt_at IS NOT NULL)
                ),
                CHECK (discarded_at IS NULL OR last_error_type IS NOT NULL)
            ) STRICT
            """
        )
        connection.execute(
            """
            INSERT INTO outbox(
                sequence, message_id, run_id, topic, message_key, payload, created_at,
                available_at, attempt_count, last_attempt_at, last_error_type,
                claim_token, claim_until, published_at, discarded_at
            )
            SELECT
                sequence, message_id, run_id, topic, message_key, payload, created_at,
                available_at, attempt_count, last_attempt_at, last_error_type,
                claim_token, claim_until, published_at, discarded_at
            FROM outbox_v5
            """
        )
        connection.execute("DROP TABLE outbox_v5")
        connection.execute(
            """
            CREATE INDEX outbox_ready
            ON outbox(available_at, claim_until, sequence)
            WHERE published_at IS NULL AND discarded_at IS NULL
            """
        )
        connection.execute("PRAGMA user_version = 4")
        connection.commit()


def _open_state_store_concurrently(database_path: Path, *, workers: int = 8) -> tuple[int, ...]:
    barrier = threading.Barrier(workers)

    def open_store() -> int:
        barrier.wait()
        with SQLiteStateStore(database_path) as store:
            return store.schema_version

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return tuple(pool.map(lambda _index: open_store(), range(workers)))


def test_concurrent_openers_initialize_and_reopen_one_state_database(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent-instance.sqlite3"

    assert _open_state_store_concurrently(database_path) == (SCHEMA_VERSION,) * 8
    assert _open_state_store_concurrently(database_path) == (SCHEMA_VERSION,) * 8


def test_schema_v3_migration_assigns_deterministic_sequence_and_initial_retry_state(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"
    with SQLiteStateStore(database_path) as store:
        _seed_outbox(store, "z-last", "a-first", "m-published")

    _downgrade_outbox_to_v3(database_path)

    with SQLiteStateStore(database_path) as migrated:
        records = migrated.list_outbox()

        assert migrated.schema_version == SCHEMA_VERSION
        assert tuple(record.message_id for record in records) == ("a-first", "m-published", "z-last")
        assert tuple(record.sequence for record in records) == (1, 2, 3)
        assert all(record.available_at == record.created_at for record in records)
        assert all(record.attempt_count == 0 for record in records)
        assert all(record.last_attempt_at is None for record in records)
        assert all(record.last_error_type is None for record in records)
        assert all(record.last_error_message is None for record in records)
        assert records[1].published_at == _FINISHED_AT
        assert tuple(record.message_id for record in migrated.list_outbox(pending_only=True)) == (
            "a-first",
            "z-last",
        )


def test_schema_v4_migration_preserves_failure_audit_with_explicit_legacy_message(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"
    with SQLiteStateStore(database_path) as store:
        _seed_outbox(store, "failed-message")
        claimed = store.claim_ready_outbox(_claim_request(_WORKER_A, limit=1))[0]
        store.record_outbox_failure(
            OutboxFailureUpdate(
                message_id=claimed.message_id,
                claim_token=_WORKER_A,
                expected_attempt_count=0,
                failed_at=_FINISHED_AT,
                error_type="RuntimeError",
                error_message="original message is not representable in v4",
                available_at=None,
            )
        )

    _downgrade_outbox_to_v4(database_path)

    with SQLiteStateStore(database_path) as migrated:
        version = migrated.schema_version
        record = migrated.list_outbox()[0]

    assert version == SCHEMA_VERSION
    assert record.attempt_count == 1
    assert record.last_error_type == "RuntimeError"
    assert record.last_error_message == "(error message unavailable in schema v4)"
    assert record.discarded_at == _FINISHED_AT


def test_schema_v3_migration_rolls_back_before_version_bump_when_another_table_is_invalid(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"
    with SQLiteStateStore(database_path):
        pass
    _downgrade_outbox_to_v3(database_path)

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("ALTER TABLE settings ADD COLUMN unexpected TEXT")
        connection.commit()

    with pytest.raises(SchemaVersionError, match="schema columns mismatch for settings"):
        SQLiteStateStore(database_path)

    with closing(sqlite3.connect(database_path)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        outbox_columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(outbox)"))
        tables = frozenset(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        )

    assert version == (3,)
    assert outbox_columns == (
        "message_id",
        "run_id",
        "topic",
        "message_key",
        "payload",
        "created_at",
        "published_at",
    )
    assert "outbox_v3" not in tables


def test_finalize_run_rolls_back_all_writes_when_outbox_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "instance.sqlite3"
    duplicate_message = OutboxMessage(
        message_id="shared-message-id",
        topic="run.finished",
        payload={"source": "seed"},
    )

    with SQLiteStateStore(database_path) as store:
        preserved_checkpoint = store.put_task_state(
            "event.lifecycle",
            "reset",
            version=1,
            payload={"pending": True},
            updated_at=_STARTED_AT,
        )
        store.start_run(
            _run_start(
                "seed-run",
                "seed-task",
                mode=RunMode.ASSIST_SESSION,
                content_revision="content-seed",
                client_ui_revision="client-ui-seed",
            )
        )
        store.finalize_run(
            "seed-run",
            RunFinalization(
                status=RunStatus.SUCCEEDED,
                finished_at=_FINISHED_AT,
                outbox_messages=(duplicate_message,),
            ),
        )
        store.start_run(
            _run_start(
                "rollback-run",
                "rollback-task",
                mode=RunMode.DIRECT_COMMAND,
                settings_revision=2,
                content_revision="content-rollback",
                client_ui_revision="client-ui-rollback",
            )
        )

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            store.finalize_run(
                "rollback-run",
                RunFinalization(
                    status=RunStatus.FAULTED,
                    finished_at=_FINISHED_AT,
                    error="worker crashed",
                    schedule_mutations=(
                        ScheduleMutation(
                            task_id="rollback-task",
                            enabled=True,
                            due_at=_FINISHED_AT + timedelta(minutes=10),
                            priority=10,
                        ),
                    ),
                    task_state_mutations=(
                        UpsertTaskStateMutation(
                            namespace="encounter.progress",
                            key="rollback-task",
                            schema_version=1,
                            payload={"runs": 3},
                        ),
                        DeleteTaskStateMutation(namespace="event.lifecycle", key="reset"),
                    ),
                    events=(RunEvent(kind="worker.crashed", payload={"exit_code": 1}, occurred_at=_FINISHED_AT),),
                    outbox_messages=(
                        OutboxMessage(
                            message_id="shared-message-id",
                            topic="run.finished",
                            payload={"source": "rollback"},
                        ),
                    ),
                ),
            )

        rolled_back_run = store.get_run("rollback-run")
        assert rolled_back_run is not None
        assert rolled_back_run.status is RunStatus.RUNNING
        assert rolled_back_run.finished_at is None
        assert rolled_back_run.result_payload is None
        assert store.get_schedule("rollback-task") is None
        assert store.get_task_state("encounter.progress", "rollback-task") is None
        assert store.get_task_state("event.lifecycle", "reset") == preserved_checkpoint
        assert store.list_run_events("rollback-run") == ()
        assert tuple(record.run_id for record in store.list_outbox()) == ("seed-run",)
