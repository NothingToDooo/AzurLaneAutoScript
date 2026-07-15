from typing import TYPE_CHECKING

import pywebio.io_ctrl as upstream_io_ctrl
import pywebio.session as upstream_session
from pywebio.output import OutputPosition

from module.webui.pin import put_input

if TYPE_CHECKING:
    import pytest


def test_put_input_preserves_custom_attrs_scope_and_position(monkeypatch: pytest.MonkeyPatch) -> None:
    # 只验证输入与 pin 的数据契约，不让 PyWebIO 为测试启动 Script Mode。
    monkeypatch.setattr(
        upstream_session,
        "get_session_implement",
        lambda: upstream_session.ThreadBasedSession,
    )
    monkeypatch.setattr(upstream_io_ctrl, "get_current_session", object)

    spec = put_input(
        "contract_input",
        value="value",
        data_contract="preserved",
        scope="contract-scope",
        position=OutputPosition.TOP,
    ).embed_data()

    assert spec["type"] == "pin"
    assert spec["input"]["name"] == "contract_input"
    assert spec["input"]["data_contract"] == "preserved"
    assert spec["scope"] == "#pywebio-scope-contract-scope"
    assert spec["position"] == OutputPosition.TOP
