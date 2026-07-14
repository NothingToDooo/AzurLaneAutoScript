from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from uuid import UUID

import pytest

from module.application import (
    Blocked,
    Cancelled,
    Deferred,
    DeleteTaskState,
    DisableTask,
    ExecutionMode,
    Faulted,
    OperatorNotificationKind,
    OperatorNotificationRequest,
    RequestAppRestart,
    RescheduleSelf,
    RescheduleTask,
    Retryable,
    RunId,
    RunMetadata,
    StaleRunMetadataError,
    Succeeded,
    TaskId,
    TaskResult,
    UpsertTaskState,
    WakePolicy,
    WakeTask,
)
from module.state import (
    InterruptedRunError,
    RunMode,
    RunStateError,
    RunStatus,
    ScheduleMutation,
    SQLiteRunRepository,
    SQLiteStateStore,
    new_uuid7_run_id,
)

if TYPE_CHECKING:
    from pathlib import Path

    from module.application import RunOutcome
    from module.state import JsonValue

_STARTED_AT = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)
_FINISHED_AT = _STARTED_AT + timedelta(minutes=5)
_OLD_SCHEDULE_AT = _STARTED_AT - timedelta(hours=1)


class _FixedClock:
    def __init__(self, *timestamps: datetime) -> None:
        self.timestamps = timestamps
        self.calls = 0

    def now(self) -> datetime:
        timestamp = self.timestamps[self.calls]
        self.calls += 1
        return timestamp


def _metadata() -> RunMetadata:
    return RunMetadata(
        settings_revision=8,
        content_revision="content-20260713",
        client_ui_revision="cn-ui-v3",
    )


@pytest.mark.parametrize(
    ("execution_mode", "run_mode"),
    [
        (ExecutionMode.SCHEDULED_JOB, RunMode.SCHEDULED_JOB),
        (ExecutionMode.ASSIST_SESSION, RunMode.ASSIST_SESSION),
        (ExecutionMode.DIRECT_COMMAND, RunMode.DIRECT_COMMAND),
    ],
)
def test_begin_run_maps_mode_and_persists_provenance(
    tmp_path: Path,
    execution_mode: ExecutionMode,
    run_mode: RunMode,
) -> None:
    clock = _FixedClock(_STARTED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-fixed"))

        start = repository.begin_run(TaskId("research"), execution_mode, _metadata())

        persisted = store.get_run(start.run_id.value)
        assert start.run_id == RunId("run-fixed")
        assert start.started_at == _STARTED_AT
        assert persisted is not None
        assert persisted.task_id == "research"
        assert persisted.mode is run_mode
        assert persisted.settings_revision == 8
        assert persisted.content_revision == "content-20260713"
        assert persisted.client_ui_revision == "cn-ui-v3"
        assert persisted.started_at == _STARTED_AT
        assert clock.calls == 1


def test_begin_run_translates_a_settings_revision_race(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT)
    metadata = RunMetadata(
        settings_revision=1,
        content_revision="content-1",
        client_ui_revision="ui-1",
    )
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        store.update_settings({"generation": 1}, expected_revision=0, updated_at=_STARTED_AT)
        store.update_settings({"generation": 2}, expected_revision=1, updated_at=_FINISHED_AT)
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-stale"))

        with pytest.raises(StaleRunMetadataError) as raised:
            repository.begin_run(TaskId("research"), ExecutionMode.SCHEDULED_JOB, metadata)

        assert raised.value.expected_revision == 1
        assert raised.value.actual_revision == 2
        assert store.get_run("run-stale") is None


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_payload", "expected_error"),
    [
        (Succeeded(), RunStatus.SUCCEEDED, None, None),
        (Deferred("wait for reset"), RunStatus.DEFERRED, {"reason": "wait for reset"}, None),
        (Retryable("network busy"), RunStatus.RETRYABLE, {"reason": "network busy"}, None),
        (Blocked("missing resource"), RunStatus.BLOCKED, {"reason": "missing resource"}, None),
        (Cancelled("manual stop"), RunStatus.CANCELLED, {"reason": "manual stop"}, None),
        (
            Faulted(ValueError("invalid state")),
            RunStatus.FAULTED,
            {"error_type": "ValueError", "message": "invalid state"},
            "ValueError: invalid state",
        ),
    ],
)
def test_finalize_run_maps_every_outcome_and_emits_finished_fact(
    tmp_path: Path,
    outcome: RunOutcome,
    expected_status: RunStatus,
    expected_payload: JsonValue,
    expected_error: str | None,
) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-outcome"))
        run_id = repository.begin_run(TaskId("daily"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        repository.finalize_run(run_id, TaskResult(outcome=outcome))

        persisted = store.get_run(run_id.value)
        assert persisted is not None
        assert persisted.status is expected_status
        assert persisted.result_payload == expected_payload
        assert persisted.error == expected_error
        assert persisted.finished_at == _FINISHED_AT

        expected_finished_payload = {
            "run_id": "run-outcome",
            "task_id": "daily",
            "status": expected_status.value,
            "result": expected_payload,
        }
        events = store.list_run_events(run_id.value)
        assert len(events) == 1
        assert events[0].kind == "run.finished"
        assert events[0].payload == expected_finished_payload
        assert events[0].occurred_at == _FINISHED_AT

        outbox = store.list_outbox()
        expected_outbox_count = 2 if isinstance(outcome, Faulted) else 1
        assert len(outbox) == expected_outbox_count
        finished_message = next(message for message in outbox if message.topic == "run.finished")
        assert finished_message.message_id == "run-outcome:run.finished"
        assert finished_message.key == "daily"
        assert finished_message.payload == expected_finished_payload
        assert finished_message.created_at == _FINISHED_AT
        assert clock.calls == 2


def test_fault_without_message_still_persists_non_empty_error(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-fault"))
        run_id = repository.begin_run(TaskId("daily"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        repository.finalize_run(run_id, TaskResult(outcome=Faulted(RuntimeError())))

        persisted = store.get_run(run_id.value)
        assert persisted is not None
        assert persisted.error == "RuntimeError"
        assert persisted.result_payload == {"error_type": "RuntimeError", "message": ""}


def test_fault_atomically_enqueues_a_secret_free_operator_notification(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-fault-notify"))
        run_id = repository.begin_run(TaskId("daily"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        repository.finalize_run(run_id, TaskResult(outcome=Faulted(RuntimeError("credential=secret"))))

        notification = next(
            message for message in store.list_outbox() if message.topic == "operator.notification.requested"
        )
        assert notification.message_id == "run-fault-notify:operator.notification.requested:run_faulted"
        assert notification.key == "daily"
        assert notification.payload == {
            "schema_version": 1,
            "kind": "run_faulted",
            "run_id": "run-fault-notify",
            "task_id": "daily",
            "error_type": "RuntimeError",
        }
        assert "secret" not in repr(notification.payload)


def test_task_notification_is_persisted_with_the_run_finalization(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-campaign-notify"))
        run_id = repository.begin_run(TaskId("main"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        repository.finalize_run(
            run_id,
            TaskResult(
                outcome=Succeeded(),
                notifications=(
                    OperatorNotificationRequest(
                        OperatorNotificationKind.CAMPAIGN_RUN_COUNT_LIMIT,
                        resource="campaign_main/12-4",
                    ),
                ),
            ),
        )

        notification = next(
            message for message in store.list_outbox() if message.topic == "operator.notification.requested"
        )
        assert notification.message_id == (
            "run-campaign-notify:operator.notification.requested:campaign_run_count_limit"
        )
        assert notification.payload == {
            "schema_version": 1,
            "kind": "campaign_run_count_limit",
            "run_id": "run-campaign-notify",
            "task_id": "main",
            "resource": "campaign_main/12-4",
        }


def test_finalize_translates_schedule_effects_and_restart_outbox(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    main_due_at = _FINISHED_AT + timedelta(hours=1)
    enabled_due_at = _FINISHED_AT + timedelta(hours=2)
    disabled_preserved_due_at = _FINISHED_AT + timedelta(hours=2, minutes=30)
    forced_due_at = _FINISHED_AT + timedelta(hours=3)
    new_due_at = _FINISHED_AT + timedelta(hours=4)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        store.upsert_schedule(
            ScheduleMutation(task_id="main", enabled=False, due_at=_OLD_SCHEDULE_AT, priority=90),
            updated_at=_OLD_SCHEDULE_AT,
        )
        store.upsert_schedule(
            ScheduleMutation(task_id="wake-enabled", enabled=True, due_at=_OLD_SCHEDULE_AT, priority=80),
            updated_at=_OLD_SCHEDULE_AT,
        )
        store.upsert_schedule(
            ScheduleMutation(task_id="force-disabled", enabled=False, due_at=_OLD_SCHEDULE_AT, priority=70),
            updated_at=_OLD_SCHEDULE_AT,
        )
        store.upsert_schedule(
            ScheduleMutation(task_id="preserve-disabled", enabled=False, due_at=_OLD_SCHEDULE_AT, priority=65),
            updated_at=_OLD_SCHEDULE_AT,
        )
        store.upsert_schedule(
            ScheduleMutation(task_id="disable-existing", enabled=True, due_at=_OLD_SCHEDULE_AT, priority=60),
            updated_at=_OLD_SCHEDULE_AT,
        )
        repository = SQLiteRunRepository(
            store,
            {"new-force": 50, "new-disable": 40},
            clock,
            lambda: RunId("run-effects"),
        )
        run_id = repository.begin_run(TaskId("main"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id
        result = TaskResult(
            outcome=Succeeded(),
            effects=(
                RescheduleSelf(main_due_at),
                WakeTask(TaskId("wake-enabled"), enabled_due_at, WakePolicy.RESPECT_DISABLED),
                RescheduleTask(TaskId("preserve-disabled"), disabled_preserved_due_at),
                WakeTask(TaskId("force-disabled"), forced_due_at, WakePolicy.FORCE_ENABLE),
                WakeTask(TaskId("new-force"), new_due_at, WakePolicy.FORCE_ENABLE),
                DisableTask(TaskId("disable-existing")),
                DisableTask(TaskId("new-disable")),
                RequestAppRestart("recover emulator"),
            ),
        )

        repository.finalize_run(run_id, result)

        main = store.get_schedule("main")
        wake_enabled = store.get_schedule("wake-enabled")
        force_disabled = store.get_schedule("force-disabled")
        preserve_disabled = store.get_schedule("preserve-disabled")
        new_force = store.get_schedule("new-force")
        disable_existing = store.get_schedule("disable-existing")
        new_disable = store.get_schedule("new-disable")
        assert main is not None
        assert (main.enabled, main.due_at, main.priority) == (False, main_due_at, 90)
        assert wake_enabled is not None
        assert (wake_enabled.enabled, wake_enabled.due_at, wake_enabled.priority) == (True, enabled_due_at, 80)
        assert force_disabled is not None
        assert (force_disabled.enabled, force_disabled.due_at, force_disabled.priority) == (True, forced_due_at, 70)
        assert preserve_disabled is not None
        assert (preserve_disabled.enabled, preserve_disabled.due_at, preserve_disabled.priority) == (
            False,
            disabled_preserved_due_at,
            65,
        )
        assert new_force is not None
        assert (new_force.enabled, new_force.due_at, new_force.priority) == (True, new_due_at, 50)
        assert disable_existing is not None
        assert (disable_existing.enabled, disable_existing.due_at, disable_existing.priority) == (
            False,
            _OLD_SCHEDULE_AT,
            60,
        )
        assert new_disable is not None
        assert (new_disable.enabled, new_disable.due_at, new_disable.priority) == (False, None, 40)
        assert all(record.updated_at == _FINISHED_AT for record in store.list_schedules())

        outbox = store.list_outbox()
        assert tuple(message.topic for message in outbox) == ("run.finished", "app.restart.requested")
        restart = next(message for message in outbox if message.topic == "app.restart.requested")
        assert restart.message_id == "run-effects:app.restart.requested"
        assert restart.payload == {"run_id": "run-effects", "reason": "recover emulator"}
        assert restart.created_at == _FINISHED_AT
        assert clock.calls == 2


def test_finalize_atomically_translates_crash_progress_upsert_and_event_reset_delete(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        store.put_task_state(
            "event.lifecycle",
            "reset",
            version=1,
            payload={"pending": True},
            updated_at=_STARTED_AT,
        )
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-checkpoint"))
        run_id = repository.begin_run(TaskId("raid"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        repository.finalize_run(
            run_id,
            TaskResult(
                outcome=Succeeded(),
                state_effects=(
                    UpsertTaskState(
                        namespace="encounter.progress",
                        key="raid",
                        schema_version=3,
                        payload={"runs_completed": 2, "stages": ["easy", "normal"]},
                    ),
                    DeleteTaskState(namespace="event.lifecycle", key="reset"),
                ),
            ),
        )

        checkpoint = store.get_task_state("encounter.progress", "raid")
        assert checkpoint is not None
        assert checkpoint.version == 3
        assert checkpoint.payload == {"runs_completed": 2, "stages": ["easy", "normal"]}
        assert checkpoint.updated_at == _FINISHED_AT
        assert store.get_task_state("event.lifecycle", "reset") is None


def test_respect_disabled_skips_disabled_and_missing_schedules(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        disabled = store.upsert_schedule(
            ScheduleMutation(task_id="disabled", enabled=False, due_at=_OLD_SCHEDULE_AT, priority=17),
            updated_at=_OLD_SCHEDULE_AT,
        )
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-respect-disabled"))
        run_id = repository.begin_run(TaskId("main"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        repository.finalize_run(
            run_id,
            TaskResult(
                outcome=Succeeded(),
                effects=(
                    WakeTask(TaskId("disabled"), _FINISHED_AT, WakePolicy.RESPECT_DISABLED),
                    WakeTask(TaskId("missing"), _FINISHED_AT, WakePolicy.RESPECT_DISABLED),
                ),
            ),
        )

        assert store.get_schedule("disabled") == disabled
        assert store.get_schedule("missing") is None
        persisted = store.get_run(run_id.value)
        assert persisted is not None
        assert persisted.status is RunStatus.SUCCEEDED


def test_unknown_schedule_priority_leaves_run_unfinalized(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-missing-priority"))
        run_id = repository.begin_run(TaskId("main"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        with pytest.raises(KeyError, match="missing schedule priority for task: unknown"):
            repository.finalize_run(
                run_id,
                TaskResult(
                    outcome=Succeeded(),
                    effects=(WakeTask(TaskId("unknown"), _FINISHED_AT, WakePolicy.FORCE_ENABLE),),
                ),
            )

        persisted = store.get_run(run_id.value)
        assert persisted is not None
        assert persisted.status is RunStatus.RUNNING
        assert store.get_schedule("unknown") is None
        assert store.list_run_events(run_id.value) == ()
        assert store.list_outbox() == ()
        assert clock.calls == 1


def test_reschedule_task_requires_an_existing_schedule_and_is_atomic(tmp_path: Path) -> None:
    clock = _FixedClock(_STARTED_AT, _FINISHED_AT)
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, clock, lambda: RunId("run-missing-schedule"))
        run_id = repository.begin_run(TaskId("main"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        with pytest.raises(RunStateError, match="missing schedule: missing"):
            repository.finalize_run(
                run_id,
                TaskResult(
                    outcome=Succeeded(),
                    effects=(RescheduleTask(TaskId("missing"), _FINISHED_AT),),
                ),
            )

        persisted = store.get_run(run_id.value)
        assert persisted is not None
        assert persisted.status is RunStatus.RUNNING
        assert store.list_run_events(run_id.value) == ()
        assert store.list_outbox() == ()


def test_recover_interrupted_runs_finalizes_every_running_run_with_audit_facts(tmp_path: Path) -> None:
    clock = _FixedClock(
        _STARTED_AT,
        _STARTED_AT + timedelta(seconds=1),
        _FINISHED_AT,
        _FINISHED_AT,
    )
    run_ids = iter((RunId("run-stale-1"), RunId("run-stale-2")))
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, clock, lambda: next(run_ids))
        first = repository.begin_run(TaskId("main"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id
        second = repository.begin_run(TaskId("daily"), ExecutionMode.SCHEDULED_JOB, _metadata()).run_id

        recovered = repository.recover_interrupted_runs("previous agent exited unexpectedly")

        assert recovered == (first, second)
        assert all(run.status is RunStatus.FAULTED for run in store.list_runs())
        assert all(run.error == "InterruptedRunError: previous agent exited unexpectedly" for run in store.list_runs())
        assert tuple(event.kind for run_id in recovered for event in store.list_run_events(run_id.value)) == (
            "run.finished",
            "run.finished",
        )
        outbox = store.list_outbox()
        assert tuple(message.topic for message in outbox).count("run.finished") == 2
        assert tuple(message.topic for message in outbox).count("operator.notification.requested") == 2
        assert {message.key for message in outbox} == {"main", "daily"}


def test_recover_interrupted_runs_rejects_an_empty_reason(tmp_path: Path) -> None:
    with SQLiteStateStore(tmp_path / "instance.sqlite3") as store:
        repository = SQLiteRunRepository(store, {}, _FixedClock(_STARTED_AT), lambda: RunId("unused"))
        with pytest.raises(ValueError, match="reason must not be empty"):
            repository.recover_interrupted_runs(" ")

    assert issubclass(InterruptedRunError, RuntimeError)


def test_priority_contract_rejects_negative_and_none_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="priority must not be negative"):
        ScheduleMutation(task_id="negative", enabled=True, due_at=None, priority=-1)

    with (
        SQLiteStateStore(tmp_path / "instance.sqlite3") as store,
        pytest.raises(TypeError, match="schedule priority must be an integer"),
    ):
        SQLiteRunRepository(
            store,
            {"none": cast("int", None)},
            _FixedClock(_STARTED_AT),
            lambda: RunId("run-invalid-priority"),
        )


def test_default_run_id_factory_creates_uuid7_identifier() -> None:
    run_id = new_uuid7_run_id()

    assert isinstance(run_id, RunId)
    assert UUID(run_id.value).version == 7
