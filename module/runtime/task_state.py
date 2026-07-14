import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.runtime.errors import TaskStateDocumentError
from module.state.models import TaskStateRecord

if TYPE_CHECKING:
    from module.runtime.settings import FrozenJsonValue


def _validate_identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = f"{field_name} must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)


def _freeze_json(
    value: object,
    *,
    path: str,
    ancestors: set[int] | None = None,
) -> FrozenJsonValue:
    if value is None:
        return None
    if type(value) in {bool, int, str}:
        return cast("bool | int | str", value)
    if type(value) is float:
        number = cast("float", value)
        if not math.isfinite(number):
            message = f"{path} must contain a finite JSON number"
            raise TaskStateDocumentError(message)
        return number

    if ancestors is None:
        ancestors = set()
    if isinstance(value, list | tuple | Mapping):
        identity = id(value)
        if identity in ancestors:
            message = f"{path} must not contain cycles"
            raise TaskStateDocumentError(message)
        ancestors.add(identity)
        try:
            if isinstance(value, list | tuple):
                return tuple(
                    _freeze_json(item, path=f"{path}[{index}]", ancestors=ancestors) for index, item in enumerate(value)
                )
            if any(type(key) is not str for key in value):
                message = f"{path} field names must be strings"
                raise TaskStateDocumentError(message)
            return MappingProxyType(
                {
                    cast("str", key): _freeze_json(item, path=f"{path}.{key}", ancestors=ancestors)
                    for key, item in value.items()
                }
            )
        finally:
            ancestors.remove(identity)

    message = f"{path} must contain only JSON values"
    raise TaskStateDocumentError(message)


@dataclass(frozen=True, slots=True)
class TaskStateEntry:
    schema_version: int
    payload: FrozenJsonValue
    updated_at: datetime

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version <= 0:
            message = "schema_version must be a positive integer"
            raise ValueError(message)
        if not isinstance(self.updated_at, datetime):
            message = "updated_at must be a datetime"
            raise TypeError(message)
        if self.updated_at.utcoffset() is None:
            message = "updated_at must be timezone-aware"
            raise ValueError(message)
        object.__setattr__(self, "payload", _freeze_json(self.payload, path="$.payload"))


@dataclass(frozen=True, slots=True)
class TaskStateDocument:
    """单个 task namespace 的不可变 checkpoint 快照。"""

    namespace: str
    entries: Mapping[str, TaskStateEntry]

    def __post_init__(self) -> None:
        _validate_identifier(self.namespace, field_name="namespace")
        if not isinstance(self.entries, Mapping):
            message = "entries must be a mapping"
            raise TypeError(message)
        copied: dict[str, TaskStateEntry] = {}
        for key, entry in self.entries.items():
            _validate_identifier(key, field_name="task state key")
            if not isinstance(entry, TaskStateEntry):
                message = "entries must contain TaskStateEntry values"
                raise TypeError(message)
            copied[key] = entry
        object.__setattr__(self, "entries", MappingProxyType(copied))

    @classmethod
    def empty(cls, namespace: str) -> TaskStateDocument:
        return cls(namespace=namespace, entries=MappingProxyType({}))

    @classmethod
    def from_records(
        cls,
        namespace: str,
        records: Iterable[TaskStateRecord],
    ) -> TaskStateDocument:
        _validate_identifier(namespace, field_name="namespace")
        if isinstance(records, TaskStateRecord):
            message = "records must be an iterable of TaskStateRecord values"
            raise TypeError(message)

        entries: dict[str, TaskStateEntry] = {}
        for record in records:
            if not isinstance(record, TaskStateRecord):
                message = "records must contain TaskStateRecord values"
                raise TypeError(message)
            if record.namespace != namespace:
                message = f"task state namespace must be {namespace!r}, got {record.namespace!r}"
                raise TaskStateDocumentError(message)
            if record.key in entries:
                message = f"duplicate task state key: {record.key}"
                raise TaskStateDocumentError(message)
            entries[record.key] = TaskStateEntry(
                schema_version=record.version,
                payload=cast("FrozenJsonValue", record.payload),
                updated_at=record.updated_at,
            )
        return cls(namespace=namespace, entries=entries)

    def get(self, key: str) -> TaskStateEntry | None:
        _validate_identifier(key, field_name="key")
        return self.entries.get(key)
