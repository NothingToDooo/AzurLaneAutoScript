import inspect
import json
import textwrap
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast, get_args, get_origin

from module.application import ExecutionMode
from module.base.atomic import atomic_write
from module.base.decorator import cached_property
from module.base.timer import timer
from module.config.config_manual import ManualConfig
from module.config.configuration_file import write_config_file
from module.config.deep import deep_default, deep_exist, deep_get, deep_iter, deep_set
from module.config.utils import (
    LANGUAGES,
    data_to_type,
    filepath_args,
    filepath_argument,
    filepath_code,
    filepath_i18n,
    path_to_arg,
    read_file,
    write_file,
)
from module.content.activity_profile import CoalitionDefinition, CoalitionFleetRule, RaidDefinition, RaidMode
from module.content.manifest import load_default_event_manifests, render_campaign_readme
from module.content.models import EventPack, EventRelease
from module.project_paths import PROJECT_ROOT
from module.task_registry import TASK_CATALOG, command_to_config_name, get_task_definition

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from module.config.deep import DeepValue, MutableDeepData, MutableDeepValue
    from module.config.utils import ArgumentDefinition

CONFIG_IMPORT = """
import datetime
from typing import ClassVar, TypedDict

from module.config.config_manual import (
    FindPeaksParameter,  # ruff:ignore[typing-only-first-party-import] - get_type_hints 运行时解析。
)
from module.config.deep import MutableDeepValue

# 本文件由 module/config/config_updater.py 自动生成。
# 不要手动修改。

type ConfigValue = MutableDeepValue
""".strip().split("\n")

GENERATED_CONFIG_HEADER = [
    "class GeneratedConfig:",
    '    """',
    "    Auto generated configuration",
    '    """',
]
GENERATED_INDENT = "    "
GENERATED_LINE_LENGTH = 120
ARCHIVES_PREFIX = {"cn": "档案 "}
MAINS = ["Main", "Main2", "Main3"]
EVENTS = ["Event", "Event2", "EventA", "EventB", "EventC", "EventD", "EventSp"]
GEMS_FARMINGS = ["GemsFarming"]
RAIDS = ["Raid", "RaidDaily"]
WAR_ARCHIVES = ["WarArchives"]
COALITIONS = ["Coalition", "CoalitionSp"]
MARITIME_ESCORTS = ["MaritimeEscort"]
HOSPITAL = ["Hospital"]
CONFIG_SCOPE_TASKS = frozenset(
    {"Alas", "General"} | {scope for definition in TASK_CATALOG.values() for scope in definition.config_scopes}
)
INTERVAL_ARGUMENTS = frozenset({"SuccessInterval", "FailureInterval"})
OVERRIDE_METADATA_FIELDS = frozenset(
    {"display", "mode", "option", "option_bold", "type", "validate", "value", "valuetype"}
)
WIDGET_TYPES = frozenset({"checkbox", "datetime", "input", "lock", "select", "state", "storage", "textarea"})
DISPLAY_MODES = frozenset({"disabled", "display", "hide"})
PIN_VALUE_TYPES = frozenset({"bool", "float", "ignore", "int", "str"})


def _generated_comment(text: str, prefix: str = "") -> list[str]:
    return [
        f"{GENERATED_INDENT}# {line}"
        for line in textwrap.wrap(
            f"{prefix}{text}",
            width=110,
            break_long_words=False,
            break_on_hyphens=False,
        )
    ]


def _generated_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _generated_string_segments(value: str) -> list[str]:
    wrapper = textwrap.TextWrapper(
        width=100,
        break_long_words=False,
        break_on_hyphens=False,
        drop_whitespace=False,
        replace_whitespace=False,
    )
    segments = []
    for segment in value.splitlines(keepends=True):
        suffix = "\n" if segment.endswith("\n") else ""
        body = segment.removesuffix("\n")
        chunks = wrapper.wrap(body) or [""]
        for index, raw_chunk in enumerate(chunks):
            chunk = raw_chunk + suffix if index == len(chunks) - 1 else raw_chunk
            segments.append(chunk)
    return segments


def _generated_union(types: Iterable[str]) -> str:
    unique = list(dict.fromkeys(types))
    return " | ".join(unique)


def _generated_type(value: MutableDeepValue, *, none_type: str = "MutableDeepValue") -> str:
    if value is None:
        result = none_type
    elif isinstance(value, bool):
        result = "bool"
    elif isinstance(value, int):
        result = "int"
    elif isinstance(value, float):
        result = "float"
    elif isinstance(value, str):
        result = "str"
    elif isinstance(value, datetime):
        result = "datetime.datetime"
    elif isinstance(value, list):
        item_type = _generated_union(_generated_type(item) for item in value) if value else "MutableDeepValue"
        result = f"list[{item_type}]"
    elif isinstance(value, tuple):
        item_type = _generated_union(_generated_type(item) for item in value) if value else "MutableDeepValue"
        result = f"tuple[{item_type}, ...]"
    elif isinstance(value, dict):
        mapping = value
        item_type = (
            _generated_union(_generated_type(item) for item in mapping.values()) if mapping else "MutableDeepValue"
        )
        result = f"dict[str, {item_type}]"
    else:
        message = f"Unsupported generated config value: {value!r}"
        raise TypeError(message)
    return result


def _manual_override_type(annotation: object | None, value: MutableDeepValue) -> str:
    if annotation is None:
        return _generated_type(value)
    if get_origin(annotation) is not ClassVar:
        message = f"ManualConfig field annotation must be ClassVar: {annotation!r}"
        raise TypeError(message)
    arguments = get_args(annotation)
    if len(arguments) != 1:
        message = f"ManualConfig ClassVar annotation must contain one type: {annotation!r}"
        raise TypeError(message)
    return inspect.formatannotation(arguments[0])


def _manual_override_fields() -> Iterator[tuple[str, MutableDeepValue, str]]:
    annotations = inspect.get_annotations(ManualConfig, eval_str=True)
    for name, value in vars(ManualConfig).items():
        if name.startswith("_") or callable(value) or isinstance(value, (classmethod, property, staticmethod)):
            continue
        if isinstance(value, (bool, int, float, str, datetime, list, tuple, dict)) or value is None:
            yield name, value, _manual_override_type(annotations.get(name), value)


def _generated_value(name: str, value: MutableDeepValue) -> list[str]:
    if isinstance(value, str):
        line = f"{GENERATED_INDENT}{name} = {_generated_string(value)}"
        if "\n" not in value or len(line) <= GENERATED_LINE_LENGTH:
            return [line]

        lines = [f"{GENERATED_INDENT}{name} = ("]
        lines.extend(
            f"{GENERATED_INDENT * 2}{_generated_string(segment)}" for segment in _generated_string_segments(value)
        )
        lines.append(f"{GENERATED_INDENT})")
        return lines
    if isinstance(value, dict):
        return [f"{GENERATED_INDENT}{name}: ClassVar[{_generated_type(value)}] = {value!r}"]
    if isinstance(value, list):
        return [f"{GENERATED_INDENT}{name}: ClassVar[{_generated_type(value)}] = {value!r}"]
    return [f"{GENERATED_INDENT}{name} = {value!r}"]


def _parse_descriptor_value(
    path: list[str],
    descriptor: dict[str, MutableDeepValue],
) -> MutableDeepValue:
    """按参数描述符解析生成值，只转换显式声明的 datetime。"""

    if "value" not in descriptor:
        message = f"argument descriptor has no value: {'.'.join(path)}"
        raise ValueError(message)
    value = descriptor["value"]
    if value is None or descriptor.get("type") != "datetime" or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        message = f"datetime argument value must be text: {'.'.join(path)}"
        raise TypeError(message)
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        message = f"invalid datetime argument value at {'.'.join(path)}: {value!r}"
        raise ValueError(message) from error


class ConfigGenerator:
    _event_manifest_loader = staticmethod(load_default_event_manifests)
    _argument_path = filepath_argument("argument")
    _task_path = filepath_argument("task")
    _default_path = filepath_argument("default")
    _override_path = filepath_argument("override")
    _gui_path = filepath_argument("gui")

    @cached_property
    def argument(self) -> MutableDeepData:
        """读取 argument.yaml 并标准化为 `<group>.<argument>` 路径。

        每项包含 type 和 value；可选 option，datetime 项还包含 validate。
        """
        data: MutableDeepData = {}
        raw = read_file(self._argument_path)
        for path, raw_value in deep_iter(raw, depth=2):
            arg: dict[str, MutableDeepValue] = {
                "type": "input",
                "value": "",
            }
            value = (
                cast("dict[str, MutableDeepValue]", raw_value)
                if isinstance(raw_value, dict)
                else {"value": cast("MutableDeepValue", raw_value)}
            )
            arg["type"] = data_to_type(cast("ArgumentDefinition", value), arg=path[1])
            if isinstance(value["value"], datetime):
                arg["type"] = "datetime"
                arg["validate"] = "datetime"
            # 手动定义优先级最高。
            arg.update(value)
            deep_set(data, keys=path, value=arg)

        arg = {
            "type": "storage",
            "value": {},
            "valuetype": "ignore",
            "display": "disabled",
        }
        deep_set(data, keys=["Storage", "Storage"], value=arg)
        return data

    @cached_property
    def task(self) -> MutableDeepData:
        """读取 task.yaml 的 `<task_group>.<task>.{command, groups}` 结构。"""
        return read_file(self._task_path)

    @cached_property
    def default(self) -> MutableDeepData:
        """读取 default.yaml 的 `<task>.<group>.<argument>` 默认值。"""
        return read_file(self._default_path)

    @cached_property
    def override(self) -> MutableDeepData:
        """读取 override.yaml 的 `<task>.<group>.<argument>` 覆盖值。"""
        return read_file(self._override_path)

    @cached_property
    def gui(self) -> MutableDeepData:
        """读取 gui.yaml 的 `<i18n_group>.<i18n_key>` 结构。"""
        return read_file(self._gui_path)

    def _parse_task_groups(self, task: str, groups: DeepValue) -> tuple[str, ...]:
        if not isinstance(groups, list) or any(not isinstance(group, str) or not group for group in groups):
            message = f"task groups must contain non-empty strings: {task}"
            raise TypeError(message)
        parsed_groups = tuple(group for group in groups if isinstance(group, str))
        if len(set(parsed_groups)) != len(parsed_groups):
            message = f"duplicate task group: {task}"
            raise ValueError(message)
        if "Storage" in parsed_groups:
            message = f"task must not declare Storage: {task}"
            raise ValueError(message)
        unknown_groups = tuple(group for group in parsed_groups if group not in self.argument)
        if unknown_groups:
            message = f"unknown task group: {task}.{unknown_groups[0]}"
            raise ValueError(message)
        return parsed_groups

    def _parse_task_node(self, task: str, node: DeepValue) -> tuple[str | None, tuple[str, ...]]:
        if not isinstance(node, dict):
            message = f"task node must be a mapping: {task}"
            raise TypeError(message)
        node_data = cast("dict[str, DeepValue]", node)
        if set(node_data) - {"command", "groups"}:
            message = f"invalid task node: {task}"
            raise ValueError(message)
        groups = self._parse_task_groups(task, node_data.get("groups"))

        command = node_data.get("command")
        if command is None:
            return None, groups
        if not isinstance(command, str) or get_task_definition(command) is None:
            message = f"unknown task command: {command}"
            raise ValueError(message)
        if command_to_config_name(command) != task:
            message = f"task command does not match config node: {command} != {task}"
            raise ValueError(message)
        return command, groups

    @staticmethod
    def _validate_task_placement(task: str, command: str | None, groups: tuple[str, ...], *, is_tool: bool) -> None:
        if command is None:
            if task not in CONFIG_SCOPE_TASKS:
                message = f"unknown scope-only task: {task}"
                raise ValueError(message)
            if "Scheduler" in groups:
                message = f"scope-only task must not contain Scheduler: {task}"
                raise ValueError(message)
            if is_tool:
                message = f"scope-only task must not be on a tool page: {task}"
                raise ValueError(message)
            return

        definition = get_task_definition(command)
        if definition is None:
            message = f"unknown task command: {command}"
            raise ValueError(message)
        is_scheduled = "Scheduler" in groups
        if is_scheduled:
            if is_tool or definition.execution_mode is not ExecutionMode.SCHEDULED_JOB:
                message = f"task execution mode does not allow Scheduler: {task}"
                raise ValueError(message)
            return
        if is_tool:
            if definition.execution_mode is ExecutionMode.SCHEDULED_JOB:
                message = f"task execution mode does not allow tool page: {task}"
                raise ValueError(message)
            return
        message = f"executable task must be scheduled or tool: {task}"
        raise ValueError(message)

    def _iter_task_nodes(self) -> Iterator[tuple[str, str, str | None, tuple[str, ...]]]:
        commands: dict[str, str] = {}
        task_names: dict[str, str] = {}
        for task_group, group_data in self.task.items():
            if not isinstance(group_data, dict):
                message = f"task group must contain a task mapping: {task_group}"
                raise TypeError(message)
            tasks = group_data.get("tasks", {})
            if not isinstance(tasks, dict):
                message = f"task group must contain a task mapping: {task_group}"
                raise TypeError(message)
            task_nodes = cast("dict[str, DeepValue]", tasks)
            for task, node in task_nodes.items():
                if not isinstance(task, str):
                    message = f"task name must be a string: {task!r}"
                    raise TypeError(message)
                command, groups = self._parse_task_node(task, node)
                if command is not None and command in commands:
                    message = f"duplicate task command: {command} ({commands[command]}, {task})"
                    raise ValueError(message)
                if task in task_names:
                    message = f"duplicate task name: {task} ({task_names[task]}, {task_group})"
                    raise ValueError(message)
                self._validate_task_placement(task, command, groups, is_tool=group_data.get("page") == "tool")
                if command is not None:
                    commands[command] = task
                task_names[task] = task_group
                yield task_group, task, command, groups

    def _iter_task_argument_groups(self) -> Iterator[tuple[str, tuple[str, ...]]]:
        for _task_group, task, _command, groups in self._iter_task_nodes():
            # 给所有任务加入存储组，但不修改 task.yaml 的缓存数据。
            yield task, (*groups, "Storage")

    def _build_task_args(self) -> MutableDeepData:
        data: MutableDeepData = {}
        for task, groups in self._iter_task_argument_groups():
            for group in groups:
                deep_set(data, keys=[task, group], value=deepcopy(self.argument[group]))
        return data

    @staticmethod
    def _argument_descriptor(data: MutableDeepData, path: list[str]) -> dict[str, MutableDeepValue]:
        if not deep_exist(data, path):
            message = f"argument path does not exist: {'.'.join(path)}"
            raise KeyError(message)
        raw_argument = deep_get(data, keys=path)
        if not isinstance(raw_argument, dict):
            message = f"argument descriptor must be a mapping: {'.'.join(path)}"
            raise TypeError(message)
        argument = cast("dict[str, MutableDeepValue]", raw_argument)
        if "value" not in argument:
            message = f"argument descriptor has no value: {'.'.join(path)}"
            raise ValueError(message)
        return argument

    @staticmethod
    def _is_interval_argument(path: list[str]) -> bool:
        return len(path) == 3 and path[1] == "Scheduler" and path[2] in INTERVAL_ARGUMENTS

    @classmethod
    def _validate_value_type(cls, path: list[str], expected: DeepValue, value: DeepValue) -> None:
        if cls._is_interval_argument(path):
            if type(value) is int:
                if value < 0:
                    message = f"scheduler interval must be non-negative: {'.'.join(path)}"
                    raise ValueError(message)
                return
            if isinstance(value, str):
                start, separator, end = value.partition("-")
                if (
                    separator != "-"
                    or not start.isascii()
                    or not start.isdecimal()
                    or not end.isascii()
                    or not end.isdecimal()
                    or int(start) > int(end)
                ):
                    message = f"scheduler interval range is invalid at {'.'.join(path)}: {value!r}"
                    raise ValueError(message)
                return
            message = f"scheduler interval must be an int or minute range: {'.'.join(path)}"
            raise TypeError(message)

        if type(value) is not type(expected):
            message = (
                f"argument value type mismatch at {'.'.join(path)}: "
                f"expected {type(expected).__name__}, got {type(value).__name__}"
            )
            raise TypeError(message)

    @classmethod
    def _validate_options(
        cls,
        path: list[str],
        expected: DeepValue,
        raw_options: DeepValue,
        *,
        field: str,
    ) -> list[DeepValue]:
        if not isinstance(raw_options, list):
            message = f"override metadata {field} must be a list: {'.'.join(path)}"
            raise TypeError(message)
        options = cast("list[DeepValue]", raw_options)
        for option in options:
            cls._validate_value_type(path, expected, option)
        return options

    @classmethod
    def _validate_argument_value(
        cls,
        path: list[str],
        argument: dict[str, MutableDeepValue],
        value: DeepValue,
    ) -> None:
        expected = argument["value"]
        cls._validate_value_type(path, expected, value)
        raw_options = argument.get("option")
        if raw_options is None:
            return
        options = cls._validate_options(path, expected, raw_options, field="option")
        if value not in options:
            message = f"argument value is not an option at {'.'.join(path)}: {value!r}"
            raise ValueError(message)

    @staticmethod
    def _validate_string_metadata(path: list[str], field: str, value: DeepValue) -> str:
        if not isinstance(value, str) or not value:
            message = f"override metadata {field} must be non-empty text: {'.'.join(path)}"
            raise TypeError(message)
        return value

    @classmethod
    def _validate_override_scalar_metadata(
        cls,
        path: list[str],
        override: dict[str, MutableDeepValue],
    ) -> None:
        for field in ("mode", "validate"):
            if field in override:
                cls._validate_string_metadata(path, field, override[field])
        enumerated = (("type", WIDGET_TYPES), ("display", DISPLAY_MODES), ("valuetype", PIN_VALUE_TYPES))
        for field, allowed in enumerated:
            if field not in override:
                continue
            value = cls._validate_string_metadata(path, field, override[field])
            if value not in allowed:
                message = f"unsupported override metadata {field} at {'.'.join(path)}: {value!r}"
                raise ValueError(message)

    @classmethod
    def _validate_override_value_and_options(
        cls,
        path: list[str],
        argument: dict[str, MutableDeepValue],
        override: dict[str, MutableDeepValue],
    ) -> None:
        expected = argument["value"]
        value = override.get("value", expected)
        cls._validate_value_type(path, expected, value)
        raw_options = override.get("option", argument.get("option"))
        options: list[DeepValue] | None = None
        if raw_options is not None:
            options = cls._validate_options(path, expected, raw_options, field="option")
            if value not in options:
                message = f"override value is not an option at {'.'.join(path)}: {value!r}"
                raise ValueError(message)
        if "option_bold" in override:
            bold_options = cls._validate_options(path, expected, override["option_bold"], field="option_bold")
            if options is None or any(option not in options for option in bold_options):
                message = f"override option_bold must be contained in option: {'.'.join(path)}"
                raise ValueError(message)

    @classmethod
    def _validate_dict_override(
        cls,
        path: list[str],
        argument: dict[str, MutableDeepValue],
        override: dict[str, MutableDeepValue],
    ) -> None:
        unknown = set(override) - OVERRIDE_METADATA_FIELDS
        if unknown:
            message = f"unsupported override metadata at {'.'.join(path)}: {sorted(unknown)}"
            raise ValueError(message)
        cls._validate_override_scalar_metadata(path, override)
        cls._validate_override_value_and_options(path, argument, override)

    def _apply_default_values(self, data: MutableDeepData) -> None:
        for path, value in deep_iter(self.default, depth=3):
            argument = self._argument_descriptor(data, path)
            self._validate_argument_value(path, argument, value)
            deep_set(data, keys=[*path, "value"], value=cast("MutableDeepValue", value))

    @staticmethod
    def _normalized_override(value: dict[str, MutableDeepValue]) -> dict[str, MutableDeepValue]:
        value = deepcopy(value)
        typ = value.get("type")
        if typ not in {"state", "lock"} and deep_get(value, keys="value") is not None:
            deep_default(value, keys="display", value="hide")
        return value

    @staticmethod
    def _apply_override_value(data: MutableDeepData, path: list[str], value: DeepValue) -> None:
        if isinstance(value, dict):
            override = ConfigGenerator._normalized_override(cast("dict[str, MutableDeepValue]", value))
            for arg_k, arg_v in override.items():
                deep_set(data, keys=[*path, arg_k], value=arg_v)
            return

        deep_set(data, keys=[*path, "value"], value=cast("MutableDeepValue", value))
        deep_set(data, keys=[*path, "display"], value="hide")

    def _apply_override_values(self, data: MutableDeepData) -> None:
        for path, value in deep_iter(self.override, depth=3):
            argument = self._argument_descriptor(data, path)
            if isinstance(value, dict):
                self._validate_dict_override(path, argument, cast("dict[str, MutableDeepValue]", value))
            else:
                self._validate_argument_value(path, argument, value)
            self._apply_override_value(data, path, value)

    def _hide_task_commands(self, data: MutableDeepData) -> None:
        for task, _groups in self._iter_task_argument_groups():
            if deep_get(data, keys=f"{task}.Scheduler.Command"):
                deep_set(data, keys=f"{task}.Scheduler.Command.value", value=task)
                deep_set(data, keys=f"{task}.Scheduler.Command.display", value="hide")

    @cached_property
    @timer
    def args(self) -> MutableDeepData:
        """合并 task、argument、override 和 default 定义，生成标准化 args 数据。"""
        data = self._build_task_args()
        self._apply_default_values(data)
        self._apply_override_values(data)
        self._hide_task_commands(data)
        return data

    def _code_arguments(self) -> list[tuple[list[str], dict[str, MutableDeepValue], MutableDeepValue]]:
        arguments: list[tuple[list[str], dict[str, MutableDeepValue], MutableDeepValue]] = []
        for path, raw_data in deep_iter(self.argument, depth=2):
            if not isinstance(raw_data, dict):
                message = f"Invalid argument definition at {'.'.join(path)}"
                raise TypeError(message)
            data = cast("dict[str, MutableDeepValue]", raw_data)
            parsed = _parse_descriptor_value(path, data)
            arguments.append((path, data, parsed))
        return arguments

    @timer
    def generate_code(self) -> None:
        """根据标准化参数生成 config_generated.py。"""
        arguments = self._code_arguments()

        field_names = {path_to_arg(".".join(path)) for path, _data, _value in arguments}
        override_lines = ["class ConfigOverrides(TypedDict, total=False):"]
        visited_fields: set[str] = set()
        for name, _value, type_name in _manual_override_fields():
            override_lines.append(f"{GENERATED_INDENT}{name}: {type_name}")
            visited_fields.add(name)
        for path, data, value in arguments:
            name = path_to_arg(".".join(path))
            if name in visited_fields:
                continue
            none_type = "str | None" if data.get("type") in {"input", "textarea"} else "MutableDeepValue"
            override_lines.append(f"{GENERATED_INDENT}{name}: {_generated_type(value, none_type=none_type)}")
            visited_fields.add(name)

        record_lines = ["class RecordUpdates(TypedDict, total=False):"]
        for path, _data, value in arguments:
            name = path_to_arg(".".join(path))
            if name.endswith("Value") and name.replace("Value", "Record") in field_names:
                record_lines.append(f"{GENERATED_INDENT}{name}: {_generated_type(value)}")

        visited_group = set()
        visited_path = set()
        config_lines: list[str] = list(GENERATED_CONFIG_HEADER)
        for path, data, value in arguments:
            group = path[0]
            if group not in visited_group:
                config_lines.extend(("", f"    # 配置组 `{group}`"))
                visited_group.add(group)

            option: list[str] = []
            options = data.get("option")
            if isinstance(options, list):
                option = _generated_comment(", ".join(str(opt) for opt in options), prefix="可选项：")
            path_key = ".".join(path)
            config_lines.extend(option)
            config_lines.extend(_generated_value(path_to_arg(path_key), value))
            visited_path.add(path_key)

        lines = [*CONFIG_IMPORT, "", "", *override_lines, "", "", *record_lines, "", "", *config_lines]
        with Path(filepath_code()).open("w", encoding="utf-8", newline="") as f:
            f.writelines(f"{text}\n" for text in lines)

    @staticmethod
    def _load_i18n_words(
        new: MutableDeepData,
        old: DeepValue,
        keys: list[str],
        *,
        default: bool = True,
        words: Iterable[str] = ("name", "help"),
    ) -> None:
        for word in words:
            key = [*keys, str(word)]
            fallback = ".".join(key) if default else str(word)
            value = deep_get(old, keys=key, default=fallback)
            deep_set(new, keys=key, value=value)

    def _generate_task_i18n(self, new: MutableDeepData, old: DeepValue) -> None:
        for task_group, task, _command, _groups in self._iter_task_nodes():
            self._load_i18n_words(new, old, ["Menu", task_group])
            self._load_i18n_words(new, old, ["Task", task])

    def _generate_argument_i18n(self, new: MutableDeepData, old: DeepValue) -> None:
        visited_group = set()
        for path, data in deep_iter(self.argument, depth=2):
            if path[0] not in visited_group:
                self._load_i18n_words(new, old, [path[0], "_info"])
                visited_group.add(path[0])
            self._load_i18n_words(new, old, path)
            if isinstance(data, dict):
                options = data.get("option")
                if isinstance(options, list):
                    self._load_i18n_words(
                        new,
                        old,
                        path,
                        words=(str(option) for option in options),
                        default=False,
                    )

    def _event_names_by_directory(self) -> dict[str, str]:
        # 只保留国服名称，其他服务器分支不再参与生成。
        events: dict[str, str] = {}
        for pack in self.event_packs:
            names = [release for release in pack.releases if release.name_cn]
            if names:
                name = max(names, key=lambda release: release.order).name_cn
                if name is not None:
                    name = name.replace("、", "")
                    if pack.kind == "war_archives":
                        name = f"{ARCHIVES_PREFIX['cn']}{name}"
                    events[str(pack.pack_id)] = name
        return events

    def _generate_event_i18n(self, new: MutableDeepData) -> None:
        events = self._event_names_by_directory()
        for pack in sorted(self.event_packs, key=lambda item: str(item.pack_id)):
            pack_id = str(pack.pack_id)
            name = events.get(pack_id, pack_id)
            deep_set(new, keys=f"Campaign.Event.{pack_id}", value=name)

    def _generate_gui_i18n(self, new: MutableDeepData, old: DeepValue) -> None:
        for path, _ in deep_iter(self.gui, depth=2):
            group, key = path
            self._load_i18n_words(new, old, keys=["Gui", group], words=(key,))

    def generate_i18n_data(self, old: MutableDeepData) -> MutableDeepData:
        new: MutableDeepData = {}
        self._generate_task_i18n(new, old)
        self._generate_argument_i18n(new, old)
        self._generate_event_i18n(new)
        self._generate_gui_i18n(new, old)
        return new

    @timer
    def generate_i18n(self, lang: str) -> None:
        """用标准化参数补全旧翻译，并写回 `i18n/<lang>.json`。"""
        old = read_file(filepath_i18n(lang))
        write_file(filepath_i18n(lang), self.generate_i18n_data(old))

    @cached_property
    def menu(self) -> MutableDeepData:
        """根据 task.yaml 生成菜单数据。"""
        data: MutableDeepData = {}
        task_nodes = tuple(self._iter_task_nodes())
        for task_group in self.task:
            raw_menu = deep_get(self.task, keys=[task_group, "menu"])
            menu = raw_menu if isinstance(raw_menu, str) and raw_menu in {"collapse", "list"} else "collapse"
            deep_set(data, keys=[task_group, "menu"], value=menu)
            raw_page = deep_get(self.task, keys=[task_group, "page"])
            page = raw_page if isinstance(raw_page, str) and raw_page in {"setting", "tool"} else "setting"
            deep_set(data, keys=[task_group, "page"], value=page)
            tasks = [task for group, task, _command, _groups in task_nodes if group == task_group]
            deep_set(data, keys=[task_group, "tasks"], value=cast("MutableDeepValue", tasks))

        return data

    @cached_property
    @timer
    def event_packs(self) -> tuple[EventPack, ...]:
        return self._event_manifest_loader()

    @staticmethod
    def _latest_named_options(packs: tuple[EventPack, ...], kind: str) -> list[str]:
        releases: list[tuple[EventRelease, str]] = []
        for pack in packs:
            if not isinstance(pack, EventPack):
                message = "event_packs must contain EventPack instances"
                raise TypeError(message)
            if pack.kind != kind:
                continue
            for release in pack.releases:
                if not isinstance(release, EventRelease):
                    message = "pack releases must contain EventRelease instances"
                    raise TypeError(message)
                if release.name_cn is not None:
                    releases.append((release, str(pack.pack_id)))
        if not releases:
            return []
        latest_date = max(release.opened_on for release, _ in releases)
        latest = sorted(
            ((release.order, pack_id) for release, pack_id in releases if release.opened_on == latest_date),
            reverse=True,
        )
        return list(dict.fromkeys(pack_id for _, pack_id in latest))

    @staticmethod
    def _war_archive_options(packs: tuple[EventPack, ...]) -> list[str]:
        archives = []
        for pack in packs:
            if not isinstance(pack, EventPack):
                message = "event_packs must contain EventPack instances"
                raise TypeError(message)
            named = [release.order for release in pack.releases if release.name_cn is not None]
            if pack.kind == "war_archives" and named:
                archives.append((max(named), str(pack.pack_id)))
        archives.sort(reverse=True)
        return [pack_id for _, pack_id in archives]

    def _set_event_options(self, tasks: list[str], options: list[str], *, bold: bool) -> None:
        for task in tasks:
            deep_set(
                self.args,
                keys=f"{task}.Campaign.Event.option",
                value=cast("MutableDeepValue", options.copy()),
            )
            if bold:
                deep_set(
                    self.args,
                    keys=f"{task}.Campaign.Event.option_bold",
                    value=cast("MutableDeepValue", options.copy()),
                )

    def _set_event_value(self, tasks: list[str], options: list[str]) -> None:
        if not options:
            message = f"current activity manifest options are empty: {', '.join(tasks)}"
            raise ValueError(message)
        for task in tasks:
            deep_set(self.args, keys=f"{task}.Campaign.Event.value", value=options[0])

    @classmethod
    def _latest_pack(cls, packs: tuple[EventPack, ...], kind: str) -> EventPack | None:
        options = cls._latest_named_options(packs, kind)
        if not options:
            return None
        selected = options[0]
        return next(pack for pack in packs if str(pack.pack_id) == selected)

    @staticmethod
    def _event_default_stage(pack: EventPack) -> str | None:
        terminals = [rule.stage for rule in pack.policy.progressions if rule.next_stage is None]
        if terminals:
            return terminals[-1]
        if pack.stages:
            return pack.stages[-1].ref.stage_id
        return None

    @staticmethod
    def _event_progression_chains(pack: EventPack) -> list[list[str]]:
        rules = pack.policy.progressions
        if not rules:
            return []
        next_by_stage = {rule.stage: rule.next_stage for rule in rules}
        referenced = {rule.next_stage for rule in rules if rule.next_stage is not None}
        roots = [rule.stage for rule in rules if rule.stage not in referenced]
        chains: list[list[str]] = []
        for root in roots:
            chain = [root]
            while (next_stage := next_by_stage.get(chain[-1])) is not None:
                if next_stage in chain:
                    message = f"event progression cycle in {pack.pack_id}: {next_stage}"
                    raise ValueError(message)
                chain.append(next_stage)
            chains.append(chain)
        return chains

    def _set_latest_event_defaults(self, packs: tuple[EventPack, ...], options: list[str]) -> None:
        if not options:
            message = "current event manifest with a named release is required"
            raise ValueError(message)
        self._set_event_value(EVENTS, options)
        pack = self._latest_pack(packs, "event")
        if pack is None:
            message = "current event pack is required"
            raise ValueError(message)
        stage = self._event_default_stage(pack)
        if stage is None:
            message = f"current event pack has no default stage: {pack.pack_id}"
            raise ValueError(message)

        for task in EVENTS:
            deep_set(self.args, keys=f"{task}.Campaign.Name.value", value=stage)

        chains = self._event_progression_chains(pack)
        primary_chain = chains[-1] if chains else [stage]
        alternate_chain = chains[0] if chains else primary_chain
        deep_set(self.args, keys="Event2.Campaign.Name.value", value=alternate_chain[-1])

        stage_ids = {item.ref.stage_id for item in pack.stages}
        if "sp" in stage_ids:
            deep_set(self.args, keys="EventSp.Campaign.Name.value", value="sp")
        for task, chain in (
            ("EventA", primary_chain),
            ("EventB", primary_chain),
            ("EventC", alternate_chain),
            ("EventD", alternate_chain),
        ):
            deep_set(self.args, keys=f"{task}.EventDaily.StageFilter.value", value=" > ".join(chain))

    def _set_latest_archive_defaults(self, packs: tuple[EventPack, ...], options: list[str]) -> None:
        if not options:
            message = "current war archive manifest with a named release is required"
            raise ValueError(message)
        self._set_event_value(WAR_ARCHIVES, options)
        selected = options[0]
        pack = next((pack for pack in packs if str(pack.pack_id) == selected), None)
        if pack is None:
            message = f"current war archive pack is missing: {selected}"
            raise ValueError(message)
        stage = self._event_default_stage(pack)
        if stage is None:
            message = f"current war archive pack has no default stage: {pack.pack_id}"
            raise ValueError(message)
        deep_set(self.args, keys="WarArchives.Campaign.Name.value", value=stage)

    def _set_latest_raid_defaults(self, packs: tuple[EventPack, ...], options: list[str]) -> None:
        if not options:
            message = "current raid manifest with a named release is required"
            raise ValueError(message)
        self._set_event_value(RAIDS, options)
        pack = self._latest_pack(packs, "raid")
        if pack is None:
            message = "current raid pack is required"
            raise ValueError(message)
        definition = pack.activity
        if definition is None:
            message = f"current raid pack has no activity definition: {pack.pack_id}"
            raise ValueError(message)
        if not isinstance(definition, RaidDefinition):
            message = f"latest raid pack has no raid definition: {pack.pack_id}"
            raise TypeError(message)

        modes = [mode.value for mode in definition.modes]
        preferred = RaidMode.HARD if RaidMode.HARD in definition.modes else definition.modes[-1]
        deep_set(self.args, keys="Raid.Raid.Mode.option", value=cast("MutableDeepValue", modes))
        deep_set(self.args, keys="Raid.Raid.Mode.value", value=preferred.value)

        daily_modes = [mode.value for mode in definition.daily_modes]
        if not daily_modes:
            message = f"current raid pack has no daily mode: {pack.pack_id}"
            raise ValueError(message)
        daily_filter = [mode for mode in ("hard", "normal", "easy") if mode in daily_modes]
        if not daily_filter:
            daily_filter = [mode for mode in daily_modes if mode != "ex"] or daily_modes
        deep_set(self.args, keys="RaidDaily.RaidDaily.StageFilter.value", value=" > ".join(daily_filter))

    @staticmethod
    def _coalition_fleet_value(rule: CoalitionFleetRule) -> str:
        return "multi" if rule is CoalitionFleetRule.MULTI else "single"

    def _set_latest_coalition_defaults(self, packs: tuple[EventPack, ...], options: list[str]) -> None:
        if not options:
            message = "current coalition manifest with a named release is required"
            raise ValueError(message)
        self._set_event_value(COALITIONS, options)
        pack = self._latest_pack(packs, "coalition")
        if pack is None:
            message = "current coalition pack is required"
            raise ValueError(message)
        definition = pack.activity
        if definition is None:
            message = f"current coalition pack has no activity definition: {pack.pack_id}"
            raise ValueError(message)
        if not isinstance(definition, CoalitionDefinition):
            message = f"latest coalition pack has no coalition definition: {pack.pack_id}"
            raise TypeError(message)

        stages = list(definition.stages)
        primary_options = [stage.stage_id.value for stage in stages if stage.stage_id.value != "sp"]
        primary_candidates = [stage for stage in stages if stage.stage_id.value not in {"sp", "ex"}]
        primary = primary_candidates[-1] if primary_candidates else stages[0]
        deep_set(
            self.args,
            keys="Coalition.Coalition.Mode.option",
            value=cast("MutableDeepValue", primary_options),
        )
        deep_set(self.args, keys="Coalition.Coalition.Mode.value", value=primary.stage_id.value)
        deep_set(
            self.args,
            keys="Coalition.Coalition.Fleet.value",
            value=self._coalition_fleet_value(primary.fleet_rule),
        )

        special = next((stage for stage in stages if stage.stage_id.value == "sp"), None)
        if special is None:
            special = next(
                (stage for stage in reversed(stages) if stage.fleet_rule is CoalitionFleetRule.MULTI),
                stages[-1],
            )
        deep_set(
            self.args,
            keys="CoalitionSp.Coalition.Mode.option",
            value=cast("MutableDeepValue", [special.stage_id.value]),
        )
        deep_set(self.args, keys="CoalitionSp.Coalition.Mode.value", value=special.stage_id.value)
        deep_set(
            self.args,
            keys="CoalitionSp.Coalition.Fleet.value",
            value=self._coalition_fleet_value(special.fleet_rule),
        )

    def insert_event(self) -> None:
        """把最新活动 manifest 投影到 UI 参数和首次运行默认值。"""
        packs = tuple(self.event_packs)
        event_options = self._latest_named_options(packs, "event")
        raid_options = self._latest_named_options(packs, "raid")
        coalition_options = self._latest_named_options(packs, "coalition")
        archive_options = self._war_archive_options(packs)
        self._set_event_options(EVENTS, event_options, bold=True)
        self._set_event_options(GEMS_FARMINGS, ["campaign_main", *event_options], bold=False)
        self._set_event_options(RAIDS, raid_options, bold=True)
        self._set_event_options(COALITIONS, coalition_options, bold=True)
        self._set_event_options(WAR_ARCHIVES, archive_options, bold=False)
        self._set_latest_event_defaults(packs, event_options)
        self._set_latest_raid_defaults(packs, raid_options)
        self._set_latest_coalition_defaults(packs, coalition_options)
        self._set_latest_archive_defaults(packs, archive_options)

    @staticmethod
    def write_campaign_readme(packs: tuple[EventPack, ...]) -> None:
        atomic_write(PROJECT_ROOT / "campaign" / "Readme.md", render_campaign_readme(packs))

    @timer
    def generate(self) -> None:
        _ = self.args
        _ = self.menu
        packs = self.event_packs
        self.insert_event()
        self.write_campaign_readme(packs)
        write_file(filepath_args(), self.args)
        write_file(filepath_args("menu"), self.menu)
        self.generate_code()
        for lang in LANGUAGES:
            self.generate_i18n(lang)


def build_template() -> MutableDeepData:
    """只根据当前参数定义生成 template，不读取或迁移用户配置。"""

    args = read_file(filepath_args())
    template: MutableDeepData = {}
    for keys, raw_data in deep_iter(args, depth=3):
        if not isinstance(raw_data, dict):
            message = f"Invalid generated argument at {'.'.join(keys)}"
            raise TypeError(message)
        data = cast("dict[str, MutableDeepValue]", raw_data)
        parsed = _parse_descriptor_value(keys, data)
        deep_set(template, keys=keys, value=parsed)
    return template


def main() -> None:
    ConfigGenerator().generate()
    write_config_file("template", build_template())


if __name__ == "__main__":
    main()
