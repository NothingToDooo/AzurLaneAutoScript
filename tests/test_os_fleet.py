from typing import TYPE_CHECKING, ClassVar, Literal, TypeVar, override

import numpy as np
import pytest

from module.base.button import Button
from module.map.map_grids import SelectedGrids
from module.os import fleet as fleet_module
from module.os.fleet import BossFleet, OSFleet
from module.os.radar import Radar, RadarGrid
from module.os_combat import assets as os_combat_assets
from module.ui.assets import BACK_ARROW

_T = TypeVar("_T")

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.timer import Timer
    from module.base.type_alias import ImageArray


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


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((2, 2, 3), dtype=np.uint8)
        self.clicks: list[Button] = []

    def click(self, button: Button) -> None:
        self.clicks.append(button)


class _RadarGrid(RadarGrid):
    def __init__(self) -> None:
        pass


class _Radar(Radar):
    def __init__(self, owner: _Fleet) -> None:
        self.owner = owner

    @override
    def select(self, **kwargs: object) -> SelectedGrids[RadarGrid]:
        self.owner.calls.append(("radar_select", kwargs))
        if kwargs.get("is_enemy"):
            matched = self.owner.radar_enemy_results.pop(0) if self.owner.radar_enemy_results else False
        elif kwargs.get("is_question"):
            matched = self.owner.radar_question_results.pop(0) if self.owner.radar_question_results else False
        else:
            matched = False
        return SelectedGrids([_RadarGrid()] if matched else [])


class _Fleet(OSFleet):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self._radar = _Radar(self)
        self.calls: list[tuple[object, ...]] = []
        self.loop_count = 5
        self.in_map_results: list[bool] = []
        self.radar_enemy_results: list[bool] = []
        self.radar_question_results: list[bool] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.combat_executing_results: list[Button | Literal[False]] = []
        self.combat_quit_results: list[bool] = []
        self.combat_quit_reconfirm_results: list[bool] = []
        self.leave_button_results: list[Button | None] = []
        self.interval_resets: list[object] = []
        self.fleet_filter_results: list[BossFleet | str] = []
        self.fleet_set_results: list[bool] = []
        self.low_resolve_results: list[bool] = []
        self.boss_goto_calls: list[dict[str, object]] = []
        self.map_exit_count = 0
        self.boss_leave_count = 0

    def leave_boss(self) -> None:
        OSFleet.boss_leave(self)

    def clear_boss(self, *, has_fleet_step: bool = True, is_month: bool = False) -> bool:
        return self.boss_clear(has_fleet_step=has_fleet_step, is_month=is_month)

    @property
    @override
    def radar(self) -> _Radar:
        return self._radar

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
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
        del skip_first, timeout
        return iter([self.device.image] * self.loop_count)

    def update_os(self) -> None:
        self.calls.append(("update_os",))

    def predict(self) -> None:
        self.calls.append(("predict",))

    def predict_radar(self) -> None:
        self.calls.append(("predict_radar",))

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self._next_result(self.in_map_results, default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    @override
    def is_combat_executing(self) -> Button | Literal[False]:
        self.calls.append(("is_combat_executing",))
        return self._next_result(self.combat_executing_results, default=False)

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button))
        self.interval_resets.append(button)

    def handle_combat_quit(self, *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_combat_quit",))
        return self._next_result(self.combat_quit_results, default=False)

    def handle_combat_quit_reconfirm(self, *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_combat_quit_reconfirm",))
        return self._next_result(self.combat_quit_reconfirm_results, default=False)

    @override
    def get_boss_leave_button(self) -> Button | None:
        self.calls.append(("get_boss_leave_button",))
        return self._next_result(self.leave_button_results, default=None)

    @override
    def parse_fleet_filter(self) -> list[BossFleet | str]:
        self.calls.append(("parse_fleet_filter",))
        return self.fleet_filter_results

    def os_order_execute(self, *_args: object, **kwargs: object) -> tuple[bool, bool]:
        self.calls.append(("os_order_execute", kwargs))
        return bool(kwargs.get("recon_scan", True)), bool(kwargs.get("submarine_call", True))

    @override
    def fleet_set(self, index: int | None = None, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("fleet_set", index))
        return self._next_result(self.fleet_set_results, default=True)

    @override
    def handle_os_map_fleet_lock(self, *, enable: bool | None = None) -> bool:
        self.calls.append(("handle_os_map_fleet_lock", {"enable": enable}))
        return False

    def fleet_low_resolve_appear(self) -> bool:
        self.calls.append(("fleet_low_resolve_appear",))
        return self._next_result(self.low_resolve_results, default=False)

    def boss_goto(self, *_args: object, **kwargs: object) -> None:
        self.calls.append(("boss_goto", kwargs))
        self.boss_goto_calls.append(kwargs)

    def relative_goto(self, *_args: object, **kwargs: object) -> None:
        self.calls.append(("relative_goto", kwargs))

    def map_exit(self) -> None:
        self.calls.append(("map_exit",))
        self.map_exit_count += 1

    def boss_leave(self) -> None:
        self.calls.append(("boss_leave",))
        self.boss_leave_count += 1


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
    leave_button = Button(area=(), color=(), button=(), name="BOSS_LEAVE_TEST")
    fleet.in_map_results = [True, True, True]
    fleet.radar_enemy_results = [False, True]
    fleet.leave_button_results = [leave_button]
    _Timer.reached_results = {0: [True], 1: [False]}

    fleet.leave_boss()

    assert fleet.device.clicks == [leave_button]
    assert _Timer.reset_count == 1


def test_boss_clear_exits_when_question_mark_returns_after_attack() -> None:
    fleet = _Fleet()
    boss_fleet = BossFleet(1)
    fleet.fleet_filter_results = [boss_fleet]
    fleet.radar_question_results = [True]

    result = fleet.clear_boss(has_fleet_step=True)

    assert result is True
    assert fleet.map_exit_count == 1
    assert fleet.boss_goto_calls == [{"location": (0, 0), "has_fleet_step": True, "is_month": False}]


def test_boss_clear_calls_submarine_order_for_non_fleet_entry() -> None:
    fleet = _Fleet()
    fleet.fleet_filter_results = ["CallSubmarine", BossFleet(1)]
    fleet.radar_question_results = [True]

    result = fleet.clear_boss()

    assert result is True
    assert ("os_order_execute", {"recon_scan": False, "submarine_call": True}) in fleet.calls


def test_boss_clear_skips_low_resolve_fleet_to_standby() -> None:
    fleet = _Fleet()
    boss_fleet = BossFleet(1)
    boss_fleet.standby_loca = (0, -1)
    fleet.fleet_filter_results = [boss_fleet]
    fleet.low_resolve_results = [True]

    result = fleet.clear_boss(has_fleet_step=True)

    assert result is False
    assert fleet.boss_goto_calls == [{"location": (0, -1), "has_fleet_step": True, "is_month": False}]
