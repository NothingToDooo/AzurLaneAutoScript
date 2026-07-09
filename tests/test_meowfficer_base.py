from typing import ClassVar, TypeVar

import pytest

from module.combat.assets import GET_ITEMS_1
from module.meowfficer import assets as meow_assets
from module.meowfficer import base as base_module
from module.meowfficer.base import MeowfficerBase
from module.ui.assets import MEOWFFICER_CHECK

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}
    reset_count: ClassVar[int] = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> None:
        _Timer.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Meowfficer(MeowfficerBase):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.match_results: list[bool] = []
        self.additional_results: list[bool] = []

    def close_menu(self) -> None:
        self.meow_menu_close()

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def match_template_color(self, button: object, **kwargs: object) -> bool:
        self.calls.append(("match_template_color", button_key(button), kwargs))
        return self._next_result(self.match_results, default=False)

    def appear(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def meow_additional(self) -> bool:
        self.calls.append(("meow_additional",))
        return self._next_result(self.additional_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(base_module, "Timer", _Timer)


def test_meow_menu_close_exits_when_main_menu_is_visible() -> None:
    meow = _Meowfficer()
    meow.match_results = [True]

    meow.close_menu()

    assert meow.device.clicks == []
    assert meow.device.screenshot_count == 0


def test_meow_menu_close_uses_safe_click_timer() -> None:
    meow = _Meowfficer()
    meow.match_results = [False, True]
    _Timer.reached_results = {0: [True]}

    meow.close_menu()

    assert meow.device.clicks == [MEOWFFICER_CHECK]
    assert meow.device.screenshot_count == 1
    assert _Timer.reset_count == 1


def test_meow_menu_close_clicks_known_subpage_back_to_menu() -> None:
    meow = _Meowfficer()
    meow.match_results = [False, True]
    meow.appear_results[button_key(meow_assets.MEOWFFICER_FORT_CHECK)] = [True]

    meow.close_menu()

    assert meow.device.clicks == [MEOWFFICER_CHECK]
    assert _Timer.reset_count == 1


def test_meow_menu_close_resets_after_reward_popup() -> None:
    meow = _Meowfficer()
    meow.match_results = [False, True]
    meow.appear_then_click_results[button_key(GET_ITEMS_1)] = [True]

    meow.close_menu()

    assert _Timer.reset_count == 1
    assert ("appear_then_click", button_key(GET_ITEMS_1), {"offset": 5, "interval": 3}) in meow.calls
