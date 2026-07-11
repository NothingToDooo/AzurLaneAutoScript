from typing import ClassVar, TypeVar

import pytest

from module.combat import assets as combat_assets
from module.commission import assets as commission_assets
from module.commission import commission as commission_module
from module.commission.commission import RewardCommission
from module.exception import OilMaxed
from module.ui.assets import REWARD_GOTO_COMMISSION

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> None:
        pass


class _Config:
    SERVER = "cn"


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _CommissionUI(RewardCommission):
    config: _Config
    device: _Device

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.page_results: list[bool] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.main_results: list[bool] = []
        self.additional_results: list[bool] = []

    def receive(self) -> bool:
        return self._commission_receive()

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def ui_page_appear(self, page: object, *_args: object, **kwargs: object) -> bool:
        self.calls.append(("ui_page_appear", page, kwargs))
        return self._next_result(self.page_results, default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def ui_main_appear_then_click(self, page: object, *_args: object, **kwargs: object) -> bool:
        self.calls.append(("ui_main_appear_then_click", page, kwargs))
        return self._next_result(self.main_results, default=False)

    def ui_additional(self, *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("ui_additional",))
        return self._next_result(self.additional_results, default=False)

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button))


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    monkeypatch.setattr(commission_module, "Timer", _Timer)


def test_commission_receive_handles_reward_save_popup() -> None:
    ui = _CommissionUI()
    ui.page_results = [False, True]
    ui.appear_results[button_key(combat_assets.GET_ITEMS_1)] = [True]

    result = ui.receive()

    assert result is True
    assert commission_assets.REWARD_SAVE_CLICK in ui.device.clicks


def test_commission_receive_goto_commission_does_not_mark_reward() -> None:
    ui = _CommissionUI()
    ui.page_results = [False, True]
    ui.appear_then_click_results[button_key(REWARD_GOTO_COMMISSION)] = [True]
    _Timer.reached_results = {0: [True]}

    result = ui.receive()

    assert result is False
    assert ("interval_reset", combat_assets.GET_SHIP) in ui.calls


def test_commission_receive_raises_oil_maxed_on_cn() -> None:
    ui = _CommissionUI()
    ui.page_results = [False]
    ui.appear_results[button_key(commission_assets.OIL_MAXED)] = [True]

    with pytest.raises(OilMaxed):
        ui.receive()
