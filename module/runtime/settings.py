import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, time, timedelta
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.runtime.errors import SettingsDocumentError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from _typeshed import DataclassInstance

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type FrozenJsonValue = bool | int | float | str | tuple[FrozenJsonValue, ...] | Mapping[str, FrozenJsonValue] | None
type FrozenTaskSettings = Mapping[str, FrozenJsonValue]


@dataclass(frozen=True, slots=True)
class CompiledTaskSettings:
    """把一个不可变 typed settings 值和它自己的修订号绑定在一起。"""

    settings: object
    revision: int

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision <= 0:
            message = "revision must be a positive integer"
            raise ValueError(message)


def _canonical_primitive(value: object, *, path: str) -> JsonValue:
    if value is None:
        return None
    if type(value) is bool:
        return value
    if type(value) is int:
        return cast("int", value)
    if type(value) is str:
        return value
    if type(value) is float:
        number = cast("float", value)
        if not math.isfinite(number):
            message = f"{path} must be finite"
            raise SettingsDocumentError(message)
        return number
    message = f"{path} must be a primitive typed value"
    raise SettingsDocumentError(message)


def _canonical_temporal_or_enum(value: object, *, path: str, active: set[int]) -> JsonValue:
    if isinstance(value, Enum):
        return {
            "$enum": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_setting(value.value, path=f"{path}.value", active=active),
        }
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            message = f"{path} datetime must be timezone-aware"
            raise SettingsDocumentError(message)
        return {"$datetime": value.astimezone(UTC).isoformat()}
    if isinstance(value, time):
        if value.utcoffset() is not None:
            message = f"{path} time must be timezone-naive"
            raise SettingsDocumentError(message)
        return {"$time": value.isoformat()}
    if isinstance(value, timedelta):
        microseconds = ((value.days * 86_400 + value.seconds) * 1_000_000) + value.microseconds
        return {"$timedelta_microseconds": microseconds}
    message = f"{path} must be a temporal or enum typed value"
    raise SettingsDocumentError(message)


def _canonical_tuple(value: tuple[object, ...], *, path: str, active: set[int]) -> JsonValue:
    return {
        "$tuple": [_canonical_setting(item, path=f"{path}[{index}]", active=active) for index, item in enumerate(value)]
    }


def _canonical_dataclass(value: object, *, path: str, active: set[int]) -> JsonValue:
    params = getattr(type(value), "__dataclass_params__", None)
    if params is None or not params.frozen:
        message = f"{path} must contain immutable typed values"
        raise SettingsDocumentError(message)
    identity = id(value)
    if identity in active:
        message = f"{path} must not contain cycles"
        raise SettingsDocumentError(message)
    active.add(identity)
    try:
        field_values = {
            item.name: _canonical_setting(
                getattr(value, item.name),
                path=f"{path}.{item.name}",
                active=active,
            )
            for item in fields(cast("DataclassInstance", value))
        }
    finally:
        active.remove(identity)
    return {
        "$type": f"{type(value).__module__}.{type(value).__qualname__}",
        "fields": field_values,
    }


def _canonical_setting(value: object, *, path: str, active: set[int]) -> JsonValue:
    if value is None or type(value) in {bool, int, float, str}:
        return _canonical_primitive(value, path=path)
    if isinstance(value, Enum | datetime | time | timedelta):
        return _canonical_temporal_or_enum(value, path=path, active=active)
    if isinstance(value, tuple):
        return _canonical_tuple(value, path=path, active=active)
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_dataclass(value, path=path, active=active)
    message = f"{path} must contain immutable typed values"
    raise SettingsDocumentError(message)


def _typed_task_revision(task_id: str, settings: object) -> int:
    encoded = json.dumps(
        {
            "format": "alas-typed-task-settings-v1",
            "task_id": task_id,
            "settings": _canonical_setting(settings, path=f"$.tasks.{task_id}", active=set()),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return int(hashlib.sha256(encoded).hexdigest()[:15], 16) + 1


def compile_task_settings(
    tasks: Mapping[str, object],
    *,
    task_ids: Iterable[str],
) -> Mapping[str, CompiledTaskSettings]:
    """验证 typed settings 覆盖范围，并为每个任务生成独立修订号。"""

    if not isinstance(tasks, Mapping):
        message = "task settings must be a mapping"
        raise TypeError(message)
    if any(not isinstance(task_id, str) for task_id in tasks):
        message = "task settings must use task id strings"
        raise TypeError(message)
    expected = _expected_task_ids(task_ids)
    values = dict(tasks)
    actual = set(values)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        message = f"task settings coverage mismatch: missing={missing}, unknown={unknown}"
        raise SettingsDocumentError(message)
    compiled = {
        task_id: CompiledTaskSettings(
            settings=settings,
            revision=_typed_task_revision(task_id, settings),
        )
        for task_id, settings in values.items()
    }
    return MappingProxyType(compiled)


def _expected_task_ids(task_ids: Iterable[str]) -> frozenset[str]:
    if isinstance(task_ids, str):
        message = "task_ids must be an iterable of task id strings"
        raise TypeError(message)
    values = tuple(task_ids)
    if any(not isinstance(task_id, str) or not task_id or task_id != task_id.strip() for task_id in values):
        message = "task_ids must contain trimmed non-empty strings"
        raise TypeError(message)
    if len(set(values)) != len(values):
        message = "task_ids must not contain duplicates"
        raise ValueError(message)
    return frozenset(values)
