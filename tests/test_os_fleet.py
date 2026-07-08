from typing import ClassVar, TypeVar

import pytest

from module.os import fleet as fleet_module
from module.os.fleet import OSFleet
from module.os_combat import assets as os_combat_assets
from module.ui.assets import BACK_ARROW

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

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> _Timer:
        _Timer.reset_count += 1
        return self


class _Button:
    name = "BOSS_LEAVE_TEST"


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []

    def click(self, button: object) -> None:
        self.clicks.append(button)


class _Radar:
    def __init__(self, owner: _Fleet) -> None:
        self.owner = owner

    def select(self, **kwargs: object) -> list[object]:
        self.owner.calls.append(("radar_select", kwargs))
        has_enemy = self.owner.radar_enemy_results.pop(0) if self.owner.radar_enemy_results else False
        return [object()] if has_enemy else []


class _Fleet(OSFleet):
    def __init__(self) -> None:
        self.device = _Device()
        self.radar = _Radar(self)
        self.calls: list[tuple[object, ...]] = []
        self.in_map_results: list[bool] = []
        self.radar_enemy_results: list[bool] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.combat_executing_results: list[object | None] = []
        self.combat_quit_results: list[bool] = []
        self.combat_quit_reconfirm_results: list[bool] = []
        self.leave_button_results: list[object | None] = []
        self.interval_resets: list[object] = []

    def leave_boss(self) -> None:
        self.boss_leave()

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def loop(self) -> range:
        return range(5)

    def update_os(self) -> None:
        self.calls.append(("update_os",))

    def predict(self) -> None:
        self.calls.append(("predict",))

    def predict_radar(self) -> None:
        self.calls.append(("predict_radar",))

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self._next_result(self.in_map_results, default=False)

    def appear(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

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

    def get_boss_leave_button(self) -> object | None:
        self.calls.append(("get_boss_leave_button",))
        return self._next_result(self.leave_button_results, default=None)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(fleet_module, "Timer", _Timer)


def test_boss_leave_finishes_when_boss_is_found_on_radar() -> None:
    fleet = _Fleet()
    fleet.in_map_results = [True]
    fleet.radar_enemy_results = [True]

    fleet.leave_boss()

    assert fleet.device.clicks == []
    assert ("update_os",) in fleet.calls
    assert ("predict",) in fleet.calls
    assert ("predict_radar",) in fleet.calls


def test_boss_leave_backs_out_from_battle_preparation() -> None:
    fleet = _Fleet()
    fleet.in_map_results = [False, True]
    fleet.radar_enemy_results = [True]
    fleet.appear_results[button_key(os_combat_assets.BATTLE_PREPARATION)] = [True]
    _Timer.reached_results = {1: [True]}

    fleet.leave_boss()

    assert fleet.device.clicks == [BACK_ARROW]
    assert _Timer.reset_count == 1


def test_boss_leave_clicks_leave_button_until_boss_returns() -> None:
    fleet = _Fleet()
    leave_button = _Button()
    fleet.in_map_results = [True, True, True]
    fleet.radar_enemy_results = [False, True]
    fleet.leave_button_results = [leave_button]
    _Timer.reached_results = {0: [True], 1: [False]}

    fleet.leave_boss()

    assert fleet.device.clicks == [leave_button]
    assert _Timer.reset_count == 1
