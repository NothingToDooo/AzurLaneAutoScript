from typing import TYPE_CHECKING

from module.webui import pin as pin_module

if TYPE_CHECKING:
    import pytest

    from module.webui.pin import OutputPosition


def test_put_input_pins_output_and_forwards_attrs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    def fake_input(**kwargs: object) -> str:
        calls["input"] = kwargs
        return "input-output"

    def fake_pin_output(output: str, scope: str | None, position: OutputPosition) -> str:
        calls["pin"] = (output, scope, position)
        return "pinned"

    monkeypatch.setattr(
        pin_module, "check_dom_name_value", lambda name, label: calls.setdefault("check", (name, label))
    )
    monkeypatch.setattr(pin_module, "pywebio_input", fake_input)
    monkeypatch.setattr(pin_module, "_pin_output", fake_pin_output)

    result = pin_module.put_input(
        "demo",
        input_type="password",
        value="v",
        scope="scope-a",
        position="after",
        data_test="ok",
    )

    assert result == "pinned"
    assert calls["check"] == ("demo", "pin `name`")
    assert calls["input"] == {"name": "demo", "type": "password", "value": "v", "data_test": "ok", "label": ""}
    assert calls["pin"] == ("input-output", "scope-a", "after")


def test_put_select_removes_pin_options_before_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    monkeypatch.setattr(pin_module, "check_dom_name_value", lambda _name, _label: None)
    monkeypatch.setattr(pin_module, "select", lambda **kwargs: calls.setdefault("select", kwargs))
    monkeypatch.setattr(pin_module, "_pin_output", lambda output, scope, position: (output, scope, position))

    result = pin_module.put_select("choice", options=["a"], value="a", scope="scope-b")

    assert calls["select"] == {"name": "choice", "options": ["a"], "value": "a", "label": ""}
    assert result == (calls["select"], "scope-b", pin_module.OutputPosition.BOTTOM)
