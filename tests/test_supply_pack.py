from typing import TYPE_CHECKING

import module.freebies.supply_pack as supply_pack_module
from module.base.button import Button
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2
from module.freebies.assets import BUY_CONFIRM
from module.freebies.supply_pack import SupplyPack
from module.ui.page import page_supply_pack

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import pytest


class _FakeTimer:
    default_reached_results: tuple[bool, ...] = ()

    def __init__(self, _limit: float, count: int = 0) -> None:
        del count
        self.reached_results: list[bool] = list(self.__class__.default_reached_results)
        self.reset_count = 0

    def start(self) -> _FakeTimer:
        return self

    def reset(self) -> _FakeTimer:
        self.reset_count += 1
        return self

    def reached(self) -> bool:
        if self.reached_results:
            return self.reached_results.pop(0)
        return True


class _FakeDevice:
    def __init__(self) -> None:
        self.clicked = []
        self.screenshot_count = 0

    def click(self, button: Button) -> None:
        self.clicked.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeSupplyPack(SupplyPack):
    device: _FakeDevice

    def __init__(
        self,
        *,
        appear_results: Mapping[Button, Iterable[bool]] | None = None,
        appear_then_click_results: Mapping[Button, Iterable[bool]] | None = None,
        popup_results: Iterable[bool] | None = None,
    ) -> None:
        self.device = _FakeDevice()
        self.appear_results = {id(button): list(results) for button, results in (appear_results or {}).items()}
        self.appear_then_click_results = {
            id(button): list(results) for button, results in (appear_then_click_results or {}).items()
        }
        self.popup_results = list(popup_results or [])
        self.interval_cleared = []
        self.interval_reset_buttons = []

    @staticmethod
    def _pop_button_result(results_by_button: dict[int, list[bool]], button: Button) -> bool:
        results = results_by_button.get(id(button), [])
        if results:
            return results.pop(0)
        return False

    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return self._pop_button_result(self.appear_results, button)

    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return self._pop_button_result(self.appear_then_click_results, button)

    def handle_popup_confirm(self, name: str = "", offset: object = None, interval: float = 2) -> bool:
        _ = (name, offset, interval)
        if self.popup_results:
            return self.popup_results.pop(0)
        return False

    def interval_clear(self, button: Button, *_args: object, **_kwargs: object) -> None:
        self.interval_cleared.append(button)

    def interval_reset(self, button: Button, *_args: object, **_kwargs: object) -> None:
        self.interval_reset_buttons.append(button)


def test_supply_pack_buy_executes_purchase(monkeypatch: pytest.MonkeyPatch) -> None:
    supply_button = Button(area=(0, 0, 1, 1), color=(), button=(0, 0, 1, 1), name="SUPPLY_BUTTON")
    _FakeTimer.default_reached_results = (True,)
    monkeypatch.setattr(supply_pack_module, "Timer", _FakeTimer)
    supply_pack = _FakeSupplyPack(
        appear_results={
            supply_button: [True, False, False, False, False],
            page_supply_pack.check_button: [True],
        },
        appear_then_click_results={
            BUY_CONFIRM: [True, False, False],
            GET_ITEMS_1: [False],
            GET_ITEMS_2: [False],
        },
        popup_results=[True, False],
    )

    assert supply_pack.supply_pack_buy(supply_button)
    assert supply_pack.interval_cleared == [GET_ITEMS_1, GET_ITEMS_2, supply_button, BUY_CONFIRM]
    assert supply_pack.interval_reset_buttons == [supply_button, BUY_CONFIRM]
    assert supply_pack.device.clicked == [supply_button]


def test_supply_pack_buy_stops_after_three_failed_clicks(monkeypatch: pytest.MonkeyPatch) -> None:
    supply_button = Button(area=(0, 0, 1, 1), color=(), button=(0, 0, 1, 1), name="SUPPLY_BUTTON")
    _FakeTimer.default_reached_results = ()
    monkeypatch.setattr(supply_pack_module, "Timer", _FakeTimer)
    supply_pack = _FakeSupplyPack(
        appear_results={
            supply_button: [True, True, True, True],
        }
    )

    assert not supply_pack.supply_pack_buy(supply_button)
    assert supply_pack.device.clicked == [supply_button, supply_button, supply_button]
