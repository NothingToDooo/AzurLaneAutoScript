from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, override

import pytest

from module.config.config import TaskEnd
from module.os.tasks import cross_month
from module.os.tasks.cross_month import OpsiCrossMonth


class _FixedDateTime:
    values: ClassVar[list[datetime]] = []
    fallback = datetime(2026, 1, 1, 0, 0, 0)

    @classmethod
    def now(cls) -> datetime:
        if cls.values:
            return cls.values.pop(0)
        return cls.fallback


class _Device:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class _Config:
    def __init__(self) -> None:
        self.overrides: list[dict[str, object]] = []
        self.cross_gets: list[str] = []
        self.delays: list[datetime] = []
        self.OpsiFleet_Fleet = 1
        self.cross_values: dict[str, int | str] = {
            "OpsiDaily.OpsiFleet.Fleet": 1,
            "OpsiObscure.OpsiFleet.Fleet": 2,
            "OpsiAbyssal.OpsiFleetFilter.Filter": "fleet-1 > fleet-2",
            "OpsiMeowfficerFarming.OpsiFleet.Fleet": 3,
        }

    def override(self, **kwargs: object) -> None:
        self.overrides.append(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def cross_get(self, keys: str) -> int | str:
        self.cross_gets.append(keys)
        return self.cross_values[keys]

    def task_delay(self, target: datetime) -> None:
        self.delays.append(target)

    @staticmethod
    def task_stop() -> None:
        raise TaskEnd

    @staticmethod
    def task_switched() -> bool:
        return True


@dataclass
class _Zone:
    zone_id: int
    location: tuple[int, int]


class _Zones:
    @staticmethod
    def select(**_kwargs: object) -> list[_Zone]:
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


class _CrossMonthRunner(OpsiCrossMonth):
    config: _Config
    device: _Device
    zone: _Zone

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.zone = _Zone(zone_id=1, location=(1, 1))
        self.zones = _Zones()
        self.daily_accept_results = [True]
        self.daily_finish_results = [1]
        self.storage_results = {
            "ABYSSAL": [True, False],
            "OBSCURE": [True, False],
        }
        self.abyssal_results = [False]
        self.handle_after_count = 0
        self.stop_after_handle_count = 2

    def os_mission_overview_accept(self) -> bool:
        self.calls.append(("os_mission_overview_accept",))
        return self.daily_accept_results.pop(0)

    def zone_init(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("zone_init",))

    def os_finish_daily_mission(self, *_args: object, **_kwargs: object) -> int:
        self.calls.append(("os_finish_daily_mission",))
        return self.daily_finish_results.pop(0)

    @override
    def storage_get_next_item(self, item: str, use_logger: bool = False) -> bool:
        self.calls.append(("storage_get_next_item", item, use_logger))
        return self.storage_results[item].pop(0)

    def run_abyssal(self) -> bool:
        self.calls.append(("run_abyssal",))
        return self.abyssal_results.pop(0)

    def map_exit(self) -> None:
        self.calls.append(("map_exit",))

    @override
    def fleet_repair(self, revert: bool = True) -> None:
        self.calls.append(("fleet_repair", revert))

    def fleet_set(self, index: int | None = None, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("fleet_set", index))
        return True

    @override
    def os_order_execute(self, *, recon_scan: bool = True, submarine_call: bool = True) -> None:
        self.calls.append(("os_order_execute", recon_scan, submarine_call))

    def run_auto_search(
        self,
        *,
        question: bool = True,
        rescan: str | bool | None = None,
        after_auto_search: bool = True,
    ) -> int:
        del question, after_auto_search
        self.calls.append(("run_auto_search", rescan))
        return 0

    def handle_after_auto_search(self) -> None:
        self.calls.append(("handle_after_auto_search",))
        self.handle_after_count += 1
        if self.handle_after_count >= self.stop_after_handle_count:
            raise TaskEnd

    def zone_select(self, hazard_level: int) -> _ZoneSet:
        self.calls.append(("zone_select", hazard_level))
        return _ZoneSet([_Zone(zone_id=44, location=(4, 4))])

    def globe_goto(self, zone: _Zone, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("globe_goto", zone.zone_id))


def _patch_reset_time(monkeypatch: pytest.MonkeyPatch, reset: datetime, now_values: list[datetime]) -> None:
    monkeypatch.setattr(cross_month, "get_os_next_reset", lambda: reset)
    _FixedDateTime.values = list(now_values)
    _FixedDateTime.fallback = now_values[-1]
    monkeypatch.setattr(cross_month, "datetime", _FixedDateTime)


def test_os_cross_month_stops_when_too_far_from_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 0, 0, 0)
    reset = now + timedelta(minutes=11)
    _patch_reset_time(monkeypatch, reset, [now])
    runner = _CrossMonthRunner()

    with pytest.raises(TaskEnd):
        runner.os_cross_month()

    assert runner.config.delays == [reset - timedelta(minutes=10)]
    assert runner.calls == []


def test_os_cross_month_waits_until_reset_in_minute_slices(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 0, 0, 0)
    reset = now + timedelta(seconds=130)
    _patch_reset_time(monkeypatch, reset, [now, now, now + timedelta(seconds=70), reset])
    runner = _CrossMonthRunner()
    runner.storage_results = {"ABYSSAL": [False], "OBSCURE": [False]}
    runner.stop_after_handle_count = 1

    with pytest.raises(TaskEnd):
        runner.os_cross_month()

    assert runner.device.sleeps == [60, 60]


def test_os_cross_month_runs_cleanup_sequence_after_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 0, 0, 0)
    _patch_reset_time(monkeypatch, now, [now, now])
    runner = _CrossMonthRunner()

    with pytest.raises(TaskEnd):
        runner.os_cross_month()

    assert runner.config.cross_gets == [
        "OpsiDaily.OpsiFleet.Fleet",
        "OpsiObscure.OpsiFleet.Fleet",
        "OpsiAbyssal.OpsiFleetFilter.Filter",
        "OpsiMeowfficerFarming.OpsiFleet.Fleet",
    ]
    assert runner.config.overrides == [
        {
            "OpsiGeneral_DoRandomMapEvent": True,
            "OpsiFleet_Fleet": 1,
            "OpsiFleet_Submarine": False,
        },
        {
            "OpsiGeneral_DoRandomMapEvent": False,
            "HOMO_EDGE_DETECT": False,
            "STORY_OPTION": 0,
            "OpsiGeneral_UseLogger": True,
            "OpsiObscure_ForceRun": True,
            "OpsiFleet_Fleet": 2,
            "OpsiFleet_Submarine": False,
            "OpsiFleetFilter_Filter": "fleet-1 > fleet-2",
            "OpsiAbyssal_ForceRun": True,
        },
        {
            "OpsiGeneral_DoRandomMapEvent": True,
            "OpsiGeneral_BuyActionPointLimit": 0,
            "HOMO_EDGE_DETECT": True,
            "STORY_OPTION": -2,
            "OpsiFleet_Fleet": 3,
            "OpsiFleet_Submarine": False,
            "OpsiMeowfficerFarming_ActionPointPreserve": 0,
            "OpsiMeowfficerFarming_HazardLevel": 3,
            "OpsiMeowfficerFarming_TargetZone": 0,
        },
    ]
    assert runner.calls == [
        ("os_mission_overview_accept",),
        ("zone_init",),
        ("os_finish_daily_mission",),
        ("storage_get_next_item", "ABYSSAL", True),
        ("zone_init",),
        ("run_abyssal",),
        ("map_exit",),
        ("fleet_repair", False),
        ("storage_get_next_item", "ABYSSAL", True),
        ("storage_get_next_item", "OBSCURE", True),
        ("zone_init",),
        ("fleet_set", 2),
        ("os_order_execute", True, False),
        ("run_auto_search", "current"),
        ("map_exit",),
        ("handle_after_auto_search",),
        ("storage_get_next_item", "OBSCURE", True),
        ("zone_select", 3),
        ("globe_goto", 44),
        ("fleet_set", 3),
        ("os_order_execute", False, False),
        ("run_auto_search", None),
        ("handle_after_auto_search",),
    ]


def test_os_cross_month_retries_empty_daily_before_success(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 1, 1, 0, 0, 0)
    _patch_reset_time(monkeypatch, now, [now, now])
    runner = _CrossMonthRunner()
    runner.daily_accept_results = [False, True]
    runner.daily_finish_results = [0, 1]
    runner.storage_results = {"ABYSSAL": [False], "OBSCURE": [False]}
    runner.stop_after_handle_count = 1

    with pytest.raises(TaskEnd):
        runner.os_cross_month()

    assert runner.device.sleeps == [60]
    assert runner.calls[:6] == [
        ("os_mission_overview_accept",),
        ("zone_init",),
        ("os_finish_daily_mission",),
        ("os_mission_overview_accept",),
        ("zone_init",),
        ("os_finish_daily_mission",),
    ]
