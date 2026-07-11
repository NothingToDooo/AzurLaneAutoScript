from typing import ClassVar, TypeVar

import pytest

from module.os.assets import GLOBE_GOTO_MAP
from module.os_handler import assets as os_assets
from module.os_handler import mission as mission_module
from module.os_handler.mission import MissionHandler

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

    @staticmethod
    def reset() -> None:
        _Timer.reset_count += 1


class _MissionHandler(MissionHandler):
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.in_mission_results: list[bool] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.match_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.popup_results: list[bool] = []
        self.get_items_results: list[bool] = []
        self.info_bar_results: list[bool] = []
        self.loop_count = 5

    def enter(self) -> None:
        self.os_mission_enter()

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def loop(self, *_args: object, **_kwargs: object) -> range:
        return range(self.loop_count)

    def is_in_os_mission(self) -> bool:
        self.calls.append(("is_in_os_mission",))
        return self._next_result(self.in_mission_results, default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def match_template_color(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("match_template_color", key, kwargs))
        return self._next_result(self.match_results.get(key, []), default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def handle_map_get_items(self, *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_map_get_items",))
        return self._next_result(self.get_items_results, default=False)

    def handle_info_bar(self) -> bool:
        self.calls.append(("handle_info_bar",))
        return self._next_result(self.info_bar_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(mission_module, "Timer", _Timer)


def test_os_mission_enter_exits_after_empty_mission_list_is_stable() -> None:
    mission = _MissionHandler()
    mission.in_mission_results = [True]
    mission.appear_results[button_key(os_assets.MISSION_FINISH)] = [False]
    mission.match_results[button_key(os_assets.MISSION_CHECKOUT)] = [False]
    _Timer.reached_results = {0: [True]}

    mission.enter()

    assert (
        "appear_then_click",
        button_key(os_assets.MISSION_ENTER),
        {"offset": (200, 5), "interval": 5},
    ) not in mission.calls


def test_os_mission_enter_clicks_entry_then_stops_when_checkout_found() -> None:
    mission = _MissionHandler()
    mission.in_mission_results = [False, True]
    mission.appear_then_click_results[button_key(os_assets.MISSION_ENTER)] = [True]
    mission.appear_results[button_key(os_assets.MISSION_FINISH)] = [False]
    mission.match_results[button_key(os_assets.MISSION_CHECKOUT)] = [True]

    mission.enter()

    assert (
        "appear_then_click",
        button_key(os_assets.MISSION_ENTER),
        {"offset": (200, 5), "interval": 5},
    ) in mission.calls
    assert ("appear_then_click", button_key(GLOBE_GOTO_MAP), {"offset": (20, 20), "interval": 2}) not in mission.calls
