from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, override

import pytest

from module.map.map_grids import SelectedGrids
from module.os.globe_zone import Zone
from module.os.tasks import cross_month
from module.os.tasks.cross_month import OpsiCrossMonth
from module.os_handler.action_point import ActionPointLimit

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.os.globe_operation import ZoneType
    from module.os.globe_zone import ZoneName
    from module.os.map import RescanMode


class _FixedDateTime:
    values: ClassVar[list[datetime]] = []

    @classmethod
    def now(cls) -> datetime:
        return cls.values.pop(0)


class _Device:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class _Config:
    def __init__(self) -> None:
        self.OpsiFleet_Fleet = 0
        self.overrides: list[dict[str, object]] = []

    def override(self, **kwargs: object) -> None:
        self.overrides.append(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)


def _zone(zone_id: int) -> Zone:
    return Zone(
        zone_id,
        {
            "shape": "A1",
            "hazard_level": 3,
            "cn": f"zone-{zone_id}",
            "area_pos": (zone_id * 10, zone_id * 10),
            "offset_pos": (0, 0),
            "region": 1,
        },
    )


class _CrossMonthRunner(OpsiCrossMonth):
    config: _Config
    device: _Device
    zone: Zone

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.zone = _zone(1)
        self._zones = SelectedGrids([self.zone, _zone(22)])
        self.storage_results: dict[str, list[bool]] = {"ABYSSAL": [], "OBSCURE": []}
        self.calls: list[tuple[object, ...]] = []
        self.stop_on_search = False

    @property
    @override
    def zones(self) -> SelectedGrids[Zone]:
        return self._zones

    def storage_get_next_item(self, item: str, *, use_logger: bool = True) -> bool:
        self.calls.append(("storage_get_next_item", item, use_logger))
        results = self.storage_results[item]
        return results.pop(0) if results else False

    def zone_init(self, *, fallback_init: bool = True) -> Zone | None:
        self.calls.append(("zone_init", fallback_init))
        return self.zone

    def run_abyssal(self) -> bool:
        self.calls.append(("run_abyssal",))
        return True

    def fleet_repair(self, *, revert: bool = True) -> None:
        self.calls.append(("fleet_repair", revert))

    def fleet_set(self, index: int | None = None, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("fleet_set", index))
        return True

    def os_order_execute(self, *, recon_scan: bool = True, submarine_call: bool = True) -> tuple[bool, bool]:
        self.calls.append(("os_order_execute", recon_scan, submarine_call))
        return recon_scan, submarine_call

    @override
    def run_auto_search(
        self,
        *,
        question: bool = True,
        rescan: RescanMode | bool | None = None,
        after_auto_search: bool = True,
    ) -> int:
        del question, after_auto_search
        self.calls.append(("run_auto_search", rescan))
        if self.stop_on_search:
            raise ActionPointLimit
        return 0

    def map_exit(self) -> None:
        self.calls.append(("map_exit",))

    @override
    def handle_after_auto_search(self) -> bool:
        self.calls.append(("handle_after_auto_search",))
        return False

    @override
    def zone_select(self, hazard_level: int) -> SelectedGrids[Zone]:
        self.calls.append(("zone_select", hazard_level))
        return SelectedGrids([_zone(22)])

    @override
    def globe_goto(
        self,
        zone: ZoneName,
        types: ZoneType | Sequence[ZoneType] = ("SAFE", "DANGEROUS"),
        *,
        refresh: bool = False,
        stop_if_safe: bool = False,
    ) -> bool:
        del types, refresh, stop_if_safe
        assert isinstance(zone, Zone)
        self.calls.append(("globe_goto", zone.zone_id))
        self.zone = zone
        return True


def test_cross_month_waits_in_bounded_slices(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _CrossMonthRunner()
    reset = datetime(2026, 8, 1, 0, 0)
    _FixedDateTime.values = [
        datetime(2026, 7, 31, 23, 58, 30),
        datetime(2026, 7, 31, 23, 59, 30),
        reset,
    ]
    monkeypatch.setattr(cross_month, "datetime", _FixedDateTime)

    runner._wait_until_opsi_reset(reset)  # ruff:ignore[private-member-access] - 验证跨月等待边界。

    assert runner.device.sleeps == [60, 30]


def test_cross_month_monthly_cleanup_uses_explicit_typed_settings() -> None:
    runner = _CrossMonthRunner()
    runner.storage_results = {"ABYSSAL": [True, False], "OBSCURE": [True, False]}

    runner._clear_opsi_monthly_items(  # ruff:ignore[private-member-access] - 验证跨月清理边界。
        obscure_fleet=2,
        abyssal_fleet_filter="fleet-1 > fleet-2",
    )

    assert runner.config.overrides[0]["OpsiFleet_Fleet"] == 2
    assert runner.config.overrides[0]["OpsiFleetFilter_Filter"] == "fleet-1 > fleet-2"
    assert ("run_abyssal",) in runner.calls
    assert ("run_auto_search", "current") in runner.calls


def test_cross_month_farming_uses_explicit_fleet_until_action_point_limit() -> None:
    runner = _CrossMonthRunner()
    runner.stop_on_search = True

    with pytest.raises(ActionPointLimit):
        runner._run_opsi_meowfficer_farming_after_reset(fleet_index=3)  # ruff:ignore[private-member-access]

    assert runner.config.overrides[0]["OpsiFleet_Fleet"] == 3
    assert ("fleet_set", 3) in runner.calls
