import json
import textwrap
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from module.base.atomic import atomic_write
from module.base.decorator import cached_property
from module.base.timer import timer
from module.config.deep import deep_default, deep_get, deep_iter, deep_set
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

REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_IMPORT = '''
import datetime
from typing import ClassVar

# 本文件由 module/config/config_updater.py 自动生成。
# 不要手动修改。


class GeneratedConfig:
    """
    Auto generated configuration
    """
'''.strip().split("\n")
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


def _generated_value(name: str, value) -> list[str]:
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
        return [f"{GENERATED_INDENT}{name}: ClassVar[dict[str, object]] = {value!r}"]
    if isinstance(value, list):
        return [f"{GENERATED_INDENT}{name}: ClassVar[list[object]] = {value!r}"]
    if isinstance(value, set):
        return [f"{GENERATED_INDENT}{name}: ClassVar[set[object]] = {value!r}"]
    return [f"{GENERATED_INDENT}{name} = {value!r}"]


class ConfigGenerator:
    @cached_property
    def argument(self):
        """读取 argument.yaml 并标准化为 `<group>.<argument>` 路径。

        每项包含 type 和 value；可选 option，datetime 项还包含 validate。
        """
        data = {}
        raw = read_file(filepath_argument("argument"))
        for path, raw_value in deep_iter(raw, depth=2):
            arg = {
                "type": "input",
                "value": "",
            }
            value = raw_value if isinstance(raw_value, dict) else {"value": raw_value}
            arg["type"] = data_to_type(value, arg=path[1])
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
    def task(self):
        """读取 task.yaml 的 `<task_group>.<task>.{command, groups}` 结构。"""
        return read_file(filepath_argument("task"))

    @cached_property
    def default(self):
        """读取 default.yaml 的 `<task>.<group>.<argument>` 默认值。"""
        return read_file(filepath_argument("default"))

    @cached_property
    def override(self):
        """读取 override.yaml 的 `<task>.<group>.<argument>` 覆盖值。"""
        return read_file(filepath_argument("override"))

    @cached_property
    def gui(self):
        """读取 gui.yaml 的 `<i18n_group>.<i18n_key>` 结构。"""
        return read_file(filepath_argument("gui"))

    def _parse_task_groups(self, task: str, groups: object) -> tuple[str, ...]:
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

    def _parse_task_node(self, task: str, node: object) -> tuple[str | None, tuple[str, ...]]:
        if not isinstance(node, dict):
            message = f"task node must be a mapping: {task}"
            raise TypeError(message)
        if set(node) - {"command", "groups"}:
            message = f"invalid task node: {task}"
            raise ValueError(message)
        groups = self._parse_task_groups(task, node.get("groups"))

        command = node.get("command")
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
            for task, node in tasks.items():
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

    def _iter_task_argument_groups(self):
        for _task_group, task, _command, groups in self._iter_task_nodes():
            # 给所有任务加入存储组，但不修改 task.yaml 的缓存数据。
            yield task, (*groups, "Storage")

    def _build_task_args(self):
        data = {}
        for task, groups in self._iter_task_argument_groups():
            for group in groups:
                deep_set(data, keys=[task, group], value=deepcopy(self.argument[group]))
        return data

    @staticmethod
    def _argument_value(argument):
        if isinstance(argument, dict):
            return argument.get("value", None)
        return argument

    @staticmethod
    def _override_validation_value(argument, override):
        if isinstance(override, dict):
            # 字典覆盖通常用于改元数据，沿用旧语义，只用原参数值做合法性校验。
            return ConfigGenerator._argument_value(argument)
        return override

    @staticmethod
    def _has_incompatible_override_type(path, old_value, value):
        return (
            type(value) is not type(old_value)
            and old_value is not None
            and path[2] not in ["SuccessInterval", "FailureInterval"]
        )

    @staticmethod
    def _has_invalid_override_option(argument, value):
        return isinstance(argument, dict) and "option" in argument and value not in argument["option"]

    def _can_apply_override(self, data, path, value):
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

    def _apply_default_values(self, data) -> None:
        for path, value in deep_iter(self.default, depth=3):
            if self._can_apply_override(data, path, value):
                deep_set(data, keys=[*path, "value"], value=value)

    @staticmethod
    def _normalized_override(value):
        value = deepcopy(value)
        typ = value.get("type")
        if typ not in {"state", "lock"} and deep_get(value, keys="value") is not None:
            deep_default(value, keys="display", value="hide")
        return value

    @staticmethod
    def _apply_override_value(data, path, value) -> None:
        if isinstance(value, dict):
            for arg_k, arg_v in ConfigGenerator._normalized_override(value).items():
                deep_set(data, keys=[*path, arg_k], value=arg_v)
            return

        deep_set(data, keys=[*path, "value"], value=value)
        deep_set(data, keys=[*path, "display"], value="hide")

    def _apply_override_values(self, data) -> None:
        for path, value in deep_iter(self.override, depth=3):
            if self._can_apply_override(data, path, value):
                self._apply_override_value(data, path, value)

    def _hide_task_commands(self, data) -> None:
        for task, _groups in self._iter_task_argument_groups():
            if deep_get(data, keys=f"{task}.Scheduler.Command"):
                deep_set(data, keys=f"{task}.Scheduler.Command.value", value=task)
                deep_set(data, keys=f"{task}.Scheduler.Command.display", value="hide")

    @cached_property
    @timer
    def args(self):
        """合并 task、argument、override 和 default 定义，生成标准化 args 数据。"""
        data = self._build_task_args()
        self._apply_default_values(data)
        self._apply_override_values(data)
        self._hide_task_commands(data)
        return data

    @timer
    def generate_code(self):
        """根据标准化参数生成 config_generated.py。"""
        visited_group = set()
        visited_path = set()
        lines: list[str] = list(CONFIG_IMPORT)
        for path, data in deep_iter(self.argument, depth=2):
            group = path[0]
            if group not in visited_group:
                lines.extend(("", f"    # 配置组 `{group}`"))
                visited_group.add(group)

            option = []
            if data.get("option"):
                option = _generated_comment(", ".join([str(opt) for opt in data["option"]]), prefix="可选项：")
            path_key = ".".join(path)
            lines.extend(option)
            lines.extend(_generated_value(path_to_arg(path_key), parse_value(data["value"], data=data)))
            visited_path.add(path_key)

        with Path(filepath_code()).open("w", encoding="utf-8", newline="") as f:
            f.writelines(f"{text}\n" for text in lines)

    @staticmethod
    def _load_i18n_words(new, old, keys, default=True, words=("name", "help")) -> None:
        for word in words:
            key = [*keys, str(word)]
            fallback = ".".join(key) if default else str(word)
            value = deep_get(old, keys=key, default=fallback)
            deep_set(new, keys=key, value=value)

    def _generate_task_i18n(self, new, old) -> None:
        for task_group, task, _command, _groups in self._iter_task_nodes():
            self._load_i18n_words(new, old, ["Menu", task_group])
            self._load_i18n_words(new, old, ["Task", task])

    def _generate_argument_i18n(self, new, old) -> None:
        visited_group = set()
        for path, data in deep_iter(self.argument, depth=2):
            if path[0] not in visited_group:
                self._load_i18n_words(new, old, [path[0], "_info"])
                visited_group.add(path[0])
            self._load_i18n_words(new, old, path)
            if "option" in data:
                self._load_i18n_words(new, old, path, words=data["option"], default=False)

    def _event_names_by_directory(self):
        # 只保留国服名称，其他服务器分支不再参与生成。
        events = {}
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

    def _generate_event_i18n(self, new) -> None:
        events = self._event_names_by_directory()
        for pack in sorted(self.event_packs, key=lambda item: str(item.pack_id)):
            pack_id = str(pack.pack_id)
            name = events.get(pack_id, pack_id)
            deep_set(new, keys=f"Campaign.Event.{pack_id}", value=name)

    def _generate_gui_i18n(self, new, old) -> None:
        for path, _ in deep_iter(self.gui, depth=2):
            group, key = path
            self._load_i18n_words(new, old, keys=["Gui", group], words=(key,))

    def generate_i18n_data(self, old):
        new = {}
        self._generate_task_i18n(new, old)
        self._generate_argument_i18n(new, old)
        self._generate_event_i18n(new)
        self._generate_gui_i18n(new, old)
        return new

    @timer
    def generate_i18n(self, lang):
        """用标准化参数补全旧翻译，并写回 `i18n/<lang>.json`。"""
        old = read_file(filepath_i18n(lang))
        write_file(filepath_i18n(lang), self.generate_i18n_data(old))

    @cached_property
    def menu(self):
        """根据 task.yaml 生成菜单数据。"""
        data = {}
        task_nodes = tuple(self._iter_task_nodes())
        for task_group in self.task:
            value = deep_get(self.task, keys=[task_group, "menu"])
            if value not in ["collapse", "list"]:
                value = "collapse"
            deep_set(data, keys=[task_group, "menu"], value=value)
            value = deep_get(self.task, keys=[task_group, "page"])
            if value not in ["setting", "tool"]:
                value = "setting"
            deep_set(data, keys=[task_group, "page"], value=value)
            tasks = [task for group, task, _command, _groups in task_nodes if group == task_group]
            deep_set(data, keys=[task_group, "tasks"], value=tasks)

        return data

    @cached_property
    @timer
    def event_packs(self) -> tuple[EventPack, ...]:
        return load_default_event_manifests()

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
            deep_set(self.args, keys=f"{task}.Campaign.Event.option", value=options.copy())
            if bold:
                deep_set(self.args, keys=f"{task}.Campaign.Event.option_bold", value=options.copy())

    def insert_event(self):
        packs = tuple(self.event_packs)
        self._set_event_options(EVENTS + GEMS_FARMINGS, self._latest_named_options(packs, "event"), bold=True)
        self._set_event_options(RAIDS, self._latest_named_options(packs, "raid"), bold=True)
        self._set_event_options(COALITIONS, self._latest_named_options(packs, "coalition"), bold=True)
        self._set_event_options(WAR_ARCHIVES, self._war_archive_options(packs), bold=False)

    @staticmethod
    def write_campaign_readme(packs: tuple[EventPack, ...]) -> None:
        atomic_write(REPO_ROOT / "campaign" / "Readme.md", render_campaign_readme(packs))

    @timer
    def generate(self):
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
    @cached_property
    def args(self):
        return read_file(filepath_args())

    @staticmethod
    def _should_reset_config_value(value, data, is_template):
        typ = data["type"]
        display = data.get("display")
        return (
            is_template
            or value is None
            or value == ""
            or typ in ["lock", "state"]
            or (display == "hide" and typ != "stored")
        )

    def _rebuild_config_from_args(self, old, is_template):
        new = {}
        for keys, data in deep_iter(self.args, depth=3):
            value = deep_get(old, keys=keys, default=data["value"])
            if self._should_reset_config_value(value, data, is_template):
                value = data["value"]
            value = parse_value(value, data=data)
            deep_set(new, keys=keys, value=value)
        return new

    @staticmethod
    def _migrate_opsi_hazard_leveling_enable(new):
        if deep_get(new, keys="OpsiHazard1Leveling.Scheduler.Enable"):
            deep_set(new, keys="OpsiMeowfficerFarming.Scheduler.Enable", value=True)

    def _refresh_latest_campaign_event(self, new, tasks):
        for task in tasks:
            opts = deep_get(self.args, keys=f"{task}.Campaign.Event.option", default=[])
            if opts and deep_get(new, keys=f"{task}.Campaign.Event", default="campaign_main") not in opts:
                deep_set(new, keys=f"{task}.Campaign.Event", value=opts[0])

    def _keep_war_archives_away_from_campaign_main(self, new):
        for task in WAR_ARCHIVES:
            opts = deep_get(self.args, keys=f"{task}.Campaign.Event.option", default=[])
            if opts and deep_get(new, keys=f"{task}.Campaign.Event", default="campaign_main") == "campaign_main":
                deep_set(new, keys=f"{task}.Campaign.Event", value=opts[0])

    @staticmethod
    def _replace_default_campaign_stage(new, tasks, stage):
        for task in tasks:
            if deep_get(new, keys=f"{task}.Campaign.Name", default="12-4") in ["7-2", "12-4"]:
                deep_set(new, keys=f"{task}.Campaign.Name", value=stage)

    def config_update(self, old, is_template=False):
        new = self._rebuild_config_from_args(old, is_template=is_template)
        self._migrate_opsi_hazard_leveling_enable(new)

        # 更新到最新活动。
        if not is_template:
            self._refresh_latest_campaign_event(new, EVENTS + RAIDS + COALITIONS + GEMS_FARMINGS)
        # 作战档案不允许使用 campaign_main。
        self._keep_war_archives_away_from_campaign_main(new)

        # 活动任务不允许默认关卡 12-4。
        self._replace_default_campaign_stage(new, EVENTS + WAR_ARCHIVES, "D3")
        self._replace_default_campaign_stage(new, COALITIONS, "area1-normal")

        return self._override(new)

    def _override(self, data):
        return data

    def save_callback(self, key: str, _value: object) -> Iterable[tuple[str, object]]:
        """配置值保存回调；Emotion 的 `*Value` 变化时产出对应 `*Record` 路径和当前时间。"""
        if "Emotion" in key and "Value" in key:
            keys = key.split(".")
            keys[-1] = keys[-1].replace("Value", "Record")
            yield ".".join(keys), datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def read_file(self, config_name, is_template=False):
        """读取并迁移 `./config/{config_name}.json`，只返回结果而不立即写回。"""
        old = read_file(filepath_config(config_name))
        return self.config_update(old, is_template=is_template)

    @staticmethod
    def write_file(config_name, data):
        write_file(filepath_config(config_name), data)

    @timer
    def update_file(self, config_name, is_template=False):
        data = self.read_file(config_name, is_template=is_template)
        self.write_file(config_name, data)
        return data


def main() -> None:
    ConfigGenerator().generate()
    ConfigUpdater().update_file("template", is_template=True)


if __name__ == "__main__":
    main()
