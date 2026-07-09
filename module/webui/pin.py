"""
基于 pywebio.pin 修改，给 put_xxx() 增加 **other_html_attrs。
"""

from typing import TYPE_CHECKING, Any

from pywebio.input import checkbox, select, textarea
from pywebio.input import input as pywebio_input
from pywebio.output import OutputPosition
from pywebio.pin import _pin_output, check_dom_name_value

if TYPE_CHECKING:
    from pywebio.io_ctrl import Output

type PinOptions = list[dict[str, Any] | tuple[Any, ...] | list[Any] | str]


def _pop_pin_options(kwargs):
    return kwargs.pop("scope", None), kwargs.pop("position", OutputPosition.BOTTOM)


def put_input(name, type="text", **kwargs) -> Output:  # noqa: A002 - 保持 pywebio.input.input() 兼容参数名。
    """输出 input 控件，参数参考 `pywebio.input.input()`。"""
    check_dom_name_value(name, "pin `name`")
    scope, position = _pop_pin_options(kwargs)
    kwargs.setdefault("label", "")
    single_input_return = pywebio_input(
        name=name,
        type=type,
        **kwargs,
    )
    return _pin_output(single_input_return, scope, position)


def put_textarea(name, **kwargs) -> Output:
    """输出 textarea 控件，参数参考 `pywebio.input.textarea()`。"""
    check_dom_name_value(name, "pin `name`")
    scope, position = _pop_pin_options(kwargs)
    kwargs.setdefault("label", "")
    kwargs.setdefault("rows", 6)
    single_input_return = textarea(
        name=name,
        **kwargs,
    )
    return _pin_output(single_input_return, scope, position)


def put_select(name, options: PinOptions | None = None, **kwargs) -> Output:
    """输出 select 控件，参数参考 `pywebio.input.select()`。"""
    check_dom_name_value(name, "pin `name`")
    scope, position = _pop_pin_options(kwargs)
    kwargs.setdefault("label", "")
    options = [] if options is None else options
    single_input_return = select(name=name, options=options, **kwargs)
    return _pin_output(single_input_return, scope, position)


def put_checkbox(name, options: PinOptions | None = None, **kwargs) -> Output:
    """输出 checkbox 控件，参数参考 `pywebio.input.checkbox()`。"""
    check_dom_name_value(name, "pin `name`")
    scope, position = _pop_pin_options(kwargs)
    kwargs.setdefault("label", "")
    options = [] if options is None else options
    single_input_return = checkbox(name=name, options=options, **kwargs)
    return _pin_output(single_input_return, scope, position)
