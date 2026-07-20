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


@pytest.mark.parametrize(
    ("node", "expected"),
    [("A1", CellId(0, 0)), ("Z9", CellId(25, 8)), ("AA10", CellId(26, 9))],
)
def test_cell_id_parses_canonical_grid_nodes(node: str, expected: CellId) -> None:
    cell = CellId.parse(node)

    assert cell == expected
    assert cell.node == node


@pytest.mark.parametrize("node", ["a1", "A0", " A1", "A1 ", "", 1, True])
def test_cell_id_rejects_noncanonical_grid_nodes(node: object) -> None:
    with pytest.raises(ContentValidationError, match="uppercase grid node"):
        CellId.parse(node)


def _map_definition_with_candidates(
    candidates: tuple[CellId, ...] | None,
) -> MapDefinition:
    shape = GridShape(2, 1)
    cells = tuple(CellSpec(cell_id, "--", 50.0) for cell_id in shape.cell_ids())
    variant = RunVariant(cells, ())
    return MapDefinition(
        name="TEST",
        shape=shape,
        camera_data=(CellId(0, 0),),
        camera_data_spawn_point=(CellId(0, 0),),
        normal=variant,
        loop=variant,
        normal_enemy_spawn_candidates=candidates,
    )


def test_map_definition_accepts_a_complete_normal_enemy_spawn_candidate_mask() -> None:
    candidates = (CellId(0, 0), CellId(1, 0))

    definition = _map_definition_with_candidates(candidates)

    assert definition.normal_enemy_spawn_candidates == candidates


def test_map_definition_rejects_an_empty_normal_enemy_spawn_candidate_mask() -> None:
    with pytest.raises(ContentValidationError, match="must not be empty"):
        _map_definition_with_candidates(())


def test_map_definition_rejects_duplicate_normal_enemy_spawn_candidates() -> None:
    with pytest.raises(ContentValidationError, match="duplicate cells"):
        _map_definition_with_candidates((CellId(0, 0), CellId(0, 0)))


def test_map_definition_rejects_a_normal_enemy_spawn_candidate_outside_its_shape() -> None:
    with pytest.raises(ContentValidationError, match="outside its shape"):
        _map_definition_with_candidates((CellId(2, 0),))


def test_map_definition_rejects_an_untyped_normal_enemy_spawn_candidate() -> None:
    candidates = cast("tuple[CellId, ...]", (object(),))

    with pytest.raises(TypeError, match="must contain CellId values"):
        _map_definition_with_candidates(candidates)


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
