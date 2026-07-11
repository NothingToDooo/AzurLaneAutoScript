from typing import TYPE_CHECKING, ClassVar, TypeVar, override

import numpy as np
import pytest

from module.base.button import Button
from module.private_quarters import assets as pq_assets
from module.private_quarters import clerk as clerk_module
from module.private_quarters.clerk import PQShopClerk
from module.statistics.item import Item

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.timer import Timer
    from module.base.type_alias import ImageArray

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

    @staticmethod
    def reset() -> None:
        _Timer.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.clicks: list[object] = []

    def click(self, button: object) -> None:
        self.clicks.append(button)


def _item() -> Item:
    image = np.zeros((96, 96, 3), dtype=np.uint8)
    button = Button(area=(0, 0, 96, 96), color=(), button=(0, 0, 96, 96), name="PQ_ITEM")
    item = Item(image, button)
    item.name = "private-quarters-item"
    return item


class _Shop(PQShopClerk):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.loop_count = 8
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}

    @override
    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        del skip_first, timeout
        return iter([self.device.image] * self.loop_count)

    def enter_purchase_confirm(self, item: Item) -> None:
        self._pq_shop_enter_purchase_confirm(item, skip_first_screenshot=True)

    def finish_purchase_confirm(self) -> None:
        self._pq_shop_finish_purchase_confirm()

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def shop_interval_clear(self) -> None:
        self.calls.append(("shop_interval_clear",))


class _TrackingShop(PQShopClerk):
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def buy_execute(self) -> None:
        self.shop_buy_execute(_item())

    def _pq_shop_prepare_buy(self) -> None:
        self.calls.append(("_pq_shop_prepare_buy",))

    @override
    def _pq_shop_enter_purchase_confirm(self, item: Item, *, skip_first_screenshot: bool) -> None:
        assert skip_first_screenshot is True
        self.calls.append(("_pq_shop_enter_purchase_confirm", item))

    def _pq_shop_finish_purchase_confirm(self) -> None:
        self.calls.append(("_pq_shop_finish_purchase_confirm",))


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(clerk_module, "Timer", _Timer)


def test_pq_shop_buy_execute_runs_purchase_stages() -> None:
    shop = _TrackingShop()

    shop.buy_execute()

    assert [call[0] for call in shop.calls] == [
        "_pq_shop_prepare_buy",
        "_pq_shop_enter_purchase_confirm",
        "_pq_shop_finish_purchase_confirm",
    ]


def test_pq_shop_enter_purchase_confirm_clicks_item_and_amount_buttons() -> None:
    shop = _Shop()
    item = _item()
    shop.loop_count = 4
    shop.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET)] = [False, False, False, True]
    shop.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET)] = [False, False, False]
    shop.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_SHOP_CHECK)] = [True, False, False]
    shop.appear_then_click_results[button_key(pq_assets.PRIVATE_QUARTERS_SHOP_AMOUNT_MAX)] = [True, False]
    shop.appear_then_click_results[button_key(pq_assets.PRIVATE_QUARTERS_SHOP_CONFIRM_AMOUNT)] = [True]

    shop.enter_purchase_confirm(item)

    assert shop.device.clicks == [item]
    assert any(call[0] == "appear_then_click" for call in shop.calls)


def test_pq_shop_finish_purchase_confirm_clicks_until_shop_returns() -> None:
    shop = _Shop()
    shop.loop_count = 2
    _Timer.reached_results = {0: [True]}
    shop.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_ROSES_GET)] = [True, True, False]
    shop.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_SHOP_WEEKLY_CAKES_GET)] = [False]
    shop.appear_results[button_key(pq_assets.PRIVATE_QUARTERS_SHOP_CHECK)] = [True]

    shop.finish_purchase_confirm()

    assert shop.device.clicks == [pq_assets.PRIVATE_QUARTERS_SHOP_CHECK]
    assert _Timer.reset_count == 1
