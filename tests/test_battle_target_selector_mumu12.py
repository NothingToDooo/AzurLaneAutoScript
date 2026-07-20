from typing import TYPE_CHECKING, TypedDict, Unpack

import pytest

from module.adapters.battle_program_read_mumu12 import (
    ProgramBattlefieldView,
    ProgramBattleSelectionContext,
    ProgramCellFacts,
)
from module.adapters.battle_program_selection_mumu12 import BattleTargetSelector
from module.content import battle_program as program_model
from module.content.battle_policy import (
    ClearAnyEnemy,
    ClearEnemy,
    ClearFilteredEnemy,
    ClearPriorityEnemy,
    ClearSiren,
    EnemySortKey,
    parse_enemy_filter,
)
from module.content.cell import CellId
from module.content.mechanic_rules import EncounterExpectation
from module.gameplay.campaign import EnemyPriorityMode

if TYPE_CHECKING:
    from module.adapters.battle_program_mumu12_contracts import FleetIndex

A1 = CellId(0, 0)
B1 = CellId(1, 0)
C1 = CellId(2, 0)


class _FactOverrides(TypedDict, total=False):
    weight: float
    cost_1: float
    cost_2: float
    enemy: bool
    siren: bool
    fortress: bool
    boss: bool
    scale: int
    genre: str


def _facts(
    cell: CellId,
    **overrides: Unpack[_FactOverrides],
) -> ProgramCellFacts:
    return ProgramCellFacts(
        cell=cell,
        weight=overrides.get("weight", 1),
        cost_1=overrides.get("cost_1", 1),
        cost_2=overrides.get("cost_2", 1),
        is_enemy=overrides.get("enemy", False),
        is_siren=overrides.get("siren", False),
        is_boss=overrides.get("boss", False),
        is_fortress=overrides.get("fortress", False),
        is_mystery=False,
        may_ammo=False,
        enemy_scale=overrides.get("scale", 1),
        enemy_genre=overrides.get("genre", "LightInvertedOrthant"),
    )


def _context(
    *,
    fleet: FleetIndex = 1,
    priority: EnemyPriorityMode = EnemyPriorityMode.DEFAULT,
    clear_all: bool = False,
    movable_normal_enemy: bool = False,
    enemy_filter: str = "1L > 1M > 1E",
) -> ProgramBattleSelectionContext:
    return ProgramBattleSelectionContext(
        executor_fleet=fleet,
        enemy_priority=priority,
        clear_all=clear_all,
        movable_normal_enemy=movable_normal_enemy,
        default_enemy_filter=parse_enemy_filter(enemy_filter),
    )


@pytest.mark.parametrize(
    ("fleet", "expected"),
    [
        (1, A1),
        (2, B1),
    ],
)
def test_default_order_uses_weight_then_executor_fleet_cost(fleet: FleetIndex, expected: CellId) -> None:
    battlefield = ProgramBattlefieldView(
        (
            _facts(A1, enemy=True, cost_1=1, cost_2=9),
            _facts(B1, enemy=True, cost_1=9, cost_2=1),
        )
    )

    selected = BattleTargetSelector().select(ClearEnemy(), battlefield, _context(fleet=fleet))

    assert selected is not None
    assert selected.cell == expected
    assert selected.fleet == fleet


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ((EnemySortKey.FLEET_1_COST,), A1),
        ((EnemySortKey.FLEET_2_COST,), B1),
    ],
)
def test_explicit_fleet_cost_sort_does_not_change_the_executor(
    sort: tuple[EnemySortKey, ...],
    expected: CellId,
) -> None:
    battlefield = ProgramBattlefieldView(
        (
            _facts(A1, enemy=True, cost_1=1, cost_2=9),
            _facts(B1, enemy=True, cost_1=2, cost_2=1),
        )
    )

    selected = BattleTargetSelector().select(ClearEnemy(sort=sort), battlefield, _context(fleet=1))

    assert selected is not None
    assert selected.cell == expected
    assert selected.fleet == 1


def test_enemy_sort_strings_are_normalized_to_typed_keys_at_the_domain_boundary() -> None:
    action = ClearAnyEnemy(sort=("cost_2", "enemy_scale"))

    assert action.sort == (EnemySortKey.FLEET_2_COST, EnemySortKey.ENEMY_SCALE)


def test_priority_enemy_uses_declared_groups_before_default_order() -> None:
    battlefield = ProgramBattlefieldView(
        (
            _facts(A1, enemy=True, scale=1, weight=0),
            _facts(B1, enemy=True, scale=3, genre="LightInvertedOrthant", weight=0),
            _facts(C1, enemy=True, scale=2, genre="LightInvertedOrthant", weight=9),
        )
    )
    selector = BattleTargetSelector()

    selected = selector.select(ClearPriorityEnemy(), battlefield, _context())
    selected_with_scale_1 = selector.select(ClearPriorityEnemy(include_scale_1=True), battlefield, _context())

    assert selected is not None
    assert selected.cell == C1
    assert selected_with_scale_1 is not None
    assert selected_with_scale_1.cell == A1


@pytest.mark.parametrize(
    ("priority", "clear_all", "strongest", "expected"),
    [
        (EnemyPriorityMode.DEFAULT, False, False, A1),
        (EnemyPriorityMode.LARGE_ENEMY_FIRST, False, False, B1),
        (EnemyPriorityMode.SMALL_ENEMY_FIRST, False, False, A1),
        (EnemyPriorityMode.DEFAULT, True, False, B1),
        (EnemyPriorityMode.SMALL_ENEMY_FIRST, False, True, B1),
    ],
)
def test_enemy_strength_policy_is_explicit(
    priority: EnemyPriorityMode,
    *,
    clear_all: bool,
    strongest: bool,
    expected: CellId,
) -> None:
    battlefield = ProgramBattlefieldView(
        (
            _facts(A1, enemy=True, scale=1, weight=0),
            _facts(B1, enemy=True, scale=3, weight=9),
        )
    )

    selected = BattleTargetSelector().select(
        ClearEnemy(strongest=strongest),
        battlefield,
        _context(priority=priority, clear_all=clear_all),
    )

    assert selected is not None
    assert selected.cell == expected


def test_filtered_enemy_applies_filter_order_before_preserve() -> None:
    battlefield = ProgramBattlefieldView(
        (
            _facts(A1, enemy=True, genre="LightInvertedOrthant", weight=1),
            _facts(B1, enemy=True, genre="LightInvertedOrthant", weight=2),
            _facts(C1, enemy=True, genre="MainInvertedOrthant", weight=0),
        )
    )
    selector = BattleTargetSelector()

    selected = selector.select(ClearFilteredEnemy(preserve=1), battlefield, _context(enemy_filter="1L > 1M"))
    overridden = selector.select(
        ClearFilteredEnemy(preserve=0, enemy_filter="1M"),
        battlefield,
        _context(enemy_filter="1L"),
    )

    assert selected is not None
    assert selected.cell == B1
    assert overridden is not None
    assert overridden.cell == C1


def test_large_enemy_priority_replaces_filter_and_resets_preserve() -> None:
    battlefield = ProgramBattlefieldView(
        (
            _facts(A1, enemy=True, scale=1),
            _facts(B1, enemy=True, scale=3),
        )
    )

    selected = BattleTargetSelector().select(
        ClearFilteredEnemy(preserve=99, enemy_filter="1L"),
        battlefield,
        _context(priority=EnemyPriorityMode.LARGE_ENEMY_FIRST),
    )

    assert selected is not None
    assert selected.cell == B1


def test_movable_normal_enemy_uses_explicit_fleet_2_cost_and_reports_siren() -> None:
    battlefield = ProgramBattlefieldView(
        (
            _facts(A1, enemy=True, cost_2=9),
            _facts(B1, siren=True, cost_2=1, genre="Siren_Compiler"),
        )
    )

    selected = BattleTargetSelector().select(
        ClearFilteredEnemy(preserve=99, enemy_filter="1L"),
        battlefield,
        _context(fleet=1, movable_normal_enemy=True),
    )

    assert selected is not None
    assert selected.cell == B1
    assert selected.fleet == 1
    assert selected.encounter is EncounterExpectation.SIREN
    assert selected.program_target is program_model.ProgramBattleTarget.SIREN


@pytest.mark.parametrize(
    ("action", "facts", "encounter", "target"),
    [
        (
            ClearAnyEnemy(),
            _facts(A1, enemy=True),
            EncounterExpectation.ENEMY,
            program_model.ProgramBattleTarget.ENEMY,
        ),
        (
            ClearAnyEnemy(),
            _facts(A1, siren=True, genre="Siren_Compiler"),
            EncounterExpectation.SIREN,
            program_model.ProgramBattleTarget.SIREN,
        ),
        (
            ClearSiren(),
            _facts(A1, fortress=True, genre="Fortress"),
            EncounterExpectation.FORTRESS,
            program_model.ProgramBattleTarget.SIREN,
        ),
        (
            ClearAnyEnemy(),
            _facts(A1, fortress=True, genre="Fortress"),
            EncounterExpectation.FORTRESS,
            program_model.ProgramBattleTarget.SIREN,
        ),
    ],
)
def test_selected_target_carries_exact_encounter_and_program_target(
    action: ClearAnyEnemy | ClearSiren,
    facts: ProgramCellFacts,
    encounter: EncounterExpectation,
    target: program_model.ProgramBattleTarget,
) -> None:
    selected = BattleTargetSelector().select(action, ProgramBattlefieldView((facts,)), _context())

    assert selected is not None
    assert selected.encounter is encounter
    assert selected.program_target is target


def test_siren_genre_matching_preserves_case_insensitive_content_input() -> None:
    battlefield = ProgramBattlefieldView((_facts(A1, siren=True, genre="Siren_Compiler"),))

    selected = BattleTargetSelector().select(
        ClearSiren(genres=("siren_Compiler",)),
        battlefield,
        _context(),
    )

    assert selected is not None
    assert selected.cell == A1
