from types import SimpleNamespace

from module.map import assets as map_assets
from module.map import map_operation as map_operation_module
from module.map.map_operation import MapOperation


class _Timer:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.reset_count = 0

    def reached(self):
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self):
        self.reset_count += 1


class _Resettable:
    def __init__(self) -> None:
        self.reset_count = 0

    def reset(self) -> None:
        self.reset_count += 1


class _Device:
    def __init__(self, calls) -> None:
        self.calls = calls
        self.screenshot_count = 0

    def click(self, button) -> None:
        self.calls.append(("click", button))

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _MapOperation(MapOperation):
    def __init__(self, *, auto_search: bool = False) -> None:
        self.calls = []
        self.device = _Device(self.calls)
        self.config = SimpleNamespace(StopCondition_MapAchievement="100_percent")
        self.map_clear_percentage_timer = _Resettable()
        self.map_is_auto_search = auto_search
        self.map_fleet_checked = False
        self.in_map_results = []
        self.daily_misclick_results = []
        self.fleet_preparation_visible_results = []
        self.map_mode_results = []
        self.map_preparation_results = []
        self.map_stop_results = []
        self.auto_search_continue_results = []
        self.retirement_results = []
        self.data_key_results = []
        self.submarine_popup_results = []
        self.low_emotion_results = []
        self.urgent_results = []
        self.book_popup_results = []
        self.story_results = []
        self.stage_click_results = []
        self.auto_search_running_results = []
        self.combat_loading_results = []
        self.enemy_searching_results = []

    @staticmethod
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def is_in_map(self):
        self.calls.append(("is_in_map",))
        return self._next(self.in_map_results)

    def appear(self, button, **_kwargs):
        self.calls.append(("appear", button))
        if button == map_operation_module.DAILY_CHECK:
            return self._next(self.daily_misclick_results)
        if button == map_assets.FLEET_PREPARATION:
            return self._next(self.fleet_preparation_visible_results)
        return False

    def handle_map_mode_switch(self, mode):
        self.calls.append(("handle_map_mode_switch", mode))
        return self._next(self.map_mode_results)

    def handle_map_preparation(self):
        self.calls.append(("handle_map_preparation",))
        return self._next(self.map_preparation_results)

    def map_get_info(self) -> None:
        self.calls.append(("map_get_info",))

    def handle_map_walk_speedup(self) -> None:
        self.calls.append(("handle_map_walk_speedup",))

    def handle_fast_forward(self) -> None:
        self.calls.append(("handle_fast_forward",))

    def handle_auto_search(self) -> None:
        self.calls.append(("handle_auto_search",))

    def triggered_map_stop(self):
        self.calls.append(("triggered_map_stop",))
        return self._next(self.map_stop_results)

    def handle_2x_book_setting(self, *, mode) -> None:
        self.calls.append(("handle_2x_book_setting", mode))

    def fleet_preparation(self) -> None:
        self.calls.append(("fleet_preparation",))

    def handle_auto_submarine_call_disable(self) -> None:
        self.calls.append(("handle_auto_submarine_call_disable",))

    def handle_auto_search_setting(self) -> None:
        self.calls.append(("handle_auto_search_setting",))

    def handle_auto_search_continue(self):
        return self._next(self.auto_search_continue_results)

    def handle_retirement(self):
        return self._next(self.retirement_results)

    def handle_use_data_key(self):
        return self._next(self.data_key_results)

    def handle_submarine_support_popup(self):
        return self._next(self.submarine_popup_results)

    def handle_combat_low_emotion(self):
        return self._next(self.low_emotion_results)

    def handle_urgent_commission(self):
        return self._next(self.urgent_results)

    def handle_2x_book_popup(self):
        return self._next(self.book_popup_results)

    def handle_story_skip(self):
        return self._next(self.story_results)

    def appear_then_click(self, button):
        result = self._next(self.stage_click_results)
        if result:
            self.device.click(button)
        return result

    def is_auto_search_running(self):
        return self._next(self.auto_search_running_results)

    def is_combat_loading(self):
        return self._next(self.combat_loading_results)

    def handle_in_map_with_enemy_searching(self):
        return self._next(self.enemy_searching_results)


def _patch_timers(monkeypatch, timers) -> None:
    timer_queue = list(timers)
    monkeypatch.setattr(map_operation_module, "Timer", lambda *_args, **_kwargs: timer_queue.pop(0))


def test_enter_map_returns_false_when_already_in_map() -> None:
    operation = _MapOperation()
    operation.in_map_results = [True]

    assert operation.enter_map(map_assets.MAP_PREPARATION) is False

    assert operation.map_clear_percentage_timer.reset_count == 1
    assert operation.device.screenshot_count == 0


def test_enter_map_runs_map_preparation_before_clicking(monkeypatch) -> None:
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


def test_enter_map_runs_fleet_preparation_before_clicking(monkeypatch) -> None:
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


def test_enter_map_breaks_when_auto_search_running(monkeypatch) -> None:
    _patch_timers(monkeypatch, [_Timer([False]), _Timer([False]), _Timer([False])])
    operation = _MapOperation(auto_search=True)
    operation.in_map_results = [False]
    operation.auto_search_running_results = [True]

    assert operation.enter_map(map_assets.MAP_PREPARATION) is True
