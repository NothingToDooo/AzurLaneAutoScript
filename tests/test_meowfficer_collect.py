from typing import ClassVar, TypeVar

import pytest

from module.meowfficer import assets as meow_assets
from module.meowfficer import collect as collect_module
from module.meowfficer.collect import MeowfficerCollect

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

    def start(self) -> _Timer:
        return self

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> None:
        _Timer.reset_count += 1


class _ClickRecord:
    def __init__(self) -> None:
        self.pop_count = 0

    def pop(self) -> None:
        self.pop_count += 1


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.click_record = _ClickRecord()
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Config:
    MeowfficerTrain_RetainTalentedGold = False
    MeowfficerTrain_RetainTalentedPurple = False


class _MeowfficerCollect(MeowfficerCollect):
    config: _Config
    device: _Device

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.popup_results: list[bool] = []
        self.special_results: list[bool] = []

    def get(self) -> None:
        self.meow_get()

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def handle_meow_popup_dismiss(self) -> bool:
        self.calls.append(("handle_meow_popup_dismiss",))
        return self._next_result(self.popup_results, default=False)

    def _meow_is_special_talented(self) -> bool:
        self.calls.append(("_meow_is_special_talented",))
        return self._next_result(self.special_results, default=False)

    def _meow_skip_popup_after_locking(self, *_args: object, **kwargs: object) -> None:
        self.calls.append(("_meow_skip_popup_after_locking", kwargs))

    def _meow_skip_lock(self) -> None:
        self.calls.append(("_meow_skip_lock",))

    def _meow_apply_lock(self, lock: object = True) -> None:
        self.calls.append(("_meow_apply_lock", lock))

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button))


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(collect_module, "Timer", _Timer)


def test_meow_get_exits_when_train_page_is_stable() -> None:
    meow = _MeowfficerCollect()
    meow.appear_results[button_key(meow_assets.MEOWFFICER_TRAIN_START)] = [True]
    _Timer.reached_results = {0: [True]}

    meow.get()

    assert meow.device.clicks == []
    assert meow.device.screenshot_count == 0


def test_meow_get_dismisses_popup_before_exit() -> None:
    meow = _MeowfficerCollect()
    meow.appear_results[button_key(meow_assets.MEOWFFICER_TRAIN_START)] = [False, True]
    meow.popup_results = [True]
    _Timer.reached_results = {0: [True]}

    meow.get()

    assert ("handle_meow_popup_dismiss",) in meow.calls
    assert meow.device.screenshot_count == 1


def test_meow_get_skips_gold_lock_when_not_retaining() -> None:
    meow = _MeowfficerCollect()
    meow.appear_results[button_key(meow_assets.MEOWFFICER_TRAIN_START)] = [False, True]
    meow.appear_results[button_key(meow_assets.MEOWFFICER_GET_CHECK)] = [True]
    meow.appear_results[button_key(meow_assets.MEOWFFICER_APPLY_UNLOCK)] = [False]
    meow.appear_results[button_key(meow_assets.MEOWFFICER_GOLD_CHECK)] = [True]
    meow.special_results = [True]
    _Timer.reached_results = {0: [True]}

    meow.get()

    assert ("_meow_skip_lock",) in meow.calls
    assert meow.device.clicks == []


def test_meow_get_locks_talented_purple_and_continues_next() -> None:
    meow = _MeowfficerCollect()
    meow.config.MeowfficerTrain_RetainTalentedPurple = True
    meow.appear_results[button_key(meow_assets.MEOWFFICER_TRAIN_START)] = [False, True]
    meow.appear_results[button_key(meow_assets.MEOWFFICER_GET_CHECK)] = [True]
    meow.appear_results[button_key(meow_assets.MEOWFFICER_APPLY_UNLOCK)] = [False]
    meow.appear_results[button_key(meow_assets.MEOWFFICER_GOLD_CHECK)] = [False]
    meow.appear_results[button_key(meow_assets.MEOWFFICER_PURPLE_CHECK)] = [True]
    meow.special_results = [True]
    _Timer.reached_results = {0: [True]}

    meow.get()

    assert ("_meow_apply_lock", True) in meow.calls
    assert meow.device.clicks == [meow_assets.MEOWFFICER_TRAIN_CLICK_SAFE_AREA]
    assert meow.device.click_record.pop_count == 1
    assert ("interval_reset", meow_assets.MEOWFFICER_GET_CHECK) in meow.calls
