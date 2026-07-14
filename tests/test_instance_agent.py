from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import cast

import pytest

from module.application import (
    AbortToken,
    ExecutionMode,
    Faulted,
    PreemptionRequest,
    RescheduleSelf,
    RunCoordinator,
    RunId,
    RunMetadata,
    RunStart,
    StaleRunMetadataError,
    Succeeded,
    Task,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.application.scheduler import ScheduleItem, Scheduler, SchedulerDecision
from module.supervisor.device_lease import (
    DeviceLease,
    DeviceLeaseConflictError,
    InvalidDeviceLeaseError,
)
from module.supervisor.instance_agent import (
    EmptyTickResult,
    InstanceAgent,
    ReadyTickResult,
    StaleScheduleSelectionError,
    TaskResolution,
    TaskResolver,
    WaitingTickResult,
)

_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)
_TASK_ID = TaskId("commission")
_SERIAL = "127.0.0.1:16384"
_OWNER = "instance-account-a"
_METADATA = RunMetadata(settings_revision=7, content_revision="content-v3", client_ui_revision="ui-v2")


class _ScheduleSource:
    def __init__(self, items: tuple[ScheduleItem, ...]) -> None:
        self.items = items
        self.calls = 0

    def list_items(self) -> tuple[ScheduleItem, ...]:
        self.calls += 1
        return self.items


class _RecordingRepository:
    def __init__(
        self,
        events: list[str],
        *,
        begin_error: Exception | None = None,
        begin_errors: list[Exception] | None = None,
        finalize_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.begin_error = begin_error
        self.begin_errors = [] if begin_errors is None else begin_errors
        self.finalize_error = finalize_error
        self.begin_calls: list[tuple[TaskId, ExecutionMode, RunMetadata]] = []
        self.finalize_calls: list[tuple[RunId, TaskResult]] = []

    def begin_run(self, task_id: TaskId, mode: ExecutionMode, metadata: RunMetadata) -> RunStart:
        self.events.append("begin")
        self.begin_calls.append((task_id, mode, metadata))
        if self.begin_errors:
            raise self.begin_errors.pop(0)
        if self.begin_error is not None:
            raise self.begin_error
        return RunStart(RunId("run-instance-1"), _NOW)

    def finalize_run(self, run_id: RunId, result: TaskResult) -> None:
        self.events.append("finalize")
        self.finalize_calls.append((run_id, result))
        if self.finalize_error is not None:
            raise self.finalize_error


class _RecordingTask:
    def __init__(
        self,
        result: TaskResult,
        events: list[str],
        *,
        error: BaseException | None = None,
        lease_registry: _InMemoryDeviceLeases | None = None,
    ) -> None:
        self.result = result
        self.events = events
        self.error = error
        self.lease_registry = lease_registry
        self.contexts: list[TaskContext] = []
        self.lease_holders: list[str | None] = []

    def run(self, context: TaskContext) -> TaskResult:
        self.events.append("task")
        self.contexts.append(context)
        if self.lease_registry is not None:
            self.lease_holders.append(self.lease_registry.holder(_SERIAL))
        if self.error is not None:
            raise self.error
        return self.result


class _RecordingResolver:
    def __init__(
        self,
        resolution: TaskResolution | object,
        events: list[str],
        *,
        error: BaseException | None = None,
    ) -> None:
        self.resolution = resolution
        self.events = events
        self.error = error
        self.calls: list[tuple[TaskId, ExecutionMode]] = []

    def resolve(self, task_id: TaskId, mode: ExecutionMode) -> TaskResolution:
        self.events.append("resolve")
        self.calls.append((task_id, mode))
        if self.error is not None:
            raise self.error
        return cast("TaskResolution", self.resolution)


class _InMemoryDeviceLeases:
    def __init__(self) -> None:
        self._sequence = count(1)
        self._leases: dict[str, DeviceLease] = {}

    def acquire(self, serial: str, owner: str) -> DeviceLease:
        current = self._leases.get(serial)
        if current is not None:
            raise DeviceLeaseConflictError(serial=serial, requested_by=owner, held_by=current.owner)
        lease = DeviceLease(serial=serial, owner=owner, token=f"instance-lease-{next(self._sequence)}")
        self._leases[serial] = lease
        return lease

    def release(self, lease: DeviceLease) -> None:
        if self._leases.get(lease.serial) is not lease:
            message = f"device lease is not current: {lease.serial}/{lease.owner}"
            raise InvalidDeviceLeaseError(message)
        del self._leases[lease.serial]

    def holder(self, serial: str) -> str | None:
        lease = self._leases.get(serial)
        return None if lease is None else lease.owner

    def active_leases(self) -> tuple[DeviceLease, ...]:
        return tuple(sorted(self._leases.values(), key=lambda lease: lease.serial))


@dataclass(slots=True)
class _Harness:
    agent: InstanceAgent
    registry: _InMemoryDeviceLeases
    repository: _RecordingRepository
    resolver: _RecordingResolver
    schedule_source: _ScheduleSource


def _registry() -> _InMemoryDeviceLeases:
    return _InMemoryDeviceLeases()


def _ready_item() -> ScheduleItem:
    return ScheduleItem(task_id=_TASK_ID, enabled=True, due_at=_NOW - timedelta(seconds=1), priority=3)


def _harness(  # noqa: PLR0913
    items: tuple[ScheduleItem, ...],
    task: Task,
    events: list[str],
    *,
    registry: _InMemoryDeviceLeases | None = None,
    begin_error: Exception | None = None,
    begin_errors: list[Exception] | None = None,
    finalize_error: Exception | None = None,
    resolution: TaskResolution | object | None = None,
    resolver_error: BaseException | None = None,
) -> _Harness:
    active_registry = _registry() if registry is None else registry
    repository = _RecordingRepository(
        events,
        begin_error=begin_error,
        begin_errors=begin_errors,
        finalize_error=finalize_error,
    )
    active_resolution = TaskResolution(task, _METADATA, (_ready_item(),)) if resolution is None else resolution
    resolver = _RecordingResolver(active_resolution, events, error=resolver_error)
    source = _ScheduleSource(items)
    agent = InstanceAgent(
        scheduler=Scheduler(source, hoard_window=timedelta(seconds=30)),
        coordinator=RunCoordinator(repository),
        device_leases=active_registry,
        task_resolver=resolver,
        device_serial=_SERIAL,
        lease_owner=_OWNER,
    )
    return _Harness(agent, active_registry, repository, resolver, source)


def test_ready_tick_resolves_one_snapshot_and_executes_under_lease() -> None:
    events: list[str] = []
    registry = _registry()
    expected = TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_NOW + timedelta(hours=1)),),
    )
    task = _RecordingTask(expected, events, lease_registry=registry)
    harness = _harness((_ready_item(),), task, events, registry=registry)
    abort = AbortToken()
    preemption = PreemptionRequest()

    tick_result = harness.agent.tick(_NOW, abort=abort, preemption=preemption)

    assert tick_result == ReadyTickResult(item=_ready_item(), result=expected)
    assert tick_result.decision is SchedulerDecision.READY
    assert events == ["resolve", "begin", "task", "finalize"]
    assert harness.resolver.calls == [(_TASK_ID, ExecutionMode.SCHEDULED_JOB)]
    assert harness.repository.begin_calls == [(_TASK_ID, ExecutionMode.SCHEDULED_JOB, _METADATA)]
    assert task.lease_holders == [_OWNER]
    assert task.contexts[0].abort is abort
    assert task.contexts[0].preemption is preemption
    assert registry.holder(_SERIAL) is None


def test_execute_re_resolves_after_a_settings_revision_race() -> None:
    events: list[str] = []
    expected = TaskResult(
        outcome=Succeeded(),
        effects=(RescheduleSelf(_NOW + timedelta(hours=1)),),
    )
    task = _RecordingTask(expected, events)
    harness = _harness(
        (_ready_item(),),
        task,
        events,
        begin_errors=[StaleRunMetadataError(expected_revision=6, actual_revision=7)],
    )

    result = harness.agent.tick(_NOW)

    assert result == ReadyTickResult(item=_ready_item(), result=expected)
    assert events == ["resolve", "begin", "resolve", "begin", "task", "finalize"]
    assert harness.resolver.calls == [
        (_TASK_ID, ExecutionMode.SCHEDULED_JOB),
        (_TASK_ID, ExecutionMode.SCHEDULED_JOB),
    ]
    assert len(harness.repository.begin_calls) == 2
    assert len(task.contexts) == 1
    assert harness.registry.holder(_SERIAL) is None


def test_tick_never_runs_a_task_disabled_in_the_resolution_snapshot() -> None:
    events: list[str] = []
    task = _RecordingTask(TaskResult(Succeeded()), events)
    disabled_resolution = TaskResolution(
        task,
        _METADATA,
        (ScheduleItem(task_id=_TASK_ID, enabled=False, due_at=None, priority=3),),
    )
    harness = _harness(
        (_ready_item(),),
        task,
        events,
        resolution=disabled_resolution,
    )

    with pytest.raises(StaleScheduleSelectionError, match="changed during every"):
        harness.agent.tick(_NOW)

    assert harness.schedule_source.calls == 8
    assert len(harness.resolver.calls) == 8
    assert harness.repository.begin_calls == []
    assert task.contexts == []
    assert harness.registry.holder(_SERIAL) is None


def test_public_execute_rejects_bypassing_scheduled_selection() -> None:
    events: list[str] = []
    harness = _harness((), _RecordingTask(TaskResult(Succeeded()), events), events)

    with pytest.raises(ValueError, match=r"selected through tick\(\)"):
        harness.agent.execute(_TASK_ID, ExecutionMode.SCHEDULED_JOB)

    assert harness.resolver.calls == []
    assert harness.registry.active_leases() == ()


def test_waiting_tick_is_explicit_and_has_no_runtime_side_effects() -> None:
    events: list[str] = []
    due_at = _NOW + timedelta(minutes=5)
    item = ScheduleItem(task_id=_TASK_ID, enabled=True, due_at=due_at, priority=3)
    harness = _harness((item,), _RecordingTask(TaskResult(Succeeded()), events), events)

    result = harness.agent.tick(_NOW)

    assert result == WaitingTickResult(item=item, wake_at=due_at + timedelta(seconds=30))
    assert result.decision is SchedulerDecision.WAITING
    assert events == []
    assert harness.registry.active_leases() == ()


def test_empty_tick_is_explicit_and_has_no_runtime_side_effects() -> None:
    events: list[str] = []
    harness = _harness((), _RecordingTask(TaskResult(Succeeded()), events), events)

    result = harness.agent.tick(_NOW)

    assert result == EmptyTickResult()
    assert result.decision is SchedulerDecision.EMPTY
    assert events == []
    assert harness.registry.active_leases() == ()


def test_tick_rejects_naive_time_before_reading_schedule() -> None:
    events: list[str] = []
    harness = _harness((_ready_item(),), _RecordingTask(TaskResult(Succeeded()), events), events)

    with pytest.raises(ValueError, match="now must be timezone-aware"):
        harness.agent.tick(datetime(2026, 7, 13, 12))

    assert harness.schedule_source.calls == 0
    assert events == []


def test_lease_conflict_prevents_resolution_and_preserves_current_owner() -> None:
    events: list[str] = []
    registry = _registry()
    current = registry.acquire(_SERIAL, "other-instance")
    harness = _harness(
        (_ready_item(),),
        _RecordingTask(TaskResult(Succeeded()), events),
        events,
        registry=registry,
    )

    with pytest.raises(DeviceLeaseConflictError, match="already leased"):
        harness.agent.tick(_NOW)

    assert events == []
    assert registry.active_leases() == (current,)


def test_task_exception_is_finalized_as_faulted_then_releases_lease() -> None:
    events: list[str] = []
    error = ValueError("screen recognition failed")
    task = _RecordingTask(TaskResult(Succeeded()), events, error=error)
    harness = _harness((_ready_item(),), task, events)

    tick_result = harness.agent.tick(_NOW)

    assert isinstance(tick_result, ReadyTickResult)
    assert isinstance(tick_result.result.outcome, Faulted)
    assert tick_result.result.outcome.error is error
    assert harness.registry.holder(_SERIAL) is None


@pytest.mark.parametrize(
    ("begin_error", "finalize_error", "expected_events"),
    [
        (OSError("begin write failed"), None, ["resolve", "begin"]),
        (None, OSError("finalize write failed"), ["resolve", "begin", "task", "finalize"]),
    ],
)
def test_repository_failure_propagates_and_releases_lease(
    begin_error: Exception | None,
    finalize_error: Exception | None,
    expected_events: list[str],
) -> None:
    events: list[str] = []
    harness = _harness(
        (_ready_item(),),
        _RecordingTask(TaskResult(Succeeded()), events),
        events,
        begin_error=begin_error,
        finalize_error=finalize_error,
    )

    with pytest.raises(OSError, match="write failed"):
        harness.agent.tick(_NOW)

    assert events == expected_events
    assert harness.registry.holder(_SERIAL) is None


def test_invalid_resolution_and_resolver_error_release_lease() -> None:
    for resolution, resolver_error, message in (
        (object(), None, "TaskResolution"),
        (None, LookupError("unknown task"), "unknown task"),
    ):
        events: list[str] = []
        harness = _harness(
            (_ready_item(),),
            _RecordingTask(TaskResult(Succeeded()), events),
            events,
            resolution=resolution,
            resolver_error=resolver_error,
        )

        with pytest.raises((TypeError, LookupError), match=message):
            harness.agent.tick(_NOW)

        assert harness.repository.begin_calls == []
        assert harness.registry.holder(_SERIAL) is None


def test_base_exception_propagates_but_releases_lease() -> None:
    events: list[str] = []
    task = _RecordingTask(TaskResult(Succeeded()), events, error=KeyboardInterrupt("process stop"))
    harness = _harness((_ready_item(),), task, events)

    with pytest.raises(KeyboardInterrupt, match="process stop"):
        harness.agent.tick(_NOW)

    assert events == ["resolve", "begin", "task"]
    assert harness.registry.holder(_SERIAL) is None


@pytest.mark.parametrize("mode", [ExecutionMode.DIRECT_COMMAND, ExecutionMode.ASSIST_SESSION])
def test_execute_supports_non_scheduled_modes_without_reading_schedule(mode: ExecutionMode) -> None:
    events: list[str] = []
    expected = TaskResult(Succeeded())
    harness = _harness((), _RecordingTask(expected, events), events)

    result = harness.agent.execute(_TASK_ID, mode)

    assert result is expected
    assert harness.schedule_source.calls == 0
    assert harness.resolver.calls == [(_TASK_ID, mode)]
    assert harness.repository.begin_calls == [(_TASK_ID, mode, _METADATA)]
    assert harness.registry.holder(_SERIAL) is None


def test_task_resolution_rejects_incoherent_boundaries() -> None:
    events: list[str] = []
    task = _RecordingTask(TaskResult(Succeeded()), events)

    with pytest.raises(TypeError, match=r"Task\.run"):
        TaskResolution(cast("Task", object()), _METADATA)
    with pytest.raises(TypeError, match="metadata"):
        TaskResolution(task, cast("RunMetadata", object()))


def test_constructor_requires_resolver_and_valid_lease_identity() -> None:
    events: list[str] = []
    repository = _RecordingRepository(events)
    scheduler = Scheduler(_ScheduleSource(()), hoard_window=timedelta(0))
    registry = _registry()

    with pytest.raises(TypeError, match=r"task_resolver must implement resolve\(\)"):
        InstanceAgent(
            scheduler=scheduler,
            coordinator=RunCoordinator(repository),
            device_leases=registry,
            task_resolver=cast("TaskResolver", object()),
            device_serial=_SERIAL,
            lease_owner=_OWNER,
        )

    resolver = _RecordingResolver(TaskResolution(_RecordingTask(TaskResult(Succeeded()), events), _METADATA), events)
    with pytest.raises(ValueError, match="device_serial"):
        InstanceAgent(
            scheduler=scheduler,
            coordinator=RunCoordinator(repository),
            device_leases=registry,
            task_resolver=resolver,
            device_serial=" bad serial ",
            lease_owner=_OWNER,
        )
