import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from module.runtime.configuration_publisher import ConfigurationClock, ConfigurationPublisher
from module.runtime.errors import ConfigurationPublicationConflictError, RuntimeRestartRequiredError
from module.runtime.factories import TaskFactoryRegistry
from module.state import JsonValue, RevisionConflictError, ScheduleMutation, SQLiteStateStore

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class RuntimeConfigurationSnapshot:
    payload: JsonValue
    schedules: tuple[ScheduleMutation, ...]
    source_revision: str
    assembly_revision: str
    device_serial: str

    def __post_init__(self) -> None:
        if not isinstance(self.payload, dict):
            message = "payload must be an object"
            raise TypeError(message)
        if not isinstance(self.schedules, tuple) or any(
            not isinstance(schedule, ScheduleMutation) for schedule in self.schedules
        ):
            message = "schedules must be a tuple of ScheduleMutation values"
            raise TypeError(message)
        for field_name, revision in (
            ("source_revision", self.source_revision),
            ("assembly_revision", self.assembly_revision),
        ):
            if not isinstance(revision, str):
                message = f"{field_name} must be a string"
                raise TypeError(message)
            if re.fullmatch(r"sha256:[0-9a-f]{64}", revision) is None:
                message = f"{field_name} must be a canonical sha256 revision"
                raise ValueError(message)
        if not isinstance(self.device_serial, str) or not self.device_serial.strip():
            message = "device_serial must be a non-empty string"
            raise ValueError(message)


class RuntimeConfigurationSource(Protocol):
    def load(self) -> RuntimeConfigurationSnapshot: ...


class ConfigurationChangeSignal(Protocol):
    def wait(self, timeout: float) -> bool: ...

    def clear(self) -> None: ...


class RuntimeConfigurationControl:
    """在任务安全点刷新编译配置；无效候选不会改变 last-known-good snapshot。"""

    __slots__ = (
        "_assembly_revision",
        "_closed",
        "_device_serial",
        "_error_reporter",
        "_last_error",
        "_publisher",
        "_signal",
        "_source",
        "_store",
    )

    def __init__(  # noqa: PLR0913
        self,
        *,
        state_path: Path,
        factories: TaskFactoryRegistry,
        clock: ConfigurationClock,
        source: RuntimeConfigurationSource,
        signal: ConfigurationChangeSignal,
        initial: RuntimeConfigurationSnapshot,
        error_reporter: Callable[[Exception], object],
    ) -> None:
        if not isinstance(state_path, Path):
            message = "state_path must be a Path"
            raise TypeError(message)
        if not isinstance(factories, TaskFactoryRegistry):
            message = "factories must be a TaskFactoryRegistry"
            raise TypeError(message)
        if isinstance(source, type) or not callable(getattr(source, "load", None)):
            message = "source must implement load()"
            raise TypeError(message)
        if isinstance(signal, type) or not all(callable(getattr(signal, method, None)) for method in ("wait", "clear")):
            message = "signal must implement wait() and clear()"
            raise TypeError(message)
        if not isinstance(initial, RuntimeConfigurationSnapshot):
            message = "initial must be a RuntimeConfigurationSnapshot"
            raise TypeError(message)
        if not callable(error_reporter):
            message = "error_reporter must be callable"
            raise TypeError(message)

        store = SQLiteStateStore(state_path)
        self._store = store
        try:
            self._publisher = ConfigurationPublisher(store=store, factories=factories, clock=clock)
            self._source = source
            self._signal = signal
            self._assembly_revision = initial.assembly_revision
            self._device_serial = initial.device_serial
            self._error_reporter = error_reporter
            self._last_error: Exception | None = None
            self._closed = False
            self._synchronize(initial)
        except BaseException:
            store.close()
            raise

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def wait(self, timeout: float) -> bool:
        if type(timeout) not in {int, float} or timeout < 0:
            message = "timeout must be a non-negative number"
            raise ValueError(message)
        return self._signal.wait(float(timeout))

    def refresh_if_changed(self) -> bool:
        self._require_open()
        if not self._signal.wait(0):
            return False
        self._signal.clear()
        try:
            changed = self._synchronize(self._load_candidate())
        except Exception as error:  # noqa: BLE001
            self._last_error = error
            self._error_reporter(error)
            return False
        self._last_error = None
        return changed

    def _load_candidate(self) -> RuntimeConfigurationSnapshot:
        candidate = self._source.load()
        if not isinstance(candidate, RuntimeConfigurationSnapshot):
            message = "RuntimeConfigurationSource.load() must return a RuntimeConfigurationSnapshot"
            raise TypeError(message)
        if candidate.device_serial != self._device_serial:
            message = "runtime configuration changed the immutable device serial; restart the instance"
            raise ValueError(message)
        if candidate.assembly_revision != self._assembly_revision:
            message = "runtime configuration changed assembly-bound fields; restart the instance to apply them"
            raise RuntimeRestartRequiredError(message)
        return candidate

    def close(self) -> None:
        if self._closed:
            return
        self._store.close()
        self._closed = True

    def _synchronize(self, candidate: RuntimeConfigurationSnapshot) -> bool:
        for _attempt in range(3):
            current_source = self._store.read_configuration_source()
            if current_source is not None and current_source.source_revision == candidate.source_revision:
                return False

            if current_source is None:
                settings = self._store.read_settings()
                expected_revision = 0 if settings is None else settings.revision
            else:
                # read_configuration_source 已在同一 read tx 验证该 revision 仍是当前 settings；
                # 直接拿它做 write CAS，避免把旧 source baseline 与夹写后的 settings 拼接。
                expected_revision = current_source.settings_revision
            try:
                if current_source is None:
                    self._publisher.publish(
                        candidate.payload,
                        candidate.schedules,
                        source_revision=candidate.source_revision,
                        expected_revision=expected_revision,
                    )
                else:
                    self._publisher.publish_update(
                        candidate.payload,
                        candidate.schedules,
                        current_source.source_schedules,
                        source_revision=candidate.source_revision,
                        expected_revision=expected_revision,
                    )
            except RevisionConflictError:
                refreshed = self._store.read_configuration_source()
                if refreshed is not None and refreshed.source_revision == candidate.source_revision:
                    return True
                continue
            return True
        message = "configuration publication conflicted repeatedly"
        raise ConfigurationPublicationConflictError(message)

    def _require_open(self) -> None:
        if self._closed:
            message = "runtime configuration control is closed"
            raise RuntimeError(message)
