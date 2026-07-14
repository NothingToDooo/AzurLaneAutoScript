import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.runtime.errors import SettingsDocumentError
from module.state import SettingsSnapshot

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from module.state import JsonValue

SETTINGS_SCHEMA_VERSION = 1

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


@dataclass(frozen=True, slots=True)
class TaskSettingsDocument:
    """一次 settings revision 的深度只读、按 TaskId 完整解析结果。"""

    revision: int
    updated_at: datetime
    tasks: Mapping[str, FrozenTaskSettings]

    @classmethod
    def from_snapshot(
        cls,
        snapshot: SettingsSnapshot,
        *,
        task_ids: Iterable[str],
    ) -> TaskSettingsDocument:
        if not isinstance(snapshot, SettingsSnapshot):
            message = "snapshot must be a SettingsSnapshot"
            raise TypeError(message)
        expected = _expected_task_ids(task_ids)
        payload = snapshot.payload
        if not isinstance(payload, dict):
            message = "settings payload must be an object"
            raise SettingsDocumentError(message)
        allowed_fields = {"schema_version", "tasks"}
        if set(payload) != allowed_fields:
            missing = sorted(allowed_fields - set(payload))
            unknown = sorted(set(payload) - allowed_fields)
            message = f"settings payload fields mismatch: missing={missing}, unknown={unknown}"
            raise SettingsDocumentError(message)
        if type(payload["schema_version"]) is not int or payload["schema_version"] != SETTINGS_SCHEMA_VERSION:
            message = f"settings schema_version must be {SETTINGS_SCHEMA_VERSION}"
            raise SettingsDocumentError(message)

        raw_tasks = payload["tasks"]
        if not isinstance(raw_tasks, dict):
            message = "settings tasks must be an object"
            raise SettingsDocumentError(message)
        actual = set(raw_tasks)
        if actual != expected:
            missing = sorted(expected - actual)
            unknown = sorted(actual - expected)
            message = f"settings task coverage mismatch: missing={missing}, unknown={unknown}"
            raise SettingsDocumentError(message)

        frozen: dict[str, FrozenTaskSettings] = {}
        for task_id, raw_settings in raw_tasks.items():
            if not isinstance(raw_settings, dict):
                message = f"settings task {task_id!r} must be an object"
                raise SettingsDocumentError(message)
            frozen[task_id] = MappingProxyType(
                {key: _freeze_json(value, path=f"$.tasks.{task_id}.{key}") for key, value in raw_settings.items()}
            )

        return cls(
            revision=snapshot.revision,
            updated_at=snapshot.updated_at,
            tasks=MappingProxyType(frozen),
        )

    def for_task(self, task_id: str) -> FrozenTaskSettings:
        if not isinstance(task_id, str):
            message = "task_id must be a string"
            raise TypeError(message)
        try:
            return self.tasks[task_id]
        except KeyError:
            message = f"settings do not contain task: {task_id}"
            raise SettingsDocumentError(message) from None
