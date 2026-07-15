import inspect
from importlib.metadata import version
from typing import TYPE_CHECKING

import pywebio.io_ctrl as upstream_io_ctrl
import pywebio.pin as upstream_pin
import pywebio.session as upstream_session
from pywebio.input import input as upstream_input
from pywebio.output import OutputPosition

if TYPE_CHECKING:
    import pytest

VERIFIED_PYWEBIO_VERSION = "1.8.4"


def test_pywebio_private_pin_output_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    assert version("pywebio") == VERIFIED_PYWEBIO_VERSION

    public_helpers = {
        "put_checkbox": upstream_pin.put_checkbox,
        "put_input": upstream_pin.put_input,
        "put_select": upstream_pin.put_select,
        "put_textarea": upstream_pin.put_textarea,
    }
    helpers_accepting_custom_attrs = {
        name
        for name, helper in public_helpers.items()
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(helper).parameters.values()
        )
    }
    assert helpers_accepting_custom_attrs == set()

    private_pin_output = vars(upstream_pin)["_pin_output"]
    assert tuple(inspect.signature(private_pin_output).parameters) == (
        "single_input_return",
        "scope",
        "position",
    )

    # 只验证输入与 pin 的数据契约，不让 PyWebIO 为测试启动 Script Mode。
    monkeypatch.setattr(
        upstream_session,
        "get_session_implement",
        lambda: upstream_session.ThreadBasedSession,
    )
    monkeypatch.setattr(upstream_io_ctrl, "get_current_session", object)

    single_input_return = upstream_input(
        name="contract_input",
        label="",
        value="value",
        data_contract="preserved",
    )
    spec = private_pin_output(single_input_return, "contract-scope", OutputPosition.BOTTOM).embed_data()

    assert spec["type"] == "pin"
    assert spec["input"]["name"] == "contract_input"
    assert spec["input"]["data_contract"] == "preserved"
    assert spec["scope"] == "#pywebio-scope-contract-scope"
    assert spec["position"] == OutputPosition.BOTTOM
