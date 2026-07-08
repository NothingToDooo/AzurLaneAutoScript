from typing import ClassVar

import pytest

from module.awaken import awaken as awaken_module
from module.awaken.awaken import Awaken


class _Asset:
    def __init__(self, name: str) -> None:
        self.name = name
        self.match_results: list[bool] = []

    def match_luma(self, _image: object, **_kwargs: object) -> bool:
        if self.match_results:
            return self.match_results.pop(0)
        return False

    def __repr__(self) -> str:
        return self.name


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
        self.click_record_clear_count = 0

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def click_record_clear(self) -> None:
        self.click_record_clear_count += 1


class _Awaken(Awaken):
    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.cost_results: list[object] = []
        self.popup_results: list[bool] = []
        self.finish_results: list[bool] = []
        self.in_awaken_results: list[bool] = []

    def _next_result(self, results: list, *, default: object) -> object:
        if results:
            return results.pop(0)
        return default

    def appear(self, button: _Asset, **kwargs: object) -> bool:
        self.calls.append(("appear", button.name, kwargs))
        return self._next_result(self.appear_results.get(button.name, []), default=False)

    def appear_then_click(self, button: _Asset, **kwargs: object) -> bool:
        self.calls.append(("appear_then_click", button.name, kwargs))
        return self._next_result(self.appear_then_click_results.get(button.name, []), default=False)

    def _get_awaken_cost(self, use_array=False):
        self.calls.append(("_get_awaken_cost", use_array))
        return self.cost_results.pop(0)

    def awaken_popup_close(self, skip_first_screenshot=True):
        self.calls.append(("awaken_popup_close", skip_first_screenshot))

    def interval_clear(self, button: object) -> None:
        self.calls.append(("interval_clear", button))

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def handle_awaken_finish(self) -> bool:
        self.calls.append(("handle_awaken_finish",))
        return self._next_result(self.finish_results, default=False)

    def is_in_awaken(self) -> bool:
        self.calls.append(("is_in_awaken",))
        return self._next_result(self.in_awaken_results, default=False)


@pytest.fixture(autouse=True)
def _patch_awaken_assets(monkeypatch: pytest.MonkeyPatch) -> dict[str, _Asset]:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    monkeypatch.setattr(awaken_module, "Timer", _Timer)
    assets = {
        "AWAKEN_CONFIRM": _Asset("AWAKEN_CONFIRM"),
        "LEVEL_UP": _Asset("LEVEL_UP"),
        "AWAKENING": _Asset("AWAKENING"),
    }
    for name, asset in assets.items():
        monkeypatch.setattr(awaken_module.awaken_assets, name, asset)
    return assets


def test_awaken_once_returns_no_exp_when_level_up_visible() -> None:
    awaken_module.awaken_assets.LEVEL_UP.match_results = [True]
    awaken = _Awaken()
    awaken.appear_results = {"AWAKEN_CONFIRM": [False]}

    assert awaken.awaken_once() == "no_exp"

    assert ("awaken_popup_close", True) not in awaken.calls


def test_awaken_once_closes_popup_when_resources_insufficient() -> None:
    awaken = _Awaken()
    awaken.appear_results = {"AWAKEN_CONFIRM": [True]}
    awaken.cost_results = [False]

    assert awaken.awaken_once() == "insufficient"

    assert ("awaken_popup_close", True) in awaken.calls


def test_awaken_once_closes_popup_when_cost_check_times_out() -> None:
    awaken = _Awaken()
    awaken.appear_results = {"AWAKEN_CONFIRM": [True]}
    awaken.cost_results = ["invalid"]
    _Timer.reached_results = {1: [True]}

    assert awaken.awaken_once() == "timeout"

    assert ("awaken_popup_close", True) in awaken.calls


def test_awaken_once_confirms_and_returns_success() -> None:
    awaken = _Awaken()
    awaken.appear_results = {"AWAKEN_CONFIRM": [True]}
    awaken.cost_results = [True]
    awaken.appear_then_click_results = {"AWAKEN_CONFIRM": [True, False]}
    awaken.finish_results = [True]
    awaken.in_awaken_results = [True]

    assert awaken.awaken_once() == "success"

    assert ("interval_clear", awaken_module.awaken_assets.AWAKEN_CONFIRM) in awaken.calls
    assert awaken.device.click_record_clear_count == 1
