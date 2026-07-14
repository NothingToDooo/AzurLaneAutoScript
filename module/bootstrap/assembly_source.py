import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol, cast

from module.bootstrap.configuration_compiler import (
    CompiledConfiguration,
    ConfigurationDocument,
    WebConfigurationCompiler,
)
from module.bootstrap.runtime_provider import InstanceAssembly, InstanceAssemblySource
from module.bootstrap.task_factories import GameTaskDependencies
from module.runtime import ConfigurationChangeSignal, InstanceRuntimeConfig
from module.supervisor import DeviceLeaseRegistry


class ConfigurationLoadError(ValueError):
    pass


def validate_instance_name(value: str) -> str:
    if not isinstance(value, str):
        message = "instance_name must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = "instance_name must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)
    if value in {".", ".."} or any(character in value for character in ("/", "\\", ":")):
        message = "instance_name must not contain path semantics"
        raise ValueError(message)
    if len(value) > 128:
        message = "instance_name must not exceed 128 characters"
        raise ValueError(message)
    return value


class ConfigurationDocumentSource(Protocol):
    def load(self, instance_name: str) -> ConfigurationDocument: ...

    def watch_paths(self, instance_name: str) -> tuple[Path, ...]: ...


class GameRuntimeBundleSource(Protocol):
    def build(
        self,
        instance_name: str,
        document: ConfigurationDocument,
        configuration: CompiledConfiguration,
    ) -> GameRuntimeBundle: ...


@dataclass(frozen=True, slots=True)
class GameRuntimeBundle:
    tasks: GameTaskDependencies
    content_revision: str
    client_ui_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.tasks, GameTaskDependencies):
            message = "tasks must be GameTaskDependencies"
            raise TypeError(message)
        for field_name, value in (
            ("content_revision", self.content_revision),
            ("client_ui_revision", self.client_ui_revision),
        ):
            if not isinstance(value, str):
                message = f"{field_name} must be a string"
                raise TypeError(message)
            if not value or value != value.strip():
                message = f"{field_name} must be trimmed and non-empty"
                raise ValueError(message)


@dataclass(frozen=True, slots=True)
class InstanceAssemblyLayout:
    state_root: Path
    lease_lock_root: Path
    hoard_window: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if not isinstance(self.state_root, Path):
            message = "state_root must be a Path"
            raise TypeError(message)
        if not isinstance(self.lease_lock_root, Path):
            message = "lease_lock_root must be a Path"
            raise TypeError(message)
        if not isinstance(self.hoard_window, timedelta) or self.hoard_window < timedelta():
            message = "hoard_window must be a non-negative timedelta"
            raise ValueError(message)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            message = f"duplicate configuration field: {key}"
            raise ConfigurationLoadError(message)
        result[key] = value
    return result


class JsonConfigurationDocumentSource:
    """读取当前 WebUI JSON；只为默认实例提供显式 template 初始值。"""

    __slots__ = ("_config_root", "_default_instance", "_template_path")

    def __init__(
        self,
        config_root: Path,
        template_path: Path,
        *,
        default_instance: str = "alas",
    ) -> None:
        if not isinstance(config_root, Path):
            message = "config_root must be a Path"
            raise TypeError(message)
        if not isinstance(template_path, Path):
            message = "template_path must be a Path"
            raise TypeError(message)
        self._config_root = config_root
        self._template_path = template_path
        self._default_instance = validate_instance_name(default_instance)

    def load(self, instance_name: str) -> ConfigurationDocument:
        name = validate_instance_name(instance_name)
        path = self._config_root / f"{name}.json"
        if not path.is_file():
            if name != self._default_instance:
                message = f"configuration file does not exist: {path}"
                raise FileNotFoundError(message)
            path = self._template_path
        try:
            value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        except (OSError, UnicodeError, json.JSONDecodeError, ConfigurationLoadError) as error:
            if isinstance(error, ConfigurationLoadError):
                raise
            message = f"failed to load configuration {path}: {error}"
            raise ConfigurationLoadError(message) from error
        if not isinstance(value, Mapping):
            message = f"configuration {path} must contain a JSON object"
            raise ConfigurationLoadError(message)
        if any(not isinstance(key, str) for key in value):
            message = f"configuration {path} must use string field names"
            raise ConfigurationLoadError(message)
        return cast("ConfigurationDocument", value)

    def watch_paths(self, instance_name: str) -> tuple[Path, ...]:
        name = validate_instance_name(instance_name)
        instance_path = self._config_root / f"{name}.json"
        if name == self._default_instance:
            return (instance_path, self._template_path)
        return (instance_path,)


class ConfigurationFileSignal:
    """WebUI 事件即时唤醒，文件指纹轮询仅作外部编辑的兜底。"""

    __slots__ = ("_external", "_fingerprint", "_paths")

    def __init__(
        self,
        paths: tuple[Path, ...],
        external: ConfigurationChangeSignal | None = None,
    ) -> None:
        if not isinstance(paths, tuple) or not paths or any(not isinstance(path, Path) for path in paths):
            message = "paths must be a non-empty tuple of Path values"
            raise TypeError(message)
        if external is not None and (
            isinstance(external, type)
            or not all(callable(getattr(external, method, None)) for method in ("wait", "clear"))
        ):
            message = "external must implement wait() and clear()"
            raise TypeError(message)
        self._paths = paths
        self._external = external
        self._fingerprint = self._read_fingerprint()

    def wait(self, timeout: float) -> bool:
        if type(timeout) not in {int, float} or timeout < 0:
            message = "timeout must be a non-negative number"
            raise ValueError(message)
        deadline = time.monotonic() + timeout
        while True:
            if self._external is not None and self._external.wait(0):
                return True
            if self._read_fingerprint() != self._fingerprint:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            interval = min(remaining, 1.0)
            if self._external is not None:
                if self._external.wait(interval):
                    return True
            else:
                time.sleep(interval)

    def clear(self) -> None:
        if self._external is not None:
            self._external.clear()
        self._fingerprint = self._read_fingerprint()

    def _read_fingerprint(self) -> tuple[tuple[str, int | None, int | None], ...]:
        fingerprint: list[tuple[str, int | None, int | None]] = []
        for path in self._paths:
            try:
                stat = path.stat()
            except FileNotFoundError:
                fingerprint.append((str(path), None, None))
            else:
                fingerprint.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(fingerprint)


class FilesystemInstanceAssemblySource(InstanceAssemblySource):
    """配置文档、typed runtime bundle 与实例状态路径的唯一组装入口。"""

    __slots__ = (
        "_bundle_source",
        "_compiler",
        "_configuration_source",
        "_hoard_window",
        "_lease_lock_root",
        "_process_id",
        "_state_root",
    )

    def __init__(
        self,
        configuration_source: ConfigurationDocumentSource,
        bundle_source: GameRuntimeBundleSource,
        layout: InstanceAssemblyLayout,
        *,
        compiler: WebConfigurationCompiler | None = None,
        process_id: Callable[[], int] = os.getpid,
    ) -> None:
        if isinstance(configuration_source, type) or not all(
            callable(getattr(configuration_source, method, None)) for method in ("load", "watch_paths")
        ):
            message = "configuration_source must implement load() and watch_paths()"
            raise TypeError(message)
        if isinstance(bundle_source, type) or not callable(getattr(bundle_source, "build", None)):
            message = "bundle_source must implement build()"
            raise TypeError(message)
        if not isinstance(layout, InstanceAssemblyLayout):
            message = "layout must be an InstanceAssemblyLayout"
            raise TypeError(message)
        selected_compiler = compiler or WebConfigurationCompiler()
        if not isinstance(selected_compiler, WebConfigurationCompiler):
            message = "compiler must be a WebConfigurationCompiler"
            raise TypeError(message)
        if isinstance(process_id, type) or not callable(process_id):
            message = "process_id must be callable"
            raise TypeError(message)
        self._configuration_source = configuration_source
        self._bundle_source = bundle_source
        self._state_root = layout.state_root
        self._lease_lock_root = layout.lease_lock_root
        self._compiler = selected_compiler
        self._hoard_window = layout.hoard_window
        self._process_id = process_id

    def load(self, instance_name: str) -> InstanceAssembly:
        name = validate_instance_name(instance_name)
        document = self._configuration_source.load(name)
        configuration = self._compiler.compile(document)
        process_id = self._process_id()
        if type(process_id) is not int or process_id <= 0:
            message = "process_id must return a positive integer"
            raise ValueError(message)
        self._state_root.mkdir(parents=True, exist_ok=True)
        self._lease_lock_root.mkdir(parents=True, exist_ok=True)
        lease_owner = f"{name}:pid-{process_id}"
        leases = DeviceLeaseRegistry(self._lease_lock_root)
        lease = leases.acquire(configuration.device_serial, lease_owner)
        try:
            # production bundle 可能在构造 Device 时访问模拟器；初始化也必须处于同一 OS lease 内。
            bundle = self._bundle_source.build(name, document, configuration)
        finally:
            leases.release(lease)
        if not isinstance(bundle, GameRuntimeBundle):
            message = "GameRuntimeBundleSource.build() must return a GameRuntimeBundle"
            raise TypeError(message)
        return InstanceAssembly(
            runtime=InstanceRuntimeConfig(
                state_path=self._state_root / f"{name}.sqlite3",
                lease_lock_root=self._lease_lock_root,
                device_serial=configuration.device_serial,
                lease_owner=lease_owner,
                hoard_window=self._hoard_window,
            ),
            tasks=bundle.tasks,
            configuration=configuration,
            content_revision=bundle.content_revision,
            client_ui_revision=bundle.client_ui_revision,
        )

    def load_configuration(self, instance_name: str) -> CompiledConfiguration:
        name = validate_instance_name(instance_name)
        return self._compiler.compile(self._configuration_source.load(name))

    def configuration_signal(
        self,
        instance_name: str,
        external: ConfigurationChangeSignal | None = None,
    ) -> ConfigurationFileSignal:
        paths = self._configuration_source.watch_paths(validate_instance_name(instance_name))
        return ConfigurationFileSignal(paths, external)
