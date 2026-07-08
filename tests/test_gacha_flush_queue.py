from typing import ClassVar, TypeVar

import pytest

from module.gacha import assets as gacha_assets
from module.gacha import gacha_reward as gacha_module
from module.gacha.gacha_reward import RewardGacha

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

    def start(self) -> _Timer:
        return self

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
        self.sleeps: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def sleep(self, value: object) -> None:
        self.sleeps.append(value)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _RewardGacha(RewardGacha):
    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.retirement_results: list[bool] = []
        self.popup_results: list[bool] = []
        self.get_items_results: list[bool] = []

    def flush(self) -> None:
        self.gacha_flush_queue()

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def gacha_side_navbar_ensure(self, **kwargs: object) -> None:
        self.calls.append(("gacha_side_navbar_ensure", kwargs))

    def appear(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def handle_retirement(self) -> bool:
        self.calls.append(("handle_retirement",))
        return self._next_result(self.retirement_results, default=False)

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def handle_get_items_ship(self) -> bool:
        self.calls.append(("handle_get_items_ship",))
        return self._next_result(self.get_items_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(gacha_module, "Timer", _Timer)


def test_gacha_flush_queue_returns_to_pool_when_queue_already_empty() -> None:
    gacha = _RewardGacha()
    gacha.appear_results[button_key(gacha_assets.BUILD_QUEUE_EMPTY)] = [True]

    gacha.flush()

    assert ("gacha_side_navbar_ensure", {"bottom": 3}) in gacha.calls
    assert ("gacha_side_navbar_ensure", {"upper": 1}) in gacha.calls
    assert gacha.device.clicks == []


def test_gacha_flush_queue_clicks_finish_popup_safe_area_once() -> None:
    gacha = _RewardGacha()
    gacha.appear_results[button_key(gacha_assets.BUILD_QUEUE_EMPTY)] = [False, False]
    gacha.appear_results[button_key(gacha_assets.BUILD_SUBMIT_ORDERS)] = [True]
    gacha.popup_results = [True, False]
    _Timer.reached_results = {0: [True]}

    gacha.flush()

    assert gacha.device.sleeps == [(0.5, 0.8)]
    assert gacha.device.clicks == [gacha_assets.BUILD_FINISH_ORDERS]
    assert _Timer.reset_count == 1
    assert gacha.device.screenshot_count == 1
