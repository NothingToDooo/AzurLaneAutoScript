from typing import ClassVar, TypeVar

import pytest

from module.exception import RequestHumanTakeover
from module.os import map as map_module
from module.os.map import OSMap

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
        self.stuck_record_clear_count = 0

    def stuck_record_clear(self) -> None:
        self.stuck_record_clear_count += 1


class _Config:
    def __init__(self) -> None:
        self.task_switched_results: list[bool] = []

    def task_switched(self) -> bool:
        if self.task_switched_results:
            return self.task_switched_results.pop(0)
        return False


class _AutoSearchMap(OSMap):
    config: _Config
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.config = _Config()
        self.calls: list[tuple[object, ...]] = []
        self.loop_count = 3
        self.in_map_results: list[bool] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.map_option_results: list[bool] = []
        self.retirement_results: list[bool] = []
        self.combat_appear_results: list[bool] = []
        self.auto_search_combat_results: list[bool] = []
        self.map_event_results: list[str] = []
        self.need_repair: list[bool] = []
        self.ash_popup_canceled = True

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def loop(self) -> range:
        return range(self.loop_count)

    def hp_reset(self) -> None:
        self.calls.append(("hp_reset",))

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self._next_result(self.in_map_results, default=True)

    def appear(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def handle_os_auto_search_map_option(self, enable: object = True) -> bool:
        self.calls.append(("handle_os_auto_search_map_option", enable))
        return self._next_result(self.map_option_results, default=False)

    def handle_retirement(self) -> bool:
        self.calls.append(("handle_retirement",))
        return self._next_result(self.retirement_results, default=False)

    def combat_appear(self) -> bool:
        self.calls.append(("combat_appear",))
        return self._next_result(self.combat_appear_results, default=False)

    def on_auto_search_battle_count_add(self) -> None:
        self.calls.append(("on_auto_search_battle_count_add",))

    def interrupt_auto_search(self) -> None:
        self.calls.append(("interrupt_auto_search",))

    def auto_search_combat(self) -> bool:
        self.calls.append(("auto_search_combat",))
        return self._next_result(self.auto_search_combat_results, default=False)

    def hp_get(self) -> None:
        self.calls.append(("hp_get",))

    def handle_map_event(self) -> str:
        self.calls.append(("handle_map_event",))
        return self._next_result(self.map_event_results, default="")


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(map_module, "Timer", _Timer)


def test_os_auto_search_daemon_counts_finished_combat() -> None:
    runner = _AutoSearchMap()
    runner.appear_results[button_key(map_module.AUTO_SEARCH_OS_MAP_OPTION_OFF)] = [True]
    runner.combat_appear_results = [True]
    runner.auto_search_combat_results = [True]

    result = runner.os_auto_search_daemon()

    assert result == 1
    assert ("on_auto_search_battle_count_add",) in runner.calls


def test_os_auto_search_daemon_raises_when_auto_search_never_unlocks() -> None:
    runner = _AutoSearchMap()
    _Timer.reached_results = {0: [True]}

    with pytest.raises(RequestHumanTakeover):
        runner.os_auto_search_daemon()


def test_os_auto_search_daemon_disables_search_after_fleet_needs_repair() -> None:
    runner = _AutoSearchMap()
    runner.appear_results[button_key(map_module.AUTO_SEARCH_OS_MAP_OPTION_OFF)] = [True]
    runner.combat_appear_results = [True]
    runner.auto_search_combat_results = [False]
    runner.need_repair = [True]
    _Timer.reached_results = {1: [False, True]}

    result = runner.os_auto_search_daemon()

    assert result == 0
    assert ("handle_os_auto_search_map_option", True) in runner.calls
    assert ("handle_os_auto_search_map_option", False) in runner.calls


def test_os_auto_search_daemon_interrupts_when_strategic_task_switched() -> None:
    runner = _AutoSearchMap()
    runner.appear_results[button_key(map_module.AUTO_SEARCH_OS_MAP_OPTION_OFF)] = [True]
    runner.combat_appear_results = [True]
    runner.auto_search_combat_results = [True]
    runner.config.task_switched_results = [True]

    result = runner.os_auto_search_daemon(strategic=True)

    assert result == 1
    assert runner.calls.index(("interrupt_auto_search",)) < runner.calls.index(("auto_search_combat",))


def test_os_auto_search_daemon_marks_ash_popup_after_retirement_interrupt() -> None:
    runner = _AutoSearchMap()
    runner.loop_count = 1
    runner.appear_results[button_key(map_module.AUTO_SEARCH_OS_MAP_OPTION_OFF)] = [True]
    runner.retirement_results = [True]

    result = runner.os_auto_search_daemon()

    assert result == 0
    assert runner.ash_popup_canceled is True
    assert ("combat_appear",) not in runner.calls
