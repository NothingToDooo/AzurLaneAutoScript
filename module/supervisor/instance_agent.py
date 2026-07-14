from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, Protocol

from module.application.coordinator import StaleRunMetadataError
from module.application.identifiers import TaskId
from module.application.metadata import RunMetadata
from module.application.scheduler import ScheduleItem, SchedulePlanner, Scheduler, SchedulerDecision
from module.application.task import ExecutionMode, Task, TaskResult

if TYPE_CHECKING:
    from module.application.cancellation import AbortToken, PreemptionRequest
    from module.application.coordinator import RunCoordinator
    from module.supervisor.device_lease import DeviceLease


@dataclass(frozen=True, slots=True)
class TaskResolution:
    """同一个 settings/content/UI snapshot 解析出的任务及运行 provenance。"""

    task: Task
    metadata: RunMetadata
    schedules: tuple[ScheduleItem, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.task, type) or not callable(getattr(self.task, "run", None)):
            message = "task must implement Task.run()"
            raise TypeError(message)
        if not isinstance(self.metadata, RunMetadata):
            message = "metadata must be RunMetadata"
            raise TypeError(message)
        if not isinstance(self.schedules, tuple):
            message = "schedules must be a tuple"
            raise TypeError(message)
        if any(not isinstance(item, ScheduleItem) for item in self.schedules):
            message = "schedules must contain ScheduleItem values"
            raise TypeError(message)
        task_ids = tuple(item.task_id for item in self.schedules)
        if len(task_ids) != len(set(task_ids)):
            message = "schedules must not contain duplicate task ids"
            raise ValueError(message)


class TaskResolver(Protocol):
    def resolve(self, task_id: TaskId, mode: ExecutionMode) -> TaskResolution: ...


class DeviceLeaseManager(Protocol):
    def acquire(self, serial: str, owner: str) -> DeviceLease: ...

    def release(self, lease: DeviceLease) -> None: ...


@dataclass(frozen=True, slots=True)
class ReadyTickResult:
    item: ScheduleItem
    result: TaskResult

    decision: ClassVar[SchedulerDecision] = SchedulerDecision.READY

    def __post_init__(self) -> None:
        if not isinstance(self.item, ScheduleItem):
            message = "item must be a ScheduleItem"
            raise TypeError(message)
        if not self.item.enabled:
            message = "item must be enabled"
            raise ValueError(message)
        if not isinstance(self.result, TaskResult):
            message = "result must be a TaskResult"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class WaitingTickResult:
    item: ScheduleItem
    wake_at: datetime

    decision: ClassVar[SchedulerDecision] = SchedulerDecision.WAITING

    def __post_init__(self) -> None:
        if not isinstance(self.item, ScheduleItem):
            message = "item must be a ScheduleItem"
            raise TypeError(message)
        if not self.item.enabled:
            message = "item must be enabled"
            raise ValueError(message)
        _validate_aware_datetime(self.wake_at, field_name="wake_at")
        due_at = self.item.due_at
        if due_at is None or self.wake_at < due_at:
            message = "wake_at must not precede item due_at"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class EmptyTickResult:
    decision: ClassVar[SchedulerDecision] = SchedulerDecision.EMPTY


type InstanceTickResult = ReadyTickResult | WaitingTickResult | EmptyTickResult
type RunCompletionHook = Callable[[], object]

_MAX_RESOLUTION_ATTEMPTS = 8


class StaleScheduleSelectionError(RuntimeError):
    """任务解析 snapshot 中的 ready task 已不同于 scheduler 先前选择。"""


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def _validate_dependency_method(value: object, *, method: str, dependency: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method, None)):
        message = f"{dependency} must implement {method}()"
        raise TypeError(message)


class InstanceAgent:
    __slots__ = (
        "_coordinator",
        "_device_leases",
        "_device_serial",
        "_lease_owner",
        "_run_completion_hook",
        "_scheduler",
        "_task_resolver",
    )

    def __init__(  # noqa: PLR0913
        self,
        *,
        scheduler: Scheduler,
        coordinator: RunCoordinator,
        device_leases: DeviceLeaseManager,
        task_resolver: TaskResolver,
        device_serial: str,
        lease_owner: str,
        run_completion_hook: RunCompletionHook | None = None,
    ) -> None:
        _validate_dependency_method(scheduler, method="next", dependency="scheduler")
        _validate_dependency_method(coordinator, method="execute", dependency="coordinator")
        _validate_dependency_method(device_leases, method="acquire", dependency="device_leases")
        _validate_dependency_method(device_leases, method="release", dependency="device_leases")
        _validate_dependency_method(task_resolver, method="resolve", dependency="task_resolver")
        if run_completion_hook is not None and not callable(run_completion_hook):
            message = "run_completion_hook must be callable or None"
            raise TypeError(message)
        _validate_identifier(device_serial, field_name="device_serial")
        _validate_identifier(lease_owner, field_name="lease_owner")

        self._scheduler = scheduler
        self._coordinator = coordinator
        self._device_leases = device_leases
        self._task_resolver = task_resolver
        self._device_serial = device_serial
        self._lease_owner = lease_owner
        self._run_completion_hook = run_completion_hook

    def tick(
        self,
        now: datetime,
        *,
        abort: AbortToken | None = None,
        preemption: PreemptionRequest | None = None,
    ) -> InstanceTickResult:
        _validate_aware_datetime(now, field_name="now")
        for _attempt in range(_MAX_RESOLUTION_ATTEMPTS):
            selection = self._scheduler.next(now)

            if selection.decision is SchedulerDecision.EMPTY:
                return EmptyTickResult()

            item = selection.item
            if item is None:
                message = f"{selection.decision.value} selection must contain an item"
                raise RuntimeError(message)

            if selection.decision is SchedulerDecision.WAITING:
                wake_at = selection.wake_at
                if wake_at is None:
                    message = "waiting selection must contain wake_at"
                    raise RuntimeError(message)
                return WaitingTickResult(item=item, wake_at=wake_at)

            try:
                result = self._execute(
                    item.task_id,
                    ExecutionMode.SCHEDULED_JOB,
                    scheduled_at=now,
                    abort=abort,
                    preemption=preemption,
                )
            except StaleScheduleSelectionError:
                continue
            return ReadyTickResult(item=item, result=result)

        message = "schedule changed during every task resolution attempt"
        raise StaleScheduleSelectionError(message)

    def execute(
        self,
        task_id: TaskId,
        mode: ExecutionMode,
        *,
        abort: AbortToken | None = None,
        preemption: PreemptionRequest | None = None,
    ) -> TaskResult:
        """执行 scheduled、assist 或 direct task，并统一持有设备 lease。"""
        if not isinstance(task_id, TaskId):
            message = "task_id must be a TaskId"
            raise TypeError(message)
        if not isinstance(mode, ExecutionMode):
            message = "mode must be an ExecutionMode"
            raise TypeError(message)
        if mode is ExecutionMode.SCHEDULED_JOB:
            message = "scheduled jobs must be selected through tick()"
            raise ValueError(message)
        return self._execute(
            task_id,
            mode,
            scheduled_at=None,
            abort=abort,
            preemption=preemption,
        )

    def _execute(
        self,
        task_id: TaskId,
        mode: ExecutionMode,
        *,
        scheduled_at: datetime | None,
        abort: AbortToken | None,
        preemption: PreemptionRequest | None,
    ) -> TaskResult:

        lease = self._device_leases.acquire(self._device_serial, self._lease_owner)
        try:
            for attempt in range(_MAX_RESOLUTION_ATTEMPTS):
                resolution = self._task_resolver.resolve(task_id, mode)
                if not isinstance(resolution, TaskResolution):
                    message = "TaskResolver.resolve() must return a TaskResolution"
                    raise TypeError(message)
                if mode is ExecutionMode.SCHEDULED_JOB:
                    if scheduled_at is None:
                        message = "scheduled execution requires scheduled_at"
                        raise RuntimeError(message)
                    self._validate_scheduled_resolution(task_id, scheduled_at, resolution)
                try:
                    result = self._coordinator.execute(
                        task_id,
                        mode,
                        resolution.metadata,
                        resolution.task,
                        abort=abort,
                        preemption=preemption,
                    )
                except StaleRunMetadataError:
                    if attempt + 1 == _MAX_RESOLUTION_ATTEMPTS:
                        raise
                    continue
                if not isinstance(result, TaskResult):
                    message = "RunCoordinator.execute() must return a TaskResult"
                    raise TypeError(message)
                break
        finally:
            self._device_leases.release(lease)

        if self._run_completion_hook is not None:
            self._run_completion_hook()
        return result

    @staticmethod
    def _validate_scheduled_resolution(
        task_id: TaskId,
        scheduled_at: datetime,
        resolution: TaskResolution,
    ) -> None:
        selection = SchedulePlanner.select(
            resolution.schedules,
            now=scheduled_at,
            hoard_window=timedelta(0),
        )
        if (
            selection.decision is not SchedulerDecision.READY
            or selection.item is None
            or selection.item.task_id != task_id
        ):
            message = f"resolved schedule no longer selects task {task_id.value!r}"
            raise StaleScheduleSelectionError(message)


def _validate_identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = f"{field_name} must not be empty or contain whitespace"
        raise ValueError(message)
