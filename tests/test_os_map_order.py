from typing import ClassVar, TypeVar

import pytest

from module.os_handler import map_order as map_order_module
from module.os_handler.map_order import MapOrderHandler

_T = TypeVar("_T")


class _Button:
    name = "ORDER_TEST"


class _Zone:
    pass


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


class _MapOrder(MapOrderHandler):
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.in_map_results: list[bool] = []
        self.in_order_results: list[bool] = []
        self.appear_results: list[bool] = []
        self.click_results: list[bool] = []
        self.popup_results: list[bool] = []
        self.map_event_results: list[bool] = []
        self.cat_attack_results: list[bool] = []
        self.action_point_results: list[bool] = []
        self.enter_count = 0
        self.quit_count = 0

    def execute(self, button: _Button) -> bool:
        return self.order_execute(button)

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def loop(self, *_args: object, **_kwargs: object):
        return range(5)

    def order_enter(self) -> None:
        self.calls.append(("order_enter",))
        self.enter_count += 1

    def order_quit(self) -> None:
        self.calls.append(("order_quit",))
        self.quit_count += 1

    def name_to_zone(self, name: int, *_args: object, **_kwargs: object) -> _Zone:
        self.calls.append(("name_to_zone", name))
        return _Zone()

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self._next_result(self.in_map_results, default=False)

    def is_in_map_order(self) -> bool:
        self.calls.append(("is_in_map_order",))
        return self._next_result(self.in_order_results, default=False)

    def appear(self, button: object, *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("appear", button))
        return self._next_result(self.appear_results, default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        self.calls.append(("appear_then_click", button, kwargs))
        return self._next_result(self.click_results, default=False)

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def handle_map_event(self) -> bool:
        self.calls.append(("handle_map_event",))
        return self._next_result(self.map_event_results, default=False)

    def handle_map_cat_attack(self) -> bool:
        self.calls.append(("handle_map_cat_attack",))
        return self._next_result(self.cat_attack_results, default=False)

    def handle_action_point(self, *_args: object, **kwargs: object) -> bool:
        self.calls.append(("handle_action_point", kwargs))
        return self._next_result(self.action_point_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(map_order_module, "Timer", _Timer)


def test_order_execute_returns_true_after_map_is_stable() -> None:
    order = _MapOrder()
    _Timer.reached_results = {1: [True]}
    order.in_map_results = [True]

    result = order.execute(_Button())

    assert result is True
    assert order.enter_count == 1


def test_order_execute_quits_when_order_button_is_missing() -> None:
    order = _MapOrder()
    _Timer.reached_results = {0: [True]}
    order.in_map_results = [False]
    order.in_order_results = [True]
    order.appear_results = [False]

    result = order.execute(_Button())

    assert result is False
    assert order.quit_count == 1


def test_order_execute_reenters_after_action_point_handler() -> None:
    order = _MapOrder()
    _Timer.reached_results = {1: [True]}
    order.in_map_results = [False, True]
    order.in_order_results = [False]
    order.action_point_results = [True]

    result = order.execute(_Button())

    assert result is True
    assert order.enter_count == 2
