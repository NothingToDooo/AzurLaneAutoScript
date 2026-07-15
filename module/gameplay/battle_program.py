from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol, assert_never

from module.content import battle_program as program_model
from module.content.battle_policy import ClearBossRoadblock
from module.content.campaign_session import (
    BattleTarget,
    CampaignSession,
    CampaignSessionState,
    CampaignSessionStatus,
)
from module.content.mechanic_rules import EncounterExpectation, FleetRole, PickupMapItem

if TYPE_CHECKING:
    from collections.abc import Collection

    from module.application import CancellationSource
    from module.content.battle_policy import BattleStep
    from module.content.cell import CellId


@dataclass(frozen=True, slots=True)
class MechanicApplied:
    pass


@dataclass(frozen=True, slots=True)
class MechanicNotApplied:
    pass


@dataclass(frozen=True, slots=True)
class MechanicSettled:
    target: program_model.ProgramBattleTarget
    advances_wave: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.target, program_model.ProgramBattleTarget):
            message = "settled mechanic outcome requires a ProgramBattleTarget"
            raise TypeError(message)
        if type(self.advances_wave) is not bool:
            message = "settled mechanic outcome advances_wave must be a bool"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MechanicFailed:
    evidence: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            message = "failed mechanic outcome requires non-empty evidence"
            raise ValueError(message)


type MechanicActionOutcome = MechanicApplied | MechanicNotApplied | MechanicSettled | MechanicFailed
type BattleActionOutcome = (
    program_model.ProgramBattleSettled | program_model.ProgramNoTarget | program_model.ProgramFailed
)


class BattleProgramPort(Protocol):
    def read_metric(
        self,
        metric: program_model.ProgramMetric,
        cancellation: CancellationSource,
    ) -> int: ...

    def read_cell_property(
        self,
        cell: CellId,
        cell_property: program_model.CellProperty,
        cancellation: CancellationSource,
    ) -> program_model.CellPropertyValue: ...

    def is_fleet_at(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool: ...

    def has_map_presence(
        self,
        presence: program_model.MapPresence,
        cancellation: CancellationSource,
    ) -> bool: ...

    def is_boss_at(self, cell: CellId, cancellation: CancellationSource) -> bool: ...

    def is_boss_accessible(
        self,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool: ...

    def is_cell_accessible_for_fleet(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool: ...

    def has_candidate_enemy(
        self,
        candidates: tuple[CellId, ...],
        excluded_genres: tuple[str, ...],
        cancellation: CancellationSource,
    ) -> bool: ...

    def execute_battle(
        self,
        action: BattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome: ...

    def execute_mechanic(
        self,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome: ...

    def execute_preset_route(
        self,
        action: program_model.ExecutePresetRoute,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome: ...

    def execute_fixed_target(
        self,
        action: program_model.ExecuteFixedTarget,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome: ...

    def mark_all_siren_candidates(self, cancellation: CancellationSource) -> None: ...

    def set_map_weights(
        self,
        rows: tuple[tuple[int, ...], ...],
        cancellation: CancellationSource,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class BattleProgramExecution:
    result: program_model.CompleteBattleProgramResult
    true_flags: frozenset[program_model.ProgramFlag]
    markers: frozenset[program_model.ProgramMarker] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(
            self.result,
            (
                program_model.ProgramBattleSettled,
                program_model.ProgramNoTarget,
                program_model.ProgramContinue,
                program_model.ProgramFailed,
                program_model.ProgramCampaignEnded,
                program_model.ProgramDelegated,
            ),
        ):
            message = "battle program execution requires a complete program result"
            raise TypeError(message)
        flags = frozenset(self.true_flags)
        if any(not isinstance(flag, program_model.ProgramFlag) for flag in flags):
            message = "battle program execution flags must contain ProgramFlag values"
            raise TypeError(message)
        markers = frozenset(self.markers)
        if any(not isinstance(marker, program_model.ProgramMarker) for marker in markers):
            message = "battle program execution markers must contain ProgramMarker values"
            raise TypeError(message)
        object.__setattr__(self, "true_flags", flags)
        object.__setattr__(self, "markers", markers)


class BattleProgramReducer:
    """把解释器的已确认事实收敛为唯一可持久化的 Campaign 安全点。"""

    @staticmethod
    def reduce(
        session: CampaignSession,
        state: CampaignSessionState,
        execution: BattleProgramExecution,
    ) -> CampaignSessionState:
        if not isinstance(session, CampaignSession):
            message = "battle program reducer requires a CampaignSession"
            raise TypeError(message)
        session.validate_state(state)
        if not isinstance(execution, BattleProgramExecution):
            message = "battle program reducer requires a BattleProgramExecution"
            raise TypeError(message)
        if state.status is not CampaignSessionStatus.ACTIVE or state.pending is not None:
            message = "battle program reducer requires an active pending-free state"
            raise ValueError(message)
        safe_state = replace(
            state,
            next_intent_index=0,
            program_state_initialized=True,
            program_flags=execution.true_flags,
            program_markers=execution.markers,
        )
        result = execution.result
        if isinstance(result, program_model.ProgramBattleSettled):
            return BattleProgramReducer._settled(session, safe_state, result)
        if isinstance(result, program_model.ProgramNoTarget):
            return replace(
                safe_state,
                status=CampaignSessionStatus.BLOCKED,
                reason=f"battle {state.battle_index} program found no eligible target",
            )
        if isinstance(result, program_model.ProgramFailed):
            return replace(
                safe_state,
                status=CampaignSessionStatus.FAILED,
                reason=result.evidence.strip(),
            )
        if isinstance(
            result,
            program_model.ProgramContinue | program_model.ProgramCampaignEnded | program_model.ProgramDelegated,
        ):
            return safe_state
        assert_never(result)

    @staticmethod
    def _settled(
        session: CampaignSession,
        state: CampaignSessionState,
        result: program_model.ProgramBattleSettled,
    ) -> CampaignSessionState:
        target = BattleProgramReducer._target(result.target)
        return session.settle_confirmed_battle(
            state,
            target,
            advances_wave=result.advances_wave,
        )

    @staticmethod
    def _target(target: program_model.ProgramBattleTarget) -> BattleTarget:
        if target is program_model.ProgramBattleTarget.ENEMY:
            return BattleTarget.ENEMY
        if target is program_model.ProgramBattleTarget.SIREN:
            return BattleTarget.SIREN
        if target is program_model.ProgramBattleTarget.BOSS:
            return BattleTarget.BOSS
        assert_never(target)


@dataclass(slots=True)
class _ExecutionState:
    true_flags: set[program_model.ProgramFlag]
    markers: set[program_model.ProgramMarker]
    remaining_statements: int


class BattleProgramInterpreter:
    """解释封闭的 BattleProgram AST，并把所有外部读写限制在一个显式端口。"""

    __slots__ = ("_max_depth", "_statement_budget")

    def __init__(self, *, max_depth: int = 32, statement_budget: int = 1024) -> None:
        if type(max_depth) is not int or max_depth < 0:
            message = "max_depth must be a non-negative integer"
            raise ValueError(message)
        if type(statement_budget) is not int or statement_budget <= 0:
            message = "statement_budget must be a positive integer"
            raise ValueError(message)
        self._max_depth = max_depth
        self._statement_budget = statement_budget

    def execute(
        self,
        program: program_model.BattleProgram,
        port: BattleProgramPort,
        persisted_program_flags: Collection[program_model.ProgramFlag],
        cancellation: CancellationSource,
        persisted_program_markers: Collection[program_model.ProgramMarker] = (),
    ) -> BattleProgramExecution:
        if not isinstance(program, program_model.BattleProgram):
            message = "program must be a BattleProgram"
            raise TypeError(message)
        flags = set(persisted_program_flags)
        if any(not isinstance(flag, program_model.ProgramFlag) for flag in flags):
            message = "persisted_program_flags must contain ProgramFlag values"
            raise TypeError(message)
        markers = set(persisted_program_markers)
        if any(not isinstance(marker, program_model.ProgramMarker) for marker in markers):
            message = "persisted_program_markers must contain ProgramMarker values"
            raise TypeError(message)

        cancellation.raise_if_requested()
        state = _ExecutionState(flags, markers, self._statement_budget)
        result = self._execute_block(
            program.statements,
            port,
            cancellation,
            state,
            branch_depth=0,
        )
        if result is None:
            result = program_model.ProgramNoTarget()
        return BattleProgramExecution(
            result=result,
            true_flags=frozenset(state.true_flags),
            markers=frozenset(state.markers),
        )

    def _execute_block(
        self,
        statements: tuple[program_model.ProgramStatement, ...],
        port: BattleProgramPort,
        cancellation: CancellationSource,
        state: _ExecutionState,
        *,
        branch_depth: int,
    ) -> program_model.CompleteBattleProgramResult | None:
        if not statements:
            return None
        if branch_depth > self._max_depth:
            return program_model.ProgramFailed(f"battle program branch depth exceeded max_depth={self._max_depth}")

        for statement in statements:
            if state.remaining_statements == 0:
                return program_model.ProgramFailed(f"battle program exceeded statement_budget={self._statement_budget}")
            state.remaining_statements -= 1
            result = self._execute_statement(
                statement,
                port,
                cancellation,
                state,
                branch_depth=branch_depth,
            )
            if result is not None:
                return result
        return None

    def _execute_statement(
        self,
        statement: program_model.ProgramStatement,
        port: BattleProgramPort,
        cancellation: CancellationSource,
        state: _ExecutionState,
        *,
        branch_depth: int,
    ) -> program_model.CompleteBattleProgramResult | None:
        if isinstance(statement, program_model.AttemptBattleAction | program_model.ReturnBattleAction):
            return self._execute_battle_statement(statement, port, cancellation)
        if isinstance(
            statement,
            program_model.AttemptMechanicAction
            | program_model.PerformMechanicAction
            | program_model.ReturnMechanicAction,
        ):
            return self._execute_mechanic_statement(statement, port, cancellation, state)
        if isinstance(statement, program_model.MechanicActionBranch | program_model.ProgramBranch):
            return self._execute_branch_statement(
                statement,
                port,
                cancellation,
                state,
                branch_depth=branch_depth,
            )
        if isinstance(statement, program_model.AttemptPresetRoute | program_model.AttemptFixedTarget):
            return self._execute_route_statement(statement, port, cancellation)
        if isinstance(
            statement,
            program_model.SetProgramFlag
            | program_model.SetProgramFlagFromCondition
            | program_model.SetProgramMarker
            | program_model.SetProgramMarkerFromCondition
            | program_model.MarkAllSirenCandidates
            | program_model.SetMapWeights,
        ):
            return self._execute_state_statement(statement, port, cancellation, state)
        if isinstance(
            statement,
            program_model.ReturnProgramContinue
            | program_model.ReturnProgramNoTarget
            | program_model.EndCampaign
            | program_model.DelegateBattle,
        ):
            return self._execute_return_statement(statement)
        assert_never(statement)

    def _execute_battle_statement(
        self,
        statement: program_model.AttemptBattleAction | program_model.ReturnBattleAction,
        port: BattleProgramPort,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome | None:
        outcome = self._execute_battle(port, statement.action, cancellation)
        if isinstance(outcome, program_model.ProgramBattleSettled) and isinstance(
            statement.action,
            ClearBossRoadblock,
        ):
            outcome = replace(outcome, advances_wave=False)
        if isinstance(statement, program_model.AttemptBattleAction) and isinstance(
            outcome,
            program_model.ProgramNoTarget,
        ):
            return None
        return outcome

    def _execute_mechanic_statement(
        self,
        statement: (
            program_model.AttemptMechanicAction
            | program_model.PerformMechanicAction
            | program_model.ReturnMechanicAction
        ),
        port: BattleProgramPort,
        cancellation: CancellationSource,
        state: _ExecutionState,
    ) -> program_model.CompleteBattleProgramResult | None:
        outcome = self._execute_mechanic_with_state(
            port,
            statement.action,
            cancellation,
            state,
        )
        if isinstance(statement, program_model.AttemptMechanicAction):
            return self._attempt_mechanic_result(outcome, statement.expected_target)
        if isinstance(statement, program_model.PerformMechanicAction):
            return self._perform_mechanic_result(outcome, statement.expected_target)
        return self._return_mechanic_result(outcome, statement.expected_target)

    @staticmethod
    def _attempt_mechanic_result(
        outcome: MechanicActionOutcome,
        expected_target: EncounterExpectation,
    ) -> program_model.CompleteBattleProgramResult | None:
        if isinstance(outcome, MechanicNotApplied):
            return None
        if isinstance(outcome, MechanicApplied):
            return program_model.ProgramContinue()
        return BattleProgramInterpreter._mechanic_terminal(outcome, expected_target, "attempt mechanic")

    @staticmethod
    def _perform_mechanic_result(
        outcome: MechanicActionOutcome,
        expected_target: EncounterExpectation | None,
    ) -> program_model.CompleteBattleProgramResult | None:
        if isinstance(outcome, MechanicApplied | MechanicNotApplied):
            return None
        if isinstance(outcome, MechanicSettled) and expected_target is None:
            return program_model.ProgramFailed("perform mechanic settled a battle without an expected_target")
        return BattleProgramInterpreter._mechanic_terminal(outcome, expected_target, "perform mechanic")

    @staticmethod
    def _return_mechanic_result(
        outcome: MechanicActionOutcome,
        expected_target: EncounterExpectation | None,
    ) -> program_model.CompleteBattleProgramResult:
        if isinstance(outcome, MechanicApplied):
            return program_model.ProgramContinue()
        if isinstance(outcome, MechanicNotApplied):
            return program_model.ProgramNoTarget()
        return BattleProgramInterpreter._mechanic_terminal(outcome, expected_target, "return mechanic")

    def _execute_branch_statement(
        self,
        statement: program_model.MechanicActionBranch | program_model.ProgramBranch,
        port: BattleProgramPort,
        cancellation: CancellationSource,
        state: _ExecutionState,
        *,
        branch_depth: int,
    ) -> program_model.CompleteBattleProgramResult | None:
        if isinstance(statement, program_model.MechanicActionBranch):
            outcome = self._execute_mechanic_with_state(
                port,
                statement.action,
                cancellation,
                state,
            )
            if isinstance(outcome, MechanicSettled | MechanicFailed):
                return self._mechanic_terminal(outcome, statement.expected_target, "mechanic branch")
            nested = statement.when_applied if isinstance(outcome, MechanicApplied) else statement.when_not_applied
        else:
            condition = self._evaluate_condition(
                statement.condition,
                port,
                cancellation,
                state,
                condition_depth=0,
            )
            if isinstance(condition, program_model.ProgramFailed):
                return condition
            nested = statement.when_true if condition else statement.when_false
        return self._execute_block(
            nested,
            port,
            cancellation,
            state,
            branch_depth=branch_depth + 1,
        )

    def _execute_route_statement(
        self,
        statement: program_model.AttemptPresetRoute | program_model.AttemptFixedTarget,
        port: BattleProgramPort,
        cancellation: CancellationSource,
    ) -> program_model.CompleteBattleProgramResult | None:
        if isinstance(statement, program_model.AttemptPresetRoute):
            outcome = self._execute_preset_route(port, statement.action, cancellation)
            operation = "preset route"
        else:
            outcome = self._execute_fixed_target(port, statement.action, cancellation)
            operation = "fixed target"
        return self._attempt_outcome(outcome, statement.expected_target, operation)

    def _execute_state_statement(
        self,
        statement: (
            program_model.SetProgramFlag
            | program_model.SetProgramFlagFromCondition
            | program_model.SetProgramMarker
            | program_model.SetProgramMarkerFromCondition
            | program_model.MarkAllSirenCandidates
            | program_model.SetMapWeights
        ),
        port: BattleProgramPort,
        cancellation: CancellationSource,
        state: _ExecutionState,
    ) -> program_model.ProgramFailed | None:
        if isinstance(statement, program_model.SetProgramFlag):
            self._set_flag(state, statement.flag, value=statement.value)
        elif isinstance(
            statement,
            program_model.SetProgramFlagFromCondition | program_model.SetProgramMarkerFromCondition,
        ):
            condition = self._evaluate_condition(
                statement.condition,
                port,
                cancellation,
                state,
                condition_depth=0,
            )
            if isinstance(condition, program_model.ProgramFailed):
                return condition
            if isinstance(statement, program_model.SetProgramFlagFromCondition):
                self._set_flag(state, statement.flag, value=condition)
            else:
                self._set_marker(state, statement.marker, value=condition)
        elif isinstance(statement, program_model.SetProgramMarker):
            self._set_marker(state, statement.marker, value=statement.value)
        elif isinstance(statement, program_model.MarkAllSirenCandidates):
            cancellation.raise_if_requested()
            port.mark_all_siren_candidates(cancellation)
        elif isinstance(statement, program_model.SetMapWeights):
            cancellation.raise_if_requested()
            port.set_map_weights(statement.rows, cancellation)
        else:
            assert_never(statement)
        return None

    @staticmethod
    def _set_marker(
        state: _ExecutionState,
        marker: program_model.ProgramMarker,
        *,
        value: bool,
    ) -> None:
        if value:
            state.markers.add(marker)
        else:
            state.markers.discard(marker)

    @staticmethod
    def _execute_return_statement(
        statement: (
            program_model.ReturnProgramContinue
            | program_model.ReturnProgramNoTarget
            | program_model.EndCampaign
            | program_model.DelegateBattle
        ),
    ) -> program_model.CompleteBattleProgramResult:
        if isinstance(statement, program_model.ReturnProgramContinue):
            return program_model.ProgramContinue()
        if isinstance(statement, program_model.ReturnProgramNoTarget):
            return program_model.ProgramNoTarget()
        if isinstance(statement, program_model.EndCampaign):
            return program_model.ProgramCampaignEnded()
        if isinstance(statement, program_model.DelegateBattle):
            return program_model.ProgramDelegated(statement.target)
        assert_never(statement)

    def _evaluate_condition(
        self,
        condition: program_model.ProgramCondition,
        port: BattleProgramPort,
        cancellation: CancellationSource,
        state: _ExecutionState,
        *,
        condition_depth: int,
    ) -> bool | program_model.ProgramFailed:
        if condition_depth > self._max_depth:
            return program_model.ProgramFailed(f"battle program condition depth exceeded max_depth={self._max_depth}")
        if isinstance(condition, program_model.ProgramFlagCondition):
            return (condition.flag in state.true_flags) is condition.value
        if isinstance(condition, program_model.ProgramMarkerCondition):
            return (condition.marker in state.markers) is condition.value
        if isinstance(condition, program_model.MetricCondition | program_model.CellPropertyCondition):
            return self._evaluate_comparison_condition(condition, port, cancellation)
        if isinstance(
            condition,
            program_model.FleetAtCondition
            | program_model.MapPresenceCondition
            | program_model.BossAtCondition
            | program_model.BossAccessibleCondition
            | program_model.CellAccessibleForFleetCondition
            | program_model.CandidateEnemyCondition,
        ):
            return self._evaluate_boolean_condition(condition, port, cancellation)
        if isinstance(
            condition,
            program_model.AllProgramConditions | program_model.AnyProgramCondition | program_model.NotProgramCondition,
        ):
            return self._evaluate_composite_condition(
                condition,
                port,
                cancellation,
                state,
                condition_depth=condition_depth,
            )
        assert_never(condition)

    def _evaluate_comparison_condition(
        self,
        condition: program_model.MetricCondition | program_model.CellPropertyCondition,
        port: BattleProgramPort,
        cancellation: CancellationSource,
    ) -> bool | program_model.ProgramFailed:
        if isinstance(condition, program_model.MetricCondition):
            cancellation.raise_if_requested()
            actual = port.read_metric(condition.metric, cancellation)
            if type(actual) is not int:
                return self._invalid_port_value("read_metric", actual, "int")
            return self._compare(
                actual=actual,
                operator=condition.operator,
                expected=condition.value,
                location="metric condition",
            )
        expected_type = self._cell_property_type(condition.property)
        if type(condition.value) is not expected_type:
            return program_model.ProgramFailed(
                f"{condition.property.value} condition value must be {expected_type.__name__}"
            )
        cancellation.raise_if_requested()
        actual = port.read_cell_property(condition.cell, condition.property, cancellation)
        if type(actual) is not expected_type:
            return self._invalid_port_value("read_cell_property", actual, expected_type.__name__)
        return self._compare(
            actual=actual,
            operator=condition.operator,
            expected=condition.value,
            location="cell property condition",
        )

    def _evaluate_boolean_condition(
        self,
        condition: (
            program_model.FleetAtCondition
            | program_model.MapPresenceCondition
            | program_model.BossAtCondition
            | program_model.BossAccessibleCondition
            | program_model.CellAccessibleForFleetCondition
            | program_model.CandidateEnemyCondition
        ),
        port: BattleProgramPort,
        cancellation: CancellationSource,
    ) -> bool | program_model.ProgramFailed:
        cancellation.raise_if_requested()
        if isinstance(condition, program_model.FleetAtCondition):
            value = port.is_fleet_at(condition.cell, condition.fleet, cancellation)
            operation = "is_fleet_at"
        elif isinstance(condition, program_model.MapPresenceCondition):
            value = port.has_map_presence(condition.presence, cancellation)
            operation = "has_map_presence"
        elif isinstance(condition, program_model.BossAtCondition):
            value = port.is_boss_at(condition.cell, cancellation)
            operation = "is_boss_at"
        elif isinstance(condition, program_model.BossAccessibleCondition):
            value = port.is_boss_accessible(condition.fleet, cancellation)
            operation = "is_boss_accessible"
        elif isinstance(condition, program_model.CellAccessibleForFleetCondition):
            value = port.is_cell_accessible_for_fleet(condition.cell, condition.fleet, cancellation)
            operation = "is_cell_accessible_for_fleet"
        elif isinstance(condition, program_model.CandidateEnemyCondition):
            value = port.has_candidate_enemy(
                condition.candidates,
                condition.excluded_genres,
                cancellation,
            )
            operation = "has_candidate_enemy"
        else:
            assert_never(condition)
        return self._strict_boolean(value, operation)

    def _evaluate_composite_condition(
        self,
        condition: (
            program_model.AllProgramConditions | program_model.AnyProgramCondition | program_model.NotProgramCondition
        ),
        port: BattleProgramPort,
        cancellation: CancellationSource,
        state: _ExecutionState,
        *,
        condition_depth: int,
    ) -> bool | program_model.ProgramFailed:
        if isinstance(condition, program_model.NotProgramCondition):
            result = self._evaluate_condition(
                condition.condition,
                port,
                cancellation,
                state,
                condition_depth=condition_depth + 1,
            )
            return result if isinstance(result, program_model.ProgramFailed) else not result
        for nested in condition.conditions:
            result = self._evaluate_condition(
                nested,
                port,
                cancellation,
                state,
                condition_depth=condition_depth + 1,
            )
            if isinstance(result, program_model.ProgramFailed):
                return result
            if isinstance(condition, program_model.AllProgramConditions) and not result:
                return False
            if isinstance(condition, program_model.AnyProgramCondition) and result:
                return True
        return isinstance(condition, program_model.AllProgramConditions)

    @staticmethod
    def _cell_property_type(cell_property: program_model.CellProperty) -> type[bool | int | str]:
        if cell_property in (program_model.CellProperty.ACCESSIBLE, program_model.CellProperty.IS_MYSTERY):
            return bool
        if cell_property is program_model.CellProperty.ENEMY_SCALE:
            return int
        if cell_property is program_model.CellProperty.ENEMY_GENRE:
            return str
        assert_never(cell_property)

    @staticmethod
    def _compare(
        *,
        actual: bool | int | str,
        operator: program_model.ComparisonOperator,
        expected: bool | int | str,
        location: str,
    ) -> bool | program_model.ProgramFailed:
        if type(actual) is not type(expected):
            return program_model.ProgramFailed(
                f"{location} compares different types: {type(actual).__name__} and {type(expected).__name__}"
            )
        if operator is program_model.ComparisonOperator.EQUAL:
            result = actual == expected
        elif operator is program_model.ComparisonOperator.NOT_EQUAL:
            result = actual != expected
        elif type(actual) is not int or type(expected) is not int:
            return program_model.ProgramFailed(f"{location} ordering requires integer operands")
        elif operator is program_model.ComparisonOperator.LESS_THAN:
            result = actual < expected
        elif operator is program_model.ComparisonOperator.LESS_THAN_OR_EQUAL:
            result = actual <= expected
        elif operator is program_model.ComparisonOperator.GREATER_THAN:
            result = actual > expected
        elif operator is program_model.ComparisonOperator.GREATER_THAN_OR_EQUAL:
            result = actual >= expected
        else:
            assert_never(operator)
        return result

    @staticmethod
    def _strict_boolean(value: object, operation: str) -> bool | program_model.ProgramFailed:
        if type(value) is bool:
            return value
        return BattleProgramInterpreter._invalid_port_value(operation, value, "bool")

    @staticmethod
    def _invalid_port_value(
        operation: str,
        value: object,
        expected_type: str,
    ) -> program_model.ProgramFailed:
        return program_model.ProgramFailed(f"{operation} returned {type(value).__name__}, expected {expected_type}")

    @staticmethod
    def _set_flag(
        state: _ExecutionState,
        flag: program_model.ProgramFlag,
        *,
        value: bool,
    ) -> None:
        if value:
            state.true_flags.add(flag)
        else:
            state.true_flags.discard(flag)

    @staticmethod
    def _mechanic_terminal(
        outcome: MechanicSettled | MechanicFailed,
        expected_target: EncounterExpectation | None,
        operation: str,
    ) -> program_model.ProgramBattleSettled | program_model.ProgramFailed:
        if isinstance(outcome, MechanicFailed):
            return program_model.ProgramFailed(outcome.evidence)
        if expected_target is not None and not BattleProgramInterpreter._target_matches(
            outcome.target,
            expected_target,
        ):
            return program_model.ProgramFailed(
                f"{operation} settled {outcome.target.value}, expected {expected_target.value}"
            )
        return program_model.ProgramBattleSettled(outcome.target, outcome.advances_wave)

    @staticmethod
    def _target_matches(
        actual: program_model.ProgramBattleTarget,
        expected: EncounterExpectation,
    ) -> bool:
        if expected is EncounterExpectation.ANY:
            return True
        if expected is EncounterExpectation.ENEMY:
            return actual is program_model.ProgramBattleTarget.ENEMY
        if expected is EncounterExpectation.SIREN:
            return actual is program_model.ProgramBattleTarget.SIREN
        if expected is EncounterExpectation.BOSS:
            return actual is program_model.ProgramBattleTarget.BOSS
        return False

    @staticmethod
    def _attempt_outcome(
        outcome: MechanicActionOutcome,
        expected_target: EncounterExpectation,
        operation: str,
    ) -> program_model.CompleteBattleProgramResult | None:
        if isinstance(outcome, MechanicNotApplied):
            return None
        if isinstance(outcome, MechanicApplied):
            return program_model.ProgramContinue()
        return BattleProgramInterpreter._mechanic_terminal(outcome, expected_target, operation)

    @staticmethod
    def _execute_battle(
        port: BattleProgramPort,
        action: BattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        cancellation.raise_if_requested()
        outcome = port.execute_battle(action, cancellation)
        if isinstance(
            outcome,
            (
                program_model.ProgramBattleSettled,
                program_model.ProgramNoTarget,
                program_model.ProgramFailed,
            ),
        ):
            return outcome
        return program_model.ProgramFailed(f"execute_battle returned unsupported outcome: {type(outcome).__name__}")

    @staticmethod
    def _execute_mechanic(
        port: BattleProgramPort,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        outcome = port.execute_mechanic(action, cancellation)
        return BattleProgramInterpreter._validated_mechanic_outcome(outcome, "execute_mechanic")

    def _execute_mechanic_with_state(
        self,
        port: BattleProgramPort,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
        state: _ExecutionState,
    ) -> MechanicActionOutcome:
        marker = self._map_item_marker(action) if isinstance(action, PickupMapItem) else None
        if marker is not None and marker in state.markers:
            return MechanicNotApplied()
        outcome = self._execute_mechanic(port, action, cancellation)
        if marker is not None and isinstance(outcome, MechanicApplied):
            state.markers.add(marker)
        return outcome

    @staticmethod
    def _map_item_marker(action: PickupMapItem) -> program_model.ProgramMarker:
        return program_model.PickedMapItem(action.kind, action.cell)

    @staticmethod
    def _execute_preset_route(
        port: BattleProgramPort,
        action: program_model.ExecutePresetRoute,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        outcome = port.execute_preset_route(action, cancellation)
        return BattleProgramInterpreter._validated_mechanic_outcome(outcome, "execute_preset_route")

    @staticmethod
    def _execute_fixed_target(
        port: BattleProgramPort,
        action: program_model.ExecuteFixedTarget,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        outcome = port.execute_fixed_target(action, cancellation)
        return BattleProgramInterpreter._validated_mechanic_outcome(outcome, "execute_fixed_target")

    @staticmethod
    def _validated_mechanic_outcome(
        outcome: object,
        operation: str,
    ) -> MechanicActionOutcome:
        if isinstance(outcome, MechanicApplied | MechanicNotApplied | MechanicSettled | MechanicFailed):
            return outcome
        return MechanicFailed(f"{operation} returned unsupported outcome: {type(outcome).__name__}")
