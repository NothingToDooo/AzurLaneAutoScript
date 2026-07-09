from typing import ClassVar, TypeVar

import pytest

from module.equipment import assets as equipment_assets
from module.equipment import equipment as equipment_module
from module.equipment.equipment import Equipment

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Timer:
    next_index: ClassVar[int] = 0
    started_results: ClassVar[dict[int, list[bool]]] = {}
    reached_results: ClassVar[dict[int, list[bool]]] = {}
    reset_count: ClassVar[int] = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def started(self) -> bool:
        results = _Timer.started_results.get(self.index)
        if results:
            return results.pop(0)
        return True

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> None:
        _Timer.reset_count += 1


class _Device:
    image = object()

    def __init__(self) -> None:
        self.screenshot_count = 0
        self.swipes: list[dict[str, object]] = []

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def swipe_vector(self, vector: object, options: object = None) -> None:
        self.swipes.append({"vector": vector, "options": options})


class _Equipment(Equipment):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.popup_results: list[bool] = []

    def swipe(self) -> bool:
        return self._ship_view_swipe(distance=-250)

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def handle_info_bar(self) -> bool:
        self.calls.append(("handle_info_bar",))
        return False

    def appear(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer_and_swipe_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.started_results = {}
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(equipment_module, "Timer", _Timer)
    monkeypatch.setattr(equipment_assets.SWIPE_CHECK, "load_color", lambda _image: None)
    monkeypatch.setattr(equipment_assets.SWIPE_CHECK, "mark_match_initialized", lambda: None)


def test_ship_view_swipe_returns_true_when_new_ship_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    equipment = _Equipment()
    match_results = [False, False]
    _Timer.started_results = {0: [False]}
    equipment.appear_results[button_key(equipment_assets.EQUIPMENT_OPEN)] = [True, True]

    monkeypatch.setattr(equipment_assets.SWIPE_CHECK, "match", lambda _image: match_results.pop(0))

    result = equipment.swipe()

    assert result is True
    assert len(equipment.device.swipes) == 1
    assert _Timer.reset_count == 1


def test_ship_view_swipe_returns_false_on_retire_equip_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    equipment = _Equipment()
    _Timer.started_results = {0: [False]}
    equipment.appear_results[button_key(equipment_assets.EQUIPMENT_OPEN)] = [False]
    equipment.appear_results[button_key(equipment_module.RETIRE_EQUIP_CONFIRM)] = [True]

    monkeypatch.setattr(equipment_assets.SWIPE_CHECK, "match", lambda _image: False)

    result = equipment.swipe()

    assert result is False
    assert len(equipment.device.swipes) == 1
