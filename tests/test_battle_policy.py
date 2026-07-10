from typing import TYPE_CHECKING, cast

import pytest

from module.content.battle_policy import BattlePolicy
from module.content.errors import ContentValidationError

if TYPE_CHECKING:
    from typing import Any


class _BossFleet:
    def __init__(self, calls: list[object], result: object) -> None:
        self.calls = calls
        self.result = result

    def clear_boss(self) -> object:
        self.calls.append("fleet_boss.clear_boss")
        return self.result


class _Campaign:
    ENEMY_FILTER = "1L > 2L"

    def __init__(
        self,
        *,
        siren: object = False,
        enemy: object = False,
        default: object = False,
        boss: object = False,
    ) -> None:
        self.calls: list[object] = []
        self.siren_result = siren
        self.enemy_result = enemy
        self.default_result = default
        self.fleet_boss = _BossFleet(self.calls, boss)

    def clear_siren(self) -> object:
        self.calls.append("clear_siren")
        return self.siren_result

    def clear_filter_enemy(self, enemy_filter: str, *, preserve: int) -> object:
        self.calls.append(("clear_filter_enemy", enemy_filter, preserve))
        return self.enemy_result

    def battle_default(self) -> object:
        self.calls.append("battle_default")
        return self.default_result


def _execute(policy: BattlePolicy, campaign: _Campaign) -> object:
    return policy.execute(cast("Any", campaign))


def test_siren_policy_short_circuits_after_clearing_siren() -> None:
    campaign = _Campaign(siren="siren-result")

    result = _execute(BattlePolicy("siren_then_filtered_enemy", preserve=2), campaign)

    assert result is True
    assert campaign.calls == ["clear_siren"]


def test_siren_policy_preserves_exact_count_and_short_circuits_after_enemy() -> None:
    campaign = _Campaign(enemy="enemy-result")

    result = _execute(BattlePolicy("siren_then_filtered_enemy", preserve=2), campaign)

    assert result is True
    assert campaign.calls == ["clear_siren", ("clear_filter_enemy", "1L > 2L", 2)]


def test_siren_policy_falls_through_to_default_and_returns_its_result() -> None:
    default_result = object()
    campaign = _Campaign(default=default_result)

    result = _execute(BattlePolicy("siren_then_filtered_enemy", preserve=0), campaign)

    assert result is default_result
    assert campaign.calls == [
        "clear_siren",
        ("clear_filter_enemy", "1L > 2L", 0),
        "battle_default",
    ]


def test_filtered_policy_never_calls_siren_and_returns_default_result() -> None:
    default_result = object()
    campaign = _Campaign(default=default_result)

    result = _execute(BattlePolicy("filtered_enemy_then_default", preserve=1), campaign)

    assert result is default_result
    assert campaign.calls == [
        ("clear_filter_enemy", "1L > 2L", 1),
        "battle_default",
    ]


def test_fleet_boss_policy_forwards_result_without_other_actions() -> None:
    boss_result = object()
    campaign = _Campaign(boss=boss_result)

    result = _execute(BattlePolicy("fleet_boss"), campaign)

    assert result is boss_result
    assert campaign.calls == ["fleet_boss.clear_boss"]


@pytest.mark.parametrize("preserve", [True, -1, 1.0, "1"])
def test_filtered_policies_require_non_negative_exact_integer(preserve: object) -> None:
    with pytest.raises(ContentValidationError, match="preserve"):
        BattlePolicy("filtered_enemy_then_default", preserve=cast("Any", preserve))


def test_policy_rejects_unknown_names_and_incompatible_preserve() -> None:
    with pytest.raises(ContentValidationError, match="unknown battle policy"):
        BattlePolicy(cast("Any", "arbitrary_expression"))
    with pytest.raises(ContentValidationError, match="preserve"):
        BattlePolicy("siren_then_filtered_enemy")
    with pytest.raises(ContentValidationError, match="preserve"):
        BattlePolicy("fleet_boss", preserve=0)
