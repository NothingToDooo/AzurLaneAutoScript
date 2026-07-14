from typing import TYPE_CHECKING, cast

import pytest

from module.content.battle_policy import ClearSelectedEnemy, DefaultBattle
from module.content.battle_program import (
    AllProgramConditions,
    AnyProgramCondition,
    AttemptFixedTarget,
    AttemptMechanicAction,
    AttemptPresetRoute,
    BattleProgram,
    BattleProgramMode,
    BossAtCondition,
    MechanicActionBranch,
    NamedProgramMarker,
    NotProgramCondition,
    ProgramBranch,
    ProgramFlag,
    ProgramFlagCondition,
    ProgramMarkerCondition,
    ProgramStatement,
    ReturnBattleAction,
    SetProgramMarker,
    SetProgramMarkerFromCondition,
)
from module.content.cell import CellId
from module.content.errors import ContentValidationError
from module.content.manifest import load_default_event_manifests
from module.content.mechanic_rules import ClearAllMystery, EncounterExpectation
from module.content.stage_loader import load_default_stage

if TYPE_CHECKING:
    from collections.abc import Iterable


def _walk_statements(statements: Iterable[ProgramStatement]) -> tuple[ProgramStatement, ...]:
    result: list[ProgramStatement] = []
    for statement in statements:
        result.append(statement)
        if isinstance(statement, ProgramBranch):
            result.extend(_walk_statements((*statement.when_true, *statement.when_false)))
        elif isinstance(statement, MechanicActionBranch):
            result.extend(_walk_statements((*statement.when_applied, *statement.when_not_applied)))
    return tuple(result)


def _stage_programs(prefix: str) -> tuple[BattleProgram, ...]:
    return tuple(
        program
        for pack in load_default_event_manifests()
        for spec in pack.stages
        if f"{spec.ref.pack_id}/{spec.ref.stage_id}#".startswith(prefix)
        for program in load_default_stage(spec.ref).battle_programs.values()
    )


def _condition_named_markers(condition: object) -> frozenset[NamedProgramMarker]:
    if isinstance(condition, ProgramMarkerCondition) and isinstance(condition.marker, NamedProgramMarker):
        return frozenset({condition.marker})
    if isinstance(condition, AllProgramConditions | AnyProgramCondition):
        return frozenset(marker for nested in condition.conditions for marker in _condition_named_markers(nested))
    if isinstance(condition, NotProgramCondition):
        return _condition_named_markers(condition.condition)
    return frozenset()


def _stage_named_markers(prefix: str) -> frozenset[NamedProgramMarker]:
    markers: set[NamedProgramMarker] = set()
    for program in _stage_programs(prefix):
        for statement in _walk_statements(program.statements):
            if isinstance(statement, ProgramBranch):
                markers.update(_condition_named_markers(statement.condition))
            elif isinstance(statement, SetProgramMarker | SetProgramMarkerFromCondition):
                if isinstance(statement.marker, NamedProgramMarker):
                    markers.add(statement.marker)
                if isinstance(statement, SetProgramMarkerFromCondition):
                    markers.update(_condition_named_markers(statement.condition))
    return frozenset(markers)


def test_battle_program_validates_action_ownership_and_collects_nested_cells() -> None:
    a1 = CellId(0, 0)
    program = BattleProgram(
        2,
        frozenset({BattleProgramMode.NORMAL}),
        (
            ProgramBranch(
                ProgramFlagCondition(ProgramFlag.CLEAR_MODE),
                (AttemptMechanicAction(ClearAllMystery(2, ignored=(a1,)), EncounterExpectation.ANY),),
                (ReturnBattleAction(DefaultBattle()),),
            ),
        ),
    )

    assert program.referenced_cells == frozenset({a1})
    with pytest.raises(ContentValidationError, match="program battle"):
        BattleProgram(
            2,
            frozenset({BattleProgramMode.NORMAL}),
            (AttemptMechanicAction(ClearAllMystery(3), EncounterExpectation.ANY),),
        )

    with pytest.raises(ContentValidationError, match="activation_modes"):
        BattleProgram(2, frozenset(), (ReturnBattleAction(DefaultBattle()),))
    with pytest.raises(TypeError, match="BattleProgramMode"):
        BattleProgram(
            2,
            cast("frozenset[BattleProgramMode]", frozenset({"normal"})),
            (ReturnBattleAction(DefaultBattle()),),
        )


def test_attempt_mechanic_requires_a_closed_battle_expectation() -> None:
    action = ClearAllMystery(0)

    with pytest.raises(TypeError, match="EncounterExpectation"):
        AttemptMechanicAction(action, cast("EncounterExpectation", None))
    with pytest.raises(ContentValidationError, match="any, enemy, siren, or boss"):
        AttemptMechanicAction(action, EncounterExpectation.MYSTERY)


def test_compiled_programs_preserve_the_known_dynamic_campaign_decisions() -> None:
    stage_7_2 = _stage_programs("campaign_main/7-2#")
    stage_7_3 = _stage_programs("campaign_main/7-3#")
    stage_16_4 = _stage_programs("campaign_main/16-4#")

    assert {program.battle for program in stage_7_2} == {0, 5}
    assert {program.battle for program in stage_7_3} == {0, 5}
    assert {program.battle for program in stage_16_4} == {0, 1, 3, 4}

    boss_locations = {
        statement.condition.cell
        for program in stage_7_3
        for statement in _walk_statements(program.statements)
        if isinstance(statement, ProgramBranch) and isinstance(statement.condition, BossAtCondition)
    }
    assert boss_locations == {CellId(0, 0), CellId(2, 5), CellId(7, 0), CellId(7, 4)}
    assert any(
        isinstance(statement, ReturnBattleAction)
        and isinstance(statement.action, ClearSelectedEnemy)
        and statement.action.candidates == (CellId(7, 5), CellId(8, 4))
        and statement.action.excluded_genres == ("Main",)
        for program in stage_16_4
        for statement in _walk_statements(program.statements)
    )


def test_20230525_programs_keep_typed_preset_and_fixed_target_routes() -> None:
    statements = tuple(
        statement
        for program in _stage_programs("event_20230525_cn/")
        for statement in _walk_statements(program.statements)
    )

    assert any(isinstance(statement, AttemptPresetRoute) for statement in statements)
    assert any(isinstance(statement, AttemptFixedTarget) for statement in statements)
    assert not _stage_named_markers("event_20230525_cn/sp#")


def test_compiled_program_markers_describe_persisted_business_facts() -> None:
    assert _stage_named_markers("campaign_main/16-4#") == frozenset({NamedProgramMarker("enemy.moved-from-f5-to-f6")})
    assert _stage_named_markers("event_20230914_cn/sp#") == frozenset({NamedProgramMarker("route.started-at-a2")})
    assert _stage_named_markers("event_20240521_cn/sp#") == frozenset({NamedProgramMarker("route.started-at-b10")})
    assert _stage_named_markers("event_20250227_cn/sp#") == frozenset({NamedProgramMarker("route.started-at-d9")})
