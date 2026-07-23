from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from module.content import battle_program as program_model
from module.content.battle_policy import BattleStep, DefaultBattle
from module.content.cell import CellId
from module.content.mechanic_rules import FleetRole, MapItemKind, PickupMapItem
from module.gameplay.battle_program import (
    BattleActionOutcome,
    BattleProgramExecution,
    BattleProgramInterpreter,
    MechanicActionOutcome,
    MechanicApplied,
)

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.gameplay.battle_program import BattleProgramPort


CELL_A = CellId(0, 0)


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
    battle_outcomes: list[BattleActionOutcome] = field(default_factory=list)
    mechanic_outcomes: list[MechanicActionOutcome] = field(default_factory=list)

    def _record(self, operation: str) -> None:
        self.trace.append(operation)
        self.calls.append(operation)

    def execute_battle(
        self,
        action: BattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        del action, cancellation
        self._record("execute_battle")
        return self.battle_outcomes.pop(0)

    def execute_mechanic(
        self,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        del action, cancellation
        self._record("execute_mechanic")
        return self.mechanic_outcomes.pop(0)


def _execute(
    statements: tuple[program_model.ProgramStatement, ...],
    *,
    port: StubBattleProgramPort | None = None,
    markers: tuple[program_model.ProgramMarker, ...] = (),
    cancellation: RecordingCancellation | None = None,
) -> BattleProgramExecution:
    resolved_port = port or StubBattleProgramPort()
    resolved_cancellation = cancellation or RecordingCancellation(resolved_port.trace)
    return BattleProgramInterpreter().execute(
        program_model.BattleProgram(
            0,
            frozenset({program_model.BattleProgramMode.NORMAL}),
            statements,
        ),
        cast("BattleProgramPort", resolved_port),
        (),
        resolved_cancellation,
        persisted_program_markers=markers,
    )


def test_attempt_battle_continues_after_no_target_until_a_battle_settles() -> None:
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


def test_persisted_program_marker_selects_the_next_execution_branch() -> None:
    marker = program_model.NamedProgramMarker("route.started-at-a2")
    first = _execute(
        (
            program_model.SetProgramMarker(marker),
            program_model.ReturnProgramContinue(),
        )
    )

    second = _execute(
        (
            program_model.ProgramBranch(
                program_model.ProgramMarkerCondition(marker),
                (program_model.DelegateBattle(program_model.BattleProgramDelegation.STAGE_POLICY),),
                (program_model.ReturnProgramNoTarget(),),
            ),
        ),
        markers=tuple(first.markers),
    )

    assert first.markers == frozenset({marker})
    assert isinstance(second.result, program_model.ProgramDelegated)
    assert second.result.target is program_model.BattleProgramDelegation.STAGE_POLICY


def test_picked_map_item_marker_prevents_duplicate_external_work() -> None:
    action = PickupMapItem(0, MapItemKind.FLARE, CELL_A, FleetRole.FLEET_BOSS)
    program = (
        program_model.PerformMechanicAction(action),
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


def test_program_fallthrough_is_a_deterministic_no_target() -> None:
    execution = _execute((program_model.SetProgramFlag(program_model.ProgramFlag.MOVABLE_ENEMY, value=True),))

    assert isinstance(execution.result, program_model.ProgramNoTarget)
    assert execution.true_flags == frozenset({program_model.ProgramFlag.MOVABLE_ENEMY})


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
