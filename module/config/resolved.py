import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from module.config.utils import path_to_arg

if TYPE_CHECKING:
    from module.config.deep import DeepValue, MutableDeepValue

type ConfigIssueReason = Literal["invalid_option", "default_fallback", "hidden_reset", "migration"]


@dataclass(frozen=True, slots=True)
class ConfigIssue:
    path: str
    raw: MutableDeepValue
    resolved: MutableDeepValue
    reason: ConfigIssueReason


@dataclass(frozen=True, slots=True)
class ResolvedField:
    value: MutableDeepValue
    source_path: str | None
    is_override: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedTaskConfig:
    task_name: str
    bind_chain: tuple[str, ...]
    _fields: tuple[tuple[str, ResolvedField], ...]

    @property
    def fields(self) -> dict[str, ResolvedField]:
        return copy.deepcopy(dict(self._fields))

    @property
    def bound_paths(self) -> dict[str, str]:
        return {name: field.source_path for name, field in self._fields if field.source_path is not None}

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(name for name, _field in self._fields)

    def source_path(self, name: str) -> str | None:
        return self._get_field(name).source_path

    def _get_field(self, name: str) -> ResolvedField:
        for field_name, field in self._fields:
            if field_name == name:
                return field
        raise AttributeError(name)

    def __getattr__(self, name: str) -> MutableDeepValue:
        return copy.deepcopy(self._get_field(name).value)


def _require_mapping(value: DeepValue, *, path: str) -> Mapping[str, DeepValue]:
    if not isinstance(value, Mapping):
        message = f"config node must be a mapping: {path}"
        raise TypeError(message)
    return cast("Mapping[str, DeepValue]", value)


def resolve_task_config(
    *,
    task_name: str,
    bind_chain: Sequence[str],
    data: Mapping[str, DeepValue],
    overrides: Mapping[str, MutableDeepValue],
) -> ResolvedTaskConfig:
    """按显式绑定链解析一份可原子发布的任务配置快照。"""
    chain = tuple(bind_chain)
    source = copy.deepcopy(_require_mapping(data, path="<root>"))
    runtime_overrides = copy.deepcopy(_require_mapping(overrides, path="<overrides>"))
    fields: dict[str, ResolvedField] = {}

    for scope_name in chain:
        scope = _require_mapping(source.get(scope_name, {}), path=scope_name)
        for group_name, raw_group in scope.items():
            group = _require_mapping(raw_group, path=f"{scope_name}.{group_name}")
            for argument_name, value in group.items():
                relative_path = f"{group_name}.{argument_name}"
                field_name = path_to_arg(relative_path)
                if field_name in fields:
                    continue
                fields[field_name] = ResolvedField(
                    value=cast("MutableDeepValue", copy.deepcopy(value)),
                    source_path=f"{scope_name}.{relative_path}",
                )

    for field_name, value in runtime_overrides.items():
        if not isinstance(field_name, str) or not field_name:
            message = f"override name must be a non-empty string: {field_name!r}"
            raise TypeError(message)
        existing = fields.get(field_name)
        fields[field_name] = ResolvedField(
            value=cast("MutableDeepValue", copy.deepcopy(value)),
            source_path=None if existing is None else existing.source_path,
            is_override=True,
        )

    return ResolvedTaskConfig(
        task_name=task_name,
        bind_chain=chain,
        _fields=tuple(fields.items()),
    )
