"""扩展 pywebio.pin，使 put_xxx() 接受 **other_html_attrs。"""

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from pywebio.input import checkbox, select, textarea
from pywebio.input import input as pywebio_input
from pywebio.output import OutputPosition

# PyWebIO 1.8.4 的公开 put_* 不接受自定义 HTML 属性；tests/test_webui_pin_contract.py 锁定了私有契约。
from pywebio.pin import _pin_output, check_dom_name_value  # ruff:ignore[import-private-name]

if TYPE_CHECKING:
    from pywebio.io_ctrl import Output

type PinPrimitive = str | int | float | bool | None
type PinInputValue = PinPrimitive | Sequence[PinInputValue] | Mapping[str, PinInputValue]
type PinCallback = Callable[[PinInputValue], str | None] | Callable[[PinInputValue], None]
type PinKeywordValue = PinInputValue | PinCallback
type PinOption = Mapping[str, PinPrimitive] | str
type PinOptions = Sequence[PinOption]


def call_pywebio_input[ResultT](
    func: Callable[..., ResultT],
    /,
    **kwargs: PinKeywordValue,
) -> ResultT:
    """调用带动态 HTML 属性的 PyWebIO 输入函数。"""
    return func(**kwargs)


def _pop_pin_options(kwargs: dict[str, PinKeywordValue]) -> tuple[str | None, int | str]:
    scope = kwargs.pop("scope", None)
    if scope is not None and not isinstance(scope, str):
        message = "pin scope must be a string"
        raise TypeError(message)
    position = kwargs.pop("position", OutputPosition.BOTTOM)
    if not isinstance(position, (int, str)):
        message = "pin position must be an integer or string"
        raise TypeError(message)
    return scope, position


def put_input(name: str, input_type: str = "text", **kwargs: PinKeywordValue) -> Output:
    check_dom_name_value(name, "pin `name`")
    scope, position = _pop_pin_options(kwargs)
    kwargs.setdefault("label", "")
    single_input_return = call_pywebio_input(
        pywebio_input,
        name=name,
        type=input_type,
        **kwargs,
    )
    return _pin_output(single_input_return, scope, position)


def put_textarea(name: str, **kwargs: PinKeywordValue) -> Output:
    check_dom_name_value(name, "pin `name`")
    scope, position = _pop_pin_options(kwargs)
    kwargs.setdefault("label", "")
    kwargs.setdefault("rows", 6)
    single_input_return = call_pywebio_input(
        textarea,
        name=name,
        **kwargs,
    )
    return _pin_output(single_input_return, scope, position)


def put_select(name: str, options: PinOptions | None = None, **kwargs: PinKeywordValue) -> Output:
    check_dom_name_value(name, "pin `name`")
    scope, position = _pop_pin_options(kwargs)
    kwargs.setdefault("label", "")
    normalized_options: list[PinOption] = [] if options is None else list(options)
    single_input_return = call_pywebio_input(select, name=name, options=normalized_options, **kwargs)
    return _pin_output(single_input_return, scope, position)


def put_checkbox(name: str, options: PinOptions | None = None, **kwargs: PinKeywordValue) -> Output:
    check_dom_name_value(name, "pin `name`")
    scope, position = _pop_pin_options(kwargs)
    kwargs.setdefault("label", "")
    normalized_options: list[PinOption] = [] if options is None else list(options)
    single_input_return = call_pywebio_input(checkbox, name=name, options=normalized_options, **kwargs)
    return _pin_output(single_input_return, scope, position)
