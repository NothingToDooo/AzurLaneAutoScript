from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Self

from module.application import AbortToken, ExecutionMode, PreemptionRequest, RunCoordinator, TaskId, TaskResult
from module.application.scheduler import Scheduler
from module.runtime.configuration_control import RuntimeConfigurationControl
from module.runtime.configuration_publisher import ConfigurationPublisher
from module.runtime.factories import TaskFactoryRegistry
from module.runtime.outbox import OutboxDelivery, OutboxDispatcher, OutboxDispatchResult, OutboxFailureFact
from module.runtime.resolver import CatalogTaskResolver
from module.state import SQLiteRunRepository, SQLiteScheduleSource, SQLiteStateStore
from module.supervisor import DeviceLeaseRegistry, InstanceAgent, InstanceLoop, InstanceLoopExit, LoopClock

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.state import ConfigurationSourceSnapshot, JsonValue, ScheduleMutation, SettingsSnapshot


def _identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = f"{field_name} must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class InstanceRuntimeConfig:
    state_path: Path
    lease_lock_root: Path
    device_serial: str
    lease_owner: str
    hoard_window: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if not isinstance(self.state_path, Path):
            message = "state_path must be a Path"
            raise TypeError(message)
        if not isinstance(self.lease_lock_root, Path):
            message = "lease_lock_root must be a Path"
            raise TypeError(message)
        _identifier(self.device_serial, field_name="device_serial")
        _identifier(self.lease_owner, field_name="lease_owner")
        if not isinstance(self.hoard_window, timedelta):
            message = "hoard_window must be a timedelta"
            raise TypeError(message)
        if self.hoard_window < timedelta(0):
            message = "hoard_window must not be negative"
            raise ValueError(message)


class InstanceRuntime:
    """一个实例的 composition root；统一拥有 state、scheduler、lease、agent 与 loop。"""

    __slots__ = (
        "_agent",
        "_closed",
        "_configuration_control",
        "_configuration_publisher",
        "_loop",
        "_store",
        "recovered_run_ids",
    )

    def __init__(
        self,
        config: InstanceRuntimeConfig,
        factories: TaskFactoryRegistry,
        clock: LoopClock,
        *,
        outbox: OutboxDelivery | None = None,
        configuration_control: RuntimeConfigurationControl | None = None,
    ) -> None:
        if not isinstance(config, InstanceRuntimeConfig):
            message = "config must be an InstanceRuntimeConfig"
            raise TypeError(message)
        if not isinstance(factories, TaskFactoryRegistry):
            message = "factories must be a TaskFactoryRegistry"
            raise TypeError(message)
        if configuration_control is not None and not isinstance(configuration_control, RuntimeConfigurationControl):
            message = "configuration_control must be a RuntimeConfigurationControl or None"
            raise TypeError(message)
        if outbox is not None and not isinstance(outbox, OutboxDelivery):
            message = "outbox must be an OutboxDelivery or None"
            raise TypeError(message)
        if (
            isinstance(clock, type)
            or not callable(getattr(clock, "now", None))
            or not callable(getattr(clock, "sleep", None))
        ):
            message = "clock must implement now() and sleep()"
            raise TypeError(message)

        store = SQLiteStateStore(config.state_path)
        try:
            priorities = {
                task_id: definition.priority
                for task_id, definition in factories.catalog.items()
                if definition.priority is not None
            }
            repository = SQLiteRunRepository(store, priorities, clock)
            self.recovered_run_ids = repository.recover_interrupted_runs(
                "instance process exited before the run reached a terminal state"
            )
            coordinator = RunCoordinator(repository)
            scheduler = Scheduler(SQLiteScheduleSource(store), hoard_window=config.hoard_window)
            resolver = CatalogTaskResolver(snapshot_source=store, factories=factories)
            leases = DeviceLeaseRegistry(config.lease_lock_root)
            outbox_dispatcher = (
                None
                if outbox is None
                else OutboxDispatcher(
                    store=store,
                    publisher=outbox.publisher,
                    clock=clock,
                    retry_policy=outbox.retry_policy,
                )
            )
            run_completion_hook = _outbox_completion_hook(
                outbox_dispatcher,
                None if outbox is None else outbox.failure_reporter,
            )
            if outbox is not None and run_completion_hook is not None:
                _drain_startup_outbox(
                    run_completion_hook,
                    max_batches=outbox.retry_policy.startup_max_batches,
                )
            self._agent = InstanceAgent(
                scheduler=scheduler,
                coordinator=coordinator,
                device_leases=leases,
                task_resolver=resolver,
                device_serial=config.device_serial,
                lease_owner=config.lease_owner,
                run_completion_hook=run_completion_hook,
            )
            self._loop = InstanceLoop(self._agent, clock, control=configuration_control)
            self._configuration_publisher = ConfigurationPublisher(
                store=store,
                factories=factories,
                clock=clock,
            )
        except BaseException:
            store.close()
            raise
        self._store = store
        self._configuration_control = configuration_control
        self._closed = False

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        if self._configuration_control is not None:
            self._configuration_control.close()
        self._store.close()
        self._closed = True

    def publish_configuration(
        self,
        payload: JsonValue,
        schedules: tuple[ScheduleMutation, ...],
        *,
        source_revision: str,
        expected_revision: int,
    ) -> SettingsSnapshot:
        self._require_open()
        return self._configuration_publisher.publish(
            payload,
            schedules,
            source_revision=source_revision,
            expected_revision=expected_revision,
        )

    def read_settings(self) -> SettingsSnapshot | None:
        self._require_open()
        return self._store.read_settings()

    def read_configuration_source(self) -> ConfigurationSourceSnapshot | None:
        self._require_open()
        return self._store.read_configuration_source()

    def run(
        self,
        *,
        abort: AbortToken | None = None,
        preemption: PreemptionRequest | None = None,
    ) -> InstanceLoopExit:
        self._require_open()
        return self._loop.run(abort=abort, preemption=preemption)

    def execute(
        self,
        task_id: TaskId,
        mode: ExecutionMode,
        *,
        abort: AbortToken | None = None,
        preemption: PreemptionRequest | None = None,
    ) -> TaskResult:
        self._require_open()
        return self._agent.execute(task_id, mode, abort=abort, preemption=preemption)

    def _require_open(self) -> None:
        if self._closed:
            message = "instance runtime is closed"
            raise RuntimeError(message)


def _outbox_completion_hook(
    dispatcher: OutboxDispatcher | None,
    failure_reporter: Callable[[OutboxFailureFact], object] | None,
) -> Callable[[], OutboxDispatchResult] | None:
    if dispatcher is None:
        return None
    if failure_reporter is None:
        return dispatcher.dispatch_pending

    def dispatch_and_report() -> OutboxDispatchResult:
        result = dispatcher.dispatch_pending()
        for failure in result.failures:
            failure_reporter(failure)
        return result

    return dispatch_and_report


def _drain_startup_outbox(
    dispatch: Callable[[], OutboxDispatchResult],
    *,
    max_batches: int,
) -> None:
    for _ in range(max_batches):
        result = dispatch()
        if result.published_count == 0 and result.failure_count == 0:
            return
