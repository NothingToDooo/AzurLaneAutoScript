import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

type ImmutableJsonValue = (
    bool | int | float | str | tuple[ImmutableJsonValue, ...] | Mapping[str, ImmutableJsonValue] | None
)


def _validate_identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or any(character.isspace() for character in value):
        message = f"{field_name} must not be empty or contain whitespace"
        raise ValueError(message)


def _validate_schema_version(value: int) -> None:
    if type(value) is not int:
        message = "schema_version must be an integer"
        raise TypeError(message)
    if value <= 0:
        message = "schema_version must be positive"
        raise ValueError(message)


def _freeze_json_container(
    value: list[object] | dict[object, object],
    *,
    path: str,
    active: set[int],
) -> ImmutableJsonValue:
    identity = id(value)
    if identity in active:
        message = f"JSON value at {path} must not contain cycles"
        raise ValueError(message)
    active.add(identity)
    try:
        if type(value) is list:
            return tuple(_freeze_json(item, path=f"{path}[{index}]", active=active) for index, item in enumerate(value))

        mapping = cast("dict[object, object]", value)
        frozen: dict[str, ImmutableJsonValue] = {}
        for key, item in mapping.items():
            if type(key) is not str:
                message = f"JSON object key at {path} must be a string"
                raise TypeError(message)
            frozen[key] = _freeze_json(item, path=f"{path}.{key}", active=active)
        return MappingProxyType(frozen)
    finally:
        active.remove(identity)


def _freeze_json(value: object, *, path: str = "$", active: set[int] | None = None) -> ImmutableJsonValue:
    if value is None:
        return None
    if type(value) in {bool, int, str}:
        return cast("bool | int | str", value)
    if type(value) is float:
        number = cast("float", value)
        if not math.isfinite(number):
            message = f"JSON number at {path} must be finite"
            raise ValueError(message)
        return number
    if type(value) is list:
        return _freeze_json_container(
            cast("list[object]", value),
            path=path,
            active=set() if active is None else active,
        )
    if type(value) is dict:
        return _freeze_json_container(
            cast("dict[object, object]", value),
            path=path,
            active=set() if active is None else active,
        )
    message = f"unsupported JSON value at {path}: {type(value).__name__}"
    raise TypeError(message)


@dataclass(frozen=True, slots=True, init=False)
class UpsertTaskState:
    """在 run 终态提交时原子写入一个有 schema 的任务 checkpoint。"""

    namespace: str
    key: str
    schema_version: int
    payload: ImmutableJsonValue

    def __init__(self, namespace: str, key: str, schema_version: int, payload: object) -> None:
        _validate_identifier(namespace, field_name="namespace")
        _validate_identifier(key, field_name="key")
        _validate_schema_version(schema_version)
        frozen_payload = _freeze_json(payload)

        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "payload", frozen_payload)


@dataclass(frozen=True, slots=True)
class DeleteTaskState:
    """在 run 终态提交时原子删除一个任务 checkpoint。"""

    namespace: str
    key: str

    def __post_init__(self) -> None:
        _validate_identifier(self.namespace, field_name="namespace")
        _validate_identifier(self.key, field_name="key")


type StateEffect = UpsertTaskState | DeleteTaskState
