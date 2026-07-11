import copy
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pywebio.exceptions import SessionException
from pywebio.output import (
    clear,
    output,
    put_button,
    put_buttons,
    put_column,
    put_html,
    put_loading,
    put_row,
    put_scope,
    put_text,
)
from pywebio.session import eval_js, local, run_js

from module.logger import WEB_THEME, Highlighter, HTMLConsole
from module.webui.lang import t
from module.webui.pin import put_checkbox, put_input, put_select, put_textarea
from module.webui.setting import State
from module.webui.utils import (
    DARK_TERMINAL_THEME,
    LIGHT_TERMINAL_THEME,
    LOG_CODE_FORMAT,
    Switch,
)

type ButtonSpec = dict[str, Any] | tuple[str, Any] | list[Any] | str

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from pywebio.io_ctrl import Output
    from rich.console import ConsoleRenderable

    from module.webui.app import AlasGUI
    from module.webui.process_manager import ProcessManager


class RichLog:
    def __init__(self, scope, font_width="0.559") -> None:
        self.scope = scope
        self.font_width = font_width
        self.console = HTMLConsole(
            force_terminal=False,
            force_interactive=False,
            width=80,
            color_system="truecolor",
            markup=False,
            record=True,
            safe_box=False,
            highlighter=Highlighter(),
            theme=WEB_THEME,
        )
        self.keep_bottom = True
        if State.theme == "dark":
            self.terminal_theme = DARK_TERMINAL_THEME
        else:
            self.terminal_theme = LIGHT_TERMINAL_THEME

    def render(self, renderable: ConsoleRenderable) -> str:
        with self.console.capture():
            self.console.print(renderable)

        return self.console.export_html(
            theme=self.terminal_theme,
            clear=True,
            code_format=LOG_CODE_FORMAT,
            inline_styles=True,
        )

    def extend(self, text):
        if text:
            run_js(
                f"""$("#pywebio-scope-{self.scope}>div").append(text);
            """,
                text=str(text),
            )
            if self.keep_bottom:
                self.scroll()

    def reset(self):
        run_js(f"""$("#pywebio-scope-{self.scope}>div").empty();""")

    def scroll(self) -> None:
        run_js(
            f"""$("#pywebio-scope-{self.scope}").scrollTop($("#pywebio-scope-{self.scope}").prop("scrollHeight"));
        """
        )

    def set_scroll(self, *, keep_bottom: bool) -> None:
        self.keep_bottom = keep_bottom

    def get_width(self):
        js = f"""
        let canvas = document.createElement('canvas');
        canvas.style.position = "absolute";
        let ctx = canvas.getContext('2d');
        document.body.appendChild(canvas);
        ctx.font = `16px Menlo, consolas, DejaVu Sans Mono, Courier New, monospace`;
        document.body.removeChild(canvas);
        let text = ctx.measureText('0');
        ctx.fillText('0', 50, 50);

        ($('#pywebio-scope-{self.scope}').width()-16)/\
        $('#pywebio-scope-{self.scope}').css('font-size').slice(0, -2)/text.width*16;\
        """
        width = eval_js(js)
        return 80 if width is None else 128 if width > 128 else int(width)

    def put_log(self, pm: ProcessManager) -> Generator:
        yield
        try:
            while True:
                last_idx = len(pm.renderables)
                html = "".join(map(self.render, pm.renderables[:]))
                self.reset()
                self.extend(html)
                counter = last_idx
                while counter < pm.renderables_max_length * 2:
                    yield
                    idx = len(pm.renderables)
                    if idx < last_idx:
                        last_idx -= pm.renderables_reduce_length
                    if idx != last_idx:
                        html = "".join(map(self.render, pm.renderables[last_idx:idx]))
                        self.extend(html)
                        counter += idx - last_idx
                        last_idx = idx
        except SessionException:
            pass


@dataclass(slots=True)
class BinarySwitchOptions:
    get_state: object
    label_on: str
    label_off: str
    onclick_on: object
    onclick_off: object
    scope: str
    color_on: str = "success"
    color_off: str = "secondary"


class BinarySwitchButton(Switch):
    def __init__(self, options: BinarySwitchOptions):
        self.scope = options.scope
        status = {
            0: {
                "func": self.update_button,
                "args": (
                    options.label_off,
                    options.onclick_off,
                    options.color_off,
                ),
            },
            1: {
                "func": self.update_button,
                "args": (
                    options.label_on,
                    options.onclick_on,
                    options.color_on,
                ),
            },
        }
        super().__init__(status=status, get_state=options.get_state, name=options.scope)

    def update_button(self, label, onclick, color):
        clear(self.scope)
        put_button(label=label, onclick=onclick, color=color, scope=self.scope)


def put_icon_buttons(
    icon_html: str,
    buttons: list[ButtonSpec],
    onclick: list[Callable[..., None]] | Callable[..., None],
) -> Output:
    first = buttons[0]
    value = first.get("value", "") if isinstance(first, dict) else ""
    return put_column(
        [
            output(put_html(icon_html)).style("z-index: 1; margin-left: 8px;text-align: center"),
            put_buttons(buttons, onclick).style(f"z-index: 2; --aside-{value}--;"),
        ],
        size="0",
    )


def put_none() -> Output:
    return put_html("<div></div>")


T_Output_Kwargs = dict[str, Any]


def get_title_help(kwargs: T_Output_Kwargs) -> Output:
    title = str(kwargs.get("title") or "")
    help_text = str(kwargs.get("help") or "")

    if help_text:
        res = put_column(
            [
                put_text(title).style("--arg-title--"),
                put_text(help_text).style("--arg-help--"),
            ],
            size="auto 1fr",
        )
    else:
        res = put_text(title).style("--arg-title--")

    return res


def put_arg_input(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    options = kwargs.get("options")
    if isinstance(options, list):
        kwargs.setdefault("datalist", options)

    return put_scope(
        f"arg_container-input-{name}",
        [
            get_title_help(kwargs),
            put_input(**kwargs).style("--input--"),
        ],
    )


def product_stored_row(kwargs: T_Output_Kwargs, key, value):
    kwargs = copy.copy(kwargs)
    name = str(kwargs["name"])
    kwargs["name"] = f"{name}_{key}"
    kwargs["value"] = value
    return put_input(**kwargs).style("--input--")


def put_arg_stored(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    kwargs["disabled"] = True

    values = dict(kwargs.pop("value", {}))
    time_ = values.pop("time", "")

    rows = [product_stored_row(kwargs, key, value) for key, value in values.items() if value]
    if time_:
        rows += [product_stored_row(kwargs, "time", time_)]
    return put_scope(
        f"arg_container-stored-{name}",
        [
            get_title_help(kwargs),
            put_scope(
                f"arg_stored-stored-value-{name}",
                rows,
            ),
        ],
    )


def put_arg_select(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    value: str = kwargs["value"]
    options: list[str] = kwargs["options"]
    options_label: list[str] = kwargs.pop("options_label", [])
    disabled: bool = kwargs.pop("disabled", False)
    _: str = kwargs.pop("invalid_feedback", None)

    if disabled:
        option = [
            {
                "label": next(
                    (opt_label for opt, opt_label in zip(options, options_label, strict=True) if opt == value), value
                ),
                "value": value,
                "selected": True,
            }
        ]
    else:
        option = [
            {
                "label": opt_label,
                "value": opt,
                "select": opt == value,
            }
            for opt, opt_label in zip(options, options_label, strict=True)
        ]
    kwargs["options"] = option

    return put_scope(
        f"arg_container-select-{name}",
        [
            get_title_help(kwargs),
            put_select(**kwargs).style("--input--"),
        ],
    )


def put_arg_state(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    value: str = kwargs["value"]
    options: list[str] = kwargs["options"]
    options_label: list[str] = kwargs.pop("options_label", [])
    _: str = kwargs.pop("invalid_feedback", None)
    bold: bool = value in kwargs.pop("option_bold", [])
    light: bool = value in kwargs.pop("option_light", [])

    option = [
        {
            "label": next(
                (opt_label for opt, opt_label in zip(options, options_label, strict=True) if opt == value), value
            ),
            "value": value,
            "selected": True,
        }
    ]
    if bold:
        kwargs["class"] = "form-control state state-bold"
    elif light:
        kwargs["class"] = "form-control state state-light"
    else:
        kwargs["class"] = "form-control state"
    kwargs["options"] = option

    return put_scope(
        f"arg_container-select-{name}",
        [
            get_title_help(kwargs),
            put_select(**kwargs).style("--input--"),
        ],
    )


def put_arg_textarea(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    mode: str = kwargs.pop("mode", None)
    kwargs.setdefault("code", {"lineWrapping": True, "lineNumbers": False, "mode": mode})

    return put_scope(
        f"arg_contianer-textarea-{name}",
        [
            get_title_help(kwargs),
            put_textarea(**kwargs),
        ],
    )


def put_arg_checkbox(kwargs: T_Output_Kwargs) -> Output:
    # 这里的 checkbox 用作二元开关，而非多选框。
    name: str = kwargs["name"]
    value: str = kwargs["value"]
    _: str = kwargs.pop("invalid_feedback", None)

    kwargs["options"] = [{"label": "", "value": True, "selected": value}]
    return put_scope(
        f"arg_container-checkbox-{name}",
        [
            get_title_help(kwargs),
            put_checkbox(**kwargs).style("text-align: center"),
        ],
    )


def put_arg_datetime(kwargs: T_Output_Kwargs) -> Output:
    name: str = kwargs["name"]
    return put_scope(
        f"arg_container-datetime-{name}",
        [
            get_title_help(kwargs),
            put_input(**kwargs).style("--input--"),
        ],
    )


def put_arg_storage(kwargs: T_Output_Kwargs) -> Output | None:
    name: str = kwargs["name"]
    if kwargs["value"] == {}:
        return None

    kwargs["value"] = json.dumps(kwargs["value"], indent=2, ensure_ascii=False, sort_keys=False, default=str)
    kwargs.setdefault("code", {"lineWrapping": True, "lineNumbers": False, "mode": "json"})

    def clear_callback():
        alasgui: AlasGUI = local.gui
        alasgui.modified_config_queue.put({"name": ".".join(name.split("_")), "value": {}})
        # 不直接写 pin[name]，见 PyWebIO issue 459。

    return put_scope(
        f"arg_container-storage-{name}",
        [
            put_textarea(**kwargs),
            put_html(f'<button class="btn btn-outline-warning btn-block">{t("Gui.Text.Clear")}</button>').onclick(
                clear_callback
            ),
        ],
    )


_widget_type_to_func: dict[str, Callable] = {
    "input": put_arg_input,
    "lock": put_arg_state,
    "datetime": put_arg_datetime,
    "select": put_arg_select,
    "textarea": put_arg_textarea,
    "checkbox": put_arg_checkbox,
    "storage": put_arg_storage,
    "state": put_arg_state,
    "stored": put_arg_stored,
}


def put_output(output_kwargs: T_Output_Kwargs) -> Output | None:
    return _widget_type_to_func[output_kwargs["widget_type"]](output_kwargs)


def get_loading_style(shape: str, *, fill: bool) -> str:
    if fill:
        return f"--loading-{shape}-fill--"
    return f"--loading-{shape}--"


def put_loading_text(
    text: str,
    *,
    shape: str = "border",
    color: str = "dark",
    fill: bool = False,
    size: str = "auto 2px 1fr",
):
    loading_style = get_loading_style(shape=shape, fill=fill)
    return put_row(
        [
            put_loading(shape=shape, color=color).style(loading_style),
            None,
            put_text(text),
        ],
        size=size,
    )
