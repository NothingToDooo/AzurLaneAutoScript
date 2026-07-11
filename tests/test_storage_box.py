from typing import ClassVar, TypeVar

import pytest

from module.retire.assets import EQUIP_CONFIRM, EQUIP_CONFIRM_2
from module.shop.assets import AMOUNT_MINUS, AMOUNT_PLUS
from module.storage import assets as storage_assets
from module.storage import storage as storage_module
from module.storage.storage import StorageHandler

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


class _Digit:
    values: ClassVar[list[int]] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    @staticmethod
    def ocr(_image: object) -> int:
        return _Digit.values.pop(0)


class _Device:
    image = object()

    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.multi_clicks: list[tuple[object, int, tuple[float, float]]] = []

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def multi_click(self, button: object, *, n: int, interval: tuple[float, float]) -> None:
        self.multi_clicks.append((button, n, interval))


class _Storage(StorageHandler):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.match_template_results: dict[str, list[bool]] = {}
        self.storage_in_material_results: list[bool] = []
        self.box_amount_results: list[int] = []

    def handle_box_amount(self, amount: int) -> int:
        return self._handle_use_box_amount(amount)

    def use_one_box(self, button: object, amount: int) -> int:
        return self._storage_use_one_box(button, amount=amount)

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    @staticmethod
    def loop(*_args: object, **_kwargs: object) -> range:
        return range(20)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def match_template_color(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("match_template_color", key, kwargs))
        return self._next_result(self.match_template_results.get(key, []), default=False)

    def _storage_in_material(self, *_args: object, **kwargs: object) -> bool:
        self.calls.append(("_storage_in_material", kwargs))
        return self._next_result(self.storage_in_material_results, default=False)

    def _handle_use_box_amount(self, amount: int) -> int:
        if self.box_amount_results:
            return self.box_amount_results.pop(0)
        return super()._handle_use_box_amount(amount)

    def interval_clear(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_clear", button))

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button))

    def ui_click(
        self,
        click_button: object,
        check_button: object = None,
        options: object = None,
        **settings: object,
    ) -> None:
        self.calls.append(("ui_click", click_button, check_button, options, settings))


@pytest.fixture(autouse=True)
def _patch_timer_and_digit(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Digit.values = []
    monkeypatch.setattr(storage_module, "Timer", _Timer)
    monkeypatch.setattr(storage_module, "Digit", _Digit)


def test_handle_use_box_amount_increases_with_retry() -> None:
    storage = _Storage()
    storage.appear_results[button_key(AMOUNT_MINUS)] = [True]
    storage.appear_results[button_key(AMOUNT_PLUS)] = [True]
    _Digit.values = [1, 3]
    _Timer.reached_results = {2: [True]}

    result = storage.handle_box_amount(3)

    assert result == 3
    assert (AMOUNT_PLUS, 2, (0.1, 0.2)) in storage.device.multi_clicks


def test_storage_use_one_box_tracks_amount_until_material_page_returns() -> None:
    storage = _Storage()
    box = object()
    storage.storage_in_material_results = [True, False, False, False, True]
    storage.appear_then_click_results[button_key(storage_assets.BOX_USE)] = [True]
    storage.match_template_results[button_key(storage_assets.BOX_AMOUNT_CONFIRM)] = [True, False]
    storage.appear_then_click_results[button_key(EQUIP_CONFIRM_2)] = [True]
    storage.appear_results[button_key(EQUIP_CONFIRM_2)] = [False]
    storage.box_amount_results = [2]

    result = storage.use_one_box(box, amount=2)

    assert result == 2
    assert box in storage.device.clicks
    assert storage_assets.BOX_AMOUNT_CONFIRM in storage.device.clicks
    assert ("interval_reset", storage_assets.BOX_AMOUNT_CONFIRM) in storage.calls


def test_storage_use_one_box_keeps_waiting_after_first_confirm() -> None:
    storage = _Storage()
    box = object()
    storage.storage_in_material_results = [False, True]
    storage.appear_then_click_results[button_key(EQUIP_CONFIRM)] = [True]
    storage.appear_results[button_key(EQUIP_CONFIRM_2)] = [False]

    result = storage.use_one_box(box, amount=1)

    assert result == 0
    assert ("interval_reset", storage_assets.MATERIAL_CHECK) in storage.calls
