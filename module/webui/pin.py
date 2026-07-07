"""
基于 pywebio.pin 修改，给 put_xxx() 增加 **other_html_attrs。
"""

from typing import TYPE_CHECKING

from pywebio.input import checkbox, select, textarea
from pywebio.input import input as pywebio_input
from pywebio.output import OutputPosition
from pywebio.pin import _pin_output, check_dom_name_value

if TYPE_CHECKING:
    from pywebio.io_ctrl import Output


def put_input(
    name,
    type="text",  # noqa: A002 - 保持 pywebio.input.input() 兼容参数名。
    *,
    label="",
    value=None,
    placeholder=None,
    readonly=None,
    datalist=None,
    help_text=None,
    scope=None,
    position=OutputPosition.BOTTOM,
    **other_html_attrs,
) -> Output:
    """输出 input 控件，参数参考 `pywebio.input.input()`。"""
    check_dom_name_value(name, "pin `name`")
    single_input_return = pywebio_input(
        name=name,
        label=label,
        value=value,
        type=type,
        placeholder=placeholder,
        readonly=readonly,
        datalist=datalist,
        help_text=help_text,
        **other_html_attrs,
    )
    return _pin_output(single_input_return, scope, position)


def put_textarea(
    name,
    *,
    label="",
    rows=6,
    code=None,
    maxlength=None,
    minlength=None,
    value=None,
    placeholder=None,
    readonly=None,
    help_text=None,
    scope=None,
    position=OutputPosition.BOTTOM,
    **other_html_attrs,
) -> Output:
    """输出 textarea 控件，参数参考 `pywebio.input.textarea()`。"""
    check_dom_name_value(name, "pin `name`")
    single_input_return = textarea(
        name=name,
        label=label,
        rows=rows,
        code=code,
        maxlength=maxlength,
        minlength=minlength,
        value=value,
        placeholder=placeholder,
        readonly=readonly,
        help_text=help_text,
        **other_html_attrs,
    )
    return _pin_output(single_input_return, scope, position)


def put_select(
    name,
    options=None,
    *,
    label="",
    multiple=None,
    value=None,
    help_text=None,
    scope=None,
    position=OutputPosition.BOTTOM,
    **other_html_attrs,
) -> Output:
    """输出 select 控件，参数参考 `pywebio.input.select()`。"""
    check_dom_name_value(name, "pin `name`")
    single_input_return = select(
        name=name, options=options, label=label, multiple=multiple, value=value, help_text=help_text, **other_html_attrs
    )
    return _pin_output(single_input_return, scope, position)


def put_checkbox(
    name,
    options=None,
    *,
    label="",
    inline=None,
    value=None,
    help_text=None,
    scope=None,
    position=OutputPosition.BOTTOM,
    **other_html_attrs,
) -> Output:
    """输出 checkbox 控件，参数参考 `pywebio.input.checkbox()`。"""
    check_dom_name_value(name, "pin `name`")
    single_input_return = checkbox(
        name=name, options=options, label=label, inline=inline, value=value, help_text=help_text, **other_html_attrs
    )
    return _pin_output(single_input_return, scope, position)
