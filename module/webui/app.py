import argparse
import json
import queue
import threading
import time
from datetime import datetime
from functools import partial
from pathlib import Path

# 先导入伪 PIL 模块，避免 pywebio 拉起不需要的 PIL。
from module.webui.fake_pil_module import import_fake_pil_module

import_fake_pil_module()

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
    put_markdown,
    put_scope,
    put_table,
    put_text,
    toast,
    use_scope,
)
from pywebio.pin import pin, pin_on_change
from pywebio.session import download, go_app, info, local, register_thread, run_js, set_env

import module.webui.lang as lang
from module.config.config import AzurLaneConfig, Function
from module.config.deep import deep_get, deep_iter, deep_set
from module.config.server import to_server
from module.config.utils import (
    alas_instance,
    alas_template,
    dict_to_kv,
    filepath_args,
    filepath_config,
    read_file,
)
from module.logger import logger
from module.ocr.rpc import start_ocr_server_process, stop_ocr_server_process
from module.submodule.submodule import load_config
from module.submodule.utils import get_config_mod
from module.webui.base import Frame
from module.webui.discord_presence import close_discord_rpc, init_discord_rpc
from module.webui.fastapi import asgi_app
from module.webui.lang import t
from module.webui.patch import fix_py37_subprocess_communicate, patch_executor, patch_mimetype
from module.webui.pin import put_input, put_select
from module.webui.process_manager import ProcessManager
from module.webui.setting import State
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
    RichLog,
    T_Output_Kwargs,
    put_icon_buttons,
    put_loading_text,
    put_none,
    put_output,
)

patch_executor()
patch_mimetype()
fix_py37_subprocess_communicate()
task_handler = TaskHandler()


class AlasGUI(Frame):
    ALAS_MENU: dict[str, dict[str, list[str]]]
    ALAS_ARGS: dict[str, dict[str, dict[str, dict[str, str]]]]
    theme = "default"

    def initial(self) -> None:
        self.ALAS_MENU = read_file(filepath_args("menu", self.alas_mod))
        self.ALAS_ARGS = read_file(filepath_args("args", self.alas_mod))
        self._init_alas_config_watcher()

    def __init__(self) -> None:
        super().__init__()
        # 已修改的键，值来自 pin_wait_change()。
        self.modified_config_queue = queue.Queue()
        # Alas 配置名。
        self.alas_name = ""
        self.alas_mod = "alas"
        self.alas_config = AzurLaneConfig("template")
        self.initial()
        # 渲染状态缓存。
        self.rendered_cache = []
        self.inst_cache = []
        self.load_home = False
        self.af_flag = False

    @use_scope("aside", clear=True)
    def set_aside(self) -> None:
        # TODO: update put_icon_buttons()

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

        def update(name, seq):
            with use_scope(f"alas-instance-{seq}", clear=True):
                icon_html = Icon.RUN
                rendered_state = ProcessManager.get_manager(inst).state
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
                # 检查状态变化。
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

    @use_scope("header_status")
    def set_status(self, state: int) -> None:
        """
        参数：
            state (int):
                1：运行中。
                2：未运行。
                3：警告，异常停止。
                4：更新时停止。
                0：隐藏。
                -1：状态未变化。
        """
        if state == -1:
            return
        clear()

        if state == 1:
            put_loading_text(t("Gui.Status.Running"), color="success")
        elif state == 2:
            put_loading_text(t("Gui.Status.Inactive"), color="secondary", fill=True)
        elif state == 3:
            put_loading_text(t("Gui.Status.Warning"), shape="grow", color="warning")
        elif state == 4:
            put_loading_text(t("Gui.Status.Updating"), shape="grow", color="success")

    @classmethod
    def set_theme(cls, theme="default") -> None:
        cls.theme = theme
        State.deploy_config.Theme = theme
        State.theme = theme
        webconfig(theme=theme)

    @use_scope("menu", clear=True)
    def alas_set_menu(self) -> None:
        """
        设置菜单。
        """
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
            _onclick = self.alas_daemon_overview if task_data.get("page") == "tool" else self.alas_set_group

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
                        onclick=_onclick,
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
                        onclick=_onclick,
                    ).style(f"--menu-{task}--").style("padding-left: 0.75rem")

        self.alas_overview()

    @use_scope("content", clear=True)
    def alas_set_group(self, task: str) -> None:
        """
        根据字典设置参数组。
        """
        self.init_menu(name=task)
        self.set_title(t(f"Task.{task}.name"))

        put_scope("_groups", [put_none(), put_scope("groups"), put_scope("navigator")])

        task_help: str = t(f"Task.{task}.help")
        if task_help:
            put_scope(
                "group__info",
                scope="groups",
                content=[put_text(task_help).style("font-size: 1rem")],
            )

        config = self.alas_config.read_file(self.alas_name)
        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            if self.set_group(group, arg_dict, config, task):
                self.set_navigator(group)

    @use_scope("groups")
    def set_group(self, group, arg_dict, config, task):
        group_name = group[0]
        server = to_server(deep_get(config, "Alas.Emulator.PackageName", "cn"))

        output_list: list[Output] = []
        for arg, arg_config in deep_iter(arg_dict, depth=1):
            output_kwargs: T_Output_Kwargs = arg_config.copy()

            # 跳过隐藏项。
            display: str | None = output_kwargs.pop("display", None)
            if display == "hide":
                continue
            # 禁用项。
            if display == "disabled":
                output_kwargs["disabled"] = True
            # 输出类型。
            output_kwargs["widget_type"] = output_kwargs.pop("type")

            arg_name = arg[0]  # [arg_name,]
            # 内部 pin 组件名。
            output_kwargs["name"] = f"{task}_{group_name}_{arg_name}"
            # 显示标题。
            output_kwargs["title"] = t(f"{group_name}.{arg_name}.name")

            # 从配置中读取值。
            value = deep_get(config, [task, group_name, arg_name], output_kwargs["value"])
            # datetime 需要先转成字符串才能给 pin 使用。
            value = str(value) if isinstance(value, datetime) else value
            # 默认值。
            output_kwargs["value"] = value
            # 可选项。
            options = output_kwargs.pop("option", [])
            server_options = output_kwargs.get(f"option_{server}")
            if output_kwargs["widget_type"] == "select" and isinstance(server_options, list) and server_options:
                options = server_options
            output_kwargs["options"] = options
            if (
                task == "GemsFarming"
                and group_name == "Campaign"
                and arg_name == "Event"
                and output_kwargs["widget_type"] == "select"
                and len(options) == 1
            ):
                continue
            if output_kwargs["widget_type"] == "select" and len(options) == 1:
                only_option = options[0]
                if only_option in output_kwargs.get("option_bold", []):
                    output_kwargs["widget_type"] = "state"
            # 可选项标签。
            options_label = [t(f"{group_name}.{arg_name}.{opt}") for opt in options]
            output_kwargs["options_label"] = options_label
            # 帮助文本。
            arg_help = t(f"{group_name}.{arg_name}.help")
            if arg_help == "" or not arg_help:
                arg_help = None
            output_kwargs["help"] = arg_help
            # 无效输入反馈。
            output_kwargs["invalid_feedback"] = t("Gui.Text.InvalidFeedBack", value)

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

    @use_scope("navigator")
    def set_navigator(self, group):
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
            label_on=t("Gui.Button.Stop"),
            label_off=t("Gui.Button.Start"),
            onclick_on=self.alas.stop,
            onclick_off=lambda: self.alas.start(None),
            get_state=lambda: self.alas.alive,
            color_on="off",
            color_off="on",
            scope="scheduler_btn",
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
            label_on=t("Gui.Button.ScrollON"),
            label_off=t("Gui.Button.ScrollOFF"),
            onclick_on=lambda: log.set_scroll(False),
            onclick_off=lambda: log.set_scroll(True),
            get_state=lambda: log.keep_bottom,
            color_on="on",
            color_off="off",
            scope="log_scroll_btn",
        )

        self.task_handler.add(switch_scheduler.g(), 1, True)
        self.task_handler.add(switch_log_scroll.g(), 1, True)
        self.task_handler.add(self.alas_update_overview_task, 10, True)
        self.task_handler.add(log.put_log(self.alas), 0.25, True)

    def _init_alas_config_watcher(self) -> None:
        def put_queue(path, value):
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
        modified: dict[str, str],
        config_name: str,
        config_updater: AzurLaneConfig = State.config_updater,
    ) -> None:
        try:
            valid = []
            invalid = []
            config = config_updater.read_file(config_name)
            n = datetime.now()
            for p, v in deep_iter(config, depth=3):
                if p[-1].endswith("un") and not isinstance(v, bool) and (v - n).days >= 31:
                    deep_set(config, p, "")
            for k, v in modified.copy().items():
                valuetype = deep_get(self.ALAS_ARGS, k + ".valuetype")
                v = parse_pin_value(v, valuetype)
                validate = deep_get(self.ALAS_ARGS, k + ".validate")
                if not str(v):
                    default = deep_get(self.ALAS_ARGS, k + ".value")
                    modified[k] = default
                    deep_set(config, k, default)
                    valid.append(k)
                    pin["_".join(k.split("."))] = default

                elif not validate or re_fullmatch(validate, v):
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
                toast(
                    t("Gui.Toast.ConfigSaved"),
                    duration=1,
                    position="right",
                    color="success",
                )
                logger.info(f"Save config {filepath_config(config_name)}, {dict_to_kv(modified)}")
                config_updater.write_file(config_name, config)
        except Exception as e:
            logger.exception(e)

    def alas_update_overview_task(self) -> None:
        if not self.visible:
            return
        self.alas_config.load()
        self.alas_config.get_next_task()

        if len(self.alas_config.pending_task) >= 1:
            if self.alas.alive:
                running = self.alas_config.pending_task[:1]
                pending = self.alas_config.pending_task[1:]
            else:
                running = []
                pending = self.alas_config.pending_task[:]
        else:
            running = []
            pending = []
        waiting = self.alas_config.waiting_task

        def put_task(func: Function):
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

        clear("running_tasks")
        clear("pending_tasks")
        clear("waiting_tasks")
        with use_scope("running_tasks"):
            if running:
                for task in running:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")
        with use_scope("pending_tasks"):
            if pending:
                for task in pending:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")
        with use_scope("waiting_tasks"):
            if waiting:
                for task in waiting:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")

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
            label_on=t("Gui.Button.Stop"),
            label_off=t("Gui.Button.Start"),
            onclick_on=self.alas.stop,
            onclick_off=lambda: self.alas.start(task),
            get_state=lambda: self.alas.alive,
            color_on="off",
            color_off="on",
            scope="scheduler_btn",
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
            label_on=t("Gui.Button.ScrollON"),
            label_off=t("Gui.Button.ScrollOFF"),
            onclick_on=lambda: log.set_scroll(False),
            onclick_off=lambda: log.set_scroll(True),
            get_state=lambda: log.keep_bottom,
            color_on="on",
            color_off="off",
            scope="log_scroll_btn",
        )

        config = self.alas_config.read_file(self.alas_name)
        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            if group[0] == "Storage":
                continue
            self.set_group(group, arg_dict, config, task)

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

        self.task_handler.add(switch_scheduler.g(), 1, True)
        self.task_handler.add(switch_log_scroll.g(), 1, True)
        self.task_handler.add(log.put_log(self.alas), 0.25, True)

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
        self.alas_mod = get_config_mod(config_name)
        self.alas = ProcessManager.get_manager(config_name)
        self.alas_config = load_config(config_name)
        self.state_switch.switch()
        self.initial()
        self.alas_set_menu()

    def ui_add_alas(self) -> None:
        with popup(t("Gui.AddAlas.PopupTitle")) as s:

            def get_unused_name():
                all_name = alas_instance()
                for i in range(2, 100):
                    if f"alas{i}" not in all_name:
                        return f"alas{i}"
                return ""

            def add():
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

                r = load_config(origin).read_file(origin)
                State.config_updater.write_file(name, r, get_config_mod(origin))
                self.set_aside()
                self.active_button("aside", self.alas_name)
                close_popup()

            def put(name=None, origin=None):
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
                    value=origin or "template-alas",
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

        def set_theme(t):
            self.set_theme(t)
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

            # 显示项目提示。
            put_markdown(
                """
            Alas 是一款免费开源软件，如果你在任何渠道付费购买了 Alas，请退款。
            项目地址：`https://github.com/LmeSzinc/AzurLaneAutoScript`
            """
            ).style("text-align: center")

    def run(self) -> None:
        # 设置 GUI。
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

        # 初始化配置监听器。
        self._init_alas_config_watcher()

        # 保存配置。
        _thread_save_config = threading.Thread(target=self._alas_thread_update_config)
        register_thread(_thread_save_config)
        _thread_save_config.start()

        visibility_state_switch = Switch(
            status={
                True: [
                    lambda: self.__setattr__("visible", True),
                    lambda: self.alas_update_overview_task() if self.page == "Overview" else 0,
                    lambda: self.task_handler._task.__setattr__("delay", 15),
                ],
                False: [
                    lambda: self.__setattr__("visible", False),
                    lambda: self.task_handler._task.__setattr__("delay", 1),
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

        # 返回上一次打开的页面。
        if aside not in ["Home", None]:
            self.ui_alas(aside)


def app_manage():
    def _import():
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

        if len(file_name.split(".")) == 2:
            config_name, _ = file_name.split(".")
            mod_name = "alas"
        else:
            config_name, mod_name, _ = file_name.rsplit(".", maxsplit=2)

        config = json.loads(file.decode(encoding="utf-8"))
        State.config_updater.write_file(config_name, config, mod_name)
        toast(t("Gui.AppManage.ImportSuccess"), color="success")

        _show_table()

    def _export(config_name: str):
        mod_name = get_config_mod(config_name)
        suffix = "" if mod_name == "alas" else f".{mod_name}"
        filename = f"{config_name}{suffix}.json"
        with Path(filepath_config(config_name, mod_name)).open("rb") as f:
            download(filename, f.read())

    def _new():
        def get_unused_name():
            all_name = alas_instance()
            for i in range(2, 100):
                if f"alas{i}" not in all_name:
                    return f"alas{i}"
            return ""

        def validate(s: str):
            if s in alas_instance():
                return t("Gui.AppManage.NameExist")
            if set(s) & set(".\\/:*?\"'<>|"):
                return t("Gui.AppManage.InvalidChar")
            if s.lower().startswith("template"):
                return t("Gui.AppManage.InvalidPrefixTemplate")
            return None

        resp = input_group(
            label=t("Gui.AppManage.TitleNew"),
            inputs=[
                pywebio_input(
                    label=t("Gui.AppManage.NewName"),
                    name="config_name",
                    value=get_unused_name(),
                    validate=validate,
                ),
                select(
                    label=t("Gui.AppManage.CopyFrom"),
                    name="copy_from",
                    options=alas_template() + alas_instance(),
                    value="template-alas",
                ),
            ],
            cancelable=True,
        )

        if resp is None:
            return

        config_name = resp["config_name"]
        origin = resp["copy_from"]

        r = load_config(origin).read_file(origin)
        State.config_updater.write_file(config_name, r, get_config_mod(origin))
        toast(t("Gui.AppManage.NewSuccess"), color="success")
        _show_table()

    def _show_table():
        clear("config_table")
        put_table(
            tdata=[
                (
                    name,
                    get_config_mod(name),
                    put_buttons(
                        buttons=[
                            {"label": t("Gui.AppManage.Export"), "value": name},
                            # {
                            #     "label": t("Gui.AppManage.Delete"),
                            #     "value": name,
                            #     "disabled": True,
                            #     "color": "danger",
                            # },
                        ],
                        onclick=[
                            partial(_export, name),
                            # partial(_delete, name),
                        ],
                        group=True,
                        small=True,
                    ),
                )
                for name in alas_instance()
            ],
            header=[
                t("Gui.AppManage.Name"),
                t("Gui.AppManage.Mod"),
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


def debug():
    """交互式 Python 调试入口。

    $ python
    >>> from module.webui.app import *
    >>> debug()
    >>>
    """
    startup()
    AlasGUI().run()


def startup():
    State.init()
    lang.reload()
    task_handler.start()
    if State.deploy_config.DiscordRichPresence:
        init_discord_rpc()
    if State.deploy_config.StartOcrServer:
        start_ocr_server_process(State.deploy_config.OcrServerPort)


def clearup():
    """
    注意：必须在 uvicorn 重新加载 app 前执行。
    """
    logger.info("Start clearup")
    close_discord_rpc()
    stop_ocr_server_process()
    for alas in ProcessManager._processes.values():
        alas.stop()
    State.clearup()
    task_handler.stop()
    logger.info("Alas closed.")


def app():
    parser = argparse.ArgumentParser(description="Alas WebUI 服务")
    parser.add_argument("-k", "--key", type=str, help="WebUI 密码，默认不启用。")
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="使用 jsdelivr 加载 pywebio 静态文件，默认本地提供。",
    )
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="启动时自动运行指定配置。",
    )
    args, _ = parser.parse_known_args()

    # 应用配置。
    AlasGUI.set_theme(theme=State.deploy_config.Theme)
    key = args.key or State.deploy_config.Password
    cdn = args.cdn or State.deploy_config.CDN
    runs: list[str] = []
    if args.run:
        runs = args.run
    elif State.deploy_config.Run:
        # TODO: 重构 poor_yaml_read()，让它支持列表。
        tmp = State.deploy_config.Run.split(",")
        runs = [entry.strip(" ['\"]") for entry in tmp if entry]
    instances = runs

    logger.hr("Webui configs")
    logger.attr("Theme", State.deploy_config.Theme)
    logger.attr("Password", bool(key))
    logger.attr("CDN", cdn)

    from deploy.atomic import atomic_failure_cleanup

    atomic_failure_cleanup("./config")

    def index():
        if key is not None and not login(key):
            logger.warning(f"{info.user_ip} login failed.")
            time.sleep(1.5)
            run_js("location.reload();")
            return
        gui = AlasGUI()
        local.gui = gui
        gui.run()

    def manage():
        if key is not None and not login(key):
            logger.warning(f"{info.user_ip} login failed.")
            time.sleep(1.5)
            run_js("location.reload();")
            return
        app_manage()

    return asgi_app(
        applications=[index, manage],
        cdn=cdn,
        static_dir=None,
        debug=True,
        on_startup=[
            startup,
            lambda: ProcessManager.restart_processes(instances=instances),
        ],
        on_shutdown=[clearup],
    )
