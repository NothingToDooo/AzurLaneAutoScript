from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from module.bootstrap.configuration_compiler import CompiledConfiguration
from module.bootstrap.task_factories import GameTaskDependencies, build_game_task_registry
from module.runtime import InstanceRuntime, InstanceRuntimeConfig, OutboxPublisher
from module.state import RevisionConflictError

if TYPE_CHECKING:
    from module.supervisor import LoopClock


def _require_revision(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


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


class ProductionRuntimeProvider:
    """生产 runtime composition root；每个进程只构建一个实例级依赖图。"""

    __slots__ = ("_clock", "_outbox_publisher", "_source")

    def __init__(
        self,
        source: InstanceAssemblySource,
        clock: LoopClock,
        *,
        outbox_publisher: OutboxPublisher | None = None,
    ) -> None:
        if isinstance(source, type) or not callable(getattr(source, "load", None)):
            message = "source must implement load()"
            raise TypeError(message)
        if isinstance(clock, type) or not all(callable(getattr(clock, method, None)) for method in ("now", "sleep")):
            message = "clock must implement now() and sleep()"
            raise TypeError(message)
        if outbox_publisher is not None and (
            isinstance(outbox_publisher, type) or not callable(getattr(outbox_publisher, "publish", None))
        ):
            message = "outbox_publisher must implement publish()"
            raise TypeError(message)
        self._source = source
        self._clock = clock
        self._outbox_publisher = outbox_publisher

    def open(self, instance_name: str) -> InstanceRuntime:
        assembly = self._source.load(instance_name)
        if not isinstance(assembly, InstanceAssembly):
            message = "InstanceAssemblySource.load() must return an InstanceAssembly"
            raise TypeError(message)
        factories = build_game_task_registry(
            assembly.tasks,
            content_revision=assembly.content_revision,
            client_ui_revision=assembly.client_ui_revision,
        )
        runtime = InstanceRuntime(
            assembly.runtime,
            factories,
            self._clock,
            outbox_publisher=self._outbox_publisher,
        )
        try:
            self._synchronize_configuration(runtime, assembly.configuration)
        except BaseException:
            runtime.close()
            raise
        return runtime

    @staticmethod
    def _synchronize_configuration(runtime: InstanceRuntime, configuration: CompiledConfiguration) -> None:
        current_source = runtime.read_configuration_source()
        if current_source is not None and current_source.source_revision == configuration.source_revision:
            return

        settings = runtime.read_settings()
        expected_revision = 0 if settings is None else settings.revision
        try:
            runtime.publish_configuration(
                configuration.payload,
                configuration.schedules,
                source_revision=configuration.source_revision,
                expected_revision=expected_revision,
            )
        except RevisionConflictError:
            refreshed_source = runtime.read_configuration_source()
            if refreshed_source is None or refreshed_source.source_revision != configuration.source_revision:
                raise
