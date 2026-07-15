from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from module.bootstrap.configuration_compiler import CompiledConfiguration
from module.bootstrap.task_factories import GameTaskDependencies, build_game_task_registry
from module.logger import logger
from module.runtime import (
    ConfigurationChangeSignal,
    InstanceRuntime,
    InstanceRuntimeConfig,
    OutboxDelivery,
    OutboxFailureFact,
    OutboxPublisher,
    RuntimeConfigurationControl,
    RuntimeConfigurationSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.supervisor import LoopClock


def _require_revision(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


def _report_outbox_failure(failure: OutboxFailureFact) -> None:
    """记录 outbox 投递失败事实。"""

    logger.error(
        "Outbox delivery failed "
        f"message_id={failure.message_id!r} topic={failure.topic!r} "
        f"error_type={failure.error_type!r} error_message={failure.error_message!r} "
        f"attempt_count={failure.attempt_count} "
        f"discarded={failure.is_discarded}"
    )


def _require_outbox_publisher(value: object) -> OutboxPublisher:
    if isinstance(value, type) or not callable(getattr(value, "publish", None)):
        message = "outbox_publisher_factory must return an OutboxPublisher"
        raise TypeError(message)
    return cast("OutboxPublisher", value)


@dataclass(frozen=True, slots=True)
class InstanceAssembly:
    runtime: InstanceRuntimeConfig
    tasks: GameTaskDependencies
    configuration: CompiledConfiguration
    content_revision: str
    client_ui_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.runtime, InstanceRuntimeConfig):
            message = "runtime must be an InstanceRuntimeConfig"
            raise TypeError(message)
        if not isinstance(self.tasks, GameTaskDependencies):
            message = "tasks must be GameTaskDependencies"
            raise TypeError(message)
        if not isinstance(self.configuration, CompiledConfiguration):
            message = "configuration must be a CompiledConfiguration"
            raise TypeError(message)
        if self.configuration.device_serial != self.runtime.device_serial:
            message = "compiled configuration device_serial must match runtime device_serial"
            raise ValueError(message)
        _require_revision(self.content_revision, field_name="content_revision")
        _require_revision(self.client_ui_revision, field_name="client_ui_revision")


class InstanceAssemblySource(Protocol):
    def load(self, instance_name: str) -> InstanceAssembly: ...

    def load_configuration(self, instance_name: str) -> CompiledConfiguration: ...

    def configuration_signal(
        self,
        instance_name: str,
        external: ConfigurationChangeSignal | None = None,
    ) -> ConfigurationChangeSignal: ...


class _BoundRuntimeConfigurationSource:
    __slots__ = ("_instance_name", "_source")

    def __init__(self, source: InstanceAssemblySource, instance_name: str) -> None:
        self._source = source
        self._instance_name = instance_name

    def load(self) -> RuntimeConfigurationSnapshot:
        return _runtime_configuration(self._source.load_configuration(self._instance_name))


def _runtime_configuration(configuration: CompiledConfiguration) -> RuntimeConfigurationSnapshot:
    return RuntimeConfigurationSnapshot(
        payload=configuration.payload,
        schedules=configuration.schedules,
        source_revision=configuration.source_revision,
        assembly_revision=configuration.assembly_revision,
        device_serial=configuration.device_serial,
    )


class ProductionRuntimeProvider:
    """生产 runtime composition root；每个进程只构建一个实例级依赖图。"""

    __slots__ = ("_clock", "_outbox_publisher_factory", "_source")

    def __init__(
        self,
        source: InstanceAssemblySource,
        clock: LoopClock,
        *,
        outbox_publisher_factory: Callable[[str], OutboxPublisher],
    ) -> None:
        if isinstance(source, type) or not all(
            callable(getattr(source, method, None)) for method in ("load", "load_configuration", "configuration_signal")
        ):
            message = "source must implement load(), load_configuration(), and configuration_signal()"
            raise TypeError(message)
        if isinstance(clock, type) or not all(callable(getattr(clock, method, None)) for method in ("now", "sleep")):
            message = "clock must implement now() and sleep()"
            raise TypeError(message)
        if not callable(outbox_publisher_factory):
            message = "outbox_publisher_factory must be callable"
            raise TypeError(message)
        self._source = source
        self._clock = clock
        self._outbox_publisher_factory = outbox_publisher_factory

    def open(
        self,
        instance_name: str,
        *,
        configuration_signal: ConfigurationChangeSignal | None = None,
    ) -> InstanceRuntime:
        signal = self._source.configuration_signal(instance_name, configuration_signal)
        assembly = self._source.load(instance_name)
        if not isinstance(assembly, InstanceAssembly):
            message = "InstanceAssemblySource.load() must return an InstanceAssembly"
            raise TypeError(message)
        factories = build_game_task_registry(
            assembly.tasks,
            content_revision=assembly.content_revision,
            client_ui_revision=assembly.client_ui_revision,
        )
        control = RuntimeConfigurationControl(
            state_path=assembly.runtime.state_path,
            factories=factories,
            clock=self._clock,
            source=_BoundRuntimeConfigurationSource(self._source, instance_name),
            signal=signal,
            initial=_runtime_configuration(assembly.configuration),
            error_reporter=logger.exception,
        )
        try:
            outbox_publisher = _require_outbox_publisher(self._outbox_publisher_factory(instance_name))
            return InstanceRuntime(
                assembly.runtime,
                factories,
                self._clock,
                outbox=OutboxDelivery(outbox_publisher, _report_outbox_failure),
                configuration_control=control,
            )
        except BaseException:
            control.close()
            raise
