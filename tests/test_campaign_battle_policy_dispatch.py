from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from module.base import decorator
from module.campaign.campaign_base import CampaignBase

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.map.map_base import CampaignMap


class _Selection:
    def __init__(self, events: list[object], *, count: int = 0) -> None:
        self.events = events
        self.count = count

    def __bool__(self) -> bool:
        return False

    def add(self, _other: object) -> _Selection:
        self.events.append("add")
        return self

    def delete(self, _other: object) -> _Selection:
        self.events.append("delete")
        return self


class _Map:
    def __init__(self, events: list[object], *, remaining: int = 0) -> None:
        self.events = events
        self.remaining = remaining

    def select(self, **criteria: bool) -> _Selection:
        field = next(iter(criteria))
        self.events.append(("select", field))
        count = self.remaining if field == "is_enemy" else 0
        return _Selection(self.events, count=count)


class _BattleHarness(CampaignBase):
    def __init__(self, *, clear_all: bool, poor_map_data: bool, battle_count: int = 0) -> None:
        self.config = cast(
            "AzurLaneConfig",
            SimpleNamespace(
                MAP_CLEAR_ALL_THIS_TIME=clear_all,
                POOR_MAP_DATA=poor_map_data,
                MAP_HAS_MOVABLE_NORMAL_ENEMY=False,
            ),
        )
        self.battle_count = battle_count
        self.events: list[object] = []
        self.map = cast("CampaignMap", _Map(self.events))

    def fleet_2_break_siren_caught(self) -> bool:
        self.events.append("break_siren_caught")
        return False

    def clear_all_mystery(self, **_kwargs: object) -> None:
        self.events.append("clear_all_mystery")

    def pick_up_ammo(self, grid: object = None) -> None:
        del grid
        self.events.append("pick_up_ammo")

    def clear_siren(self, **_kwargs: object) -> bool:
        self.events.append("clear_siren")
        return True

    def battle_boss(self) -> str:
        self.events.append("battle_boss")
        return "clear_all"

    def battle_default(self) -> str:
        self.events.append("battle_default")
        return "default"

    def battle_0(self) -> str:
        self.events.append("battle_0")
        return "numbered"


def test_decorator_module_has_no_global_config_dispatch() -> None:
    assert "Config" not in decorator.__all__
    assert not hasattr(decorator, "Config")


@pytest.mark.parametrize(
    ("clear_all", "poor_map_data", "expected_result", "expected_events"),
    [
        (False, False, "numbered", ["battle_0"]),
        (
            False,
            True,
            True,
            [
                "break_siren_caught",
                "clear_all_mystery",
                "pick_up_ammo",
                ("select", "is_boss"),
                "clear_siren",
            ],
        ),
        (
            True,
            False,
            "clear_all",
            [
                "break_siren_caught",
                "clear_all_mystery",
                "pick_up_ammo",
                ("select", "is_enemy"),
                ("select", "is_siren"),
                "add",
                ("select", "is_fortress"),
                "add",
                ("select", "is_boss"),
                "delete",
                "battle_boss",
            ],
        ),
        (
            True,
            True,
            "clear_all",
            [
                "break_siren_caught",
                "clear_all_mystery",
                "pick_up_ammo",
                ("select", "is_enemy"),
                ("select", "is_siren"),
                "add",
                ("select", "is_fortress"),
                "add",
                ("select", "is_boss"),
                "delete",
                "battle_boss",
            ],
        ),
    ],
)
def test_battle_function_selects_policy_in_explicit_priority_order(
    *,
    clear_all: bool,
    poor_map_data: bool,
    expected_result: object,
    expected_events: list[object],
) -> None:
    campaign = _BattleHarness(clear_all=clear_all, poor_map_data=poor_map_data, battle_count=3)

    assert campaign.battle_function() == expected_result
    assert campaign.events == expected_events


@pytest.mark.parametrize(
    ("battle_count", "available_battles", "expected"),
    [
        (12, {12}, "battle_12"),
        (12, {3}, "battle_3"),
        (10, {0}, "default"),
        (9, {0}, "battle_0"),
    ],
)
def test_numbered_battle_checks_at_most_ten_candidates(
    battle_count: int,
    available_battles: set[int],
    expected: str,
) -> None:
    campaign = _BattleHarness(clear_all=False, poor_map_data=False, battle_count=battle_count)
    for index in available_battles:
        setattr(campaign, f"battle_{index}", lambda index=index: f"battle_{index}")

    assert campaign.battle_function() == expected
