from typing import TYPE_CHECKING

from module.webui import pin as pin_module

if TYPE_CHECKING:
    import pytest


def test_put_select_removes_pin_options_before_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    monkeypatch.setattr(pin_module, "check_dom_name_value", lambda _name, _label: None)
    monkeypatch.setattr(pin_module, "select", lambda **kwargs: calls.setdefault("select", kwargs))
    monkeypatch.setattr(pin_module, "_pin_output", lambda output, scope, position: (output, scope, position))

    result = pin_module.put_select("choice", options=["a"], value="a", scope="scope-b")

    assert calls["select"] == {"name": "choice", "options": ["a"], "value": "a", "label": ""}
    assert result == (calls["select"], "scope-b", pin_module.OutputPosition.BOTTOM)
