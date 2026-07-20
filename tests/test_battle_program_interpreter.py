from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from module.content import battle_program as program_model
from module.content.battle_policy import BattleStep, BossStrategy, ClearBoss, ClearBossRoadblock, DefaultBattle
from module.content.cell import CellId
from module.content.mechanic_rules import (
    CandidateSortKey,
    ClearAllMystery,
    EncounterExpectation,
    FleetRole,
    MapItemKind,
    MoveFleet,
    MoveFleetToBestCandidate,
    PickupMapItem,
)
from module.gameplay.battle_program import (
    BattleActionOutcome,
    BattleProgramExecution,
    BattleProgramInterpreter,
    MechanicActionOutcome,
    MechanicApplied,
    MechanicFailed,
    MechanicNotApplied,
    MechanicSettled,
)
from module.gameplay.campaign_battle_program import default_mode_battle_program

if TYPE_CHECKING:
    from module.application import CancellationSource

CELL_A = CellId(0, 0)
CELL_B = CellId(1, 0)


class RequestedCancellation(RuntimeError):  # ruff:ignore[error-suffix-on-exception-name] - 测试取消传播的控制流信号。
    pass


@dataclass(slots=True)
class RecordingCancellation:
    trace: list[str]
    cancel_on_check: int | None = None
    checks: int = 0

    def raise_if_requested(self) -> None:
        self.checks += 1
        self.trace.append("check")
        if self.cancel_on_check == self.checks:
            raise RequestedCancellation


@dataclass(slots=True)
class StubBattleProgramPort:
    trace: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    arguments: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    metrics: dict[program_model.ProgramMetric, object] = field(default_factory=dict)
    cell_properties: dict[tuple[CellId, program_model.CellProperty], object] = field(default_factory=dict)
    booleans: dict[str, object] = field(default_factory=dict)
    battle_outcomes: list[object] = field(default_factory=list)
    mechanic_outcomes: list[object] = field(default_factory=list)

    def _record(self, operation: str, *arguments: object) -> None:
        self.trace.append(operation)
        self.calls.append(operation)
        self.arguments.append((operation, arguments))

    def _boolean(self, operation: str, *arguments: object) -> bool:
        self._record(operation, *arguments)
        return cast("bool", self.booleans.get(operation, True))

    def _mechanic(self, operation: str, *arguments: object) -> MechanicActionOutcome:
        self._record(operation, *arguments)
        return cast("MechanicActionOutcome", self.mechanic_outcomes.pop(0))

    def read_metric(
        self,
        metric: program_model.ProgramMetric,
        cancellation: CancellationSource,
    ) -> int:
        self._record("read_metric", metric, cancellation)
        return cast("int", self.metrics[metric])

    def read_cell_property(
        self,
        cell: CellId,
        cell_property: program_model.CellProperty,
        cancellation: CancellationSource,
    ) -> program_model.CellPropertyValue:
        self._record("read_cell_property", cell, cell_property, cancellation)
        return cast("program_model.CellPropertyValue", self.cell_properties[(cell, cell_property)])

    def is_fleet_at(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        return self._boolean("is_fleet_at", cell, fleet, cancellation)

    def has_map_presence(
        self,
        presence: program_model.MapPresence,
        cancellation: CancellationSource,
    ) -> bool:
        return self._boolean("has_map_presence", presence, cancellation)

    def is_boss_at(self, cell: CellId, cancellation: CancellationSource) -> bool:
        return self._boolean("is_boss_at", cell, cancellation)

    def is_boss_accessible(
        self,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        return self._boolean("is_boss_accessible", fleet, cancellation)

    def is_cell_accessible_for_fleet(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        return self._boolean("is_cell_accessible_for_fleet", cell, fleet, cancellation)

    def has_candidate_enemy(
        self,
        candidates: tuple[CellId, ...],
        excluded_genres: tuple[str, ...],
        cancellation: CancellationSource,
    ) -> bool:
        return self._boolean(
            "has_candidate_enemy",
            candidates,
            excluded_genres,
            cancellation,
        )

    def execute_battle(
        self,
        action: BattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        self._record("execute_battle", action, cancellation)
        return cast("BattleActionOutcome", self.battle_outcomes.pop(0))

    def execute_mechanic(
        self,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        return self._mechanic("execute_mechanic", action, cancellation)

    def mark_all_siren_candidates(self, cancellation: CancellationSource) -> None:
        self._record("mark_all_siren_candidates", cancellation)

    def set_map_weights(
        self,
        rows: tuple[tuple[int, ...], ...],
        cancellation: CancellationSource,
    ) -> None:
        self._record("set_map_weights", rows, cancellation)


def _execute(  # ruff:ignore[too-many-arguments] - 测试 helper 显式暴露解释器的独立输入轴。
    statements: tuple[program_model.ProgramStatement, ...],
    *,
    port: StubBattleProgramPort | None = None,
    flags: tuple[program_model.ProgramFlag, ...] = (),
    markers: tuple[program_model.ProgramMarker, ...] = (),
    interpreter: BattleProgramInterpreter | None = None,
    cancellation: RecordingCancellation | None = None,
) -> BattleProgramExecution:
    resolved_port = port or StubBattleProgramPort()
    resolved_cancellation = cancellation or RecordingCancellation(resolved_port.trace)
    return (interpreter or BattleProgramInterpreter()).execute(
        program_model.BattleProgram(
            0,
            frozenset({program_model.BattleProgramMode.NORMAL}),
            statements,
        ),
        resolved_port,
        flags,
        resolved_cancellation,
        persisted_program_markers=markers,
    )


def _mechanic_action() -> ClearAllMystery:
    return ClearAllMystery(0)


def test_attempt_battle_continues_after_no_target_and_return_battle_is_terminal() -> None:
    settled = program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY)
    port = StubBattleProgramPort(
        battle_outcomes=[program_model.ProgramNoTarget(), settled],
    )

    execution = _execute(
        (
            program_model.AttemptBattleAction(DefaultBattle()),
            program_model.ReturnBattleAction(DefaultBattle()),
        ),
        port=port,
    )

    assert execution.result == settled
    assert port.calls == ["execute_battle", "execute_battle"]


def test_return_battle_preserves_no_target_and_failure() -> None:
    no_target = _execute(
        (program_model.ReturnBattleAction(DefaultBattle()),),
        port=StubBattleProgramPort(battle_outcomes=[program_model.ProgramNoTarget()]),
    )
    failed = program_model.ProgramFailed("battle unavailable")
    failure = _execute(
        (program_model.ReturnBattleAction(DefaultBattle()),),
        port=StubBattleProgramPort(battle_outcomes=[failed]),
    )

    assert isinstance(no_target.result, program_model.ProgramNoTarget)
    assert failure.result == failed


@pytest.mark.parametrize(
    ("outcome", "expected_type"),
    [
        (MechanicApplied(), program_model.ProgramContinue),
        (MechanicSettled(program_model.ProgramBattleTarget.SIREN), program_model.ProgramBattleSettled),
        (MechanicFailed("mechanic failed"), program_model.ProgramFailed),
    ],
)
def test_attempt_mechanic_maps_terminal_outcomes(
    outcome: MechanicActionOutcome,
    expected_type: type[object],
) -> None:
    execution = _execute(
        (
            program_model.AttemptMechanicAction(
                _mechanic_action(),
                EncounterExpectation.SIREN,
            ),
        ),
        port=StubBattleProgramPort(mechanic_outcomes=[outcome]),
    )

    assert isinstance(execution.result, expected_type)


def test_attempt_mechanic_not_applied_continues_and_target_mismatch_fails() -> None:
    continued = _execute(
        (
            program_model.AttemptMechanicAction(_mechanic_action(), EncounterExpectation.ENEMY),
            program_model.ReturnProgramContinue(),
        ),
        port=StubBattleProgramPort(mechanic_outcomes=[MechanicNotApplied()]),
    )
    mismatch = _execute(
        (program_model.AttemptMechanicAction(_mechanic_action(), EncounterExpectation.BOSS),),
        port=StubBattleProgramPort(mechanic_outcomes=[MechanicSettled(program_model.ProgramBattleTarget.ENEMY)]),
    )

    assert isinstance(continued.result, program_model.ProgramContinue)
    assert isinstance(mismatch.result, program_model.ProgramFailed)
    assert "expected boss" in mismatch.result.evidence


def test_perform_mechanic_ignores_non_terminal_outcomes() -> None:
    port = StubBattleProgramPort(
        mechanic_outcomes=[MechanicApplied(), MechanicNotApplied()],
    )

    execution = _execute(
        (
            program_model.PerformMechanicAction(_mechanic_action()),
            program_model.PerformMechanicAction(_mechanic_action()),
            program_model.ReturnProgramContinue(),
        ),
        port=port,
    )

    assert isinstance(execution.result, program_model.ProgramContinue)
    assert port.calls == ["execute_mechanic", "execute_mechanic"]


def test_boss_approach_moves_execute_in_order_before_brute_boss_actions() -> None:
    best_move = MoveFleetToBestCandidate(
        0,
        (CELL_A, CELL_B),
        FleetRole.FLEET_BOSS,
        (CandidateSortKey.WEIGHT, CandidateSortKey.COST),
    )
    staging_move = MoveFleet(0, CELL_B, FleetRole.FLEET_BOSS)
    approach = program_model.BossApproachPlan(
        0,
        frozenset({program_model.BattleProgramMode.CLEAR_ALL}),
        (best_move, staging_move),
    )
    program = default_mode_battle_program(
        program_model.BattleProgramMode.CLEAR_ALL,
        0,
        approach,
    )
    assert program is not None
    dispatch = cast("program_model.ProgramBranch", program.statements[-1])
    port = StubBattleProgramPort(
        mechanic_outcomes=[MechanicApplied(), MechanicApplied()],
        battle_outcomes=[
            program_model.ProgramNoTarget(),
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.BOSS),
        ],
    )

    execution = _execute(dispatch.when_false, port=port)

    assert execution.result == program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.BOSS)
    assert port.calls == [
        "execute_mechanic",
        "execute_mechanic",
        "execute_battle",
        "execute_battle",
    ]
    assert [arguments[0] for _, arguments in port.arguments] == [
        best_move,
        staging_move,
        ClearBossRoadblock(BossStrategy.BRUTE_FORCE),
        ClearBoss(BossStrategy.BRUTE_FORCE),
    ]

    remaining_target_port = StubBattleProgramPort(
        mechanic_outcomes=[MechanicNotApplied(), MechanicNotApplied()],
        battle_outcomes=[
            program_model.ProgramNoTarget(),
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
        ],
    )
    remaining_target = _execute((dispatch,), port=remaining_target_port)

    assert remaining_target.result == program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY)
    assert best_move not in [arguments[0] for _, arguments in remaining_target_port.arguments]
    assert staging_move not in [arguments[0] for _, arguments in remaining_target_port.arguments]


def test_perform_mechanic_requires_an_expectation_before_settling() -> None:
    without_contract = _execute(
        (program_model.PerformMechanicAction(_mechanic_action()),),
        port=StubBattleProgramPort(mechanic_outcomes=[MechanicSettled(program_model.ProgramBattleTarget.ENEMY)]),
    )
    with_contract = _execute(
        (
            program_model.PerformMechanicAction(
                _mechanic_action(),
                EncounterExpectation.ENEMY,
            ),
        ),
        port=StubBattleProgramPort(mechanic_outcomes=[MechanicSettled(program_model.ProgramBattleTarget.ENEMY)]),
    )

    assert isinstance(without_contract.result, program_model.ProgramFailed)
    assert "without an expected_target" in without_contract.result.evidence
    assert with_contract.result == program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (MechanicApplied(), program_model.ProgramContinue()),
        (MechanicNotApplied(), program_model.ProgramNoTarget()),
        (
            MechanicSettled(program_model.ProgramBattleTarget.BOSS),
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.BOSS),
        ),
        (MechanicFailed("return failed"), program_model.ProgramFailed("return failed")),
    ],
)
def test_return_mechanic_is_always_terminal(
    outcome: MechanicActionOutcome,
    expected: program_model.CompleteBattleProgramResult,
) -> None:
    execution = _execute(
        (program_model.ReturnMechanicAction(_mechanic_action()),),
        port=StubBattleProgramPort(mechanic_outcomes=[outcome]),
    )

    assert execution.result == expected


@pytest.mark.parametrize(
    ("outcome", "expected_flag"),
    [
        (MechanicApplied(), program_model.ProgramFlag.MAP_HAS_MOB_MOVE),
        (MechanicNotApplied(), program_model.ProgramFlag.USE_SINGLE_FLEET),
    ],
)
def test_mechanic_branch_selects_exactly_one_block(
    outcome: MechanicActionOutcome,
    expected_flag: program_model.ProgramFlag,
) -> None:
    execution = _execute(
        (
            program_model.MechanicActionBranch(
                _mechanic_action(),
                (program_model.SetProgramFlag(program_model.ProgramFlag.MAP_HAS_MOB_MOVE, value=True),),
                (program_model.SetProgramFlag(program_model.ProgramFlag.USE_SINGLE_FLEET, value=True),),
            ),
            program_model.ReturnProgramContinue(),
        ),
        port=StubBattleProgramPort(mechanic_outcomes=[outcome]),
    )

    assert execution.true_flags == frozenset({expected_flag})


def test_mechanic_branch_settlement_is_terminal_and_validates_target() -> None:
    execution = _execute(
        (
            program_model.MechanicActionBranch(
                _mechanic_action(),
                (program_model.ReturnProgramContinue(),),
                expected_target=EncounterExpectation.SIREN,
            ),
        ),
        port=StubBattleProgramPort(mechanic_outcomes=[MechanicSettled(program_model.ProgramBattleTarget.ENEMY)]),
    )

    assert isinstance(execution.result, program_model.ProgramFailed)
    assert "expected siren" in execution.result.evidence


def test_mechanic_branch_propagates_port_failure_without_running_either_block() -> None:
    execution = _execute(
        (
            program_model.MechanicActionBranch(
                _mechanic_action(),
                (program_model.SetProgramFlag(program_model.ProgramFlag.MAP_HAS_MOB_MOVE, value=True),),
                (program_model.SetProgramFlag(program_model.ProgramFlag.USE_SINGLE_FLEET, value=True),),
            ),
        ),
        port=StubBattleProgramPort(mechanic_outcomes=[MechanicFailed("movement failed")]),
    )

    assert execution.result == program_model.ProgramFailed("movement failed")
    assert execution.true_flags == frozenset()


@pytest.mark.parametrize(
    ("operator", "actual", "expected", "condition_is_true"),
    [
        (program_model.ComparisonOperator.EQUAL, 3, 3, True),
        (program_model.ComparisonOperator.NOT_EQUAL, 3, 2, True),
        (program_model.ComparisonOperator.LESS_THAN, 2, 3, True),
        (program_model.ComparisonOperator.LESS_THAN_OR_EQUAL, 3, 3, True),
        (program_model.ComparisonOperator.GREATER_THAN, 4, 3, True),
        (program_model.ComparisonOperator.GREATER_THAN_OR_EQUAL, 3, 3, True),
        (program_model.ComparisonOperator.EQUAL, 2, 3, False),
    ],
)
def test_metric_comparison_operators_are_closed(
    operator: program_model.ComparisonOperator,
    actual: int,
    expected: int,
    *,
    condition_is_true: bool,
) -> None:
    port = StubBattleProgramPort(metrics={program_model.ProgramMetric.BATTLE_COUNT: actual})
    execution = _execute(
        (
            program_model.ProgramBranch(
                program_model.MetricCondition(
                    program_model.ProgramMetric.BATTLE_COUNT,
                    operator,
                    expected,
                ),
                (program_model.ReturnProgramContinue(),),
                (program_model.ReturnProgramNoTarget(),),
            ),
        ),
        port=port,
    )

    assert isinstance(
        execution.result,
        program_model.ProgramContinue if condition_is_true else program_model.ProgramNoTarget,
    )


def test_all_condition_kinds_are_read_through_explicit_ports() -> None:
    flag = program_model.ProgramFlag.CLEAR_MODE
    cell_conditions = (
        program_model.CellPropertyCondition(
            CELL_A,
            program_model.CellProperty.ACCESSIBLE,
            program_model.ComparisonOperator.EQUAL,
            value=True,
        ),
        program_model.CellPropertyCondition(
            CELL_A,
            program_model.CellProperty.ENEMY_SCALE,
            program_model.ComparisonOperator.GREATER_THAN,
            2,
        ),
        program_model.CellPropertyCondition(
            CELL_A,
            program_model.CellProperty.ENEMY_GENRE,
            program_model.ComparisonOperator.EQUAL,
            "Main",
        ),
        program_model.CellPropertyCondition(
            CELL_A,
            program_model.CellProperty.IS_MYSTERY,
            program_model.ComparisonOperator.EQUAL,
            value=False,
        ),
    )
    conditions: tuple[program_model.ProgramCondition, ...] = (
        program_model.ProgramFlagCondition(flag),
        *cell_conditions,
        program_model.FleetAtCondition(CELL_A),
        program_model.MapPresenceCondition(program_model.MapPresence.BOSS),
        program_model.BossAtCondition(CELL_A),
        program_model.BossAccessibleCondition(),
        program_model.CellAccessibleForFleetCondition(CELL_B, FleetRole.FLEET_2),
        program_model.CandidateEnemyCondition((CELL_A, CELL_B), ("Main",)),
        program_model.AllProgramConditions(
            (
                program_model.ProgramFlagCondition(flag),
                program_model.ProgramFlagCondition(program_model.ProgramFlag.MOVABLE_ENEMY, value=False),
            )
        ),
        program_model.AnyProgramCondition(
            (
                program_model.ProgramFlagCondition(program_model.ProgramFlag.MOVABLE_ENEMY),
                program_model.ProgramFlagCondition(flag),
            )
        ),
        program_model.NotProgramCondition(program_model.ProgramFlagCondition(program_model.ProgramFlag.MOVABLE_ENEMY)),
    )
    port = StubBattleProgramPort(
        cell_properties={
            (CELL_A, program_model.CellProperty.ACCESSIBLE): True,
            (CELL_A, program_model.CellProperty.ENEMY_SCALE): 3,
            (CELL_A, program_model.CellProperty.ENEMY_GENRE): "Main",
            (CELL_A, program_model.CellProperty.IS_MYSTERY): False,
        }
    )

    execution = _execute(
        (
            *(
                program_model.ProgramBranch(
                    condition,
                    (program_model.SetProgramFlag(program_model.ProgramFlag.MAP_HAS_MOB_MOVE, value=True),),
                )
                for condition in conditions
            ),
            program_model.ReturnProgramContinue(),
        ),
        port=port,
        flags=(flag,),
    )

    assert isinstance(execution.result, program_model.ProgramContinue)
    assert program_model.ProgramFlag.MAP_HAS_MOB_MOVE in execution.true_flags
    assert port.calls == [
        "read_cell_property",
        "read_cell_property",
        "read_cell_property",
        "read_cell_property",
        "is_fleet_at",
        "has_map_presence",
        "is_boss_at",
        "is_boss_accessible",
        "is_cell_accessible_for_fleet",
        "has_candidate_enemy",
    ]


def test_conditions_reject_bool_int_coercion_and_non_integer_ordering() -> None:
    wrong_expected_type = _execute(
        (
            program_model.ProgramBranch(
                program_model.CellPropertyCondition(
                    CELL_A,
                    program_model.CellProperty.ACCESSIBLE,
                    program_model.ComparisonOperator.EQUAL,
                    1,
                ),
                (program_model.ReturnProgramContinue(),),
            ),
        ),
    )
    string_ordering = _execute(
        (
            program_model.ProgramBranch(
                program_model.CellPropertyCondition(
                    CELL_A,
                    program_model.CellProperty.ENEMY_GENRE,
                    program_model.ComparisonOperator.GREATER_THAN,
                    "Light",
                ),
                (program_model.ReturnProgramContinue(),),
            ),
        ),
        port=StubBattleProgramPort(cell_properties={(CELL_A, program_model.CellProperty.ENEMY_GENRE): "Main"}),
    )

    assert isinstance(wrong_expected_type.result, program_model.ProgramFailed)
    assert "must be bool" in wrong_expected_type.result.evidence
    assert isinstance(string_ordering.result, program_model.ProgramFailed)
    assert "ordering requires integer" in string_ordering.result.evidence


def test_conditions_reject_wrong_runtime_types_from_ports() -> None:
    metric = _execute(
        (
            program_model.ProgramBranch(
                program_model.MetricCondition(
                    program_model.ProgramMetric.BATTLE_COUNT,
                    program_model.ComparisonOperator.EQUAL,
                    1,
                ),
                (program_model.ReturnProgramContinue(),),
            ),
        ),
        port=StubBattleProgramPort(metrics={program_model.ProgramMetric.BATTLE_COUNT: True}),
    )
    boolean = _execute(
        (
            program_model.ProgramBranch(
                program_model.BossAtCondition(CELL_A),
                (program_model.ReturnProgramContinue(),),
            ),
        ),
        port=StubBattleProgramPort(booleans={"is_boss_at": 1}),
    )

    assert isinstance(metric.result, program_model.ProgramFailed)
    assert "expected int" in metric.result.evidence
    assert isinstance(boolean.result, program_model.ProgramFailed)
    assert "expected bool" in boolean.result.evidence


def test_flags_are_persisted_as_an_immutable_true_only_set() -> None:
    execution = _execute(
        (
            program_model.SetProgramFlag(program_model.ProgramFlag.CLEAR_MODE, value=False),
            program_model.SetProgramFlagFromCondition(
                program_model.ProgramFlag.MOVABLE_ENEMY,
                program_model.ProgramFlagCondition(program_model.ProgramFlag.USE_SINGLE_FLEET),
            ),
            program_model.SetProgramFlagFromCondition(
                program_model.ProgramFlag.MAP_HAS_MOB_MOVE,
                program_model.ProgramFlagCondition(program_model.ProgramFlag.USE_SINGLE_FLEET, value=False),
            ),
            program_model.ReturnProgramContinue(),
        ),
        flags=(program_model.ProgramFlag.CLEAR_MODE, program_model.ProgramFlag.MOVABLE_ENEMY),
    )

    assert execution.true_flags == frozenset({program_model.ProgramFlag.MAP_HAS_MOB_MOVE})
    assert isinstance(execution.true_flags, frozenset)


def test_typed_program_markers_drive_branches_and_round_trip_through_their_codec() -> None:
    marker = program_model.NamedProgramMarker("route.started-at-a2")

    execution = _execute(
        (
            program_model.SetProgramMarker(marker),
            program_model.ProgramBranch(
                program_model.ProgramMarkerCondition(marker),
                (program_model.DelegateBattle(program_model.BattleProgramDelegation.STAGE_POLICY),),
                (program_model.ReturnProgramNoTarget(),),
            ),
        )
    )

    assert isinstance(execution.result, program_model.ProgramDelegated)
    assert execution.result.target is program_model.BattleProgramDelegation.STAGE_POLICY
    assert execution.markers == frozenset({marker})
    assert program_model.ProgramMarker.parse(marker.value) == marker


def test_picked_map_item_fact_prevents_duplicate_io_across_program_executions() -> None:
    action = PickupMapItem(0, MapItemKind.FLARE, CELL_A, FleetRole.FLEET_BOSS)
    program = (
        program_model.PerformMechanicAction(action),
        program_model.DelegateBattle(program_model.BattleProgramDelegation.STAGE_POLICY),
    )
    first_port = StubBattleProgramPort(mechanic_outcomes=[MechanicApplied()])

    first = _execute(program, port=first_port)
    second_port = StubBattleProgramPort()
    second = _execute(program, port=second_port, markers=tuple(first.markers))

    marker = program_model.PickedMapItem(MapItemKind.FLARE, CELL_A)
    assert first.markers == frozenset({marker})
    assert isinstance(first.result, program_model.ProgramDelegated)
    assert isinstance(second.result, program_model.ProgramDelegated)
    assert second.markers == first.markers
    assert first_port.calls == ["execute_mechanic"]
    assert second_port.calls == []


def test_map_side_effect_statements_use_the_port_and_fall_through() -> None:
    port = StubBattleProgramPort()

    execution = _execute(
        (
            program_model.MarkAllSirenCandidates(),
            program_model.SetMapWeights(((1, 2), (3, 4))),
            program_model.ReturnProgramNoTarget(),
        ),
        port=port,
    )

    assert isinstance(execution.result, program_model.ProgramNoTarget)
    assert port.calls == ["mark_all_siren_candidates", "set_map_weights"]
    assert port.arguments[1][1][0] == ((1, 2), (3, 4))


@pytest.mark.parametrize(
    ("statement", "expected_type"),
    [
        (program_model.ReturnProgramContinue(), program_model.ProgramContinue),
        (program_model.ReturnProgramNoTarget(), program_model.ProgramNoTarget),
        (program_model.EndCampaign(), program_model.ProgramCampaignEnded),
        (
            program_model.DelegateBattle(program_model.BattleProgramDelegation.STAGE_POLICY),
            program_model.ProgramDelegated,
        ),
    ],
)
def test_explicit_terminal_statements(
    statement: program_model.ProgramStatement,
    expected_type: type[object],
) -> None:
    execution = _execute((statement,))

    assert isinstance(execution.result, expected_type)


def test_program_fallthrough_is_a_deterministic_no_target() -> None:
    execution = _execute((program_model.SetProgramFlag(program_model.ProgramFlag.MOVABLE_ENEMY, value=True),))

    assert isinstance(execution.result, program_model.ProgramNoTarget)
    assert execution.true_flags == frozenset({program_model.ProgramFlag.MOVABLE_ENEMY})


def test_invalid_action_outcomes_become_program_failures() -> None:
    battle = _execute(
        (program_model.ReturnBattleAction(DefaultBattle()),),
        port=StubBattleProgramPort(battle_outcomes=[object()]),
    )
    mechanic = _execute(
        (program_model.ReturnMechanicAction(_mechanic_action()),),
        port=StubBattleProgramPort(mechanic_outcomes=[object()]),
    )

    assert isinstance(battle.result, program_model.ProgramFailed)
    assert "unsupported outcome" in battle.result.evidence
    assert isinstance(mechanic.result, program_model.ProgramFailed)
    assert "unsupported outcome" in mechanic.result.evidence


def test_mechanic_outcomes_validate_their_public_contract() -> None:
    with pytest.raises(TypeError, match="ProgramBattleTarget"):
        MechanicSettled(cast("program_model.ProgramBattleTarget", "enemy"))
    with pytest.raises(ValueError, match="non-empty evidence"):
        MechanicFailed("")


def test_every_external_operation_is_preceded_by_a_cancellation_check() -> None:
    port = StubBattleProgramPort(
        metrics={program_model.ProgramMetric.BATTLE_COUNT: 1},
        battle_outcomes=[program_model.ProgramNoTarget()],
    )
    cancellation = RecordingCancellation(port.trace)

    _execute(
        (
            program_model.ProgramBranch(
                program_model.MetricCondition(
                    program_model.ProgramMetric.BATTLE_COUNT,
                    program_model.ComparisonOperator.EQUAL,
                    1,
                ),
                (program_model.MarkAllSirenCandidates(),),
            ),
            program_model.ReturnBattleAction(DefaultBattle()),
        ),
        port=port,
        cancellation=cancellation,
    )

    for index, event in enumerate(port.trace):
        if event != "check":
            assert port.trace[index - 1] == "check"


def test_cancellation_stops_before_the_first_port_call() -> None:
    port = StubBattleProgramPort(
        battle_outcomes=[program_model.ProgramNoTarget()],
    )
    cancellation = RecordingCancellation(port.trace, cancel_on_check=2)

    with pytest.raises(RequestedCancellation):
        _execute(
            (program_model.ReturnBattleAction(DefaultBattle()),),
            port=port,
            cancellation=cancellation,
        )

    assert port.calls == []


def test_branch_and_condition_depth_limits_fail_closed() -> None:
    nested_branch = program_model.ProgramBranch(
        program_model.ProgramFlagCondition(program_model.ProgramFlag.CLEAR_MODE),
        (program_model.ReturnProgramContinue(),),
    )
    branch = _execute(
        (nested_branch,),
        flags=(program_model.ProgramFlag.CLEAR_MODE,),
        interpreter=BattleProgramInterpreter(max_depth=0),
    )
    condition = _execute(
        (
            program_model.ProgramBranch(
                program_model.NotProgramCondition(
                    program_model.ProgramFlagCondition(program_model.ProgramFlag.CLEAR_MODE)
                ),
                (program_model.ReturnProgramContinue(),),
            ),
        ),
        interpreter=BattleProgramInterpreter(max_depth=0),
    )

    assert isinstance(branch.result, program_model.ProgramFailed)
    assert "branch depth" in branch.result.evidence
    assert isinstance(condition.result, program_model.ProgramFailed)
    assert "condition depth" in condition.result.evidence


def test_statement_budget_preserves_flags_before_failing() -> None:
    execution = _execute(
        (
            program_model.SetProgramFlag(program_model.ProgramFlag.MOVABLE_ENEMY, value=True),
            program_model.ReturnProgramContinue(),
        ),
        interpreter=BattleProgramInterpreter(statement_budget=1),
    )

    assert isinstance(execution.result, program_model.ProgramFailed)
    assert "statement_budget=1" in execution.result.evidence
    assert execution.true_flags == frozenset({program_model.ProgramFlag.MOVABLE_ENEMY})
