import copy
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, override
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from module.application.coordinator import RunRepository
from module.application.effects import (
    DelayTask,
    DisableTask,
    RequestAppRestart,
    RescheduleSelf,
    RescheduleTask,
    ScheduleEffect,
    WakePolicy,
    WakeTask,
)
from module.application.identifiers import TaskId
from module.application.metadata import RunMetadata
from module.application.scheduler import ScheduleItem, ScheduleSource
from module.application.state_effects import DeleteTaskState, StateEffect, UpsertTaskState
from module.application.task import ExecutionMode, TaskResult
from module.base.atomic import atomic_read_text, atomic_write
from module.bootstrap.configuration_compiler import WebConfigurationCompiler
from module.config.deep import deep_set
from module.config.json_codec import (
    DuplicateJsonFieldError,
    NonFiniteJsonNumberError,
    StrictJsonDecodeError,
    decode_json,
)
from module.runtime.task_state import TaskStateDocument, TaskStateEntry
from module.task_registry import TASK_CATALOG, TaskDefinition

if TYPE_CHECKING:
    from module.config.deep import MutableDeepData, MutableDeepValue
    from module.runtime.settings import FrozenJsonValue


type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


_CHECKPOINT_FIELDS = frozenset({"schema_version", "payload", "updated_at"})


class ConfigStateError(RuntimeError):
    """config-backed 运行状态不完整或不符合当前契约。"""


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        message = "timezone_name must be a non-empty string"
        raise ValueError(message)
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        message = f"unknown timezone: {timezone_name}"
        raise ValueError(message) from error


class ConfigRepositoryClock(Protocol):
    def now(self) -> datetime: ...


def _read_document(path: Path) -> dict[str, object]:
    content = atomic_read_text(path)
    if not content:
        message = f"config state file is missing or empty: {path}"
        raise ConfigStateError(message)
    try:
        decoded = decode_json(content)
    except DuplicateJsonFieldError as error:
        message = f"config state contains a duplicate field: {error.field}"
        raise ConfigStateError(message) from error
    except NonFiniteJsonNumberError as error:
        message = f"config state contains a non-finite JSON number: {error.constant}"
        raise ConfigStateError(message) from error
    except StrictJsonDecodeError as error:
        message = f"config state is not valid JSON: {path}"
        raise ConfigStateError(message) from error
    if type(decoded) is not dict:
        message = "config state root must be an object"
        raise ConfigStateError(message)
    return cast("dict[str, object]", decoded)


def _compile_current_document(document: dict[str, object], timezone: ZoneInfo) -> MutableDeepData:
    try:
        return WebConfigurationCompiler(timezone_name=timezone.key).parse_runtime_document(document)
    except (TypeError, ValueError) as error:
        message = f"config state violates the current configuration contract: {error}"
        raise ConfigStateError(message) from error


def _encode_document(document: dict[str, object]) -> str:
    try:
        return json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
    except (TypeError, ValueError) as error:
        message = "config state contains a value that cannot be encoded as JSON"
        raise ConfigStateError(message) from error


def _runtime_json_default(value: object) -> str:
    if isinstance(value, datetime):
        return str(value)
    message = f"unsupported runtime configuration value: {type(value).__name__}"
    raise TypeError(message)


def _runtime_document_to_source(document: MutableDeepData) -> dict[str, object]:
    try:
        encoded = json.dumps(
            document,
            allow_nan=False,
            default=_runtime_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        decoded = decode_json(encoded)
    except (StrictJsonDecodeError, TypeError, ValueError) as error:
        message = "runtime configuration contains a value that cannot be persisted as JSON"
        raise ConfigStateError(message) from error
    if type(decoded) is not dict:
        message = "runtime configuration root must be an object"
        raise ConfigStateError(message)
    return cast("dict[str, object]", decoded)


def _object_field(parent: Mapping[str, object], key: str, *, path: str) -> dict[str, object]:
    value = parent.get(key)
    if type(value) is not dict:
        message = f"{path}.{key} must be an object"
        raise ConfigStateError(message)
    return cast("dict[str, object]", value)


def _definition(task_id: TaskId) -> TaskDefinition:
    if not isinstance(task_id, TaskId):
        message = "task_id must be a TaskId"
        raise TypeError(message)
    try:
        return TASK_CATALOG[task_id.value]
    except KeyError as error:
        message = f"unknown task: {task_id.value}"
        raise ConfigStateError(message) from error


def _scheduled_definition(task_id: TaskId) -> TaskDefinition:
    definition = _definition(task_id)
    if definition.priority is None:
        message = f"task is not schedulable: {task_id.value}"
        raise ConfigStateError(message)
    return definition


def _task_section(document: Mapping[str, object], definition: TaskDefinition) -> dict[str, object]:
    return _object_field(document, definition.config_name, path="$")


def _scheduler(document: Mapping[str, object], task_id: TaskId) -> tuple[dict[str, object], TaskDefinition]:
    definition = _scheduled_definition(task_id)
    section = _task_section(document, definition)
    scheduler = _object_field(section, "Scheduler", path=f"$.{definition.config_name}")
    enabled = scheduler.get("Enable")
    if type(enabled) is not bool:
        message = f"$.{definition.config_name}.Scheduler.Enable must be a bool"
        raise ConfigStateError(message)
    next_run = scheduler.get("NextRun")
    if not isinstance(next_run, str) or not next_run.strip():
        message = f"$.{definition.config_name}.Scheduler.NextRun must be a non-empty string"
        raise ConfigStateError(message)
    return scheduler, definition


def _parse_due_at(value: str, *, task_id: TaskId, timezone: ZoneInfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        message = f"task {task_id.value} Scheduler.NextRun must be an ISO datetime"
        raise ConfigStateError(message) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(UTC)


def _schedule_items(document: Mapping[str, object], *, timezone: ZoneInfo) -> tuple[ScheduleItem, ...]:
    scheduled = sorted(
        (definition for definition in TASK_CATALOG.values() if definition.priority is not None),
        key=lambda definition: cast("int", definition.priority),
    )
    items: list[ScheduleItem] = []
    for definition in scheduled:
        task_id = TaskId(definition.command)
        scheduler, _ = _scheduler(document, task_id)
        items.append(
            ScheduleItem(
                task_id=task_id,
                enabled=cast("bool", scheduler["Enable"]),
                due_at=_parse_due_at(
                    cast("str", scheduler["NextRun"]),
                    task_id=task_id,
                    timezone=timezone,
                ),
                priority=cast("int", definition.priority),
            )
        )
    return tuple(items)


def _read_schedule_items(config_path: Path, *, timezone: ZoneInfo) -> tuple[ScheduleItem, ...]:
    document = _read_document(config_path)
    _compile_current_document(document, timezone)
    return _schedule_items(document, timezone=timezone)


def read_schedule_items(
    config_path: Path,
    *,
    timezone_name: str = "Asia/Shanghai",
) -> tuple[ScheduleItem, ...]:
    """从单一 alas.json 读取运行时 scheduler 使用的任务列表。"""
    if not isinstance(config_path, Path):
        message = "config_path must be a Path"
        raise TypeError(message)
    return _read_schedule_items(config_path, timezone=_resolve_timezone(timezone_name))


def _storage(document: Mapping[str, object], task_id: TaskId) -> dict[str, object]:
    definition = _definition(task_id)
    section = _task_section(document, definition)
    storage_group = _object_field(section, "Storage", path=f"$.{definition.config_name}")
    return _object_field(storage_group, "Storage", path=f"$.{definition.config_name}.Storage")


def _thaw_json(value: object, *, path: str = "$") -> JsonValue:
    if value is None or type(value) in {bool, int, str}:
        return cast("bool | int | str | None", value)
    if type(value) is float:
        return cast("float", value)
    if isinstance(value, tuple | list):
        return [_thaw_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        thawed: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                message = f"checkpoint object key at {path} must be a string"
                raise ConfigStateError(message)
            thawed[key] = _thaw_json(item, path=f"{path}.{key}")
        return thawed
    message = f"checkpoint value at {path} is not JSON: {type(value).__name__}"
    raise ConfigStateError(message)


def _parse_updated_at(value: object, *, path: str) -> datetime:
    if not isinstance(value, str):
        message = f"{path} must be an ISO datetime string"
        raise ConfigStateError(message)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        message = f"{path} must be an ISO datetime string"
        raise ConfigStateError(message) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        message = f"{path} must be timezone-aware"
        raise ConfigStateError(message)
    return parsed


def _format_updated_at(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ConfigStateRepository(RunRepository, ScheduleSource):
    """单进程内唯一的 alas.json owner，统一提交 legacy 配置、调度和 checkpoint。"""

    __slots__ = (
        "_active_run",
        "_clock",
        "_config_path",
        "_document",
        "_runtime_document",
        "_timezone",
    )

    def __init__(
        self,
        clock: ConfigRepositoryClock,
        *,
        config_path: Path,
        timezone_name: str = "Asia/Shanghai",
        initial_document: Mapping[str, object] | None = None,
        initial_runtime_document: MutableDeepData | None = None,
    ) -> None:
        if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
            message = "clock must implement now()"
            raise TypeError(message)
        if not isinstance(config_path, Path):
            message = "config_path must be a Path"
            raise TypeError(message)
        if initial_document is not None and not isinstance(initial_document, Mapping):
            message = "initial_document must be a mapping or None"
            raise TypeError(message)
        if initial_runtime_document is not None and not isinstance(initial_runtime_document, dict):
            message = "initial_runtime_document must be a parsed configuration object or None"
            raise TypeError(message)
        if (initial_document is None) is not (initial_runtime_document is None):
            message = "initial_document and initial_runtime_document must be provided together"
            raise ValueError(message)
        self._clock = clock
        self._config_path = config_path
        self._timezone = _resolve_timezone(timezone_name)
        self._active_run: TaskId | None = None
        if initial_document is None:
            document = _read_document(config_path)
        else:
            if any(not isinstance(key, str) for key in initial_document):
                message = "initial_document must use string field names"
                raise TypeError(message)
            document = copy.deepcopy(dict(initial_document))
        self._document = document
        if initial_runtime_document is None:
            self._runtime_document = _compile_current_document(document, self._timezone)
        else:
            self._runtime_document = copy.deepcopy(initial_runtime_document)

    @override
    def begin_run(self, task_id: TaskId, mode: ExecutionMode, metadata: RunMetadata) -> datetime:
        _definition(task_id)
        if not isinstance(mode, ExecutionMode):
            message = "mode must be an ExecutionMode"
            raise TypeError(message)
        if not isinstance(metadata, RunMetadata):
            message = "metadata must be a RunMetadata"
            raise TypeError(message)
        if self._active_run is not None:
            message = "config state repository already has an active run"
            raise ConfigStateError(message)

        started_at = self._aware_now()
        self._active_run = task_id
        return started_at

    @override
    def finalize_run(self, result: TaskResult) -> None:
        if not isinstance(result, TaskResult):
            message = "result must be a TaskResult"
            raise TypeError(message)
        if self._active_run is None:
            message = "config state repository has no active run"
            raise ConfigStateError(message)

        task_id = self._active_run
        try:
            self._commit_result(task_id, result)
        finally:
            # 写失败必须向上抛，但同一进程仍应允许下一次调试运行。
            self._active_run = None

    @override
    def list_items(self) -> tuple[ScheduleItem, ...]:
        return _schedule_items(self._document, timezone=self._timezone)

    def runtime_document(self) -> MutableDeepData:
        """返回 legacy driver 使用的独立 parsed 快照。"""

        return copy.deepcopy(self._runtime_document)

    def apply_runtime_updates(self, updates: Mapping[str, object]) -> MutableDeepData:
        """把 legacy config 的字段修改合并到最新快照并原子提交。"""

        if not isinstance(updates, Mapping):
            message = "runtime configuration updates must be a mapping"
            raise TypeError(message)
        if any(not isinstance(path, str) or not path or path != path.strip() for path in updates):
            message = "runtime configuration update paths must be trimmed non-empty strings"
            raise ValueError(message)
        if not updates:
            return self.runtime_document()
        candidate = self.runtime_document()
        for path, value in updates.items():
            deep_set(candidate, keys=path, value=cast("MutableDeepValue", copy.deepcopy(value)))
        document = _runtime_document_to_source(candidate)
        self._persist_document(document)
        return self.runtime_document()

    def task_state(self, task_id: TaskId) -> TaskStateDocument:
        stored = _storage(self._document, task_id)
        entries: dict[str, TaskStateEntry] = {}
        for key, value in stored.items():
            if type(value) is not dict:
                message = f"checkpoint {task_id.value}.{key} must be an object"
                raise ConfigStateError(message)
            checkpoint = cast("dict[str, object]", value)
            if set(checkpoint) != _CHECKPOINT_FIELDS:
                missing = sorted(_CHECKPOINT_FIELDS - set(checkpoint))
                unknown = sorted(set(checkpoint) - _CHECKPOINT_FIELDS)
                message = f"checkpoint {task_id.value}.{key} fields mismatch: missing={missing}, unknown={unknown}"
                raise ConfigStateError(message)
            schema_version = checkpoint["schema_version"]
            if type(schema_version) is not int or schema_version <= 0:
                message = f"checkpoint {task_id.value}.{key}.schema_version must be positive"
                raise ConfigStateError(message)
            entries[key] = TaskStateEntry(
                schema_version=schema_version,
                payload=cast("FrozenJsonValue", checkpoint["payload"]),
                updated_at=_parse_updated_at(
                    checkpoint["updated_at"],
                    path=f"checkpoint {task_id.value}.{key}.updated_at",
                ),
            )
        return TaskStateDocument(namespace=task_id.value, entries=entries)

    def _commit_result(self, task_id: TaskId, result: TaskResult) -> None:
        persistent_schedule_effects = tuple(
            effect for effect in result.effects if not isinstance(effect, RequestAppRestart)
        )
        if not persistent_schedule_effects and not result.state_effects:
            return

        self._validate_state_namespaces(task_id, result.state_effects)
        document = copy.deepcopy(self._document)
        self._apply_schedule_effects(document, task_id, persistent_schedule_effects)
        self._apply_state_effects(document, task_id, result.state_effects, updated_at=self._aware_now())
        self._persist_document(document)

    def _persist_document(self, document: dict[str, object]) -> None:
        runtime_document = _compile_current_document(document, self._timezone)
        encoded = _encode_document(document)
        atomic_write(self._config_path, encoded)
        self._document = document
        self._runtime_document = runtime_document

    def _aware_now(self) -> datetime:
        now = self._clock.now()
        if not isinstance(now, datetime):
            message = "clock.now() must return a datetime"
            raise TypeError(message)
        if now.tzinfo is None or now.utcoffset() is None:
            message = "clock.now() must return a timezone-aware datetime"
            raise ValueError(message)
        return now

    def _format_due_at(self, value: datetime) -> str:
        return value.astimezone(self._timezone).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")

    def _apply_schedule_effects(
        self,
        document: dict[str, object],
        current_task_id: TaskId,
        effects: tuple[ScheduleEffect, ...],
    ) -> None:
        for effect in effects:
            if isinstance(effect, RescheduleSelf):
                scheduler, _ = _scheduler(document, current_task_id)
                scheduler["NextRun"] = self._format_due_at(effect.due_at)
                continue
            if isinstance(effect, RescheduleTask):
                scheduler, _ = _scheduler(document, effect.task_id)
                scheduler["NextRun"] = self._format_due_at(effect.due_at)
                continue
            if isinstance(effect, DelayTask):
                scheduler, _ = _scheduler(document, effect.task_id)
                current_due_at = _parse_due_at(
                    cast("str", scheduler["NextRun"]),
                    task_id=effect.task_id,
                    timezone=self._timezone,
                )
                if current_due_at < effect.due_at:
                    scheduler["NextRun"] = self._format_due_at(effect.due_at)
                continue
            if isinstance(effect, WakeTask):
                scheduler, _ = _scheduler(document, effect.task_id)
                if effect.enable_policy is WakePolicy.RESPECT_DISABLED and scheduler["Enable"] is False:
                    continue
                scheduler["Enable"] = True
                scheduler["NextRun"] = self._format_due_at(effect.due_at)
                continue
            if isinstance(effect, DisableTask):
                scheduler, _ = _scheduler(document, effect.task_id)
                scheduler["Enable"] = False
                continue
            message = f"unsupported schedule effect: {type(effect).__name__}"
            raise TypeError(message)

    @staticmethod
    def _validate_state_namespaces(task_id: TaskId, effects: tuple[StateEffect, ...]) -> None:
        foreign = tuple(effect.namespace for effect in effects if effect.namespace != task_id.value)
        if foreign:
            message = f"task {task_id.value!r} cannot mutate another task state namespace: {foreign}"
            raise ConfigStateError(message)

    @staticmethod
    def _apply_state_effects(
        document: dict[str, object],
        task_id: TaskId,
        effects: tuple[StateEffect, ...],
        *,
        updated_at: datetime,
    ) -> None:
        storage = _storage(document, task_id)
        encoded_updated_at = _format_updated_at(updated_at)
        for effect in effects:
            if isinstance(effect, UpsertTaskState):
                storage[effect.key] = {
                    "schema_version": effect.schema_version,
                    "payload": _thaw_json(effect.payload),
                    "updated_at": encoded_updated_at,
                }
            elif isinstance(effect, DeleteTaskState):
                storage.pop(effect.key, None)
            else:
                message = f"unsupported state effect: {type(effect).__name__}"
                raise TypeError(message)
