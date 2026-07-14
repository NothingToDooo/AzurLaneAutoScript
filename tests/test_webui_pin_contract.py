import inspect
import multiprocessing
from importlib.metadata import version

import pytest
import pywebio.pin as upstream_pin
from pywebio.input import input as upstream_input
from pywebio.output import OutputPosition

VERIFIED_PYWEBIO_VERSION = "1.8.4"
_CONTRACT_PROCESS_TIMEOUT_SECONDS = 30


def _assert_private_pin_output_behavior() -> None:
    private_pin_output = vars(upstream_pin)["_pin_output"]
    single_input_return = upstream_input(
        name="contract_input",
        label="",
        value="value",
        data_contract="preserved",
    )
    output = private_pin_output(single_input_return, "contract-scope", OutputPosition.BOTTOM)

    assert output.spec["type"] == "pin"
    assert output.spec["input"]["name"] == "contract_input"
    assert output.spec["input"]["data_contract"] == "preserved"
    assert output.spec["scope"] == "#pywebio-scope-contract-scope"
    assert output.spec["position"] == OutputPosition.BOTTOM


def test_pywebio_private_pin_output_contract() -> None:
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

    # PyWebIO 会为脱离 server 的 input() 注册进程级 script session；隔离运行避免污染其他 WebUI 测试。
    process = multiprocessing.get_context("spawn").Process(target=_assert_private_pin_output_behavior)
    process.start()
    process.join(_CONTRACT_PROCESS_TIMEOUT_SECONDS)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("PyWebIO private contract process did not exit")
    assert process.exitcode == 0
