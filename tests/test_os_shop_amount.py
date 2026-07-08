from typing import ClassVar, TypeVar

import pytest

from module.os_shop import shop as shop_module
from module.os_shop.shop import OSShop
from module.shop.assets import AMOUNT_MAX

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


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


class _Ocr:
    def __init__(self, values: list[int]) -> None:
        self.values = values

    def ocr(self, _image: object) -> int:
        return self.values.pop(0)


class _Device:
    image = object()

    def __init__(self) -> None:
        self.screenshot_count = 0

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Item:
    name = "item"
    cost = "YellowCoins"

    def __init__(self, *, price: int, count: int) -> None:
        self.price = price
        self.count = count


class _Shop(OSShop):
    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.currency = 0
        self.coins = 0

    def handle_amount(self, item: _Item) -> bool:
        return self.shop_buy_amount_handler(item)

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def close_shop_buy_confirm_amount(self, *, skip_first_screenshot: bool = True) -> None:
        self.calls.append(("close_shop_buy_confirm_amount", skip_first_screenshot))

    def get_currency_coins(self, item: _Item) -> int:
        self.calls.append(("get_currency_coins", item))
        return self.currency

    def get_coins_no_limit(self, item: _Item) -> int:
        self.calls.append(("get_coins_no_limit", item))
        return self.coins

    def interval_clear(self, button: object) -> None:
        self.calls.append(("interval_clear", button))

    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def ui_ensure_index(self, index: int, **kwargs: object) -> None:
        self.calls.append(("ui_ensure_index", index, kwargs))


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    monkeypatch.setattr(shop_module, "Timer", _Timer)


def test_shop_buy_amount_handler_closes_on_zero_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    shop = _Shop()
    monkeypatch.setattr(shop_module, "OCR_SHOP_AMOUNT", _Ocr([0]))

    result = shop.handle_amount(_Item(price=10, count=5))

    assert result is False
    assert ("close_shop_buy_confirm_amount", True) in shop.calls


def test_shop_buy_amount_handler_returns_true_when_buying_one(monkeypatch: pytest.MonkeyPatch) -> None:
    shop = _Shop()
    shop.currency = 10
    monkeypatch.setattr(shop_module, "OCR_SHOP_AMOUNT", _Ocr([1]))

    result = shop.handle_amount(_Item(price=10, count=5))

    assert result is True
    assert not any(call[0] == "ui_ensure_index" for call in shop.calls)


def test_shop_buy_amount_handler_sets_max_before_target_amount(monkeypatch: pytest.MonkeyPatch) -> None:
    shop = _Shop()
    shop.currency = 250
    shop.coins = 300
    shop.appear_then_click_results[button_key(AMOUNT_MAX)] = [True, False]
    fake_ocr = _Ocr([5, 2])
    monkeypatch.setattr(shop_module, "OCR_SHOP_AMOUNT", fake_ocr)

    result = shop.handle_amount(_Item(price=10, count=30))

    assert result is True
    assert ("interval_clear", AMOUNT_MAX) in shop.calls
    assert shop.device.screenshot_count == 2
    assert (
        "ui_ensure_index",
        25,
        {
            "letter": fake_ocr,
            "prev_button": shop_module.AMOUNT_MINUS,
            "next_button": shop_module.AMOUNT_PLUS,
            "skip_first_screenshot": True,
        },
    ) in shop.calls
