from typing import TYPE_CHECKING, Literal, override

from campaign.campaign_main.campaign_16_4 import I8, J6, Campaign
from module.map.utils import HasLocation
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.base.type_alias import Point
    from module.map.map_grids import RoadGrids
    from module.map.type_alias import GridLocation


type _Call = (
    tuple[str]
    | tuple[str, GridInfo, int | Literal["boss"] | None]
    | tuple[str, str, int]
    | tuple[str, GridLocation | Point | str]
)


class _FleetBoss:
    def __init__(self, calls: list[_Call]) -> None:
        self.calls = calls

    def clear_boss(self) -> bool:
        self.calls.append(("clear_boss",))
        return True


class _Map:
    def __init__(self, boss: GridInfo | None) -> None:
        self.boss = boss

    def select(self, *, is_boss: bool = False) -> list[GridInfo]:
        if is_boss and self.boss is not None:
            return [self.boss]
        return []


class _Campaign(Campaign):
    map: _Map

    def __init__(
        self,
        *,
        boss: GridInfo | None = None,
        boss_accessible: bool = True,
        clear_mode: bool = False,
        support_fleet: bool = False,
    ) -> None:
        self.calls: list[_Call] = []
        self.map = _Map(boss)
        self.boss_fleet = _FleetBoss(self.calls)
        self.map_is_clear_mode = clear_mode
        self.use_support_fleet = support_fleet
        self.boss_accessible = boss_accessible
        self.roadblocks_result = False
        self.potential_roadblocks_result = False
        self.filter_enemy_result = False

    @property
    def fleet_boss(self) -> _FleetBoss:
        return self.boss_fleet

    @override
    def check_accessibility(
        self,
        grid: GridInfo,
        fleet: int | Literal["boss"] | None = None,
    ) -> bool:
        self.calls.append(("check_accessibility", grid, fleet))
        return self.boss_accessible

    @override
    def clear_roadblocks(self, roads: Iterable[RoadGrids[GridInfo]], **kwargs: object) -> bool:
        del kwargs
        del roads
        self.calls.append(("clear_roadblocks",))
        return self.roadblocks_result

    @override
    def clear_potential_roadblocks(self, roads: Iterable[RoadGrids[GridInfo]], **kwargs: object) -> bool:
        del kwargs
        del roads
        self.calls.append(("clear_potential_roadblocks",))
        return self.potential_roadblocks_result

    @override
    def clear_filter_enemy(self, string: str, preserve: int = 0) -> bool:
        self.calls.append(("clear_filter_enemy", string, preserve))
        return self.filter_enemy_result

    @override
    def battle_default(self) -> bool:
        self.calls.append(("battle_default",))
        return False

    @override
    def goto(
        self,
        location: GridInfo | str | GridLocation,
        expected: str = "",
        *,
        step_optimize: bool | None = None,
        turning_optimize: bool | None = None,
    ) -> None:
        del expected, step_optimize, turning_optimize
        resolved = location.location if isinstance(location, GridInfo) else location
        assert resolved is not None
        self.calls.append(("goto", resolved))

    @override
    def air_strike(self, location: HasLocation | str | Point) -> bool:
        resolved = location.location if isinstance(location, HasLocation) else location
        assert resolved is not None
        self.calls.append(("air_strike", resolved))
        return True


def test_battle_4_clear_mode_clears_boss_directly() -> None:
    campaign = _Campaign(clear_mode=True)

    assert campaign.battle_4() is True

    assert campaign.calls == [("clear_boss",)]


def test_battle_4_inaccessible_boss_clears_roadblocks() -> None:
    campaign = _Campaign(boss=I8, boss_accessible=False)
    campaign.roadblocks_result = True

    assert campaign.battle_4() is True

    assert campaign.calls == [
        ("check_accessibility", campaign.map.boss, "boss"),
        ("clear_roadblocks",),
    ]


def test_battle_4_support_fleet_attacks_before_boss() -> None:
    campaign = _Campaign(boss=I8, support_fleet=True)

    assert campaign.battle_4() is True

    assert campaign.calls == [
        ("check_accessibility", campaign.map.boss, "boss"),
        ("goto", J6.location),
        ("air_strike", I8.location),
        ("clear_boss",),
    ]


def test_battle_4_without_boss_uses_path_priority() -> None:
    campaign = _Campaign()
    campaign.potential_roadblocks_result = True

    assert campaign.battle_4() is True

    assert campaign.calls == [
        ("clear_roadblocks",),
        ("clear_potential_roadblocks",),
    ]
