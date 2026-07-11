from dataclasses import dataclass
from datetime import datetime

import pytest

from module.config.config import TaskEnd
from module.os.tasks import meowfficer_farming
from module.os.tasks.meowfficer_farming import OpsiMeowfficerFarming


class _Task:
    command = "OpsiMeowfficerFarming"


class _Config:
    def __init__(self) -> None:
        self.OpsiMeowfficerFarming_HazardLevel = 3
        self.OpsiMeowfficerFarming_ActionPointPreserve = 200
        self.OpsiMeowfficerFarming_TargetZone = 0
        self.OpsiFleet_Submarine = True
        self.OpsiFleet_Fleet = "fleet_1"
        self.OpsiGeneral_BuyActionPointLimit = 0
        self.OpsiAshBeacon_EnsureFullyCollected = True
        self.OS_CL1_YELLOW_COINS_PRESERVE = 100
        self.OS_ACTION_POINT_PRESERVE = None
        self.task = _Task()
        self.overrides: list[dict[str, object]] = []
        self.delays: list[dict[str, object]] = []
        self.calls: list[tuple[object, ...]] = []
        self.ash_enabled = False

    def override(self, **kwargs: object) -> None:
        self.overrides.append(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def task_delay(self, **kwargs: object) -> None:
        self.delays.append(kwargs)

    def task_stop(self) -> None:
        self.calls.append(("task_stop",))
        raise TaskEnd

    def is_task_enabled(self, task: str) -> bool:
        self.calls.append(("is_task_enabled", task))
        return self.ash_enabled

    def check_task_switch(self, message: str = "") -> None:
        self.calls.append(("check_task_switch", message))
        raise TaskEnd


@dataclass
class _Cooldown:
    next_run: datetime


@dataclass
class _Zone:
    zone_id: int
    location: tuple[int, int]


class _Zones:
    def select(self, **_kwargs: object) -> list[_Zone]:
        return []


class _ZoneSet:
    def __init__(self, zones: list[_Zone]) -> None:
        self.zones = zones

    def delete(self, _zones: object) -> _ZoneSet:
        return self

    def sort_by_clock_degree(self, **_kwargs: object) -> _ZoneSet:
        return self

    def __getitem__(self, index: int) -> _Zone:
        return self.zones[index]


class _MeowfficerFarming(OpsiMeowfficerFarming):
    config: _Config
    zone: _Zone

    def __init__(self) -> None:
        self.config = _Config()
        self.calls: list[tuple[object, ...]] = []
        self.cl1_enabled = False
        self.ash_fully_collected = True
        self.cooling_down = None
        self.action_point_limit = 500
        self.yellow_coins = 0
        self.in_opsi_explore = False
        self.zone = _Zone(zone_id=1, location=(1, 1))
        self.zones = _Zones()

    @property
    def is_cl1_enabled(self) -> bool:
        return self.cl1_enabled

    @property
    def _ash_fully_collected(self) -> bool:
        return self.ash_fully_collected

    @property
    def nearest_task_cooling_down(self) -> _Cooldown | None:
        return self.cooling_down

    def get_action_point_limit(self) -> int:
        self.calls.append(("get_action_point_limit",))
        return self.action_point_limit

    def get_yellow_coins(self) -> int:
        self.calls.append(("get_yellow_coins",))
        return self.yellow_coins

    def is_in_opsi_explore(self) -> bool:
        self.calls.append(("is_in_opsi_explore",))
        return self.in_opsi_explore

    def action_point_set(self, *_args: object, **kwargs: object) -> None:
        self.calls.append(("action_point_set", kwargs))

    def name_to_zone(self, name: int, *_args: object, **_kwargs: object) -> _Zone:
        self.calls.append(("name_to_zone", name))
        return _Zone(zone_id=name, location=(9, 9))

    def zone_select(self, hazard_level: int) -> _ZoneSet:
        self.calls.append(("zone_select", hazard_level))
        return _ZoneSet([_Zone(zone_id=44, location=(4, 4))])

    def globe_goto(self, zone: _Zone, *_args: object, **kwargs: object) -> None:
        self.calls.append(("globe_goto", zone.zone_id, kwargs))

    def fleet_set(self, index=None, skip_first_screenshot=True) -> None:
        _ = skip_first_screenshot
        self.calls.append(("fleet_set", index))

    def os_order_execute(self, *_args: object, **kwargs: object) -> None:
        self.calls.append(("os_order_execute", kwargs))

    def run_auto_search(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("run_auto_search",))

    def handle_after_auto_search(self) -> None:
        self.calls.append(("handle_after_auto_search",))


def test_os_meowfficer_farming_runs_configured_target_zone() -> None:
    runner = _MeowfficerFarming()
    runner.config.OpsiMeowfficerFarming_TargetZone = 135

    with pytest.raises(TaskEnd):
        runner.os_meowfficer_farming()

    assert runner.config.OS_ACTION_POINT_PRESERVE == 200
    assert runner.calls == [
        ("get_action_point_limit",),
        ("is_in_opsi_explore",),
        ("action_point_set", {"cost": 0, "keep_current_ap": True, "check_rest_ap": True}),
        ("name_to_zone", 135),
        ("globe_goto", 135, {"refresh": True}),
        ("fleet_set", "fleet_1"),
        ("os_order_execute", {"recon_scan": False, "submarine_call": True}),
        ("run_auto_search",),
        ("handle_after_auto_search",),
    ]
    assert runner.config.calls == [
        ("is_task_enabled", "OpsiAshBeacon"),
        ("check_task_switch", ""),
    ]


def test_os_meowfficer_farming_uses_auto_selected_zone() -> None:
    runner = _MeowfficerFarming()
    runner.config.ash_enabled = True
    runner.ash_fully_collected = False

    with pytest.raises(TaskEnd):
        runner.os_meowfficer_farming()

    assert runner.config.OS_ACTION_POINT_PRESERVE == 0
    assert ("zone_select", 3) in runner.calls
    assert ("globe_goto", 44, {}) in runner.calls


def test_os_meowfficer_farming_delays_when_opsi_explore_is_running() -> None:
    runner = _MeowfficerFarming()
    runner.in_opsi_explore = True

    with pytest.raises(TaskEnd):
        runner.os_meowfficer_farming()

    assert runner.config.delays == [{"server_update": True}]
    assert runner.config.calls == [("task_stop",)]
    assert ("action_point_set", {"cost": 0, "keep_current_ap": True, "check_rest_ap": True}) not in runner.calls


def test_os_meowfficer_farming_delays_after_cl1_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    cooldown = _Cooldown(next_run=datetime(2026, 1, 1, 1, 0, 0))
    runner = _MeowfficerFarming()
    runner.cl1_enabled = True
    runner.action_point_limit = 2000
    runner.cooling_down = cooldown
    monkeypatch.setattr(meowfficer_farming, "get_os_reset_remain", lambda: 1)

    with pytest.raises(TaskEnd):
        runner.os_meowfficer_farming()

    assert runner.config.OpsiMeowfficerFarming_ActionPointPreserve == 1000
    assert runner.config.delays == [{"target": cooldown.next_run}]
    assert runner.config.overrides == [
        {
            "OpsiGeneral_DoRandomMapEvent": True,
            "OpsiGeneral_AkashiShopFilter": "ActionPoint",
            "OpsiFleet_Submarine": False,
        }
    ]
