import argparse
import json
import queue
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, TypeIs

from pywebio import config as webconfig
from pywebio.input import file_upload, input_group, select
from pywebio.input import input as pywebio_input
from pywebio.output import (
    Output,
    clear,
    close_popup,
    popup,
    put_button,
    put_buttons,
    put_collapse,
    put_column,
    put_error,
    put_html,
    put_scope,
    put_table,
    put_text,
    toast,
    use_scope,
)
from pywebio.pin import pin, pin_on_change
from pywebio.session import download, go_app, info, local, register_thread, run_js, set_env

from module.base.atomic import atomic_failure_cleanup
from module.config.config import AzurLaneConfig, Function
from module.config.deep import DeepValue, MutableDeepData, MutableDeepValue, deep_get, deep_iter, deep_set
from module.config.resolved import resolve_task_config
from module.config.utils import (
    alas_instance,
    alas_template,
    dict_to_kv,
    filepath_args,
    filepath_config,
    read_file,
)
from module.logger import logger
from module.webui import lang
from module.webui.app_manage_utils import (
    format_export_config_filename,
    next_alas_instance_name,
    parse_import_config_name,
    validate_new_config_name,
)
from module.webui.base import Frame
from module.webui.fastapi import AsgiAppOptions, asgi_app
from module.webui.lang import t
from module.webui.overview_utils import split_overview_tasks
from module.webui.pin import call_pywebio_input, put_input, put_select
from module.webui.process_manager import ProcessManager
from module.webui.setting import State
from module.webui.setting_form_utils import GroupOutputContext, iter_group_output_kwargs
from module.webui.utils import (
    Icon,
    Switch,
    TaskHandler,
    add_css,
    filepath_css,
    get_alas_config_listen_path,
    get_localstorage,
    get_window_visibility_state,
    login,
    parse_pin_value,
    raise_exception,
    re_fullmatch,
    to_pin_value,
)
from module.webui.widgets import (
    BinarySwitchButton,
    BinarySwitchOptions,
    RichLog,
    put_icon_buttons,
    put_loading_text,
    put_none,
    put_output,
)

if TYPE_CHECKING:
    from starlette.applications import Starlette

    from module.config.config_updater import ConfigUpdater
    from module.config.resolved import ResolvedField, ResolvedTaskConfig


task_handler = TaskHandler()


class MenuDefinition(TypedDict):
    page: str
    menu: str
    tasks: list[str]


class ConfigChange(TypedDict):
    name: str
    value: MutableDeepValue


def _read_menu() -> dict[str, MenuDefinition]:
    raw_menu = read_file(filepath_args("menu"))
    menu: dict[str, MenuDefinition] = {}
    for name, raw_definition in raw_menu.items():
        if not isinstance(raw_definition, dict):
            message = f"Menu {name} must be a mapping"
            raise TypeError(message)
        page = raw_definition.get("page")
        mode = raw_definition.get("menu")
        raw_tasks = raw_definition.get("tasks")
        if not isinstance(page, str) or not isinstance(mode, str) or not isinstance(raw_tasks, list):
            message = f"Menu {name} has an invalid definition"
            raise TypeError(message)
        tasks: list[str] = []
        for task in raw_tasks:
            if not isinstance(task, str):
                message = f"Menu {name} task names must be strings"
                raise TypeError(message)
            tasks.append(task)
        menu[name] = MenuDefinition(page=page, menu=mode, tasks=tasks)
    return menu


def _is_deep_mapping(value: DeepValue) -> TypeIs[Mapping[str, DeepValue]]:
    return isinstance(value, Mapping)


def _copy_mutable_value(value: DeepValue) -> MutableDeepValue:
    if value is None or isinstance(value, (bool, int, float, str, datetime)):
        return value
    if _is_deep_mapping(value):
        return {key: _copy_mutable_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_copy_mutable_value(item) for item in value)
    return [_copy_mutable_value(item) for item in value]


class AlasGUI(Frame):
    ALAS_MENU: dict[str, MenuDefinition]
    ALAS_ARGS: MutableDeepData
    theme = "default"

    def initial(self) -> None:
        self.ALAS_MENU = _read_menu()
        self.ALAS_ARGS = read_file(filepath_args("args"))
        self._init_alas_config_watcher()

    def __init__(self) -> None:
        super().__init__()
        self.modified_config_queue: queue.Queue[ConfigChange] = queue.Queue()
        self.alas_name = ""
        self.alas_config = AzurLaneConfig("template")
        self.initial()
        self.rendered_cache: list[int] = []
        self.inst_cache: list[str] = []
        self.load_home = False
        self.af_flag = False

    @use_scope("aside", clear=True)
    def set_aside(self) -> None:
        current_date = datetime.now().date()
        if current_date.month == 4 and current_date.day == 1:
            self.af_flag = True

        put_icon_buttons(
            Icon.DEVELOP,
            buttons=[{"label": t("Gui.Aside.Home"), "value": "Home", "color": "aside"}],
            onclick=[self.ui_develop],
        )
        put_scope("aside_instance", [put_scope(f"alas-instance-{i}", []) for i, _ in enumerate(alas_instance())])
        self.set_aside_status()
        put_icon_buttons(
            Icon.SETTING,
            buttons=[
                {
                    "label": t("Gui.AddAlas.Manage"),
                    "value": "AddAlas",
                    "color": "aside",
                }
            ],
            onclick=[lambda: go_app("manage", new_window=False)],
        )

    @use_scope("aside_instance")
    def set_aside_status(self) -> None:
        flag = True

        def update(name: str, seq: int) -> int:
            with use_scope(f"alas-instance-{seq}", clear=True):
                icon_html = Icon.RUN
                rendered_state = ProcessManager.get_manager(name).state
                if rendered_state == 1 and self.af_flag:
                    icon_html = icon_html[:31] + " anim-rotate" + icon_html[31:]
                put_icon_buttons(
                    icon_html,
                    buttons=[{"label": name, "value": name, "color": "aside"}],
                    onclick=self.ui_alas,
                )
            return rendered_state

        if not len(self.rendered_cache) or self.load_home:
            # 添加/删除实例、首次启动 app.py、进入首页时重新加载。
            flag = False
            self.inst_cache.clear()
            self.inst_cache = alas_instance()
        if flag:
            for index, inst in enumerate(self.inst_cache):
                state = ProcessManager.get_manager(inst).state
                if state != self.rendered_cache[index]:
                    self.rendered_cache[index] = update(inst, index)
                    flag = False
        else:
            self.rendered_cache.clear()
            clear("aside_instance")
            for index, inst in enumerate(self.inst_cache):
                self.rendered_cache.append(update(inst, index))
            self.load_home = False
        if not flag:
            # 重绘会丢失焦点，这里恢复侧边栏按钮焦点。
            aside_name = get_localstorage("aside")
            self.active_button("aside", aside_name)

    @staticmethod
    @use_scope("header_status")
    def set_status(state: int) -> None:
        """状态值：1 运行，2 未运行，3 异常停止，0 隐藏，-1 不更新。"""
        if state == -1:
            return
        clear()

        if state == 1:
            put_loading_text(t("Gui.Status.Running"), color="success")
        elif state == 2:
            put_loading_text(t("Gui.Status.Inactive"), color="secondary", fill=True)
        elif state == 3:
            put_loading_text(t("Gui.Status.Warning"), shape="grow", color="warning")

    @classmethod
    def set_theme(cls, theme: str = "default") -> None:
        cls.theme = theme
        State.theme = theme
        webconfig(theme=theme)

    @use_scope("menu", clear=True)
    def alas_set_menu(self) -> None:
        put_buttons(
            [
                {
                    "label": t("Gui.MenuAlas.Overview"),
                    "value": "Overview",
                    "color": "menu",
                }
            ],
            onclick=[self.alas_overview],
        ).style("--menu-Overview--")

        for menu, task_data in self.ALAS_MENU.items():
            onclick = self.alas_daemon_overview if task_data.get("page") == "tool" else self.alas_set_group

            if task_data.get("menu") == "collapse":
                task_btn_list = [
                    put_buttons(
                        [
                            {
                                "label": t(f"Task.{task}.name"),
                                "value": task,
                                "color": "menu",
                            }
                        ],
                        onclick=onclick,
                    ).style(f"--menu-{task}--")
                    for task in task_data.get("tasks", [])
                ]
                put_collapse(title=t(f"Menu.{menu}.name"), content=task_btn_list)
            else:
                title = t(f"Menu.{menu}.name")
                put_html(
                    '<div class="hr-task-group-box">'
                    '<span class="hr-task-group-line"></span>'
                    f'<span class="hr-task-group-text">{title}</span>'
                    '<span class="hr-task-group-line"></span>'
                    "</div>"
                )
                for task in task_data.get("tasks", []):
                    put_buttons(
                        [
                            {
                                "label": t(f"Task.{task}.name"),
                                "value": task,
                                "color": "menu",
                            }
                        ],
                        onclick=onclick,
                    ).style(f"--menu-{task}--").style("padding-left: 0.75rem")

        self.alas_overview()

    @use_scope("content", clear=True)
    def alas_set_group(self, task: str) -> None:
        self.init_menu(name=task)
        self.set_title(t(f"Task.{task}.name"))

        put_scope("_groups", [put_none(), put_scope("groups"), put_scope("navigator")])

        config, snapshot = self._resolve_task_settings(task)
        task_help: str = t(f"Task.{task}.help")
        task_info = []
        if task_help:
            task_info.append(put_text(task_help).style("font-size: 1rem"))
        task_info.append(put_text(self._bind_chain_help(snapshot)).style("--arg-help--"))
        put_scope("group__info", scope="groups", content=task_info)

        resolved_fields = snapshot.fields
        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            if self.set_group(group, arg_dict, config, task, resolved_fields):
                self.set_navigator(group)

    def _resolve_task_settings(self, task: str) -> tuple[MutableDeepData, ResolvedTaskConfig]:
        config = self.alas_config.read_file(self.alas_name)
        snapshot = resolve_task_config(
            task_name=task,
            bind_chain=self.alas_config.task_bind_chain(task),
            data=config,
            overrides=self.alas_config.overridden,
        )
        return config, snapshot

    @staticmethod
    def _bind_chain_help(snapshot: ResolvedTaskConfig) -> str:
        return t("Gui.Text.ConfigBindChain", " → ".join(snapshot.bind_chain))

    @staticmethod
    @use_scope("groups")
    def set_group(
        group: list[str],
        arg_dict: DeepValue,
        config: MutableDeepData,
        task: str,
        resolved_fields: Mapping[str, ResolvedField],
    ) -> int:
        group_name = group[0]

        output_list: list[Output] = []
        for output_kwargs in iter_group_output_kwargs(
            GroupOutputContext(
                task=task,
                group_name=group_name,
                arg_dict=arg_dict,
                config=config,
                translate=t,
                resolved_fields=resolved_fields,
            )
        ):
            o = put_output(output_kwargs)
            if o is not None:
                # output 创建时会继承当前 scope，这里手动覆盖。
                o.spec["scope"] = f"#pywebio-scope-group_{group_name}"
                output_list.append(o)

        if not output_list:
            return 0

        with use_scope(f"group_{group_name}"):
            put_text(t(f"{group_name}._info.name"))
            group_help = t(f"{group_name}._info.help")
            if group_help != "":
                put_text(group_help)
            put_html('<hr class="hr-group">')
            for output in output_list:
                output.show()

        return len(output_list)

    @staticmethod
    @use_scope("navigator")
    def set_navigator(group: list[str]) -> None:
        js = f"""
            $("#pywebio-scope-groups").scrollTop(
                $("#pywebio-scope-group_{group[0]}").position().top
                + $("#pywebio-scope-groups").scrollTop() - 59
            )
        """
        put_button(
            label=t(f"{group[0]}._info.name"),
            onclick=lambda: run_js(js),
            color="navigator",
        )

    @use_scope("content", clear=True)
    def alas_overview(self) -> None:
        self.init_menu(name="Overview")
        self.set_title(t("Gui.MenuAlas.Overview"))

        put_scope("overview", [put_scope("schedulers"), put_scope("logs")])

        with use_scope("schedulers"):
            put_scope(
                "scheduler-bar",
                [
                    put_text(t("Gui.Overview.Scheduler")).style("font-size: 1.25rem; margin: auto .5rem auto;"),
                    put_scope("scheduler_btn"),
                ],
            )
            put_scope(
                "running",
                [
                    put_text(t("Gui.Overview.Running")),
                    put_html('<hr class="hr-group">'),
                    put_scope("running_tasks"),
                ],
            )
            put_scope(
                "pending",
                [
                    put_text(t("Gui.Overview.Pending")),
                    put_html('<hr class="hr-group">'),
                    put_scope("pending_tasks"),
                ],
            )
            put_scope(
                "waiting",
                [
                    put_text(t("Gui.Overview.Waiting")),
                    put_html('<hr class="hr-group">'),
                    put_scope("waiting_tasks"),
                ],
            )

        switch_scheduler = BinarySwitchButton(
            BinarySwitchOptions(
                label_on=t("Gui.Button.Stop"),
                label_off=t("Gui.Button.Start"),
                onclick_on=self.alas.stop,
                onclick_off=lambda: self.alas.start(None),
                get_state=lambda: self.alas.alive,
                color_on="off",
                color_off="on",
                scope="scheduler_btn",
            )
        )

        log = RichLog("log")

        with use_scope("logs"):
            put_scope(
                "log-bar",
                [
                    put_text(t("Gui.Overview.Log")).style("font-size: 1.25rem; margin: auto .5rem auto;"),
                    put_scope(
                        "log-bar-btns",
                        [
                            put_scope("log_scroll_btn"),
                        ],
                    ),
                ],
            )
            put_scope("log", [put_html("")])

        log.console.width = log.get_width()

        switch_log_scroll = BinarySwitchButton(
            BinarySwitchOptions(
                label_on=t("Gui.Button.ScrollON"),
                label_off=t("Gui.Button.ScrollOFF"),
                onclick_on=lambda: log.set_scroll(keep_bottom=False),
                onclick_off=lambda: log.set_scroll(keep_bottom=True),
                get_state=lambda: log.keep_bottom,
                color_on="on",
                color_off="off",
                scope="log_scroll_btn",
            )
        )

        self.task_handler.add(switch_scheduler.g(), 1, pending_delete=True)
        self.task_handler.add(switch_log_scroll.g(), 1, pending_delete=True)
        self.task_handler.add(self.alas_update_overview_task, 10, pending_delete=True)
        self.task_handler.add(log.put_log(self.alas), 0.25, pending_delete=True)

    def _init_alas_config_watcher(self) -> None:
        def put_queue(path: str, value: MutableDeepValue) -> None:
            self.modified_config_queue.put({"name": path, "value": value})

        for path in get_alas_config_listen_path(self.ALAS_ARGS):
            pin_on_change(name="_".join(path), onchange=partial(put_queue, ".".join(path)))
        logger.info("Init config watcher done.")

    def _alas_thread_update_config(self) -> None:
        modified = {}
        while self.alive:
            try:
                d = self.modified_config_queue.get(timeout=10)
                config_name = self.alas_name
                config_updater = self.alas_config
            except queue.Empty:
                continue
            modified[d["name"]] = d["value"]
            while True:
                try:
                    d = self.modified_config_queue.get(timeout=1)
                    modified[d["name"]] = d["value"]
                except queue.Empty:
                    self._save_config(modified, config_name, config_updater)
                    modified.clear()
                    break

    def _save_config(
        self,
        modified: dict[str, MutableDeepValue],
        config_name: str,
        config_updater: ConfigUpdater = State.config_updater,
    ) -> None:
        try:
            self._save_config_unchecked(modified, config_name, config_updater)
        except (KeyError, OSError, TypeError, ValueError) as e:
            logger.exception(e)
            toast("设置保存失败", duration=3, position="right", color="error")

    def _save_config_unchecked(
        self,
        modified: dict[str, MutableDeepValue],
        config_name: str,
        config_updater: ConfigUpdater,
    ) -> None:
        valid = []
        invalid = []
        config = config_updater.read_file(config_name)
        n = datetime.now()
        for p, v in deep_iter(config, depth=3):
            if p[-1].endswith("un") and isinstance(v, datetime) and (v - n).days >= 31:
                deep_set(config, p, "")
        for k, raw_value in modified.copy().items():
            raw_valuetype = deep_get(self.ALAS_ARGS, k + ".valuetype")
            valuetype = raw_valuetype if isinstance(raw_valuetype, str) else None
            v = parse_pin_value(raw_value, valuetype)
            raw_validate = deep_get(self.ALAS_ARGS, k + ".validate")
            validate = raw_validate if isinstance(raw_validate, str) else None
            if not str(v):
                default = _copy_mutable_value(deep_get(self.ALAS_ARGS, k + ".value"))
                modified[k] = default
                deep_set(config, k, default)
                valid.append(k)
                pin["_".join(k.split("."))] = default

            elif not validate or (isinstance(v, str) and re_fullmatch(validate, v)):
                deep_set(config, k, v)
                modified[k] = v
                valid.append(k)
                for set_key, set_value in config_updater.save_callback(k, v):
                    modified[set_key] = set_value
                    deep_set(config, set_key, set_value)
                    valid.append(set_key)
                    pin["_".join(set_key.split("."))] = to_pin_value(set_value)
            else:
                modified.pop(k)
                invalid.append(k)
                logger.warning(f"Invalid value {v} for key {k}, skip saving.")
        self.pin_remove_invalid_mark(valid)
        self.pin_set_invalid_mark(invalid)
        if modified:
            logger.info(f"Save config {filepath_config(config_name)}, {dict_to_kv(modified)}")
            config_updater.write_file(config_name, config)
            ProcessManager.get_manager(config_name).notify_configuration_changed()
            toast(
                t("Gui.Toast.ConfigSaved"),
                duration=1,
                position="right",
                color="success",
            )

    def put_overview_task(self, func: Function) -> None:
        with use_scope(f"overview-task_{func.command}"):
            put_column(
                [
                    put_text(t(f"Task.{func.command}.name")).style("--arg-title--"),
                    put_text(str(func.next_run)).style("--arg-help--"),
                ],
                size="auto auto",
            )
            put_button(
                label=t("Gui.Button.Setting"),
                onclick=lambda: self.alas_set_group(func.command),
                color="off",
            )

    def put_overview_task_section(self, scope: str, tasks: Sequence[Function]) -> None:
        clear(scope)
        with use_scope(scope):
            if not tasks:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")
                return
            for task in tasks:
                self.put_overview_task(task)

    def alas_update_overview_task(self) -> None:
        if not self.visible:
            return
        self.alas_config.load()
        self.alas_config.get_next_task()

        running, pending, waiting = split_overview_tasks(
            self.alas_config.pending_task,
            self.alas_config.waiting_task,
            is_alive=self.alas.alive,
        )
        self.put_overview_task_section("running_tasks", running)
        self.put_overview_task_section("pending_tasks", pending)
        self.put_overview_task_section("waiting_tasks", waiting)

    @use_scope("content", clear=True)
    def alas_daemon_overview(self, task: str) -> None:
        self.init_menu(name=task)
        self.set_title(t(f"Task.{task}.name"))

        log = RichLog("log")

        if self.is_mobile:
            put_scope(
                "daemon-overview",
                [
                    put_scope("scheduler-bar"),
                    put_scope("groups"),
                    put_scope("log-bar"),
                    put_scope("log", [put_html("")]),
                ],
            )
        else:
            put_scope(
                "daemon-overview",
                [
                    put_none(),
                    put_scope(
                        "_daemon",
                        [
                            put_scope(
                                "_daemon_upper",
                                [put_scope("scheduler-bar"), put_scope("log-bar")],
                            ),
                            put_scope("groups"),
                            put_scope("log", [put_html("")]),
                        ],
                    ),
                    put_none(),
                ],
            )

        log.console.width = log.get_width()

        with use_scope("scheduler-bar"):
            put_text(t("Gui.Overview.Scheduler")).style("font-size: 1.25rem; margin: auto .5rem auto;")
            put_scope("scheduler_btn")

        switch_scheduler = BinarySwitchButton(
            BinarySwitchOptions(
                label_on=t("Gui.Button.Stop"),
                label_off=t("Gui.Button.Start"),
                onclick_on=self.alas.stop,
                onclick_off=lambda: self.alas.start(task),
                get_state=lambda: self.alas.alive,
                color_on="off",
                color_off="on",
                scope="scheduler_btn",
            )
        )

        with use_scope("log-bar"):
            put_text(t("Gui.Overview.Log")).style("font-size: 1.25rem; margin: auto .5rem auto;")
            put_scope(
                "log-bar-btns",
                [
                    put_scope("log_scroll_btn"),
                ],
            )

        switch_log_scroll = BinarySwitchButton(
            BinarySwitchOptions(
                label_on=t("Gui.Button.ScrollON"),
                label_off=t("Gui.Button.ScrollOFF"),
                onclick_on=lambda: log.set_scroll(keep_bottom=False),
                onclick_off=lambda: log.set_scroll(keep_bottom=True),
                get_state=lambda: log.keep_bottom,
                color_on="on",
                color_off="off",
                scope="log_scroll_btn",
            )
        )

        config, snapshot = self._resolve_task_settings(task)
        put_text(self._bind_chain_help(snapshot), scope="groups").style("--arg-help--")
        resolved_fields = snapshot.fields
        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            if group[0] == "Storage":
                continue
            self.set_group(group, arg_dict, config, task, resolved_fields)

        run_js(
            """
            $("#pywebio-scope-log").css(
                "grid-row-start",
                -2 - $("#pywebio-scope-_daemon").children().filter(
                    function(){
                        return $(this).css("display") === "none";
                    }
                ).length
            );
            $("#pywebio-scope-log").css(
                "grid-row-end",
                -1
            );
        """
        )

        self.task_handler.add(switch_scheduler.g(), 1, pending_delete=True)
        self.task_handler.add(switch_log_scroll.g(), 1, pending_delete=True)
        self.task_handler.add(log.put_log(self.alas), 0.25, pending_delete=True)

    @use_scope("menu", clear=True)
    def dev_set_menu(self) -> None:
        self.init_menu(collapse_menu=False, name="Develop")

        put_button(
            label=t("Gui.MenuDevelop.HomePage"),
            onclick=self.show,
            color="menu",
        ).style("--menu-HomePage--")

        put_button(
            label=t("Gui.MenuDevelop.Utils"),
            onclick=self.dev_utils,
            color="menu",
        ).style("--menu-Utils--")

    @use_scope("content", clear=True)
    def dev_utils(self) -> None:
        self.init_menu(name="Utils")
        self.set_title(t("Gui.MenuDevelop.Utils"))
        put_button(label="抛出异常", onclick=raise_exception)

    def ui_develop(self) -> None:
        if not self.is_mobile:
            self.show()
            return
        self.init_aside(name="Home")
        self.set_title(t("Gui.Aside.Home"))
        self.dev_set_menu()
        self.alas_name = ""
        if hasattr(self, "alas"):
            del self.alas
        self.state_switch.switch()

    def ui_alas(self, config_name: str) -> None:
        if config_name == self.alas_name:
            self.expand_menu()
            return
        self.init_aside(name=config_name)
        clear("content")
        self.alas_name = config_name
        self.alas = ProcessManager.get_manager(config_name)
        self.alas_config = AzurLaneConfig(config_name)
        self.state_switch.switch()
        self.initial()
        self.alas_set_menu()

    def ui_add_alas(self) -> None:
        with popup(t("Gui.AddAlas.PopupTitle")) as s:

            def get_unused_name() -> str:
                return next_alas_instance_name(alas_instance())

            def add() -> None:
                name = pin["AddAlas_name"]
                origin = pin["AddAlas_copyfrom"]

                if name in alas_instance():
                    err = "Gui.AddAlas.FileExist"
                elif set(name) & set(".\\/:*?\"'<>|"):
                    err = "Gui.AddAlas.InvalidChar"
                elif name.lower().startswith("template"):
                    err = "Gui.AddAlas.InvalidPrefixTemplate"
                else:
                    err = ""
                if err:
                    clear(s)
                    put(name, origin)
                    put_error(t(err), scope=s)
                    return

                r = State.config_updater.read_file(origin, is_template=origin == "template")
                State.config_updater.write_file(name, r)
                self.set_aside()
                self.active_button("aside", self.alas_name)
                close_popup()

            def put(name: str | None = None, origin: str | None = None) -> None:
                put_input(
                    name="AddAlas_name",
                    label=t("Gui.AddAlas.NewName"),
                    value=name or get_unused_name(),
                    scope=s,
                )
                put_select(
                    name="AddAlas_copyfrom",
                    label=t("Gui.AddAlas.CopyFrom"),
                    options=alas_template() + alas_instance(),
                    value=origin or "template",
                    scope=s,
                )
                put_buttons(
                    buttons=[
                        {"label": t("Gui.AddAlas.Confirm"), "value": "confirm"},
                        {"label": t("Gui.AddAlas.Manage"), "value": "manage"},
                    ],
                    onclick=[
                        add,
                        lambda: go_app("manage", new_window=False),
                    ],
                    scope=s,
                )

            put()

    def show(self) -> None:
        self._show()
        self.load_home = True
        self.set_aside()
        self.init_aside(name="Home")
        self.dev_set_menu()
        self.init_menu(name="HomePage")
        self.alas_name = ""
        if hasattr(self, "alas"):
            del self.alas
        self.set_status(0)

        def set_theme(theme: str) -> None:
            self.set_theme(theme)
            run_js("location.reload()")

        with use_scope("content"):
            put_text("更改主题").style("text-align: center")
            put_buttons(
                [
                    {"label": "亮色", "value": "default", "color": "light"},
                    {"label": "暗色", "value": "dark", "color": "dark"},
                ],
                onclick=set_theme,
            ).style("text-align: center")

    def run(self) -> None:
        set_env(title="Alas", output_animation=False)
        add_css(filepath_css("alas"))
        if self.is_mobile:
            add_css(filepath_css("alas-mobile"))
        else:
            add_css(filepath_css("alas-pc"))

        if self.theme == "dark":
            add_css(filepath_css("dark-alas"))
        else:
            add_css(filepath_css("light-alas"))

        # 连接丢失时自动刷新。
        # 开发时可在控制台执行 `reload=0` 禁用。
        run_js(
            """
        reload = 1;
        WebIO._state.CurrentSession.on_session_close(
            ()=>{
                setTimeout(
                    ()=>{
                        if (reload == 1){
                            location.reload();
                        }
                    }, 4000
                )
            }
        );
        """
        )

        aside = get_localstorage("aside")
        self.show()

        self._init_alas_config_watcher()

        save_config_thread = threading.Thread(target=self._alas_thread_update_config)
        register_thread(save_config_thread)
        save_config_thread.start()

        visibility_state_switch = Switch(
            status={
                True: [
                    lambda: setattr(self, "visible", True),
                    lambda: self.alas_update_overview_task() if self.page == "Overview" else None,
                    lambda: self.task_handler.set_current_task_delay(15),
                ],
                False: [
                    lambda: setattr(self, "visible", False),
                    lambda: self.task_handler.set_current_task_delay(1),
                ],
            },
            get_state=get_window_visibility_state,
            name="visibility_state",
        )

        self.state_switch = Switch(
            status=self.set_status,
            get_state=lambda: getattr(getattr(self, "alas", -1), "state", 0),
            name="state",
        )

        self.task_handler.add(self.state_switch.g(), 2)
        self.task_handler.add(self.set_aside_status, 2)
        self.task_handler.add(visibility_state_switch.g(), 15)
        self.task_handler.start()

        if aside is not None and aside != "Home":
            self.ui_alas(aside)


def app_manage() -> None:
    def _import() -> None:
        resp = file_upload(
            label=t("Gui.AppManage.Import"),
            placeholder=t("Gui.Text.ChooseFile"),
            help_text=t("Gui.AppManage.OverrideWarning"),
            accept=".json",
            required=False,
            max_size="1M",
        )

        if resp is None:
            return

        file: bytes = resp["content"]
        file_name: str = resp["filename"]

        config_name = parse_import_config_name(file_name)
        config = json.loads(file.decode(encoding="utf-8"))
        State.config_updater.write_file(config_name, config)
        toast(t("Gui.AppManage.ImportSuccess"), color="success")

        _show_table()

    def _export(config_name: str) -> None:
        filename = format_export_config_filename(config_name)
        download(filename, Path(filepath_config(config_name)).read_bytes())

    def _new() -> None:
        def validate(s: str) -> str | None:
            key = validate_new_config_name(s, alas_instance())
            return t(key) if key else None

        resp = input_group(
            label=t("Gui.AppManage.TitleNew"),
            inputs=[
                pywebio_input(
                    label=t("Gui.AppManage.NewName"),
                    name="config_name",
                    value=next_alas_instance_name(alas_instance()),
                    validate=validate,
                ),
                call_pywebio_input(
                    select,
                    label=t("Gui.AppManage.CopyFrom"),
                    name="copy_from",
                    options=alas_template() + alas_instance(),
                    value="template",
                ),
            ],
            cancelable=True,
        )

        if resp is None:
            return

        config_name = resp["config_name"]
        origin = resp["copy_from"]

        r = State.config_updater.read_file(origin, is_template=origin == "template")
        State.config_updater.write_file(config_name, r)
        toast(t("Gui.AppManage.NewSuccess"), color="success")
        _show_table()

    def _show_table() -> None:
        clear("config_table")
        put_table(
            tdata=[
                (
                    name,
                    put_buttons(
                        buttons=[
                            {"label": t("Gui.AppManage.Export"), "value": name},
                        ],
                        onclick=[
                            partial(_export, name),
                        ],
                        group=True,
                        small=True,
                    ),
                )
                for name in alas_instance()
            ],
            header=[
                t("Gui.AppManage.Name"),
                t("Gui.AppManage.Actions"),
            ],
            scope="config_table",
        )

    set_env(title="Alas", output_animation=False)
    run_js("$('head').append('<style>.footer{display:none}</style>')")

    put_html(f"<h2>{t('Gui.AppManage.PageTitle')}</h2>")
    put_scope("config_table")
    put_buttons(
        buttons=[
            {
                "label": t("Gui.AppManage.New"),
                "value": "new",
            },
            {"label": t("Gui.AppManage.Import"), "value": "import"},
            {"label": t("Gui.AppManage.Back"), "value": "back"},
        ],
        onclick=[
            _new,
            _import,
            partial(go_app, "index", new_window=False),
        ],
    )
    _show_table()


def debug() -> None:
    """交互式 Python 调试入口。

    $ python
    >>> from module.webui.app import *
    >>> debug()
    >>>
    """
    startup()
    AlasGUI().run()


def startup() -> None:
    State.init()
    lang.reload()
    task_handler.start()


def clearup() -> None:
    """必须在 uvicorn 重新加载 app 前执行。"""
    logger.info("Start clearup")
    ProcessManager.stop_all()
    State.clearup()
    task_handler.stop()
    logger.info("Alas closed.")


def app() -> Starlette:
    parser = argparse.ArgumentParser(description="Alas WebUI 服务")
    parser.add_argument("-k", "--key", type=str, help="WebUI 密码，默认不启用。")
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="启动时自动运行指定配置。",
    )
    args, _ = parser.parse_known_args()

    AlasGUI.set_theme()
    key = args.key
    instances = args.run or []

    logger.hr("Webui configs")
    logger.attr("Theme", AlasGUI.theme)
    logger.attr("Password", bool(key))

    atomic_failure_cleanup("./config")

    def index() -> None:
        if key is not None and not login(key):
            logger.warning(f"{info.user_ip} login failed.")
            time.sleep(1.5)
            run_js("location.reload();")
            return
        gui = AlasGUI()
        local.gui = gui
        gui.run()

    def manage() -> None:
        if key is not None and not login(key):
            logger.warning(f"{info.user_ip} login failed.")
            time.sleep(1.5)
            run_js("location.reload();")
            return
        app_manage()

    return asgi_app(
        applications=[index, manage],
        options=AsgiAppOptions(debug=True),
        on_startup=[
            startup,
            lambda: ProcessManager.restart_processes(instances=instances),
        ],
        on_shutdown=[clearup],
    )
