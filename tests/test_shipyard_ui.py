from typing import ClassVar

import pytest

from module.handler.assets import LOGIN_ANNOUNCE
from module.shipyard import ui as shipyard_ui
from module.shipyard.ui import SHIPYARD_CONFIRM_BUTTONS, ShipyardUI


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def start(self) -> _Timer:
        return self

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> None:
        pass


class _Device:
    image = object()

    def __init__(self) -> None:
        self.screenshot_count = 0

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _ShipyardUI(ShipyardUI):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.append = "DEV"
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.popup_results: list[bool] = []
        self.story_results: list[bool] = []
        self.info_bar_results: list[bool] = []
        self.in_ui_results: list[bool] = []
        self.total_results: list[int] = []

    def buy_confirm(self, text: str) -> None:
        self._shipyard_buy_confirm(text)

    def _next_result[T](self, results: list[T], *, default: T) -> T:
        if results:
            return results.pop(0)
        return default

    def _button_name(self, button: object) -> str:
        return getattr(button, "name", repr(button))

    def _shipyard_get_append(self) -> str:
        self.calls.append(("_shipyard_get_append",))
        return self.append

    def interval_clear(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_clear", button))

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button))

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        name = self._button_name(button)
        self.calls.append(("appear_then_click", name, kwargs))
        return self._next_result(self.appear_then_click_results.get(name, []), default=False)

    def handle_popup_confirm(self, name="", offset=None, interval=2) -> bool:
        _ = (name, offset, interval)
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def story_skip(self) -> bool:
        self.calls.append(("story_skip",))
        return self._next_result(self.story_results, default=False)

    def handle_info_bar(self) -> bool:
        self.calls.append(("handle_info_bar",))
        return self._next_result(self.info_bar_results, default=False)

    def _shipyard_in_ui(self) -> bool:
        self.calls.append(("_shipyard_in_ui",))
        return self._next_result(self.in_ui_results, default=False)

    def _shipyard_get_total(self) -> tuple[None, None, int]:
        self.calls.append(("_shipyard_get_total",))
        return None, None, self.total_results.pop(0)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    monkeypatch.setattr(shipyard_ui, "Timer", _Timer)


def test_shipyard_buy_confirm_waits_for_success_and_ui_confirm() -> None:
    shipyard = _ShipyardUI()
    button = SHIPYARD_CONFIRM_BUTTONS["DEV"]
    shipyard.story_results = [True, False]
    shipyard.in_ui_results = [True]
    _Timer.reached_results = {1: [True]}

    shipyard.buy_confirm("BP_USE")

    assert ("interval_clear", button) in shipyard.calls
    assert ("interval_reset", button) in shipyard.calls
    assert shipyard.device.screenshot_count == 1


def test_shipyard_buy_confirm_uses_ocr_fallback_when_total_reaches_zero() -> None:
    shipyard = _ShipyardUI()
    button = SHIPYARD_CONFIRM_BUTTONS["DEV"]
    shipyard.total_results = [0]
    shipyard.in_ui_results = [True]
    _Timer.reached_results = {0: [True, False], 1: [True]}

    shipyard.buy_confirm("BP_BUY")

    assert ("_shipyard_get_total",) in shipyard.calls
    assert ("interval_reset", button) in shipyard.calls


def test_shipyard_buy_confirm_accepts_fate_info_popup() -> None:
    shipyard = _ShipyardUI()
    shipyard.appear_then_click_results = {LOGIN_ANNOUNCE.name: [True, False]}
    shipyard.in_ui_results = [True]
    _Timer.reached_results = {1: [True]}

    shipyard.buy_confirm("BP_USE")

    assert (
        "appear_then_click",
        LOGIN_ANNOUNCE.name,
        {"offset": (-350, 77, -250, 177), "interval": 3},
    ) in shipyard.calls
