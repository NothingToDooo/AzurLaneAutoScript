from dataclasses import dataclass
from typing import ClassVar, TypeVar

import pytest

from module.combat.assets import GET_ITEMS_1
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


class _Device:
    image = object()

    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.click_record: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)
        self.click_record.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


@dataclass
class _Item:
    amount: int


class _EquipmentItems:
    def __init__(self, items: list[_Item]) -> None:
        self.items = items
        self.calls: list[tuple[object, ...]] = []

    def predict(self, image: object, **kwargs: object) -> list[_Item]:
        self.calls.append((image, kwargs))
        return self.items


class _Ocr:
    def __init__(self, values: list[int]) -> None:
        self.values = values

    def ocr(self, _image: object) -> int:
        return self.values.pop(0)


class _Storage(StorageHandler):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.info_bar_results: list[bool] = []
        self.popup_results: list[bool] = []

    def disassemble_once(self, amount: int) -> int:
        return self._storage_disassemble_equipment_execute_once(amount=amount)

    def confirm_disassemble(self, disassembled: int) -> int:
        return self._confirm_disassemble_equipment(disassembled=disassembled)

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    @staticmethod
    def loop(*_args: object, **_kwargs: object) -> range:
        return range(20)

    def interval_clear(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_clear", button))

    def wait_until_stable(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("wait_until_stable", button))

    def handle_info_bar(self) -> bool:
        self.calls.append(("handle_info_bar",))
        return self._next_result(self.info_bar_results, default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def handle_popup_confirm(self, name: str = "", offset: object = None, interval: float = 2) -> bool:
        _ = (name, offset, interval)
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    monkeypatch.setattr(storage_module, "Timer", _Timer)


def test_storage_disassemble_once_returns_zero_without_items(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _Storage()
    storage.appear_results[button_key(storage_assets.DISASSEMBLE_CANCEL)] = [True]
    monkeypatch.setattr(storage_module, "EQUIPMENT_ITEMS", _EquipmentItems([]))

    result = storage.disassemble_once(amount=40)

    assert result == 0
    assert ("wait_until_stable", storage_assets.MATERIAL_STABLE_CHECK) in storage.calls


def test_storage_disassemble_once_selects_until_cumulative_amount(monkeypatch: pytest.MonkeyPatch) -> None:
    item_a = _Item(2)
    item_b = _Item(3)
    item_c = _Item(10)
    storage = _Storage()
    storage.appear_results[button_key(storage_assets.DISASSEMBLE_CANCEL)] = [True, True]
    storage.appear_then_click_results[button_key(storage_assets.DISASSEMBLE_CONFIRM)] = [True, False]
    storage.appear_then_click_results[button_key(storage_assets.DISASSEMBLE_POPUP_CONFIRM)] = [True]
    monkeypatch.setattr(storage_module, "EQUIPMENT_ITEMS", _EquipmentItems([item_a, item_b, item_c]))
    monkeypatch.setattr(storage_module, "OCR_DISASSEMBLE_COUNT", _Ocr([1, 5]))

    result = storage.disassemble_once(amount=4)

    assert result == 5
    assert storage.device.clicks[:2] == [item_a, item_b]
    assert storage.device.screenshot_count >= 2


def test_confirm_disassemble_accepts_get_items_popup() -> None:
    storage = _Storage()
    storage.appear_results[button_key(GET_ITEMS_1)] = [True]
    storage.appear_results[button_key(storage_assets.DISASSEMBLE_CANCEL)] = [True]

    result = storage.confirm_disassemble(disassembled=7)

    assert result == 7
    assert storage_assets.DISASSEMBLE_CONFIRM in storage.device.clicks
