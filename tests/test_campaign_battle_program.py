import pytest

from module.content.battle_policy import (
    BossStrategy,
    ClearAnyEnemy,
    ClearBoss,
    ClearBossRoadblock,
    ClearEnemy,
    ClearSiren,
    DefaultBattle,
)
from module.content.battle_program import (
    AttemptBattleAction,
    AttemptMechanicAction,
    BattleProgram,
    BattleProgramMode,
    BossApproachPlan,
    ComparisonOperator,
    MapPresence,
    MapPresenceCondition,
    MetricCondition,
    PerformMechanicAction,
    ProgramBranch,
    ProgramFlag,
    ProgramFlagCondition,
    ProgramMetric,
    ReturnBattleAction,
    ReturnProgramContinue,
)
from module.content.cell import CellId
from module.content.errors import ContentValidationError
from module.content.mechanic_rules import (
    BreakSirenCaught,
    CandidateSortKey,
    ClearAllMystery,
    ClearMechanism,
    EncounterExpectation,
    FleetRole,
    MechanicOperation,
    MechanicProcedure,
    MoveFleet,
    MoveFleetToBestCandidate,
    PickupAmmo,
)
from module.gameplay.campaign_battle_program import (
    default_mode_battle_program,
    select_battle_program,
)

B6 = CellId(1, 5)
C7 = CellId(2, 6)
B8 = CellId(1, 7)


def _boss_approach(
    battle: int,
    *,
    modes: frozenset[BattleProgramMode] = frozenset({BattleProgramMode.CLEAR_ALL, BattleProgramMode.POOR_MAP_DATA}),
) -> BossApproachPlan:
    return BossApproachPlan(
        battle,
        modes,
        (
            MoveFleetToBestCandidate(
                battle,
                (B6, C7),
                FleetRole.FLEET_BOSS,
                (CandidateSortKey.WEIGHT, CandidateSortKey.COST),
            ),
            MoveFleet(battle, B8, FleetRole.FLEET_BOSS),
        ),
    )


def test_selector_prefers_an_active_stage_override_and_uses_typed_fallbacks() -> None:
    stage_program = BattleProgram(
        2,
        frozenset({BattleProgramMode.CLEAR_ALL}),
        (ReturnProgramContinue(),),
    )

    assert select_battle_program(BattleProgramMode.CLEAR_ALL, 2, stage_program) is stage_program
    assert select_battle_program(BattleProgramMode.NORMAL, 2, stage_program) is None
    fallback = select_battle_program(BattleProgramMode.POOR_MAP_DATA, 2, stage_program)
    assert fallback is not None
    assert fallback is not stage_program
    assert fallback.activation_modes == frozenset({BattleProgramMode.POOR_MAP_DATA})


def test_clear_all_default_program_preserves_the_legacy_decision_order() -> None:
    program = default_mode_battle_program(BattleProgramMode.CLEAR_ALL, 3)

    assert program is not None
    break_caught, clear_mystery, pickup_ammo, dispatch = program.statements
    assert isinstance(break_caught, AttemptMechanicAction)
    assert break_caught.action == BreakSirenCaught(3)
    assert isinstance(clear_mystery, PerformMechanicAction)
    assert clear_mystery.action == ClearAllMystery(3, nearby=False)
    assert isinstance(pickup_ammo, ProgramBranch)
    assert pickup_ammo.condition == MetricCondition(
        ProgramMetric.BATTLE_COUNT,
        ComparisonOperator.GREATER_THAN_OR_EQUAL,
        3,
    )
    assert pickup_ammo.when_true == (PerformMechanicAction(PickupAmmo(3)),)

    assert isinstance(dispatch, ProgramBranch)
    assert dispatch.condition == MapPresenceCondition(MapPresence.NON_BOSS_TARGET)
    remaining = dispatch.when_true[0]
    assert isinstance(remaining, ProgramBranch)
    assert remaining.condition == ProgramFlagCondition(ProgramFlag.MOVABLE_NORMAL_ENEMY)
    assert remaining.when_true == (
        AttemptBattleAction(ClearAnyEnemy(sort=("cost_2",))),
        ReturnBattleAction(DefaultBattle()),
    )
    assert remaining.when_false == (
        AttemptMechanicAction(
            MechanicProcedure(3, (MechanicOperation.CLEAR_BOUNCING_ENEMY,)),
            EncounterExpectation.ENEMY,
        ),
        AttemptBattleAction(ClearSiren()),
        PerformMechanicAction(ClearMechanism(3)),
        ReturnBattleAction(DefaultBattle()),
    )
    assert dispatch.when_false == (
        AttemptBattleAction(ClearBossRoadblock(BossStrategy.BRUTE_FORCE)),
        ReturnBattleAction(ClearBoss(BossStrategy.BRUTE_FORCE)),
    )


def test_poor_map_default_program_preserves_boss_then_siren_enemy_dispatch() -> None:
    program = default_mode_battle_program(BattleProgramMode.POOR_MAP_DATA, 4)

    assert program is not None
    dispatch = program.statements[-1]
    assert isinstance(dispatch, ProgramBranch)
    assert dispatch.condition == MapPresenceCondition(MapPresence.BOSS)
    assert dispatch.when_true == (
        AttemptBattleAction(ClearBossRoadblock(BossStrategy.BRUTE_FORCE)),
        ReturnBattleAction(ClearBoss(BossStrategy.BRUTE_FORCE)),
    )
    assert dispatch.when_false == (
        AttemptBattleAction(ClearSiren()),
        ReturnBattleAction(ClearEnemy()),
    )


def test_typed_boss_approach_is_inserted_only_inside_active_brute_boss_paths() -> None:
    approach = _boss_approach(5)

    assert approach.referenced_cells == frozenset({B6, C7, B8})
    assert default_mode_battle_program(BattleProgramMode.NORMAL, 5, approach) is None

    clear_all = default_mode_battle_program(BattleProgramMode.CLEAR_ALL, 5, approach)
    assert clear_all is not None
    clear_dispatch = clear_all.statements[-1]
    assert isinstance(clear_dispatch, ProgramBranch)
    assert all(
        not isinstance(statement, PerformMechanicAction) or statement.action not in approach.actions
        for statement in clear_dispatch.when_true
    )
    assert clear_dispatch.when_false == (
        *(PerformMechanicAction(action, EncounterExpectation.ANY) for action in approach.actions),
        AttemptBattleAction(ClearBossRoadblock(BossStrategy.BRUTE_FORCE)),
        ReturnBattleAction(ClearBoss(BossStrategy.BRUTE_FORCE)),
    )

    poor_map = default_mode_battle_program(BattleProgramMode.POOR_MAP_DATA, 5, approach)
    assert poor_map is not None
    poor_dispatch = poor_map.statements[-1]
    assert isinstance(poor_dispatch, ProgramBranch)
    assert poor_dispatch.when_true[:2] == tuple(
        PerformMechanicAction(action, EncounterExpectation.ANY) for action in approach.actions
    )
    assert poor_dispatch.when_false == (
        AttemptBattleAction(ClearSiren()),
        ReturnBattleAction(ClearEnemy()),
    )


def test_boss_approach_contract_rejects_normal_policy_and_non_boss_moves() -> None:
    with pytest.raises(ContentValidationError, match="candidates"):
        MoveFleetToBestCandidate(5, (), FleetRole.FLEET_BOSS)
    with pytest.raises(ContentValidationError, match="sort"):
        MoveFleetToBestCandidate(5, (B6,), FleetRole.FLEET_BOSS, ())
    with pytest.raises(ContentValidationError, match="normal stage policy"):
        _boss_approach(5, modes=frozenset({BattleProgramMode.NORMAL}))
    with pytest.raises(ContentValidationError, match="plan battle"):
        BossApproachPlan(
            5,
            frozenset({BattleProgramMode.CLEAR_ALL}),
            (MoveFleet(6, B8, FleetRole.FLEET_BOSS),),
        )
    with pytest.raises(ContentValidationError, match="boss fleet"):
        BossApproachPlan(
            5,
            frozenset({BattleProgramMode.CLEAR_ALL}),
            (MoveFleet(5, B8, FleetRole.FLEET_1),),
        )
