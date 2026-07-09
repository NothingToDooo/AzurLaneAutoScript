import pytest

import module.shop.clerk as shop_clerk
from module.exception import ScriptError
from module.shop.assets import SELECT_MINUS, SELECT_PLUS, SHOP_BUY_CONFIRM_SELECT
from module.shop.clerk import ShopClerk


class _FakeDevice:
    def __init__(self) -> None:
        self.image = "image"
        self.clicked = []
        self.screenshot_count = 0

    def click(self, button) -> None:
        self.clicked.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeItem:
    name = "Plate"
    group = "plate"
    price = 2


class _FakeStockOcr:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.calls = []

    def ocr(self, image):
        self.calls.append(image)
        return self.results.pop(0)


class _FakeShopClerk(ShopClerk):
    device: _FakeDevice

    def __init__(self, *, currency=0, appear_results=None) -> None:
        self.device = _FakeDevice()
        self._currency = currency
        self.appear_results = {id(button): list(results) for button, results in (appear_results or {}).items()}
        self.ensure_calls = []
        self.ensure_letter_result = None
        self.selected_items = []

    def shop_get_select(self, item):
        self.selected_items.append(item)
        return "select_button"

    def appear(self, button, *_args: object, **_kwargs) -> bool:
        results = self.appear_results.get(id(button), [])
        if results:
            return results.pop(0)
        return False

    def ui_ensure_index(self, index, controls, *_args: object, **kwargs) -> None:
        self.ensure_calls.append((index, controls, kwargs))
        self.ensure_letter_result = controls.letter(self.device.image)


class _ImmediateTimer:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def start(self):
        return self

    def reached(self) -> bool:
        return True

    def reset(self):
        return self


def test_shop_buy_select_execute_caps_limit_by_currency(monkeypatch) -> None:
    stock_ocr = _FakeStockOcr([(0, 0, 5), (1, 3, 5)])
    monkeypatch.setattr(shop_clerk, "OCR_SHOP_SELECT_STOCK", stock_ocr)
    item = _FakeItem()
    shop = _FakeShopClerk(
        currency=6,
        appear_results={
            SELECT_MINUS: [True],
            SELECT_PLUS: [True],
        },
    )

    assert shop.shop_buy_select_execute(item)
    assert shop.selected_items == [item]
    assert shop.device.clicked == ["select_button", SHOP_BUY_CONFIRM_SELECT]
    assert shop.ensure_calls[0][0] == 3
    assert shop.ensure_letter_result == 3


def test_shop_buy_select_execute_raises_when_stock_limit_is_missing(monkeypatch) -> None:
    stock_ocr = _FakeStockOcr([])
    monkeypatch.setattr(shop_clerk, "OCR_SHOP_SELECT_STOCK", stock_ocr)
    monkeypatch.setattr(shop_clerk, "Timer", _ImmediateTimer)
    shop = _FakeShopClerk(currency=6)

    with pytest.raises(ScriptError):
        shop.shop_buy_select_execute(_FakeItem())

    assert shop.device.clicked == []
