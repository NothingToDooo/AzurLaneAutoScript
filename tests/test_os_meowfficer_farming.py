from typing import TYPE_CHECKING, override

from module.map.map_grids import SelectedGrids
from module.os.globe_zone import Zone
from module.os.tasks.meowfficer_farming import OpsiMeowfficerFarming

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.os.globe_operation import ZoneType
    from module.os.globe_zone import ZoneName
    from module.os.map import RescanMode
    from module.os_handler.action_point import ActionPointZone, ActionPointZoneType


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
        self.calls: list[tuple[object, ...]] = []
        self.ash_enabled = False

    def is_task_enabled(self, task: str) -> bool:
        self.calls.append(("is_task_enabled", task))
        return self.ash_enabled


def _zone(zone_id: int) -> Zone:
    return Zone(
        zone_id,
        {
            "shape": "A1",
            "hazard_level": 3,
            "cn": f"zone-{zone_id}",
            "area_pos": (0, 0),
            "offset_pos": (0, 0),
            "region": 1,
        },
    )


class _MeowfficerFarming(OpsiMeowfficerFarming):
    config: _Config
    zone: Zone

    def __init__(self) -> None:
        self.config = _Config()
        self.calls: list[tuple[object, ...]] = []
        self.cl1_enabled = False
        self.ash_fully_collected = True
        self.action_point_limit = 500
        self.yellow_coins = 0
        self.in_opsi_explore = False
        self.zone = _zone(1)
        self._zones = SelectedGrids[Zone]([])

    @property
    @override
    def zones(self) -> SelectedGrids[Zone]:
        return self._zones

    @property
    def is_cl1_enabled(self) -> bool:
        return self.cl1_enabled

    @property
    def _ash_fully_collected(self) -> bool:
        return self.ash_fully_collected

    def get_action_point_limit(self) -> int:
        self.calls.append(("get_action_point_limit",))
        return self.action_point_limit

    def get_yellow_coins(self) -> int:
        self.calls.append(("get_yellow_coins",))
        return self.yellow_coins

    def is_in_opsi_explore(self) -> bool:
        self.calls.append(("is_in_opsi_explore",))
        return self.in_opsi_explore

    @override
    def action_point_set(
        self,
        zone: ActionPointZone | str | None = None,
        pinned: ActionPointZoneType | None = None,
        cost: int | None = None,
        *,
        keep_current_ap: bool = True,
        check_rest_ap: bool = False,
    ) -> bool:
        del zone, pinned
        self.calls.append(
            (
                "action_point_set",
                {"cost": cost, "keep_current_ap": keep_current_ap, "check_rest_ap": check_rest_ap},
            )
        )
        return True

    @override
    def name_to_zone(self, name: ZoneName) -> Zone:
        assert isinstance(name, int)
        self.calls.append(("name_to_zone", name))
        return _zone(name)

    @override
    def zone_select(self, hazard_level: int) -> SelectedGrids[Zone]:
        self.calls.append(("zone_select", hazard_level))
        return SelectedGrids([_zone(44)])

    @override
    def globe_goto(
        self,
        zone: ZoneName,
        types: ZoneType | Sequence[ZoneType] = ("SAFE", "DANGEROUS"),
        *,
        refresh: bool = False,
        stop_if_safe: bool = False,
    ) -> bool:
        del types, stop_if_safe
        assert isinstance(zone, Zone)
        kwargs = {"refresh": True} if refresh else {}
        self.calls.append(("globe_goto", zone.zone_id, kwargs))
        return True

    def fleet_set(self, index: int | None = None, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("fleet_set", index))
        return True

    def os_order_execute(self, *_args: object, **kwargs: object) -> tuple[bool, bool]:
        self.calls.append(("os_order_execute", kwargs))
        return bool(kwargs.get("recon_scan", True)), bool(kwargs.get("submarine_call", True))

    @override
    def run_auto_search(
        self,
        *,
        question: bool = True,
        rescan: RescanMode | bool | None = None,
        after_auto_search: bool = True,
    ) -> int:
        del question, rescan, after_auto_search
        self.calls.append(("run_auto_search",))
        return 0

    @override
    def handle_after_auto_search(self) -> bool:
        self.calls.append(("handle_after_auto_search",))
        return False

    def run_one_zone(self, *, preserve: int = 200) -> None:
        self._apply_meowfficer_action_point_preserve(preserve)
        self._check_meowfficer_action_points()
        zone, refresh = self._next_meowfficer_farming_zone()
        self._run_meowfficer_farming_zone(zone, refresh=refresh)


def test_os_meowfficer_farming_runs_configured_target_zone() -> None:
    runner = _MeowfficerFarming()
    runner.config.OpsiMeowfficerFarming_TargetZone = 135

    runner.run_one_zone()

    assert runner.config.OS_ACTION_POINT_PRESERVE == 200
    assert runner.calls == [
        ("action_point_set", {"cost": 0, "keep_current_ap": True, "check_rest_ap": True}),
        ("name_to_zone", 135),
        ("globe_goto", 135, {"refresh": True}),
        ("fleet_set", "fleet_1"),
        ("os_order_execute", {"recon_scan": False, "submarine_call": True}),
        ("run_auto_search",),
        ("handle_after_auto_search",),
    ]
    assert runner.config.calls == [("is_task_enabled", "OpsiAshBeacon")]


def test_os_meowfficer_farming_uses_auto_selected_zone() -> None:
    runner = _MeowfficerFarming()
    runner.config.ash_enabled = True
    runner.ash_fully_collected = False

    runner.run_one_zone()

    assert runner.config.OS_ACTION_POINT_PRESERVE == 0
    assert ("zone_select", 3) in runner.calls
    assert ("globe_goto", 44, {}) in runner.calls
