from typing import TYPE_CHECKING, assert_never

from module.content import battle_program as program_model
from module.content.battle_policy import TargetExpectation
from module.content.mechanic_rules import EncounterExpectation

if TYPE_CHECKING:
    from module.adapters.battle_program_mumu12_contracts import FleetIndex
    from module.adapters.battle_program_read_mumu12 import ProgramCellFacts


def expectation_for_facts(facts: ProgramCellFacts) -> EncounterExpectation:
    if facts.is_boss:
        return EncounterExpectation.BOSS
    if facts.is_siren:
        return EncounterExpectation.SIREN
    if facts.is_enemy:
        return EncounterExpectation.ENEMY
    return EncounterExpectation.ANY


def target_for_facts(facts: ProgramCellFacts) -> program_model.ProgramBattleTarget:
    if facts.is_boss:
        return program_model.ProgramBattleTarget.BOSS
    if facts.is_siren:
        return program_model.ProgramBattleTarget.SIREN
    return program_model.ProgramBattleTarget.ENEMY


def target_from_expectation(expected: TargetExpectation) -> program_model.ProgramBattleTarget:
    if expected is TargetExpectation.ENEMY:
        return program_model.ProgramBattleTarget.ENEMY
    if expected is TargetExpectation.SIREN:
        return program_model.ProgramBattleTarget.SIREN
    assert_never(expected)


def encounter_from_expectation(expected: TargetExpectation) -> EncounterExpectation:
    if expected is TargetExpectation.ENEMY:
        return EncounterExpectation.ENEMY
    if expected is TargetExpectation.SIREN:
        return EncounterExpectation.SIREN
    assert_never(expected)


def target_from_encounter(
    expected: EncounterExpectation,
    facts: ProgramCellFacts,
) -> program_model.ProgramBattleTarget:
    if expected is EncounterExpectation.ENEMY:
        return program_model.ProgramBattleTarget.ENEMY
    if expected is EncounterExpectation.SIREN:
        return program_model.ProgramBattleTarget.SIREN
    if expected is EncounterExpectation.BOSS:
        return program_model.ProgramBattleTarget.BOSS
    return target_for_facts(facts)


def matches_encounter(facts: ProgramCellFacts, expected: EncounterExpectation) -> bool:
    match expected:
        case EncounterExpectation.ANY:
            matched = facts.is_enemy or facts.is_siren or facts.is_fortress or facts.is_boss
        case EncounterExpectation.ENEMY:
            matched = facts.is_enemy and not facts.is_boss
        case EncounterExpectation.SIREN:
            matched = facts.is_siren
        case EncounterExpectation.FORTRESS:
            matched = facts.is_fortress
        case EncounterExpectation.BOSS:
            matched = facts.is_boss
        case EncounterExpectation.MYSTERY:
            matched = facts.is_mystery
        case EncounterExpectation.STORY:
            matched = False
        case _ as unreachable:
            assert_never(unreachable)
    return matched


def is_clearable_candidate(
    facts: ProgramCellFacts,
    fleet_index: FleetIndex,
    excluded_genres: tuple[str, ...],
    expected: TargetExpectation,
) -> bool:
    if expected is TargetExpectation.SIREN:
        present = facts.is_siren
    elif expected is TargetExpectation.ENEMY:
        present = facts.is_enemy and not facts.is_boss
    else:
        assert_never(expected)
    return bool(present and facts.accessible_for(fleet_index) and facts.enemy_genre not in excluded_genres)
