from module.content.battle_policy import BossStrategy, ClearBoss, DefaultBattle
from module.content.battle_program import (
    AttemptBattleAction,
    AttemptMechanicAction,
    BattleProgram,
    BossAccessibleCondition,
    MapPresenceCondition,
    NotProgramCondition,
    PerformMechanicAction,
    ProgramBranch,
    ProgramFlag,
    ProgramFlagCondition,
    ReturnBattleAction,
)
from module.content.cell import CellId
from module.content.mechanic_rules import AirStrike, MoveFleet, RoadblockAction, RoadblockMode
from module.content.models import StageRef
from module.content.stage_loader import load_default_stage


def _battle_4() -> BattleProgram:
    return load_default_stage(StageRef("campaign_main", "16-4")).battle_programs[4]


def test_battle_4_keeps_clear_mode_and_missing_boss_terminal_decisions() -> None:
    statements = _battle_4().statements
    clear_mode, boss_present = statements[:2]

    assert isinstance(clear_mode, ProgramBranch)
    assert clear_mode.condition == ProgramFlagCondition(ProgramFlag.CLEAR_MODE)
    assert clear_mode.when_true == (ReturnBattleAction(ClearBoss(BossStrategy.FLEET_BOSS)),)
    assert isinstance(boss_present, ProgramBranch)
    assert isinstance(boss_present.condition, MapPresenceCondition)
    assert boss_present.condition.presence.value == "boss"
    assert boss_present.when_false == ()


def test_battle_4_keeps_inaccessible_boss_roadblock_as_an_immediate_result() -> None:
    boss_present = _battle_4().statements[1]
    assert isinstance(boss_present, ProgramBranch)
    inaccessible = boss_present.when_true[0]

    assert isinstance(inaccessible, ProgramBranch)
    assert isinstance(inaccessible.condition, NotProgramCondition)
    assert isinstance(inaccessible.condition.condition, BossAccessibleCondition)
    assert len(inaccessible.when_true) == 1
    action = inaccessible.when_true[0]
    assert isinstance(action, AttemptMechanicAction)
    assert isinstance(action.action, RoadblockAction)
    assert action.action.mode is RoadblockMode.CLEAR


def test_battle_4_keeps_support_fleet_move_and_air_strike_before_boss() -> None:
    boss_present = _battle_4().statements[1]
    assert isinstance(boss_present, ProgramBranch)
    support = boss_present.when_true[1]

    assert isinstance(support, ProgramBranch)
    assert support.condition == ProgramFlagCondition(ProgramFlag.USE_SUPPORT_FLEET)
    assert len(support.when_true) == 2
    move, strike = support.when_true
    assert isinstance(move, PerformMechanicAction)
    assert isinstance(move.action, MoveFleet)
    assert move.action.destination == CellId(9, 5)
    assert isinstance(strike, PerformMechanicAction)
    assert isinstance(strike.action, AirStrike)
    assert strike.action.target == CellId(8, 7)
    assert boss_present.when_true[2] == AttemptBattleAction(ClearBoss(BossStrategy.FLEET_BOSS))


def test_battle_4_keeps_fallback_priority_after_boss_attempt() -> None:
    fallback = _battle_4().statements[2:]

    assert isinstance(fallback[0], AttemptMechanicAction)
    assert isinstance(fallback[0].action, RoadblockAction)
    assert fallback[0].action.mode is RoadblockMode.CLEAR
    assert isinstance(fallback[1], AttemptMechanicAction)
    assert isinstance(fallback[1].action, RoadblockAction)
    assert fallback[1].action.mode is RoadblockMode.CLEAR_POTENTIAL
    assert isinstance(fallback[2], AttemptBattleAction)
    assert fallback[-1] == ReturnBattleAction(DefaultBattle())
