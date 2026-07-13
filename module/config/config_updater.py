import json
import textwrap
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from module.base.atomic import atomic_write
from module.base.decorator import cached_property
from module.base.timer import timer
from module.config.config_manual import ManualConfig
from module.config.deep import deep_default, deep_exist, deep_get, deep_iter, deep_set
from module.config.resolved import ConfigIssue, ConfigIssueReason
from module.config.utils import (
    LANGUAGES,
    data_to_type,
    filepath_args,
    filepath_argument,
    filepath_code,
    filepath_config,
    filepath_i18n,
    parse_value,
    path_to_arg,
    read_file,
    write_file,
)
from module.content.manifest import load_default_event_manifests, render_campaign_readme
from module.content.models import EventPack, EventRelease
from module.logger import logger
from module.task_registry import TASK_CATALOG, command_to_config_name, get_task_spec

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from module.config.deep import DeepValue, MutableDeepData, MutableDeepValue
    from module.config.utils import ArgumentDefinition

REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_IMPORT = """
import datetime
from typing import ClassVar, TypedDict

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


def _manual_override_fields() -> Iterator[tuple[str, MutableDeepValue]]:
    for name, value in vars(ManualConfig).items():
        if name.startswith("_") or callable(value) or isinstance(value, (classmethod, property, staticmethod)):
            continue
        if isinstance(value, (bool, int, float, str, datetime, list, tuple, dict)) or value is None:
            yield name, value


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
        if not isinstance(command, str) or get_task_spec(command) is None:
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

        definition = get_task_spec(command)
        if definition is None:
            message = f"unknown task command: {command}"
            raise ValueError(message)
        is_scheduled = "Scheduler" in groups
        if is_scheduled:
            if is_tool or definition.launch_mode not in {"scheduled", "both"}:
                message = f"task launch mode does not allow Scheduler: {task}"
                raise ValueError(message)
            return
        if is_tool:
            if definition.launch_mode not in {"direct", "both"}:
                message = f"task launch mode does not allow tool page: {task}"
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
    def _argument_value(argument: DeepValue) -> DeepValue:
        if isinstance(argument, dict):
            mapping = cast("dict[str, DeepValue]", argument)
            return mapping.get("value", None)
        return argument

    @staticmethod
    def _override_validation_value(argument: DeepValue, override: DeepValue) -> DeepValue:
        if isinstance(override, dict):
            # 字典覆盖通常用于改元数据，沿用旧语义，只用原参数值做合法性校验。
            return ConfigGenerator._argument_value(argument)
        return override

    @staticmethod
    def _has_incompatible_override_type(path: list[str], old_value: DeepValue, value: DeepValue) -> bool:
        return (
            type(value) is not type(old_value)
            and old_value is not None
            and path[2] not in ["SuccessInterval", "FailureInterval"]
        )

    @staticmethod
    def _has_invalid_override_option(argument: DeepValue, value: DeepValue) -> bool:
        if not isinstance(argument, dict):
            return False
        options = argument.get("option")
        return isinstance(options, list) and value not in cast("list[DeepValue]", options)

    def _can_apply_override(self, data: MutableDeepData, path: list[str], value: DeepValue) -> bool:
        # 检查参数是否存在。
        old = deep_get(data, keys=path, default=None)
        if old is None:
            logger.warning(f"`{'.'.join(path)}` is not a existing argument")
            return False

        old_value = self._argument_value(old)
        value = self._override_validation_value(old, value)
        if self._has_incompatible_override_type(path, old_value, value):
            logger.warning(
                f"`{value}` ({type(value)}) and `{'.'.join(path)}` ({type(old_value)}) are in different types"
            )
            return False
        if self._has_invalid_override_option(old, value):
            logger.warning(f"`{value}` is not an option of argument `{'.'.join(path)}`")
            return False
        return True

    def _apply_default_values(self, data: MutableDeepData) -> None:
        for path, value in deep_iter(self.default, depth=3):
            if self._can_apply_override(data, path, value):
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
            if self._can_apply_override(data, path, value):
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
            parsed = cast("MutableDeepValue", parse_value(data["value"], data=data))
            arguments.append((path, data, parsed))
        return arguments

    @timer
    def generate_code(self) -> None:
        """根据标准化参数生成 config_generated.py。"""
        arguments = self._code_arguments()

        field_names = {path_to_arg(".".join(path)) for path, _data, _value in arguments}
        override_lines = ["class ConfigOverrides(TypedDict, total=False):"]
        visited_fields: set[str] = set()
        for name, value in _manual_override_fields():
            override_lines.append(f"{GENERATED_INDENT}{name}: {_generated_type(value)}")
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

    def insert_event(self) -> None:
        packs = tuple(self.event_packs)
        self._set_event_options(EVENTS + GEMS_FARMINGS, self._latest_named_options(packs, "event"), bold=True)
        self._set_event_options(RAIDS, self._latest_named_options(packs, "raid"), bold=True)
        self._set_event_options(COALITIONS, self._latest_named_options(packs, "coalition"), bold=True)
        self._set_event_options(WAR_ARCHIVES, self._war_archive_options(packs), bold=False)

    @staticmethod
    def write_campaign_readme(packs: tuple[EventPack, ...]) -> None:
        atomic_write(REPO_ROOT / "campaign" / "Readme.md", render_campaign_readme(packs))

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


class ConfigUpdater:
    _args_path = filepath_args()

    @cached_property
    def args(self) -> MutableDeepData:
        return read_file(self._args_path)

    @staticmethod
    def _should_reset_config_value(
        value: DeepValue,
        data: dict[str, MutableDeepValue],
        *,
        is_template: bool,
    ) -> bool:
        typ = data["type"]
        display = data.get("display")
        return (
            is_template
            or value is None
            or value == ""
            or typ in ["lock", "state"]
            or (display == "hide" and typ != "stored")
        )

    @staticmethod
    def _record_issue(
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]],
        *,
        path: str,
        raw: DeepValue,
        resolved: DeepValue,
        reason: ConfigIssueReason,
    ) -> None:
        if raw == resolved or path in pending:
            return
        pending[path] = cast("MutableDeepValue", deepcopy(raw)), reason

    @staticmethod
    def _has_invalid_config_option(value: DeepValue, data: dict[str, MutableDeepValue]) -> bool:
        options = data.get("option")
        return isinstance(options, list) and value not in cast("list[DeepValue]", options)

    def _rebuild_config_from_args(
        self,
        old: MutableDeepData,
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]],
        *,
        is_template: bool,
    ) -> MutableDeepData:
        new: MutableDeepData = {}
        for keys, raw_data in deep_iter(self.args, depth=3):
            if not isinstance(raw_data, dict):
                message = f"Invalid generated argument at {'.'.join(keys)}"
                raise TypeError(message)
            data = cast("dict[str, MutableDeepValue]", raw_data)
            path = ".".join(keys)
            exists = deep_exist(old, keys)
            value = deep_get(old, keys=keys, default=data["value"])
            if self._should_reset_config_value(value, data, is_template=is_template):
                if exists and not is_template:
                    reason: ConfigIssueReason = (
                        "hidden_reset"
                        if data.get("display") == "hide" and data["type"] != "stored"
                        else "default_fallback"
                    )
                    self._record_issue(
                        pending,
                        path=path,
                        raw=value,
                        resolved=data["value"],
                        reason=reason,
                    )
                value = data["value"]
            elif self._has_invalid_config_option(value, data):
                self._record_issue(
                    pending,
                    path=path,
                    raw=value,
                    resolved=data["value"],
                    reason="invalid_option",
                )
            parsed = cast("MutableDeepValue", parse_value(value, data=data))
            deep_set(new, keys=keys, value=parsed)
        return new

    def _migrate_opsi_hazard_leveling_enable(
        self,
        old: MutableDeepData,
        new: MutableDeepData,
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]],
    ) -> None:
        source_path = "OpsiHazard1Leveling.Scheduler.Enable"
        if not deep_get(new, keys=source_path):
            return
        target_path = "OpsiMeowfficerFarming.Scheduler.Enable"
        raw = deep_get(new, keys=target_path, default=False)
        deep_set(new, keys=target_path, value=True)
        if deep_exist(old, source_path):
            self._record_issue(pending, path=target_path, raw=raw, resolved=True, reason="migration")

    def _migrate_mumu_executable_path(
        self,
        old: MutableDeepData,
        new: MutableDeepData,
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]],
    ) -> None:
        """把旧通用模拟器路径迁移到个人版 MuMu 可执行文件路径。"""
        source_path = "Alas.EmulatorInfo.path"
        target_path = "Alas.Emulator.MuMuPath"
        source = deep_get(old, keys=source_path, default=None)
        if not isinstance(source, str) or not source.strip():
            return
        raw = deep_get(old, keys=target_path, default=None)
        if isinstance(raw, str) and raw.strip():
            return
        deep_set(new, keys=target_path, value=source)
        self._record_issue(pending, path=target_path, raw=raw, resolved=source, reason="migration")

    def _refresh_latest_campaign_event(
        self,
        old: MutableDeepData,
        new: MutableDeepData,
        tasks: Iterable[str],
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]],
    ) -> None:
        for task in tasks:
            path = f"{task}.Campaign.Event"
            options = deep_get(self.args, keys=f"{path}.option", default=[])
            raw = deep_get(new, keys=path, default="campaign_main")
            if options and raw not in options:
                resolved = options[0]
                deep_set(new, keys=path, value=resolved)
                if deep_exist(old, path):
                    self._record_issue(pending, path=path, raw=raw, resolved=resolved, reason="migration")

    def _keep_war_archives_away_from_campaign_main(
        self,
        old: MutableDeepData,
        new: MutableDeepData,
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]],
    ) -> None:
        for task in WAR_ARCHIVES:
            path = f"{task}.Campaign.Event"
            options = deep_get(self.args, keys=f"{path}.option", default=[])
            raw = deep_get(new, keys=path, default="campaign_main")
            if options and raw == "campaign_main":
                resolved = options[0]
                deep_set(new, keys=path, value=resolved)
                if deep_exist(old, path):
                    self._record_issue(pending, path=path, raw=raw, resolved=resolved, reason="migration")

    def _replace_default_campaign_stage(
        self,
        old: MutableDeepData,
        new: MutableDeepData,
        tasks: Iterable[str],
        stage: str,
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]],
    ) -> None:
        for task in tasks:
            path = f"{task}.Campaign.Name"
            raw = deep_get(new, keys=path, default="12-4")
            if raw in ["7-2", "12-4"]:
                deep_set(new, keys=path, value=stage)
                if deep_exist(old, path):
                    self._record_issue(pending, path=path, raw=raw, resolved=stage, reason="migration")

    @staticmethod
    def _finalize_issues(
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]],
        resolved: MutableDeepData,
    ) -> tuple[ConfigIssue, ...]:
        return tuple(
            ConfigIssue(
                path=path,
                raw=deepcopy(raw),
                resolved=cast("MutableDeepValue", deepcopy(deep_get(resolved, keys=path))),
                reason=reason,
            )
            for path, (raw, reason) in pending.items()
        )

    def config_update_with_issues(
        self,
        old: MutableDeepData,
        *,
        is_template: bool = False,
    ) -> tuple[MutableDeepData, tuple[ConfigIssue, ...]]:
        """迁移配置并返回只读诊断；配置结果与 ``config_update()`` 完全相同。"""
        pending: dict[str, tuple[MutableDeepValue, ConfigIssueReason]] = {}
        new = self._rebuild_config_from_args(old, pending, is_template=is_template)
        if not is_template:
            self._migrate_mumu_executable_path(old, new, pending)
        self._migrate_opsi_hazard_leveling_enable(old, new, pending)

        # 更新到最新活动。
        if not is_template:
            self._refresh_latest_campaign_event(old, new, EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS, pending)
        # 作战档案不允许使用 campaign_main。
        self._keep_war_archives_away_from_campaign_main(old, new, pending)

        # 活动任务不允许默认关卡 12-4。
        self._replace_default_campaign_stage(old, new, EVENTS + WAR_ARCHIVES, "D3", pending)
        self._replace_default_campaign_stage(old, new, COALITIONS, "area1-normal", pending)

        resolved = self._override(new)
        return resolved, self._finalize_issues(pending, resolved)

    def config_update(self, old: MutableDeepData, *, is_template: bool = False) -> MutableDeepData:
        updated, _issues = self.config_update_with_issues(old, is_template=is_template)
        return updated

    @staticmethod
    def _override(data: MutableDeepData) -> MutableDeepData:
        return data

    @staticmethod
    def save_callback(key: str, _value: MutableDeepValue) -> Iterable[tuple[str, MutableDeepValue]]:
        """配置值保存回调；Emotion 的 `*Value` 变化时产出对应 `*Record` 路径和当前时间。"""
        if "Emotion" in key and "Value" in key:
            keys = key.split(".")
            keys[-1] = keys[-1].replace("Value", "Record")
            yield ".".join(keys), datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def read_file(self, config_name: str, *, is_template: bool = False) -> MutableDeepData:
        """读取并迁移 `./config/{config_name}.json`，只返回结果而不立即写回。"""
        data, _issues = self.read_file_with_issues(config_name, is_template=is_template)
        return data

    def read_file_with_issues(
        self,
        config_name: str,
        *,
        is_template: bool = False,
    ) -> tuple[MutableDeepData, tuple[ConfigIssue, ...]]:
        """读取并迁移配置，同时返回本次解析产生的诊断。"""
        old = read_file(filepath_config(config_name))
        return self.config_update_with_issues(old, is_template=is_template)

    @staticmethod
    def write_file(config_name: str, data: MutableDeepData) -> None:
        write_file(filepath_config(config_name), data)

    @timer
    def update_file(self, config_name: str, *, is_template: bool = False) -> MutableDeepData:
        data = self.read_file(config_name, is_template=is_template)
        self.write_file(config_name, data)
        return data


def main() -> None:
    ConfigGenerator().generate()
    ConfigUpdater().update_file("template", is_template=True)


if __name__ == "__main__":
    main()
