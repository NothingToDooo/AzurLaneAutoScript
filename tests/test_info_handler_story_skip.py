from typing import ClassVar, TypeVar

import pytest

from module.handler import assets as handler_assets
from module.handler import info_handler as info_handler_module
from module.handler.info_handler import InfoHandler
from module.os_handler.assets import CLICK_SAFE_AREA as OS_CLICK_SAFE_AREA

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}
    started_results: ClassVar[dict[int, list[bool]]] = {}

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def started(self) -> bool:
        results = _Timer.started_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> None:
        pass


class _Config:
    STORY_OPTION = 1
    STORY_ALLOW_SKIP = True


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.image = object()

    def click(self, button: object) -> None:
        self.clicks.append(button)


class _InfoHandler(InfoHandler):
    config: _Config
    device: _Device
    story_popup_timeout: _Timer
    _story_option_timer: _Timer
    _story_option_confirm: _Timer
    _story_confirm: _Timer

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.popup_results: list[bool] = []
        self.story_black_results: list[bool] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.option_buttons: list[object] = []
        self.story_popup_timeout = _Timer()
        self._story_option_timer = _Timer()
        self._story_option_confirm = _Timer()
        self._story_confirm = _Timer()
        self._story_option_record = 0

    def skip_story(self) -> bool:
        return self.story_skip()

    def set_story_popup_timer(self, *, started: list[bool], reached: list[bool]) -> None:
        _Timer.started_results[self.story_popup_timeout.index] = started
        _Timer.reached_results[self.story_popup_timeout.index] = reached

    def set_story_option_timer(self, *, reached: list[bool]) -> None:
        _Timer.reached_results[self._story_option_timer.index] = reached

    def set_story_option_confirm(self, *, reached: list[bool]) -> None:
        _Timer.reached_results[self._story_option_confirm.index] = reached

    def set_story_confirm(self, *, reached: list[bool]) -> None:
        _Timer.reached_results[self._story_confirm.index] = reached

    def set_story_option_record(self, count: int) -> None:
        self._story_option_record = count

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def handle_popup_confirm(self, name="", offset=None, interval=2) -> bool:
        _ = (name, offset, interval)
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def interval_reset(self, button: object, *_args: object, **kwargs: object) -> None:
        self.calls.append(("interval_reset", button, kwargs))

    def interval_clear(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_clear", button))

    def _is_story_black(self) -> bool:
        self.calls.append(("_is_story_black",))
        return self._next_result(self.story_black_results, default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def _story_option_buttons_2(self) -> list[object]:
        self.calls.append(("_story_option_buttons_2",))
        return self.option_buttons


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.started_results = {}
    monkeypatch.setattr(info_handler_module, "Timer", _Timer)


def test_story_skip_confirms_popup_during_timeout() -> None:
    handler = _InfoHandler()
    handler.set_story_popup_timer(started=[True], reached=[False])
    handler.popup_results = [True]

    result = handler.skip_story()

    assert result is True
    assert ("interval_reset", handler_assets.STORY_SKIP_3, {}) in handler.calls
    assert ("interval_reset", handler_assets.STORY_LETTERS_ONLY, {}) in handler.calls


def test_story_skip_selects_stable_story_option() -> None:
    handler = _InfoHandler()
    option_a = object()
    option_b = object()
    handler.option_buttons = [option_a, option_b]
    handler.set_story_option_record(2)
    handler.set_story_option_timer(reached=[True])
    handler.set_story_option_confirm(reached=[True])
    handler.appear_results[button_key(handler_assets.STORY_SKIP_3)] = [True]

    result = handler.skip_story()

    assert result is True
    assert handler.device.clicks == [option_b]
    assert ("interval_reset", handler_assets.STORY_SKIP_3, {}) in handler.calls


def test_story_skip_clicks_safe_area_when_skip_disabled() -> None:
    handler = _InfoHandler()
    handler.config.STORY_ALLOW_SKIP = False
    handler.set_story_confirm(reached=[True])
    handler.appear_results[button_key(handler_assets.STORY_SKIP_3)] = [True]

    result = handler.skip_story()

    assert result is True
    assert handler.device.clicks == [OS_CLICK_SAFE_AREA]
