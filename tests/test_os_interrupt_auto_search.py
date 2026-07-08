from typing import ClassVar, TypeVar

import pytest

from module.os import map as map_module
from module.os.map import OSMap

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return str(getattr(button, "name", repr(button)))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}
    reset_count: ClassVar[int] = 0
    clear_count: ClassVar[int] = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> _Timer:
        _Timer.reset_count += 1
        return self

    def clear(self) -> _Timer:
        _Timer.clear_count += 1
        return self


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []

    def click(self, button: object) -> None:
        self.clicks.append(button)


class _Config:
    def __init__(self) -> None:
        self.task_stop_count = 0

    def task_stop(self) -> None:
        self.task_stop_count += 1


class _InterruptMap(OSMap):
    def __init__(self) -> None:
        self.device = _Device()
        self.config = _Config()
        self.calls: list[tuple[object, ...]] = []
        self.loop_count = 1
        self.in_main_results: list[bool] = []
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.combat_executing_results: list[object | None] = []
        self.combat_quit_results: list[bool] = []
        self.combat_quit_reconfirm_results: list[bool] = []
        self.ui_additional_results: list[bool] = []
        self.map_event_results: list[str] = []
        self.combat_loading_results: list[bool] = []
        self.battle_status_results: list[bool] = []
        self.exp_info_results: list[bool] = []
        self.interval_clears: list[object] = []
        self.interval_resets: list[object] = []

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def loop(self) -> range:
        return range(self.loop_count)

    def is_in_main(self) -> bool:
        self.calls.append(("is_in_main",))
        return self._next_result(self.in_main_results, default=False)

    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def interval_clear(self, button: object) -> None:
        self.calls.append(("interval_clear", button))
        self.interval_clears.append(button)

    def is_combat_executing(self) -> object | None:
        self.calls.append(("is_combat_executing",))
        return self._next_result(self.combat_executing_results, default=None)

    def interval_reset(self, button: object) -> None:
        self.calls.append(("interval_reset", button))
        self.interval_resets.append(button)

    def handle_combat_quit(self) -> bool:
        self.calls.append(("handle_combat_quit",))
        return self._next_result(self.combat_quit_results, default=False)

    def handle_combat_quit_reconfirm(self) -> bool:
        self.calls.append(("handle_combat_quit_reconfirm",))
        return self._next_result(self.combat_quit_reconfirm_results, default=False)

    def ui_additional(self) -> bool:
        self.calls.append(("ui_additional",))
        return self._next_result(self.ui_additional_results, default=False)

    def handle_map_event(self) -> str:
        self.calls.append(("handle_map_event",))
        return self._next_result(self.map_event_results, default="")

    def is_combat_loading(self) -> bool:
        self.calls.append(("is_combat_loading",))
        return self._next_result(self.combat_loading_results, default=False)

    def handle_battle_status(self) -> bool:
        self.calls.append(("handle_battle_status",))
        return self._next_result(self.battle_status_results, default=False)

    def handle_exp_info(self) -> bool:
        self.calls.append(("handle_exp_info",))
        return self._next_result(self.exp_info_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    _Timer.clear_count = 0
    monkeypatch.setattr(map_module, "Timer", _Timer)


def test_interrupt_auto_search_clears_reward_popup() -> None:
    runner = _InterruptMap()
    runner.appear_then_click_results[button_key(map_module.AUTO_SEARCH_REWARD)] = [True]

    runner.interrupt_auto_search()

    assert runner.interval_clears == [map_module.GOTO_MAIN]
    assert _Timer.reset_count == 1


def test_interrupt_auto_search_clicks_pause_when_combat_is_executing() -> None:
    runner = _InterruptMap()
    pause_button = object()
    runner.combat_executing_results = [pause_button]
    _Timer.reached_results = {0: [True]}

    runner.interrupt_auto_search()

    assert runner.device.clicks == [pause_button]
    assert runner.interval_resets == [map_module.MAINTENANCE_ANNOUNCE]
    assert _Timer.reset_count == 2


def test_interrupt_auto_search_handles_quit_without_reconfirm() -> None:
    runner = _InterruptMap()
    runner.combat_quit_results = [True]

    runner.interrupt_auto_search()

    assert ("handle_combat_quit_reconfirm",) not in runner.calls
    assert runner.interval_resets == [map_module.MAINTENANCE_ANNOUNCE]


def test_interrupt_auto_search_tracks_loading_until_combat_executes() -> None:
    runner = _InterruptMap()
    runner.loop_count = 2
    runner.combat_loading_results = [True]
    runner.combat_executing_results = ["combat"]
    _Timer.reached_results = {0: [False, False]}

    runner.interrupt_auto_search()

    assert ("is_combat_loading",) in runner.calls
    assert ("is_combat_executing",) in runner.calls
    assert _Timer.clear_count == 2


def test_interrupt_auto_search_handles_exp_info_after_main_timer() -> None:
    runner = _InterruptMap()
    runner.exp_info_results = [True]
    _Timer.reached_results = {0: [False], 1: [True]}

    runner.interrupt_auto_search()

    assert ("handle_battle_status",) in runner.calls
    assert ("handle_exp_info",) in runner.calls
