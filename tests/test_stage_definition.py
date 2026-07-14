from typing import cast

import pytest

from module.content.battle_policy import (
    BattlePolicy,
    BossStrategy,
    CellAccessibleCondition,
    ClearBoss,
    ClearChosenEnemy,
    ClearFilteredEnemy,
    DefaultBattle,
    GuardedBattleStep,
    StagePolicy,
)
from module.content.cell import CellId
from module.content.errors import ContentValidationError
from module.content.models import StageRef
from module.content.stage_definition import (
    CampaignStageDefinition,
    CellSpec,
    GridShape,
    MapDefinition,
    RunVariant,
    SpawnWave,
)
from module.content.stage_rules import MapFeatures, RepeatableCompletion, StageRules, StarRequirements

_TEST_RULES = StageRules(
    features=MapFeatures(
        siren_templates=(),
        movable_enemy_turns=(),
        has_siren=False,
        has_movable_enemy=False,
        has_map_story=False,
        has_fleet_step=False,
        has_ambush=False,
        has_mystery=False,
    ),
    completion=RepeatableCompletion(StarRequirements()),
)


def _definition(
    waves: tuple[SpawnWave, ...],
    policies: dict[int, StagePolicy | BattlePolicy],
) -> CampaignStageDefinition:
    cell = CellSpec(CellId(0, 0), "--", 50.0)
    variant = RunVariant((cell,), waves)
    return CampaignStageDefinition(
        ref=StageRef("test_pack", "test_stage"),
        map=MapDefinition(
            name="TEST",
            shape=GridShape(1, 1),
            camera_data=(cell.cell_id,),
            camera_data_spawn_point=(cell.cell_id,),
            normal=variant,
            loop=variant,
        ),
        rules=_TEST_RULES,
        enemy_filter="1L > 1M",
        battle_policies=policies,
    )


def test_stage_definition_normalizes_battle_policy_builders() -> None:
    definition = _definition(
        (SpawnWave(0, enemy=1),),
        {0: BattlePolicy("filtered_enemy_then_default", preserve=0)},
    )

    assert definition.battle_policies[0] == StagePolicy((ClearFilteredEnemy(preserve=0), DefaultBattle()))


@pytest.mark.parametrize(
    ("policies", "message"),
    [
        (cast("dict[int, StagePolicy | BattlePolicy]", {True: StagePolicy((DefaultBattle(),))}), "keys"),
        (cast("dict[int, StagePolicy | BattlePolicy]", {0: object()}), "StagePolicy values"),
    ],
)
def test_stage_definition_rejects_invalid_policy_mapping_members(
    policies: dict[int, StagePolicy | BattlePolicy],
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        _definition((SpawnWave(0, enemy=1),), policies)


def test_stage_definition_rejects_policy_for_undeclared_battle() -> None:
    with pytest.raises(ContentValidationError, match="declared spawn battles"):
        _definition((SpawnWave(0, enemy=1),), {1: StagePolicy((DefaultBattle(),))})


def test_stage_definition_requires_a_boss_policy_that_clears_boss() -> None:
    waves = (SpawnWave(0, boss=1),)

    with pytest.raises(ContentValidationError, match="explicit stage policy"):
        _definition(waves, {})
    with pytest.raises(ContentValidationError, match=r"boss battle 0 policy must end with ClearBoss"):
        _definition(waves, {0: StagePolicy((DefaultBattle(),))})


def test_stage_definition_rejects_boss_policy_on_non_boss_wave() -> None:
    with pytest.raises(ContentValidationError, match="ClearBoss steps may only appear"):
        _definition(
            (SpawnWave(0, enemy=1),),
            {0: StagePolicy((ClearBoss(BossStrategy.FLEET_BOSS),))},
        )


@pytest.mark.parametrize(
    "policy",
    [
        StagePolicy((ClearChosenEnemy(CellId(1, 0)),)),
        StagePolicy(
            (
                GuardedBattleStep(
                    CellAccessibleCondition(CellId(1, 0)),
                    DefaultBattle(),
                ),
            )
        ),
    ],
)
def test_stage_definition_rejects_every_policy_cell_reference_outside_map(policy: StagePolicy) -> None:
    with pytest.raises(ContentValidationError, match="battle policies reference a cell outside the map shape"):
        _definition((SpawnWave(0, enemy=1),), {0: policy})
