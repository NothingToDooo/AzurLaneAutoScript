from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from module.content import battle_program as program_model
from module.content.battle_policy import BattleStep, ClearFilteredEnemy, DefaultBattle
from module.content.cell import CellId
from module.content.mechanic_rules import (
    EncounterExpectation,
    FleetClearSelectedTarget,
    FleetClearTarget,
    FleetRole,
    MoveFleet,
)
from module.content.models import StageRef
from module.content.stage_loader import load_default_stage
from module.gameplay.battle_program import (
    BattleActionOutcome,
    BattleProgramExecution,
    BattleProgramInterpreter,
    BattleProgramPort,
    MechanicActionOutcome,
    MechanicApplied,
    MechanicNotApplied,
    MechanicSettled,
)

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.content.stage_definition import CampaignStageDefinition


E5 = CellId(4, 4)
F5 = CellId(5, 4)
G5 = CellId(6, 4)
D5 = CellId(3, 4)
E6 = CellId(4, 5)
F6 = CellId(5, 5)
D6 = CellId(3, 5)
G6 = CellId(6, 5)
E7 = CellId(4, 6)
F7 = CellId(5, 6)
G7 = CellId(6, 6)
C7 = CellId(2, 6)
H7 = CellId(7, 6)
D8 = CellId(3, 7)
E8 = CellId(4, 7)
F8 = CellId(5, 7)
G8 = CellId(6, 7)
STARTED_AT_E8 = program_model.NamedProgramMarker("route.started-at-e8")
STARTED_AT_F8 = program_model.NamedProgramMarker("route.started-at-f8")
SIREN_CANDIDATES = (H7, G6, D6, C7)
ACTIVE_MODES = frozenset(
    {
        program_model.BattleProgramMode.NORMAL,
        program_model.BattleProgramMode.CLEAR_ALL,
    }
)


@dataclass(slots=True)
class RecordingCancellation:
    def raise_if_requested(self) -> None:
        pass


@dataclass(slots=True)
class RecordingPort:
    fleet_1_location: CellId | None = None
    mechanic_outcomes: list[MechanicActionOutcome] = field(default_factory=list)
    battle_outcomes: list[BattleActionOutcome] = field(default_factory=list)
    mechanic_actions: list[program_model.ProgramMechanicAction] = field(default_factory=list)
    battle_actions: list[BattleStep] = field(default_factory=list)

    def is_fleet_at(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        return fleet is FleetRole.FLEET_1 and cell == self.fleet_1_location

    def execute_mechanic(
        self,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        self.mechanic_actions.append(action)
        return self.mechanic_outcomes.pop(0)

    def execute_battle(
        self,
        action: BattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        cancellation.raise_if_requested()
        self.battle_actions.append(action)
        return self.battle_outcomes.pop(0)


def _definition() -> CampaignStageDefinition:
    return load_default_stage(StageRef("event_20230525_cn", "sp"))


def _execute(
    battle: int,
    port: RecordingPort,
    *,
    flags: frozenset[program_model.ProgramFlag] = frozenset(),
    markers: frozenset[program_model.ProgramMarker] = frozenset(),
) -> BattleProgramExecution:
    return BattleProgramInterpreter().execute(
        _definition().battle_programs[battle],
        cast("BattleProgramPort", port),
        flags,
        cast("CancellationSource", RecordingCancellation()),
        persisted_program_markers=markers,
    )


def _move(battle: int, destination: CellId, fleet: FleetRole = FleetRole.FLEET_1) -> MoveFleet:
    return MoveFleet(battle, destination, fleet, EncounterExpectation.ANY)


def _clear(battle: int, target: CellId) -> FleetClearTarget:
    return FleetClearTarget(battle, target, FleetRole.FLEET_1, EncounterExpectation.ANY)


ROUTES = {
    STARTED_AT_E8: {
        0: (_move(0, G8), _move(0, E8), _clear(0, G8)),
        1: (_move(1, F6, FleetRole.FLEET_2), _clear(1, G8)),
        2: (_clear(2, F8),),
        3: (_clear(3, F7),),
        4: (_move(4, F5), _clear(4, G5)),
        5: (_move(5, E5), _clear(5, D5)),
        6: (_move(6, F5), _clear(6, G5)),
    },
    STARTED_AT_F8: {
        0: (_move(0, D8), _move(0, F8), _clear(0, D8)),
        1: (_move(1, E6, FleetRole.FLEET_2), _clear(1, D8)),
        2: (_move(2, E7), _clear(2, F6)),
        3: (_clear(3, G7),),
        4: (_clear(4, G5),),
        5: (_move(5, E5), _clear(5, D5)),
        6: (_move(6, F5), _clear(6, D5)),
    },
}


def test_sp_declares_all_route_battles_for_normal_and_clear_all_modes() -> None:
    programs = _definition().battle_programs

    assert set(programs) == set(range(7))
    assert all(program.activation_modes == ACTIVE_MODES for program in programs.values())


@pytest.mark.parametrize(
    ("start", "expected_marker"),
    [(E8, STARTED_AT_E8), (F8, STARTED_AT_F8)],
)
def test_sp_identifies_the_start_once_before_executing_a_route(
    start: CellId,
    expected_marker: program_model.NamedProgramMarker,
) -> None:
    port = RecordingPort(fleet_1_location=start)

    execution = _execute(0, port)

    assert isinstance(execution.result, program_model.ProgramContinue)
    assert execution.markers == frozenset({expected_marker})
    assert port.mechanic_actions == []
    assert port.battle_actions == []


def test_sp_rejects_an_unknown_start_instead_of_guessing_a_route() -> None:
    execution = _execute(0, RecordingPort(fleet_1_location=CellId(0, 0)))

    assert isinstance(execution.result, program_model.ProgramNoTarget)
    assert execution.markers == frozenset()


@pytest.mark.parametrize("battle", range(7))
def test_sp_rejects_ambiguous_route_markers(battle: int) -> None:
    execution = _execute(
        battle,
        RecordingPort(),
        markers=frozenset({STARTED_AT_E8, STARTED_AT_F8}),
    )

    assert isinstance(execution.result, program_model.ProgramNoTarget)
    assert execution.markers == frozenset({STARTED_AT_E8, STARTED_AT_F8})


@pytest.mark.parametrize("battle", range(1, 7))
def test_sp_requires_the_persisted_route_after_the_first_battle(battle: int) -> None:
    execution = _execute(battle, RecordingPort())

    assert isinstance(execution.result, program_model.ProgramNoTarget)
    assert execution.markers == frozenset()


@pytest.mark.parametrize(("marker", "routes"), ROUTES.items())
def test_sp_executes_the_absolute_route_selected_at_spawn(
    marker: program_model.NamedProgramMarker,
    routes: dict[int, tuple[program_model.ProgramMechanicAction, ...]],
) -> None:
    for battle, expected_actions in routes.items():
        port = RecordingPort(
            mechanic_outcomes=[
                *[MechanicApplied() for _ in expected_actions[:-1]],
                MechanicSettled(program_model.ProgramBattleTarget.ENEMY),
            ]
        )

        execution = _execute(battle, port, markers=frozenset({marker}))

        assert isinstance(execution.result, program_model.ProgramBattleSettled)
        assert tuple(port.mechanic_actions) == expected_actions
        assert port.battle_actions == []


@pytest.mark.parametrize("battle", range(7))
def test_sp_clear_mode_falls_back_after_the_ordered_siren_targets(
    battle: int,
) -> None:
    port = RecordingPort(
        mechanic_outcomes=[MechanicNotApplied()],
        battle_outcomes=[
            program_model.ProgramNoTarget(),
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
        ],
    )

    execution = _execute(
        battle,
        port,
        flags=frozenset({program_model.ProgramFlag.CLEAR_MODE}),
    )

    assert isinstance(execution.result, program_model.ProgramBattleSettled)
    assert port.mechanic_actions == [
        FleetClearSelectedTarget(
            battle,
            SIREN_CANDIDATES,
            FleetRole.FLEET_1,
            EncounterExpectation.SIREN,
        )
    ]
    assert port.battle_actions == [ClearFilteredEnemy(0), DefaultBattle()]
