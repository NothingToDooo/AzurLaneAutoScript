from typing import cast

import pytest

from module.content.battle_policy import BossStrategy
from module.content.cell import CellId
from module.content.errors import ContentValidationError
from module.content.hard_mode_policy import HardModeEquipmentCleanup, HardModeRuntimePolicy
from module.content.mechanic_rules import (
    AirStrike,
    BreakSirenCaught,
    ClearAllMystery,
    EncounterExpectation,
    FleetClearTarget,
    FleetCoordinationRules,
    FleetRole,
    MapCellAttribute,
    MapCellPatch,
    MapInteractionRules,
    MapItemKind,
    MapMutationPhase,
    MapMutationRules,
    MapMutationVariant,
    MovingEnemyRules,
    PickupAmmo,
    PickupMapItem,
    PickupRules,
    RoadblockAction,
    RoadblockMode,
    RoadblockRules,
    RoadblockSelection,
    RoadGroup,
    RoadPath,
    StageMechanicRules,
    StepFleetOn,
)


def test_mechanic_rules_preserve_closed_actions_and_expose_all_references() -> None:
    a1, a2, b2 = CellId(0, 0), CellId(0, 1), CellId(1, 1)
    road = RoadGroup((RoadPath((a1, a2)), RoadPath((a1, b2))))
    rules = StageMechanicRules(
        roadblocks=RoadblockRules((RoadblockAction(0, RoadblockMode.CLEAR, (road,), RoadblockSelection.WEAKEST),)),
        fleet_coordination=FleetCoordinationRules(
            (
                BreakSirenCaught(0),
                StepFleetOn(0, (b2,), (road,), FleetRole.FLEET_2),
                FleetClearTarget(1, a2, FleetRole.FLEET_BOSS, EncounterExpectation.SIREN),
            )
        ),
        pickups=PickupRules(
            (
                PickupAmmo(0, FleetRole.ACTIVE),
                PickupMapItem(1, MapItemKind.FLARE, b2, FleetRole.FLEET_BOSS),
            )
        ),
        map_interactions=MapInteractionRules((ClearAllMystery(0, nearby=False, ignored=(a1,)), AirStrike(1, b2))),
        map_mutations=MapMutationRules(
            (
                MapCellPatch(
                    MapMutationPhase.BEFORE_BATTLE,
                    a2,
                    MapCellAttribute.MAY_ENEMY,
                    value=True,
                    battle=1,
                ),
            )
        ),
        moving_enemies=MovingEnemyRules((2,), initial_enemy_cells=(b2,)),
    )

    assert rules.referenced_battles == frozenset({0, 1})
    assert rules.referenced_cells == frozenset({a1, a2, b2})

    with pytest.raises(ContentValidationError, match="only supports fleet_2"):
        BreakSirenCaught(0, FleetRole.FLEET_1)


def test_mechanic_models_reject_ambiguous_mutation_and_moving_enemy_state() -> None:
    a1 = CellId(0, 0)
    with pytest.raises(ContentValidationError, match="requires a battle"):
        MapCellPatch(MapMutationPhase.BEFORE_BATTLE, a1, MapCellAttribute.IS_ENEMY, value=True)
    with pytest.raises(ContentValidationError, match="does not accept a battle"):
        MapCellPatch(MapMutationPhase.MAP_INIT, a1, MapCellAttribute.IS_ENEMY, value=True, battle=0)
    with pytest.raises(TypeError, match="MapMutationVariant"):
        MapCellPatch(
            MapMutationPhase.MAP_INIT,
            a1,
            MapCellAttribute.IS_ENEMY,
            value=True,
            variant=cast("MapMutationVariant", "normal"),
        )
    with pytest.raises(ContentValidationError, match="must not overlap"):
        MovingEnemyRules(initial_enemy_cells=(a1,), initial_siren_cells=(a1,))


def test_hard_mode_policy_rejects_untyped_runtime_choices() -> None:
    policy = HardModeRuntimePolicy(
        BossStrategy.MAP_SEARCH,
        HardModeEquipmentCleanup.TAKE_OFF_WHEN_FINISHED,
    )

    assert policy.boss_strategy is BossStrategy.MAP_SEARCH
    with pytest.raises(TypeError, match="boss strategy"):
        HardModeRuntimePolicy(
            cast("BossStrategy", "map_search"),
            HardModeEquipmentCleanup.KEEP,
        )
