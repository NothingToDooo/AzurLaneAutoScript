import pytest

from module.content.battle_policy import (
    ClearPriorityEnemy,
    ClearSiren,
    DefaultBattle,
    StagePolicy,
)
from module.content.battle_program import AttemptBattleAction, AttemptMechanicAction, ReturnBattleAction
from module.content.mechanic_rules import ProtectFleet
from module.content.models import StageRef
from module.content.stage_loader import load_default_stage


@pytest.mark.parametrize("pack", ["event_20201229_cn", "war_archives_20201229_cn"])
def test_d1_priority_enemy_keeps_scale_1_before_other_filters(pack: str) -> None:
    policy = load_default_stage(StageRef(pack, "d1")).battle_policies[0]

    assert isinstance(policy, StagePolicy)
    assert policy.steps == (
        ClearSiren(),
        ClearPriorityEnemy(include_scale_1=True),
        DefaultBattle(),
    )


@pytest.mark.parametrize("pack", ["event_20201229_cn", "war_archives_20201229_cn"])
def test_d3_battle_0_keeps_fleet_protection_and_skips_scale_1(pack: str) -> None:
    program = load_default_stage(StageRef(pack, "d3")).battle_programs[0]

    protect, siren, priority, fallback = program.statements
    assert isinstance(protect, AttemptMechanicAction)
    assert isinstance(protect.action, ProtectFleet)
    assert isinstance(siren, AttemptBattleAction)
    assert siren.action == ClearSiren()
    assert isinstance(priority, AttemptBattleAction)
    assert priority.action == ClearPriorityEnemy(include_scale_1=False)
    assert fallback == ReturnBattleAction(DefaultBattle())


@pytest.mark.parametrize("pack", ["event_20201229_cn", "war_archives_20201229_cn"])
def test_d3_battle_5_keeps_scale_1_priority(pack: str) -> None:
    program = load_default_stage(StageRef(pack, "d3")).battle_programs[5]

    priority = program.statements[2]
    assert isinstance(priority, AttemptBattleAction)
    assert priority.action == ClearPriorityEnemy(include_scale_1=True)
