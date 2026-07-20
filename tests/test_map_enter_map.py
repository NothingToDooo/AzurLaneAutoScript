from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, override

from module.map import assets as map_assets
from module.map import map_operation as map_operation_module
from module.map.map_operation import MapOperation

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pytest

    from module.base.button import Button, MatchOffset


type _Call = tuple[str] | tuple[str, Button | str]


class _Timer:
    def __init__(self, results: Iterable[bool] | None = None) -> None:
        self.results = list(results or [])
        self.reset_count = 0

    def reached(self) -> bool:
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self) -> None:
        self.reset_count += 1


class _Resettable:
    def __init__(self) -> None:
        self.reset_count = 0

    def reset(self) -> None:
        self.reset_count += 1


class _Device:
    def __init__(self, calls: list[_Call]) -> None:
        self.calls = calls
        self.screenshot_count = 0

    def click(self, button: Button) -> None:
        self.calls.append(("click", button))

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _MapOperation(MapOperation):
    config: SimpleNamespace
    device: _Device
    map_clear_percentage_timer: _Resettable

    def __init__(self, *, auto_search: bool = False) -> None:
        self.calls: list[_Call] = []
        self.device = _Device(self.calls)
        self.config = SimpleNamespace(StopCondition_MapAchievement="100_percent")
        self.map_clear_percentage_timer = _Resettable()
        self.map_is_auto_search = auto_search
        self.map_fleet_checked = False
        self.in_map_results: list[bool] = []
        self.daily_misclick_results: list[bool] = []
        self.fleet_preparation_visible_results: list[bool] = []
        self.map_mode_results: list[bool] = []
        self.map_preparation_results: list[bool] = []
        self.map_stop_results: list[bool] = []
        self.auto_search_continue_results: list[bool] = []
        self.retirement_results: list[bool] = []
        self.data_key_results: list[bool] = []
        self.submarine_popup_results: list[bool] = []
        self.low_emotion_results: list[bool] = []
        self.urgent_results: list[bool] = []
        self.book_popup_results: list[bool] = []
        self.story_results: list[bool] = []
        self.stage_click_results: list[bool] = []
        self.auto_search_running_results: list[bool] = []
        self.combat_loading_results: list[bool] = []
        self.enemy_searching_results: list[bool] = []

    @staticmethod
    def _next(results: list[bool]) -> bool:
        if results:
            return results.pop(0)
        return False

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self._next(self.in_map_results)

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del offset, interval, similarity, threshold
        self.calls.append(("appear", button))
        if button == map_operation_module.DAILY_CHECK:
            return self._next(self.daily_misclick_results)
        if button == map_assets.FLEET_PREPARATION:
            return self._next(self.fleet_preparation_visible_results)
        return False

    @override
    def handle_map_mode_switch(self, mode: str) -> bool:
        self.calls.append(("handle_map_mode_switch", mode))
        return self._next(self.map_mode_results)

    @override
    def handle_map_preparation(self) -> bool:
        self.calls.append(("handle_map_preparation",))
        return self._next(self.map_preparation_results)

    def map_get_info(self) -> None:
        self.calls.append(("map_get_info",))

    @override
    def handle_map_walk_speedup(self, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("handle_map_walk_speedup",))
        return False

    @override
    def handle_fast_forward(self) -> bool:
        self.calls.append(("handle_fast_forward",))
        return False

    @override
    def handle_auto_search(self) -> bool:
        self.calls.append(("handle_auto_search",))
        return False

    def triggered_map_stop(self) -> bool:
        self.calls.append(("triggered_map_stop",))
        return self._next(self.map_stop_results)

    @override
    def handle_2x_book_setting(self, mode: Literal["prep", "auto"] = "prep") -> bool:
        self.calls.append(("handle_2x_book_setting", mode))
        return False

    @override
    def fleet_preparation(self) -> bool:
        self.calls.append(("fleet_preparation",))
        return False

    @override
    def handle_auto_submarine_call_disable(self) -> bool:
        self.calls.append(("handle_auto_submarine_call_disable",))
        return False

    @override
    def handle_auto_search_setting(self) -> bool:
        self.calls.append(("handle_auto_search_setting",))
        return False

    def handle_auto_search_continue(self) -> bool:
        return self._next(self.auto_search_continue_results)

    def handle_retirement(self) -> bool:
        return self._next(self.retirement_results)

    def handle_use_data_key(self) -> bool:
        return self._next(self.data_key_results)

    def handle_submarine_support_popup(self) -> bool:
        self.calls.append(("handle_submarine_support_popup",))
        return self._next(self.submarine_popup_results)

    def handle_combat_low_emotion(self) -> bool:
        return self._next(self.low_emotion_results)

    def handle_urgent_commission(self) -> bool:
        return self._next(self.urgent_results)

    def handle_2x_book_popup(self) -> bool:
        return self._next(self.book_popup_results)

    def handle_story_skip(self) -> bool:
        return self._next(self.story_results)

    @override
    def appear_then_click(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        del offset, interval, similarity, threshold
        result = self._next(self.stage_click_results)
        if result:
            self.device.click(button)
        return result

    def is_auto_search_running(self) -> bool:
        return self._next(self.auto_search_running_results)

    def is_combat_loading(self) -> bool:
        return self._next(self.combat_loading_results)

    def handle_in_map_with_enemy_searching(self) -> bool:
        return self._next(self.enemy_searching_results)


def _patch_timers(monkeypatch: pytest.MonkeyPatch, timers: Iterable[_Timer]) -> None:
    timer_queue = list(timers)
    monkeypatch.setattr(map_operation_module, "Timer", lambda *_args, **_kwargs: timer_queue.pop(0))


def test_enter_map_returns_false_when_already_in_map() -> None:
    operation = _MapOperation()
    operation.in_map_results = [True]

    assert operation.enter_map(map_assets.MAP_PREPARATION) is False

    assert operation.map_clear_percentage_timer.reset_count == 1
    assert operation.device.screenshot_count == 0


def test_enter_map_runs_map_preparation_before_clicking(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([False]), _Timer([True, False]), _Timer([False])])
    operation = _MapOperation()
    operation.in_map_results = [False]
    operation.map_mode_results = [True]
    operation.map_preparation_results = [True]
    operation.map_stop_results = [False]
    operation.enemy_searching_results = [True]

    assert operation.enter_map(map_assets.MAP_PREPARATION) is True

    expected = [
        ("handle_map_mode_switch", "normal"),
        ("handle_map_preparation",),
        ("map_get_info",),
        ("handle_map_walk_speedup",),
        ("handle_fast_forward",),
        ("handle_auto_search",),
        ("triggered_map_stop",),
        ("click", map_assets.MAP_PREPARATION),
    ]
    assert operation.calls[2:10] == expected


def test_enter_map_runs_fleet_preparation_before_clicking(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([False]), _Timer([False]), _Timer([True])])
    operation = _MapOperation()
    operation.in_map_results = [False]
    operation.fleet_preparation_visible_results = [True]
    operation.enemy_searching_results = [True]

    assert operation.enter_map(map_assets.MAP_PREPARATION) is True

    actual = tuple(
        call
        for call in operation.calls
        if call[0]
        in {
            "handle_2x_book_setting",
            "fleet_preparation",
            "handle_auto_submarine_call_disable",
            "handle_auto_search_setting",
            "click",
        }
    )
    expected = (
        ("handle_2x_book_setting", "prep"),
        ("fleet_preparation",),
        ("handle_auto_submarine_call_disable",),
        ("handle_auto_search_setting",),
        ("click", map_assets.FLEET_PREPARATION),
    )
    assert actual == expected
    assert operation.map_fleet_checked is True


def test_enter_map_breaks_when_auto_search_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([False]), _Timer([False]), _Timer([False])])
    operation = _MapOperation(auto_search=True)
    operation.in_map_results = [False]
    operation.auto_search_running_results = [True]

    assert operation.enter_map(map_assets.MAP_PREPARATION) is True


def test_enter_map_retries_submarine_popup_on_the_next_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([False]), _Timer([False]), _Timer([False])])
    operation = _MapOperation()
    operation.in_map_results = [False]
    operation.submarine_popup_results = [True, False]
    operation.enemy_searching_results = [True]

    assert operation.enter_map(map_assets.MAP_PREPARATION) is True

    popup_calls = [call for call in operation.calls if call == ("handle_submarine_support_popup",)]
    assert popup_calls == [
        ("handle_submarine_support_popup",),
        ("handle_submarine_support_popup",),
    ]
