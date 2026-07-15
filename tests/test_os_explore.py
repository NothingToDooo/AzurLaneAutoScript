from typing import TYPE_CHECKING, override

from module.exception import ScriptError
from module.os.globe_zone import Zone
from module.os.map_data import DIC_OS_MAP
from module.os.tasks.explore import OpsiExplore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.os.globe_operation import ZoneType
    from module.os.globe_zone import ZoneName
    from module.os.map import RescanMode


class _Config:
    def __init__(self) -> None:
        self.OS_EXPLORE_FILTER = "1 > 2"
        self.OpsiExplore_LastZone: int | str = 0
        self.OpsiExplore_SpecialRadar = True
        self.OpsiFleet_Fleet = 1
        self.OpsiFleet_Submarine = False


class _Explore(OpsiExplore):
    config: _Config

    def __init__(self, *, globe_results: dict[int, bool], combat_results: list[int]) -> None:
        self.config = _Config()
        self.globe_results = globe_results
        self.combat_results = combat_results
        self.calls = []
        self._os_explore_failed_zone = []

    @property
    def failed_zones(self) -> list[int]:
        return self._os_explore_failed_zone

    def explore_order(self) -> list[int]:
        return self._os_explore_order()

    def skip_cleared_zone(self, zone: int) -> bool:
        return self._skip_cleared_os_explore_zone(zone)

    def run_zone(self, zone: int) -> None:
        self._run_os_explore_zone(zone)

    @override
    def name_to_zone(self, name: ZoneName) -> Zone:
        if name == "bad":
            message = "bad zone"
            raise ScriptError(message)
        zone_id = name.zone_id if isinstance(name, Zone) else int(name)
        return Zone(zone_id, DIC_OS_MAP[zone_id])

    @override
    def globe_goto(
        self,
        zone: ZoneName,
        types: ZoneType | Sequence[ZoneType] = ("SAFE", "DANGEROUS"),
        *,
        refresh: bool = False,
        stop_if_safe: bool = False,
    ) -> bool:
        del types, refresh
        zone_id = zone.zone_id if isinstance(zone, Zone) else int(zone)
        self.calls.append(("globe_goto", zone, stop_if_safe))
        return self.globe_results[zone_id]

    @override
    def tuning_sample_use(self) -> None:
        self.calls.append(("tuning_sample_use", None))

    @override
    def fleet_set(self, index: int | None = None, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("fleet_set", index))
        return True

    @override
    def os_order_execute(self, *, recon_scan: bool = True, submarine_call: bool = True) -> tuple[bool, bool]:
        self.calls.append(("os_order_execute", {"recon_scan": recon_scan, "submarine_call": submarine_call}))
        return recon_scan, submarine_call

    @override
    def run_auto_search(
        self,
        *,
        question: bool = True,
        rescan: RescanMode | bool | None = None,
        after_auto_search: bool = True,
    ) -> int:
        del question, rescan, after_auto_search
        self.calls.append(("run_auto_search", None))
        return self.combat_results.pop(0)

    @override
    def handle_after_auto_search(self) -> bool:
        self.calls.append(("handle_after_auto_search", None))
        return False


def test_os_explore_order_resumes_after_last_zone() -> None:
    explore = _Explore(globe_results={}, combat_results=[])
    explore.config.OpsiExplore_LastZone = 1

    assert explore.explore_order() == [2]


def test_os_explore_invalid_last_zone_restarts_from_beginning() -> None:
    explore = _Explore(globe_results={}, combat_results=[])
    explore.config.OpsiExplore_LastZone = "bad"

    assert explore.explore_order() == [1, 2]


def test_os_explore_skips_safe_zone_and_runs_one_dangerous_zone() -> None:
    explore = _Explore(globe_results={1: False, 2: True}, combat_results=[0])

    assert explore.skip_cleared_zone(1)
    assert not explore.skip_cleared_zone(2)
    explore.run_zone(2)

    assert ("globe_goto", 1, True) in explore.calls
    assert ("globe_goto", 2, True) in explore.calls
    assert ("os_order_execute", {"recon_scan": False, "submarine_call": False}) in explore.calls
    assert explore.failed_zones == [2]
    assert explore.config.OpsiExplore_LastZone == 2
