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
    ProgramStatement,
    ReturnBattleAction,
)
from module.content.mechanic_rules import (
    BreakSirenCaught,
    ClearAllMystery,
    ClearMechanism,
    EncounterExpectation,
    MechanicOperation,
    MechanicProcedure,
    PickupAmmo,
)


def select_battle_program(
    mode: BattleProgramMode,
    battle: int,
    stage_program: BattleProgram | None,
    boss_approach: BossApproachPlan | None = None,
) -> BattleProgram | None:
    """选择当前模式的关卡覆写；没有覆写时构造模式默认程序。"""

    if not isinstance(mode, BattleProgramMode):
        message = "battle program selector requires a BattleProgramMode"
        raise TypeError(message)
    if type(battle) is not int or battle < 0:
        message = "battle program selector requires a non-negative battle"
        raise ValueError(message)
    if stage_program is not None:
        if not isinstance(stage_program, BattleProgram):
            message = "stage_program must be a BattleProgram or None"
            raise TypeError(message)
        if stage_program.battle != battle:
            message = "stage program battle does not match the active battle"
            raise ValueError(message)
        if mode in stage_program.activation_modes:
            return stage_program
    return default_mode_battle_program(mode, battle, boss_approach)


def default_mode_battle_program(
    mode: BattleProgramMode,
    battle: int,
    boss_approach: BossApproachPlan | None = None,
) -> BattleProgram | None:
    if not isinstance(mode, BattleProgramMode):
        message = "default battle program requires a BattleProgramMode"
        raise TypeError(message)
    if type(battle) is not int or battle < 0:
        message = "default battle program requires a non-negative battle"
        raise ValueError(message)
    if boss_approach is not None:
        if not isinstance(boss_approach, BossApproachPlan):
            message = "boss_approach must be a BossApproachPlan or None"
            raise TypeError(message)
        if boss_approach.battle != battle:
            message = "boss approach battle does not match the active battle"
            raise ValueError(message)
        if mode not in boss_approach.activation_modes:
            boss_approach = None
    if mode is BattleProgramMode.NORMAL:
        return None
    if mode is BattleProgramMode.CLEAR_ALL:
        statements = (*_common_prelude(battle), _clear_all_dispatch(battle, boss_approach))
    elif mode is BattleProgramMode.POOR_MAP_DATA:
        statements = (*_common_prelude(battle), _poor_map_dispatch(boss_approach))
    else:
        raise AssertionError(mode)
    return BattleProgram(battle, frozenset({mode}), statements)


def _common_prelude(battle: int) -> tuple[ProgramStatement, ...]:
    return (
        AttemptMechanicAction(
            BreakSirenCaught(battle),
            EncounterExpectation.SIREN,
        ),
        PerformMechanicAction(ClearAllMystery(battle, nearby=False)),
        ProgramBranch(
            MetricCondition(
                ProgramMetric.BATTLE_COUNT,
                ComparisonOperator.GREATER_THAN_OR_EQUAL,
                3,
            ),
            (PerformMechanicAction(PickupAmmo(battle)),),
        ),
    )


def _clear_all_dispatch(
    battle: int,
    boss_approach: BossApproachPlan | None,
) -> ProgramBranch:
    return ProgramBranch(
        MapPresenceCondition(MapPresence.NON_BOSS_TARGET),
        (_clear_remaining_targets(battle),),
        _brute_boss(boss_approach),
    )


def _clear_remaining_targets(battle: int) -> ProgramBranch:
    return ProgramBranch(
        ProgramFlagCondition(ProgramFlag.MOVABLE_NORMAL_ENEMY),
        (
            AttemptBattleAction(ClearAnyEnemy(sort=("cost_2",))),
            ReturnBattleAction(DefaultBattle()),
        ),
        (
            AttemptMechanicAction(
                MechanicProcedure(
                    battle,
                    (MechanicOperation.CLEAR_BOUNCING_ENEMY,),
                ),
                EncounterExpectation.ENEMY,
            ),
            AttemptBattleAction(ClearSiren()),
            PerformMechanicAction(ClearMechanism(battle)),
            ReturnBattleAction(DefaultBattle()),
        ),
    )


def _poor_map_dispatch(
    boss_approach: BossApproachPlan | None,
) -> ProgramBranch:
    return ProgramBranch(
        MapPresenceCondition(MapPresence.BOSS),
        _brute_boss(boss_approach),
        (
            AttemptBattleAction(ClearSiren()),
            ReturnBattleAction(ClearEnemy()),
        ),
    )


def _brute_boss(
    boss_approach: BossApproachPlan | None,
) -> tuple[ProgramStatement, ...]:
    approach = (
        tuple(PerformMechanicAction(action, EncounterExpectation.ANY) for action in boss_approach.actions)
        if boss_approach is not None
        else ()
    )
    return (
        *approach,
        AttemptBattleAction(ClearBossRoadblock(BossStrategy.BRUTE_FORCE)),
        ReturnBattleAction(ClearBoss(BossStrategy.BRUTE_FORCE)),
    )
