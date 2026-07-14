from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from module.content.battle_policy import (
    AllConditions,
    AnyCondition,
    BattleFlag,
    BattleIntent,
    BattlePlan,
    BattlePolicy,
    BattlePolicyName,
    BossStrategy,
    CellAccessibleCondition,
    ClearBoss,
    ClearBossRoadblock,
    ClearChosenEnemy,
    ClearFilteredEnemy,
    ClearSelectedEnemy,
    ClearSiren,
    DefaultBattle,
    FlagCondition,
    GuardedBattleStep,
    NotCondition,
    StagePolicy,
)
from module.content.cell import CellId
from module.content.errors import ContentValidationError


def _assign_attribute(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


def test_siren_policy_has_a_deterministic_ordered_plan() -> None:
    policy = BattlePolicy("siren_then_filtered_enemy", preserve=2)
    expected = BattlePlan((ClearSiren(), ClearFilteredEnemy(preserve=2), DefaultBattle()))

    assert policy.to_plan() == expected
    assert policy.to_plan() == policy.to_plan()


def test_filtered_policy_has_a_deterministic_ordered_plan() -> None:
    policy = BattlePolicy("filtered_enemy_then_default", preserve=1)

    assert policy.to_plan() == BattlePlan(
        (ClearFilteredEnemy(preserve=1), DefaultBattle()),
    )


def test_fleet_boss_policy_has_a_single_intent_plan() -> None:
    assert BattlePolicy("fleet_boss").to_plan() == BattlePlan(
        (ClearBoss(BossStrategy.FLEET_BOSS),),
    )


def test_battle_plan_is_a_non_empty_immutable_tuple() -> None:
    plan = BattlePlan((ClearBoss(BossStrategy.FLEET_BOSS),))

    assert isinstance(plan.intents, tuple)
    with pytest.raises(FrozenInstanceError):
        _assign_attribute(plan, "intents", ())


def test_battle_plan_rejects_empty_or_foreign_intents() -> None:
    with pytest.raises(ContentValidationError, match="must not be empty"):
        BattlePlan(())
    with pytest.raises(TypeError, match="invalid intent"):
        BattlePlan(cast("tuple[BattleIntent, ...]", (object(),)))


@pytest.mark.parametrize("preserve", [True, -1, 1.0, "1"])
def test_filtered_enemy_intent_requires_non_negative_exact_integer(preserve: object) -> None:
    with pytest.raises(ContentValidationError, match="preserve"):
        ClearFilteredEnemy(preserve=cast("int", preserve))


@pytest.mark.parametrize("preserve", [True, -1, 1.0, "1"])
def test_filtered_policies_require_non_negative_exact_integer(preserve: object) -> None:
    with pytest.raises(ContentValidationError, match="preserve"):
        BattlePolicy(
            "filtered_enemy_then_default",
            preserve=cast("int | None", preserve),
        )


def test_policy_rejects_unknown_names_and_incompatible_preserve() -> None:
    with pytest.raises(ContentValidationError, match="unknown battle policy"):
        BattlePolicy(cast("BattlePolicyName", "arbitrary_expression"))
    with pytest.raises(ContentValidationError, match="preserve"):
        BattlePolicy("siren_then_filtered_enemy")
    with pytest.raises(ContentValidationError, match="preserve"):
        BattlePolicy("fleet_boss", preserve=0)


def test_policy_exposes_no_legacy_execution_api() -> None:
    policy = BattlePolicy("fleet_boss")

    assert not hasattr(policy, "execute")
    assert not hasattr(policy, "as_method")


def test_non_atomic_boss_search_requires_an_explicit_roadblock_step() -> None:
    with pytest.raises(ContentValidationError, match="roadblock"):
        StagePolicy((ClearBoss(BossStrategy.MAP_SEARCH),))

    policy = StagePolicy(
        (
            ClearBossRoadblock(BossStrategy.MAP_SEARCH),
            ClearBoss(BossStrategy.MAP_SEARCH),
        )
    )

    assert policy.to_plan().intents == policy.steps


def test_stage_policy_exposes_its_boss_contract() -> None:
    regular = StagePolicy((DefaultBattle(),))
    guarded_boss = StagePolicy(
        (
            GuardedBattleStep(
                FlagCondition(BattleFlag.CLEAR_MODE, value=True),
                ClearBoss(BossStrategy.FLEET_BOSS),
            ),
        )
    )

    assert regular.clears_boss is False
    assert guarded_boss.clears_boss is True


def test_stage_policy_owns_all_direct_and_guarded_cell_references() -> None:
    chosen = CellId(0, 0)
    first_candidate = CellId(1, 0)
    second_candidate = CellId(2, 0)
    accessible = CellId(3, 0)
    nested_accessible = CellId(4, 0)
    policy = StagePolicy(
        (
            ClearChosenEnemy(chosen),
            ClearSelectedEnemy((first_candidate, second_candidate)),
            GuardedBattleStep(
                AllConditions(
                    (
                        CellAccessibleCondition(accessible),
                        NotCondition(
                            AnyCondition(
                                (
                                    CellAccessibleCondition(nested_accessible),
                                    FlagCondition(BattleFlag.CLEAR_MODE, value=False),
                                )
                            )
                        ),
                    )
                ),
                DefaultBattle(),
            ),
        )
    )

    assert policy.referenced_cells == frozenset(
        {chosen, first_candidate, second_candidate, accessible, nested_accessible}
    )


def test_boss_roadblock_rejects_direct_fleet_strategies() -> None:
    with pytest.raises(ContentValidationError, match="map_search or brute_force"):
        ClearBossRoadblock(BossStrategy.FLEET_BOSS)
