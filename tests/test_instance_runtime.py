from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, override

import pytest

from module.application import (
    DisableTask,
    ExecutionMode,
    RescheduleSelf,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.runtime import (
    InstanceRuntime,
    InstanceRuntimeConfig,
    OutboxDelivery,
    OutboxFailureFact,
    OutboxRetryPolicy,
    TaskBuildContext,
    TaskFactoryRegistry,
)
from module.state import (
    OutboxMessage,
    RunFinalization,
    RunMode,
    RunStartCommand,
    RunStatus,
    ScheduleMutation,
    SQLiteStateStore,
)
from module.supervisor import DeviceLeaseRegistry, InstanceLoopExitReason
from module.task_registry import LaunchSurface, TaskDefinition, TaskDomain

if TYPE_CHECKING:
    from pathlib import Path

    from module.interaction import CancellationSignal
    from module.state import JsonValue
    from module.supervisor import LoopWakeSignal

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)
_SOURCE_REVISION = "sha256:" + "0" * 64


class _Task(Task):
    @override
    def run(self, context: TaskContext) -> TaskResult:
        return TaskResult(Succeeded(), (DisableTask(context.task_id),))


class _Factory:
    @staticmethod
    def build(context: TaskBuildContext) -> Task:
        assert context.settings == MappingProxyType({})
        return _Task()


class _FixedTaskFactory:
    def __init__(self, task: Task) -> None:
        self._task = task

    def build(self, context: TaskBuildContext) -> Task:
        assert context.settings == MappingProxyType({})
        return self._task


class _SequencedTask(Task):
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._runs = 0

    @override
    def run(self, context: TaskContext) -> TaskResult:
        self._runs += 1
        self._events.append(f"run:{self._runs}")
        if self._runs == 1:
            return TaskResult(Succeeded(), (RescheduleSelf(context.started_at),))
        return TaskResult(Succeeded(), (DisableTask(context.task_id),))


class _DirectTask(Task):
    @override
    def run(self, context: TaskContext) -> TaskResult:
        del context
        return TaskResult(Succeeded())


class _Publisher:
    def __init__(
        self,
        *,
        lock_root: Path,
        device_serial: str,
        events: list[str] | None = None,
        failures_remaining: int = 0,
    ) -> None:
        self._leases = DeviceLeaseRegistry(lock_root)
        self._device_serial = device_serial
        self._events = events
        self._failures_remaining = failures_remaining
        self.message_ids: list[str] = []

    def publish(
        self,
        *,
        topic: str,
        payload: JsonValue,
        key: str | None,
        idempotency_key: str,
    ) -> None:
        del payload, key
        assert self._leases.holder(self._device_serial) is None
        self.message_ids.append(idempotency_key)
        if self._events is not None:
            self._events.append(f"publish:{topic}")
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            message = "broker unavailable"
            raise RuntimeError(message)


class _Clock:
    def __init__(self, now: datetime = _NOW) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, duration: timedelta) -> None:
        self.current += duration

    @staticmethod
    def sleep(
        seconds: float,
        cancellation: CancellationSignal,
        wake_signal: LoopWakeSignal | None = None,
    ) -> None:
        del seconds, wake_signal
        cancellation.raise_if_requested()


def _registry(
    factory: _Factory | _FixedTaskFactory | None = None,
    *,
    execution_mode: ExecutionMode = ExecutionMode.SCHEDULED_JOB,
    priority: int | None = 4,
    allowed_launches: frozenset[LaunchSurface] = frozenset({LaunchSurface.SCHEDULER}),
) -> TaskFactoryRegistry:
    definition = TaskDefinition(
        command="research",
        config_scopes=(),
        priority=priority,
        domain=TaskDomain.FACILITY,
        execution_mode=execution_mode,
        allowed_launches=allowed_launches,
    )
    return TaskFactoryRegistry(
        catalog={"research": definition},
        factories={"research": _Factory() if factory is None else factory},
        content_revision="content:1",
        client_ui_revision="ui:1",
    )


def _config(tmp_path: Path) -> InstanceRuntimeConfig:
    return InstanceRuntimeConfig(
        state_path=tmp_path / "state.sqlite3",
        lease_lock_root=tmp_path / "device-locks",
        device_serial="127.0.0.1:16384",
        lease_owner="instance-a",
    )


def _seed_pending_outbox(config: InstanceRuntimeConfig, *message_ids: str) -> None:
    with SQLiteStateStore(config.state_path) as store:
        store.start_run(
            RunStartCommand(
                run_id="run-startup-backlog",
                task_id="research",
                mode=RunMode.DIRECT_COMMAND,
                settings_revision=1,
                content_revision="content:old",
                client_ui_revision="ui:old",
                started_at=_NOW,
            )
        )
        store.finalize_run(
            "run-startup-backlog",
            RunFinalization(
                status=RunStatus.SUCCEEDED,
                finished_at=_NOW,
                outbox_messages=tuple(
                    OutboxMessage(
                        message_id=message_id,
                        topic="test.startup",
                        payload={"message_id": message_id},
                    )
                    for message_id in message_ids
                ),
            ),
        )


def test_instance_runtime_composes_state_scheduler_resolver_lease_and_loop(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with InstanceRuntime(config, _registry(), _Clock()) as runtime:
        published = runtime.publish_configuration(
            {"schema_version": 1, "tasks": {"research": {}}},
            (
                ScheduleMutation(
                    task_id="research",
                    enabled=True,
                    due_at=_NOW,
                    priority=4,
                ),
            ),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )
        result = runtime.run()

    assert published.revision == 1
    assert result.reason is InstanceLoopExitReason.EMPTY
    assert result.runs_completed == 1
    with SQLiteStateStore(config.state_path) as store:
        schedule = store.get_schedule("research")
        runs = store.list_runs()
        pending_outbox = store.list_outbox(pending_only=True)
    assert schedule is not None
    assert not schedule.enabled
    assert len(runs) == 1
    assert runs[0].status is RunStatus.SUCCEEDED
    assert len(pending_outbox) == 1


def test_scheduled_runtime_dispatches_each_run_after_releasing_device_lease(tmp_path: Path) -> None:
    config = _config(tmp_path)
    events: list[str] = []
    publisher = _Publisher(
        lock_root=config.lease_lock_root,
        device_serial=config.device_serial,
        events=events,
    )
    task = _SequencedTask(events)

    with InstanceRuntime(
        config,
        _registry(_FixedTaskFactory(task)),
        _Clock(),
        outbox=OutboxDelivery(publisher),
    ) as runtime:
        runtime.publish_configuration(
            {"schema_version": 1, "tasks": {"research": {}}},
            (ScheduleMutation(task_id="research", enabled=True, due_at=_NOW, priority=4),),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )

        result = runtime.run()

    assert result.reason is InstanceLoopExitReason.EMPTY
    assert result.runs_completed == 2
    assert events == [
        "run:1",
        "publish:run.finished",
        "run:2",
        "publish:run.finished",
    ]
    assert len(publisher.message_ids) == 2
    with SQLiteStateStore(config.state_path) as store:
        assert store.list_outbox(pending_only=True) == ()
        assert all(record.published_at is not None for record in store.list_outbox())


def test_direct_execute_persists_publish_failure_without_replacing_task_result(tmp_path: Path) -> None:
    config = _config(tmp_path)
    publisher = _Publisher(
        lock_root=config.lease_lock_root,
        device_serial=config.device_serial,
        failures_remaining=1,
    )
    registry = _registry(
        _FixedTaskFactory(_DirectTask()),
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        allowed_launches=frozenset({LaunchSurface.TOOL}),
    )

    with InstanceRuntime(config, registry, _Clock(), outbox=OutboxDelivery(publisher)) as runtime:
        runtime.publish_configuration(
            {"schema_version": 1, "tasks": {"research": {}}},
            (),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )
        result = runtime.execute(TaskId("research"), ExecutionMode.DIRECT_COMMAND)

    assert isinstance(result.outcome, Succeeded)
    assert len(publisher.message_ids) == 1
    with SQLiteStateStore(config.state_path) as store:
        runs = store.list_runs()
        pending = store.list_outbox(pending_only=True)
    assert len(runs) == 1
    assert runs[0].status is RunStatus.SUCCEEDED
    assert len(pending) == 1
    assert pending[0].message_id == publisher.message_ids[0]
    assert pending[0].attempt_count == 1
    assert pending[0].last_attempt_at == _NOW
    assert pending[0].last_error_type == "RuntimeError"
    assert pending[0].available_at == _NOW + timedelta(minutes=1)
    assert pending[0].published_at is None


def test_delivery_failure_can_be_reported_without_replacing_the_task_result(tmp_path: Path) -> None:
    config = _config(tmp_path)
    publisher = _Publisher(
        lock_root=config.lease_lock_root,
        device_serial=config.device_serial,
        failures_remaining=1,
    )
    failures: list[OutboxFailureFact] = []
    registry = _registry(
        _FixedTaskFactory(_DirectTask()),
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        allowed_launches=frozenset({LaunchSurface.TOOL}),
    )

    with InstanceRuntime(
        config,
        registry,
        _Clock(),
        outbox=OutboxDelivery(publisher, failures.append),
    ) as runtime:
        runtime.publish_configuration(
            {"schema_version": 1, "tasks": {"research": {}}},
            (),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )
        result = runtime.execute(TaskId("research"), ExecutionMode.DIRECT_COMMAND)

    assert isinstance(result.outcome, Succeeded)
    assert len(failures) == 1
    assert failures[0].message_id == publisher.message_ids[0]
    assert failures[0].topic == "run.finished"
    assert failures[0].error_type == "RuntimeError"
    assert failures[0].attempt_count == 1
    assert not failures[0].is_discarded
    with SQLiteStateStore(config.state_path) as store:
        assert len(store.list_outbox(pending_only=True)) == 1


def test_due_outbox_message_is_retried_after_a_later_run_with_stable_idempotency_key(tmp_path: Path) -> None:
    config = _config(tmp_path)
    clock = _Clock()
    publisher = _Publisher(
        lock_root=config.lease_lock_root,
        device_serial=config.device_serial,
        failures_remaining=1,
    )
    failures: list[OutboxFailureFact] = []
    registry = _registry(
        _FixedTaskFactory(_DirectTask()),
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        allowed_launches=frozenset({LaunchSurface.TOOL}),
    )
    policy = OutboxRetryPolicy(
        batch_size=8,
        max_attempts=3,
        initial_delay=timedelta(minutes=1),
        maximum_delay=timedelta(minutes=5),
    )

    with InstanceRuntime(
        config,
        registry,
        clock,
        outbox=OutboxDelivery(
            publisher,
            failure_reporter=failures.append,
            retry_policy=policy,
        ),
    ) as runtime:
        runtime.publish_configuration(
            {"schema_version": 1, "tasks": {"research": {}}},
            (),
            source_revision=_SOURCE_REVISION,
            expected_revision=0,
        )
        first_result = runtime.execute(TaskId("research"), ExecutionMode.DIRECT_COMMAND)
        clock.advance(timedelta(minutes=1))
        second_result = runtime.execute(TaskId("research"), ExecutionMode.DIRECT_COMMAND)

    assert isinstance(first_result.outcome, Succeeded)
    assert isinstance(second_result.outcome, Succeeded)
    assert len(failures) == 1
    assert len(publisher.message_ids) == 3
    assert publisher.message_ids[0] == publisher.message_ids[1]
    assert publisher.message_ids[2] != publisher.message_ids[0]
    with SQLiteStateStore(config.state_path) as store:
        records = store.list_outbox()
        assert store.list_outbox(pending_only=True) == ()
    assert tuple(record.attempt_count for record in records) == (2, 1)
    assert all(record.published_at == clock.current for record in records)


def test_startup_drains_more_than_one_bounded_outbox_batch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    message_ids = tuple(f"startup-{index}" for index in range(5))
    _seed_pending_outbox(config, *message_ids)
    publisher = _Publisher(
        lock_root=config.lease_lock_root,
        device_serial=config.device_serial,
    )
    policy = OutboxRetryPolicy(batch_size=2, startup_max_batches=4)

    with InstanceRuntime(
        config,
        _registry(),
        _Clock(),
        outbox=OutboxDelivery(publisher, retry_policy=policy),
    ):
        pass

    assert tuple(publisher.message_ids) == message_ids
    with SQLiteStateStore(config.state_path) as store:
        assert store.list_outbox(pending_only=True) == ()


def test_startup_outbox_drain_stops_at_the_aggregate_batch_cap(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_pending_outbox(config, "startup-0", "startup-1", "startup-2")
    publisher = _Publisher(
        lock_root=config.lease_lock_root,
        device_serial=config.device_serial,
    )
    policy = OutboxRetryPolicy(batch_size=1, startup_max_batches=2)

    with InstanceRuntime(
        config,
        _registry(),
        _Clock(),
        outbox=OutboxDelivery(publisher, retry_policy=policy),
    ):
        pass

    assert publisher.message_ids == ["startup-0", "startup-1"]
    with SQLiteStateStore(config.state_path) as store:
        pending = store.list_outbox(pending_only=True)
    assert tuple(record.message_id for record in pending) == ("startup-2",)


def test_instance_runtime_recovers_interrupted_runs_on_startup(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with SQLiteStateStore(config.state_path) as store:
        store.start_run(
            RunStartCommand(
                run_id="run-interrupted",
                task_id="research",
                mode=RunMode.SCHEDULED_JOB,
                settings_revision=1,
                content_revision="content:old",
                client_ui_revision="ui:old",
                started_at=_NOW,
            )
        )

    with InstanceRuntime(config, _registry(), _Clock()) as runtime:
        assert tuple(str(run_id) for run_id in runtime.recovered_run_ids) == ("run-interrupted",)

    with SQLiteStateStore(config.state_path) as store:
        run = store.get_run("run-interrupted")
    assert run is not None
    assert run.status is RunStatus.FAULTED
    assert run.error is not None
    assert "InterruptedRunError" in run.error


def test_instance_runtime_dispatches_recovered_run_facts_on_startup(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with SQLiteStateStore(config.state_path) as store:
        store.start_run(
            RunStartCommand(
                run_id="run-interrupted",
                task_id="research",
                mode=RunMode.SCHEDULED_JOB,
                settings_revision=1,
                content_revision="content:old",
                client_ui_revision="ui:old",
                started_at=_NOW,
            )
        )
    publisher = _Publisher(
        lock_root=config.lease_lock_root,
        device_serial=config.device_serial,
    )

    with InstanceRuntime(config, _registry(), _Clock(), outbox=OutboxDelivery(publisher)):
        pass

    assert len(publisher.message_ids) == 2
    assert any("operator.notification.requested:run_faulted" in message_id for message_id in publisher.message_ids)
    with SQLiteStateStore(config.state_path) as store:
        assert store.list_outbox(pending_only=True) == ()


def test_closed_instance_runtime_rejects_work(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runtime = InstanceRuntime(config, _registry(), _Clock())
    runtime.close()

    with pytest.raises(RuntimeError, match="closed"):
        runtime.run()
