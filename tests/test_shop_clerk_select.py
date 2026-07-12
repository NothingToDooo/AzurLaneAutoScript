from typing import TYPE_CHECKING

import numpy as np
import pytest

import module.shop.clerk as shop_clerk
from module.base.button import Button
from module.exception import ScriptError
from module.shop.assets import SELECT_MINUS, SELECT_PLUS, SHOP_BUY_CONFIRM_SELECT
from module.shop.clerk import ShopClerk
from module.ui.ui import IndexOcr

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from module.base.type_alias import ImageArray
    from module.shop.clerk import ShopSelectionItem
    from module.ui.ui import UiIndexControls


class _FakeDevice:
    def __init__(self) -> None:
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.clicked: list[Button] = []
        self.screenshot_count = 0

    def click(self, button: Button) -> None:
        self.clicked.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeItem:
    name = "Plate"
    group = "plate"
    tier = "t1"
    price = 2


class _FakeStockOcr:
    def __init__(self, results: Iterable[tuple[int, int, int]]) -> None:
        self.results = list(results)
        self.calls: list[ImageArray] = []

    def ocr_single(self, image: ImageArray) -> tuple[int, int, int]:
        self.calls.append(image)
        return self.results.pop(0)


class _FakeShopClerk(ShopClerk):
    device: _FakeDevice

    def __init__(
        self,
        *,
        currency: int = 0,
        appear_results: Mapping[Button, Iterable[bool]] | None = None,
    ) -> None:
        self.device = _FakeDevice()
        self._currency = currency
        self.appear_results = {id(button): list(results) for button, results in (appear_results or {}).items()}
        self.ensure_calls = []
        self.ensure_letter_result = None
        self.selected_items: list[ShopSelectionItem] = []
        self.select_button = Button(area=(0, 0, 1, 1), color=(), button=(0, 0, 1, 1), name="SELECT_ITEM")

    def shop_get_select(self, item: ShopSelectionItem) -> Button:
        self.selected_items.append(item)
        return self.select_button

    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        results = self.appear_results.get(id(button), [])
        if results:
            return results.pop(0)
        return False

    def ui_ensure_index(
        self,
        index: int,
        controls: UiIndexControls,
        *_args: object,
        **kwargs: bool,
    ) -> None:
        self.ensure_calls.append((index, controls, kwargs))
        letter = controls.letter
        if isinstance(letter, IndexOcr):
            self.ensure_letter_result = letter.ocr_single(self.device.image)
        else:
            self.ensure_letter_result = letter(self.device.image)


class _ImmediateTimer:
    def __init__(self, _limit: float, count: int = 0) -> None:
        del count

    def start(self) -> _ImmediateTimer:
        return self

    @staticmethod
    def reached() -> bool:
        return True

    def reset(self) -> _ImmediateTimer:
        return self


def test_shop_buy_select_execute_caps_limit_by_currency(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert shop.device.clicked == [shop.select_button, SHOP_BUY_CONFIRM_SELECT]
    assert shop.ensure_calls[0][0] == 3
    assert shop.ensure_letter_result == 3


def test_shop_buy_select_execute_raises_when_stock_limit_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    stock_ocr = _FakeStockOcr([])
    monkeypatch.setattr(shop_clerk, "OCR_SHOP_SELECT_STOCK", stock_ocr)
    monkeypatch.setattr(shop_clerk, "Timer", _ImmediateTimer)
    shop = _FakeShopClerk(currency=6)

    with pytest.raises(ScriptError):
        shop.shop_buy_select_execute(_FakeItem())

    assert shop.device.clicked == []
