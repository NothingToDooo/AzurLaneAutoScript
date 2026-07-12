from typing import TYPE_CHECKING, ClassVar, override

import numpy as np

from module.base.timer import Timer
from module.os import fleet as fleet_module
from module.os.fleet import OSFleet

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest

    from module.base.button import Button, MatchOffset
    from module.base.type_alias import ImageArray

UNEXPECTED_GLOBE_RECOVERY_MESSAGE = "unexpected globe recovery"
UNEXPECTED_STORAGE_RECOVERY_MESSAGE = "unexpected storage recovery"
UNEXPECTED_MISSION_RECOVERY_MESSAGE = "unexpected mission recovery"
UNEXPECTED_ORDER_RECOVERY_MESSAGE = "unexpected order recovery"


class _Timer(Timer):
    created: ClassVar[list[_Timer]] = []

    def __init__(self, *_args: object, reached_results: list[bool] | None = None, **_kwargs: object) -> None:
        self.reached_results = list(reached_results or [])
        self.reset_count = 0
        self.has_started = False
        _Timer.created.append(self)

    def start(self) -> _Timer:
        self.has_started = True
        return self

    def reset(self) -> _Timer:
        self.reset_count += 1
        return self

    def reached(self) -> bool:
        if self.reached_results:
            return self.reached_results.pop(0)
        return False


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((2, 2, 3), dtype=np.uint8)
        self.interval_values: list[float | None] = []
        self.sleep_values: list[float] = []
        self.click_record_clear_count = 0

    def screenshot_interval_set(self, interval: float | None = None) -> None:
        self.interval_values.append(interval)

    def click_record_clear(self) -> None:
        self.click_record_clear_count += 1

    def sleep(self, seconds: float) -> None:
        self.sleep_values.append(seconds)


class _Backend:
    def __init__(self, owner: _WalkStableFleet) -> None:
        self.owner = owner

    @property
    def homo_loca(self) -> tuple[int, int] | None:
        if self.owner.homo_loca_results:
            return self.owner.homo_loca_results.pop(0)
        return (0, 0)


class _View:
    def __init__(self, owner: _WalkStableFleet) -> None:
        self.backend = _Backend(owner)


class _WalkStableFleet(OSFleet):
    device: _Device
    view: _View

    def __init__(self) -> None:
        self.device = _Device()
        self.view = _View(self)
        self.loop_count = 5
        self.loop_skip_first_values: list[bool] = []
        self.map_event_results: list[str] = []
        self.in_map_results: list[bool] = []
        self.match_template_color_results: list[bool] = []
        self.enemy_searching_results: list[bool] = []
        self.homo_loca_results: list[tuple[int, int] | None] = []
        self.enemy_flashing_count = 0
        self.enemy_searching_color_initial_count = 0
        self.update_os_count = 0
        self.match_template_color_count = 0
        self.fleet_reset_view_count = 0

    @staticmethod
    def _next_result[T](results: list[T], default: T) -> T:
        if results:
            return results.pop(0)
        return default

    @override
    def loop(
        self,
        *,
        skip_first: bool = True,
        timeout: float | Timer | None = None,
    ) -> Iterator[ImageArray]:
        del timeout
        self.loop_skip_first_values.append(skip_first)
        return iter([self.device.image] * self.loop_count)

    def handle_map_event(self) -> str:
        return self._next_result(self.map_event_results, "")

    @override
    def handle_retirement(self) -> bool:
        return False

    @override
    def handle_walk_out_of_step(self) -> bool:
        return False

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del name, offset, interval
        return False

    @override
    def is_in_globe(self) -> bool:
        return False

    @override
    def os_globe_goto_map(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError(UNEXPECTED_GLOBE_RECOVERY_MESSAGE)

    @override
    def is_in_storage(self) -> bool:
        return False

    @override
    def storage_quit(self) -> None:
        raise AssertionError(UNEXPECTED_STORAGE_RECOVERY_MESSAGE)

    @override
    def is_in_os_mission(self) -> bool:
        return False

    @override
    def os_mission_quit(self) -> None:
        raise AssertionError(UNEXPECTED_MISSION_RECOVERY_MESSAGE)

    @override
    def handle_os_game_tips(self) -> bool:
        return False

    @override
    def is_in_map_order(self) -> bool:
        return False

    @override
    def order_quit(self) -> None:
        raise AssertionError(UNEXPECTED_ORDER_RECOVERY_MESSAGE)

    @override
    def combat_appear(self) -> bool:
        return False

    @override
    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        del button
        return False

    @override
    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        del button
        return False

    def enemy_searching_appear(self) -> bool:
        return self._next_result(self.enemy_searching_results, default=False)

    def handle_enemy_flashing(self) -> None:
        self.enemy_flashing_count += 1

    def is_in_map(self) -> bool:
        return self._next_result(self.in_map_results, default=True)

    def enemy_searching_color_initial(self) -> None:
        self.enemy_searching_color_initial_count += 1

    def match_template_color(self, button: object, *_args: object, **_kwargs: object) -> bool:
        _ = button
        self.match_template_color_count += 1
        return self._next_result(self.match_template_color_results, default=True)

    def update_os(self) -> None:
        self.update_os_count += 1

    def fleet_reset_view(self) -> bool:
        self.fleet_reset_view_count += 1
        return True


def test_wait_until_walk_stable_clears_story_click_record(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.created = []
    monkeypatch.setattr(fleet_module, "Timer", _Timer)
    fleet = _WalkStableFleet()
    fleet.map_event_results = ["story_skip", "map_get_items", ""]
    confirm_timer = _Timer(reached_results=[True])

    result = fleet.wait_until_walk_stable(confirm_timer=confirm_timer)

    assert result == "event"
    assert fleet.device.click_record_clear_count == 1
    assert fleet.match_template_color_count == 1
    assert fleet.device.interval_values == [0.35, None]


def test_wait_until_walk_stable_confirms_arrival_after_enemy_searching(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.created = []
    monkeypatch.setattr(fleet_module, "Timer", _Timer)
    fleet = _WalkStableFleet()
    fleet.enemy_searching_results = [True]
    confirm_timer = _Timer(reached_results=[True])

    result = fleet.wait_until_walk_stable(confirm_timer=confirm_timer)

    assert result == "search"
    assert fleet.enemy_flashing_count == 1
    assert fleet.device.sleep_values == [0.3]
    assert fleet.match_template_color_count == 1
    assert fleet.update_os_count == 1


def test_wait_until_walk_stable_returns_empty_result_for_plain_arrival(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.created = []
    monkeypatch.setattr(fleet_module, "Timer", _Timer)
    fleet = _WalkStableFleet()
    confirm_timer = _Timer(reached_results=[True])

    result = fleet.wait_until_walk_stable(confirm_timer=confirm_timer, skip_first_screenshot=True)

    assert result == ""
    assert fleet.loop_skip_first_values == [True]
    assert fleet.enemy_searching_color_initial_count == 1
    assert fleet.device.interval_values == [0.35, None]
