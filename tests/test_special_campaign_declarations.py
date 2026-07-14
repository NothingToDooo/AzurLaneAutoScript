from typing import TYPE_CHECKING

import pytest

from module.content.battle_program import (
    AllProgramConditions,
    AnyProgramCondition,
    BattleProgramDelegation,
    BattleProgramMode,
    DelegateBattle,
    MechanicActionBranch,
    NotProgramCondition,
    ProgramBranch,
    ProgramCondition,
    ProgramMarkerCondition,
    ProgramStatement,
    SetProgramMarker,
    VisitedFixedTarget,
)
from module.content.cell import CellId
from module.content.mechanic_rules import (
    CandidateSortKey,
    EncounterExpectation,
    FleetRole,
    MoveFleet,
    MoveFleetToBestCandidate,
)
from module.content.models import StageRef
from module.content.stage_loader import load_default_stage

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from module.content.stage_definition import CampaignStageDefinition


ALL_MODES = frozenset(BattleProgramMode)
CLEAR_ONLY = frozenset({BattleProgramMode.CLEAR_ALL})
NORMAL_AND_CLEAR = frozenset({BattleProgramMode.NORMAL, BattleProgramMode.CLEAR_ALL})
G3 = CellId(6, 2)
H2 = CellId(7, 1)
B6 = CellId(1, 5)
C7 = CellId(2, 6)
B8 = CellId(1, 7)


def _load(pack_id: str, stage_id: str) -> CampaignStageDefinition:
    return load_default_stage(StageRef(pack_id, stage_id))


def _walk(statements: Iterable[ProgramStatement]) -> Iterator[ProgramStatement]:
    for statement in statements:
        yield statement
        if isinstance(statement, ProgramBranch):
            yield from _walk((*statement.when_true, *statement.when_false))
        elif isinstance(statement, MechanicActionBranch):
            yield from _walk((*statement.when_applied, *statement.when_not_applied))


def _condition_markers(condition: ProgramCondition) -> frozenset[VisitedFixedTarget]:
    if isinstance(condition, ProgramMarkerCondition) and isinstance(
        condition.marker,
        VisitedFixedTarget,
    ):
        return frozenset({condition.marker})
    if isinstance(condition, NotProgramCondition):
        return _condition_markers(condition.condition)
    if isinstance(condition, AllProgramConditions | AnyProgramCondition):
        return frozenset(marker for nested in condition.conditions for marker in _condition_markers(nested))
    return frozenset()


@pytest.mark.parametrize(
    ("stage_id", "expected_modes"),
    [
        ("15-1", {0: NORMAL_AND_CLEAR}),
        ("15-2", {0: NORMAL_AND_CLEAR}),
        ("15-3", {0: NORMAL_AND_CLEAR, 3: CLEAR_ONLY}),
        (
            "15-4",
            {
                0: NORMAL_AND_CLEAR,
                1: CLEAR_ONLY,
                3: NORMAL_AND_CLEAR,
                4: frozenset({BattleProgramMode.NORMAL}),
                6: CLEAR_ONLY,
            },
        ),
    ],
)
def test_chapter_15_program_distribution_and_activation_modes(
    stage_id: str,
    expected_modes: dict[int, frozenset[BattleProgramMode]],
) -> None:
    definition = _load("campaign_main", stage_id)

    assert {
        battle: program.activation_modes for battle, program in definition.battle_programs.items()
    } == expected_modes


@pytest.mark.parametrize("stage_id", ["a1", "c1"])
def test_20240521_fixed_target_visits_are_session_markers(stage_id: str) -> None:
    definition = _load("event_20240521_cn", stage_id)

    assert set(definition.battle_programs) == set(definition.map.battles)
    assert definition.battle_programs[0].activation_modes == ALL_MODES
    expected_markers = (VisitedFixedTarget(G3), VisitedFixedTarget(H2))
    for battle in definition.map.battles - {0}:
        program = definition.battle_programs[battle]
        statements = tuple(_walk(program.statements))
        set_markers = tuple(statement.marker for statement in statements if isinstance(statement, SetProgramMarker))
        guarded_markers = frozenset(
            marker
            for statement in statements
            if isinstance(statement, ProgramBranch)
            for marker in _condition_markers(statement.condition)
        )

        assert program.activation_modes == CLEAR_ONLY
        assert set_markers == expected_markers
        assert guarded_markers == frozenset(expected_markers)


@pytest.mark.parametrize("stage_id", ["b3", "d3"])
def test_20250520_every_battle_delegates_to_the_active_default_mode(stage_id: str) -> None:
    definition = _load("event_20250520_cn", stage_id)

    assert set(definition.battle_programs) == set(definition.map.battles)
    for battle in definition.map.battles:
        program = definition.battle_programs[battle]
        terminal = program.statements[-1]

        assert program.activation_modes == ALL_MODES
        assert isinstance(terminal, DelegateBattle)
        assert terminal.target is BattleProgramDelegation.DEFAULT_MODE


@pytest.mark.parametrize(("stage_id", "boss_battle"), [("b2", 5), ("d2", 6)])
def test_20240815_boss_approach_is_typed_mode_specific_content(
    stage_id: str,
    boss_battle: int,
) -> None:
    definition = _load("event_20240815_cn", stage_id)

    assert set(definition.boss_approaches) == {boss_battle}
    approach = definition.boss_approaches[boss_battle]
    assert approach.activation_modes == frozenset({BattleProgramMode.CLEAR_ALL, BattleProgramMode.POOR_MAP_DATA})
    assert approach.actions == (
        MoveFleetToBestCandidate(
            boss_battle,
            (B6, C7),
            FleetRole.FLEET_BOSS,
            (CandidateSortKey.WEIGHT, CandidateSortKey.COST),
            EncounterExpectation.ANY,
        ),
        MoveFleet(
            boss_battle,
            B8,
            FleetRole.FLEET_BOSS,
            EncounterExpectation.ANY,
        ),
    )


def test_20211125_t4_fortress_keeps_enemies_without_block_cells() -> None:
    definition = _load("event_20211125_cn", "t4")
    structures = definition.mechanics.map_structures

    assert frozenset(structures.fortress_enemy_cells) == frozenset(
        {
            CellId(2, 1),
            CellId(2, 5),
            CellId(8, 1),
            CellId(8, 5),
        }
    )
    assert structures.fortress_block_cells == ()
