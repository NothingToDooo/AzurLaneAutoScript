import hashlib
import json
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.runtime.errors import SettingsDocumentError

if TYPE_CHECKING:
    from collections.abc import Iterable

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type FrozenJsonValue = bool | int | float | str | tuple[FrozenJsonValue, ...] | Mapping[str, FrozenJsonValue] | None
type FrozenTaskSettings = Mapping[str, FrozenJsonValue]


def _freeze_json(value: JsonValue, *, path: str) -> FrozenJsonValue:
    if value is None:
        return None
    if isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            message = f"{path} must contain a finite JSON number"
            raise SettingsDocumentError(message)
        return value
    if isinstance(value, list):
        return tuple(_freeze_json(item, path=f"{path}[{index}]") for index, item in enumerate(value))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            message = f"{path} field names must be strings"
            raise SettingsDocumentError(message)
        return MappingProxyType({key: _freeze_json(item, path=f"{path}.{key}") for key, item in value.items()})
    message = f"{path} must contain only JSON values"
    raise SettingsDocumentError(message)


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


def freeze_task_settings(
    tasks: Mapping[str, JsonValue],
    *,
    task_ids: Iterable[str],
) -> tuple[Mapping[str, FrozenTaskSettings], Mapping[str, int]]:
    """冻结编译器产出的任务配置，并生成各任务自己的修订号。"""

    if not isinstance(tasks, Mapping):
        message = "task settings must be a mapping"
        raise TypeError(message)
    if any(not isinstance(task_id, str) for task_id in tasks):
        message = "task settings must use task id strings"
        raise TypeError(message)
    expected = _expected_task_ids(task_ids)
    raw_tasks = dict(tasks)
    actual = set(raw_tasks)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        message = f"task settings coverage mismatch: missing={missing}, unknown={unknown}"
        raise SettingsDocumentError(message)

    frozen: dict[str, FrozenTaskSettings] = {}
    revisions: dict[str, int] = {}
    for task_id, raw_settings in raw_tasks.items():
        if not isinstance(raw_settings, dict):
            message = f"task settings {task_id!r} must be an object"
            raise SettingsDocumentError(message)
        frozen[task_id] = MappingProxyType(
            {key: _freeze_json(value, path=f"$.tasks.{task_id}.{key}") for key, value in raw_settings.items()}
        )
        revisions[task_id] = _task_revision(task_id, raw_settings)

    return MappingProxyType(frozen), MappingProxyType(revisions)


def _task_revision(task_id: str, settings: dict[str, JsonValue]) -> int:
    encoded = json.dumps(
        {
            "format": "alas-task-settings-v1",
            "task_id": task_id,
            "settings": settings,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return int(hashlib.sha256(encoded).hexdigest()[:15], 16) + 1
