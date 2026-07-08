from typing import ClassVar, TypeVar

import pytest

from module.os import assets as os_assets
from module.os import globe_operation as globe_operation_module
from module.os.globe_operation import GlobeOperation, RewardUncollectedError

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return str(getattr(button, "name", repr(button)))


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

    def reset(self) -> _Timer:
        _Timer.reset_count += 1
        return self


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []

    def click(self, button: object) -> None:
        self.clicks.append(button)


class _GlobeOperation(GlobeOperation):
    def __init__(self) -> None:
        self.has_switch = True
        self.pinned_name = ""
        self.selection_results: list[list[object]] = []
        self.executed_buttons: list[object] = []
        self.enter_count = 0
        self.update_pinned_on_execute = True
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.loop_count = 10
        self.in_globe_results: list[bool] = []
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.appear_results: dict[str, list[bool]] = {}
        self.map_event_results: list[bool] = []
        self.popup_results: list[bool] = []
        self.handle_zone_pinned_results: list[bool] = []
        self.zone_pinned_results: list[bool] = []
        self.interval_resets: list[str] = []

    def select_zone_type(self, types: tuple[str, ...] | list[str] | str = ("SAFE", "DANGEROUS")) -> bool:
        return self.zone_type_select(types)

    def goto_globe(self, *, unpin: bool = True) -> None:
        self.os_map_goto_globe(unpin=unpin)

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def loop(self):
        return range(self.loop_count)

    def zone_has_switch(self) -> bool:
        return self.has_switch

    def get_zone_pinned_name(self) -> str:
        return self.pinned_name

    def zone_select_enter(self) -> None:
        self.enter_count += 1

    def ensure_zone_select_expanded(self) -> list[object]:
        if self.selection_results:
            return self.selection_results.pop(0)
        return []

    def zone_select_execute(self, button: object) -> None:
        self.executed_buttons.append(button)
        if self.update_pinned_on_execute:
            self.pinned_name = self.pinned_to_name(button)

    def is_in_globe(self) -> bool:
        self.calls.append(("is_in_globe",))
        return self._next_result(self.in_globe_results, default=False)

    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def appear(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def interval_reset(self, button: object) -> None:
        key = button_key(button)
        self.calls.append(("interval_reset", key))
        self.interval_resets.append(key)

    def handle_map_event(self) -> bool:
        self.calls.append(("handle_map_event",))
        return self._next_result(self.map_event_results, default=False)

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def handle_zone_pinned(self) -> bool:
        self.calls.append(("handle_zone_pinned",))
        return self._next_result(self.handle_zone_pinned_results, default=False)

    def is_zone_pinned(self) -> bool:
        self.calls.append(("is_zone_pinned",))
        return self._next_result(self.zone_pinned_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(globe_operation_module, "Timer", _Timer)


def test_zone_type_select_skips_zone_without_switch() -> None:
    operation = _GlobeOperation()
    operation.has_switch = False

    result = operation.select_zone_type("SAFE")

    assert result is True
    assert operation.enter_count == 0


def test_zone_type_select_keeps_matching_pinned_type() -> None:
    operation = _GlobeOperation()
    operation.pinned_name = "SAFE"

    result = operation.select_zone_type(("SAFE", "DANGEROUS"))

    assert result is True
    assert operation.executed_buttons == []


def test_zone_type_select_accepts_string_type() -> None:
    operation = _GlobeOperation()
    operation.selection_results = [[os_assets.SELECT_SAFE, os_assets.SELECT_DANGEROUS]]

    result = operation.select_zone_type("SAFE")

    assert result is True
    assert operation.executed_buttons == [os_assets.SELECT_SAFE]


def test_zone_type_select_falls_back_to_default_types() -> None:
    operation = _GlobeOperation()
    operation.selection_results = [[os_assets.SELECT_DANGEROUS, os_assets.SELECT_SAFE]]

    result = operation.select_zone_type(("ARCHIVE",))

    assert result is True
    assert operation.executed_buttons == [os_assets.SELECT_SAFE]


def test_zone_type_select_returns_false_after_retry_failure() -> None:
    operation = _GlobeOperation()
    operation.update_pinned_on_execute = False
    operation.selection_results = [
        [os_assets.SELECT_SAFE],
        [os_assets.SELECT_SAFE],
        [os_assets.SELECT_SAFE],
    ]

    result = operation.select_zone_type("SAFE")

    assert result is False
    assert operation.enter_count == 3
    assert operation.executed_buttons == [os_assets.SELECT_SAFE] * 3


def test_os_map_goto_globe_clicks_map_button_and_confirms_unpinned() -> None:
    operation = _GlobeOperation()
    operation.in_globe_results = [False, True]
    operation.appear_then_click_results[button_key(os_assets.MAP_GOTO_GLOBE)] = [True]
    operation.handle_zone_pinned_results = [True, False]
    _Timer.reached_results = {0: [True]}

    operation.goto_globe()

    assert operation.interval_resets == [button_key(os_assets.MAP_GOTO_GLOBE_FOG)]
    assert _Timer.reset_count == 1
    assert operation.device.clicks == []


def test_os_map_goto_globe_raises_after_repeated_blocked_clicks() -> None:
    operation = _GlobeOperation()
    operation.in_globe_results = [False] * 5
    operation.appear_then_click_results[button_key(os_assets.MAP_GOTO_GLOBE)] = [True] * 5

    with pytest.raises(RewardUncollectedError):
        operation.goto_globe()

    assert operation.interval_resets == [button_key(os_assets.MAP_GOTO_GLOBE_FOG)] * 5


def test_os_map_goto_globe_can_keep_zone_pinned() -> None:
    operation = _GlobeOperation()
    operation.in_globe_results = [True]
    operation.zone_pinned_results = [False, True]

    operation.goto_globe(unpin=False)

    assert ("is_zone_pinned",) in operation.calls
    assert ("handle_zone_pinned",) not in operation.calls
