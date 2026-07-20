from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from module.adapters.battle_program_battle_action_mumu12 import (
    Mumu12BattleActionDependencies,
    Mumu12BattleActionExecutor,
)
from module.adapters.battle_program_fleet_coordination_mumu12 import Mumu12FleetCoordinationDriver
from module.adapters.battle_program_fleet_mumu12 import Mumu12FleetActionDriver
from module.adapters.battle_program_map_mechanic_mumu12 import Mumu12MapMechanicDriver
from module.adapters.battle_program_map_mutation_mumu12 import Mumu12MapMutationDriver
from module.adapters.battle_program_mechanic_action_mumu12 import (
    Mumu12MechanicActionDependencies,
    Mumu12MechanicActionExecutor,
)
from module.adapters.battle_program_mumu12 import Mumu12BattleProgramPort
from module.adapters.battle_program_read_mumu12 import Mumu12BattleProgramReadModel, RuntimeProgramState
from module.adapters.battle_program_roadblock_mumu12 import Mumu12RoadblockPlanner
from module.adapters.battle_program_selection_mumu12 import BattleTargetSelector
from module.adapters.battle_program_strategy_mumu12 import Mumu12StrategyActionDriver
from module.content.battle_program import BattleProgram, BattleProgramMode
from module.content.campaign_session import CampaignSession, CampaignSessionState
from module.gameplay.battle_program import BattleProgramExecution, BattleProgramInterpreter

if TYPE_CHECKING:
    from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
    from module.application import CancellationSource


@dataclass(frozen=True, slots=True)
class Mumu12CommittedBattleProgramUnit:
    port: Mumu12BattleProgramPort
    cancellation: CancellationSource


class Mumu12BattleProgramUnitSource(Protocol):
    def battle_program_mode(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> BattleProgramMode: ...

    def commit_battle_program_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CommittedBattleProgramUnit: ...


def build_mumu12_battle_program_port(
    runtime: DeclarativeCampaignMapRuntime,
    program_state: RuntimeProgramState,
) -> Mumu12BattleProgramPort:
    reads = Mumu12BattleProgramReadModel(runtime, program_state)
    fleet_actions = Mumu12FleetActionDriver(runtime)
    fleet_coordination = Mumu12FleetCoordinationDriver(runtime)
    strategy_actions = Mumu12StrategyActionDriver(runtime)
    map_mutations = Mumu12MapMutationDriver(runtime)
    map_mechanics = Mumu12MapMechanicDriver(runtime)
    roadblocks = Mumu12RoadblockPlanner(runtime, reads)
    return Mumu12BattleProgramPort(
        reads=reads,
        battle_actions=Mumu12BattleActionExecutor(
            Mumu12BattleActionDependencies(
                reads=reads,
                fleet_actions=fleet_actions,
                map_mutations=map_mutations,
                roadblocks=roadblocks,
                battle_targets=BattleTargetSelector(),
            )
        ),
        mechanic_actions=Mumu12MechanicActionExecutor(
            Mumu12MechanicActionDependencies(
                reads=reads,
                fleet_actions=fleet_actions,
                fleet_coordination=fleet_coordination,
                strategy_actions=strategy_actions,
                map_mechanics=map_mechanics,
                roadblocks=roadblocks,
            )
        ),
        map_mutations=map_mutations,
    )


def read_mumu12_battle_program_mode(
    runtime: DeclarativeCampaignMapRuntime,
    program_state: RuntimeProgramState,
    cancellation: CancellationSource,
) -> BattleProgramMode:
    return Mumu12BattleProgramReadModel(runtime, program_state).mode(cancellation)


class Mumu12CampaignBattleProgramExecutor:
    """在一个不可中断的 campaign safe unit 内解释关卡 BattleProgram。"""

    __slots__ = ("_interpreter", "_units")

    def __init__(
        self,
        units: Mumu12BattleProgramUnitSource,
        interpreter: BattleProgramInterpreter | None = None,
    ) -> None:
        self._units = units
        self._interpreter = BattleProgramInterpreter() if interpreter is None else interpreter

    def execute(
        self,
        program: BattleProgram,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleProgramExecution:
        if not isinstance(program, BattleProgram):
            message = "MuMu12 campaign program executor requires a BattleProgram"
            raise TypeError(message)
        if not isinstance(session, CampaignSession):
            message = "MuMu12 campaign program executor requires a CampaignSession"
            raise TypeError(message)
        if not isinstance(state, CampaignSessionState):
            message = "MuMu12 campaign program executor requires CampaignSessionState"
            raise TypeError(message)
        session.validate_state(state)
        if program.battle != state.battle_index:
            message = "battle program battle does not match the active session battle"
            raise ValueError(message)

        unit = self._units.commit_battle_program_unit(session, cancellation)
        port = unit.port
        persisted_flags = (
            state.program_flags if state.program_state_initialized else port.initial_flags(unit.cancellation)
        )
        persisted_markers = state.program_markers if state.program_state_initialized else frozenset()
        return self._interpreter.execute(
            program,
            port,
            persisted_flags,
            unit.cancellation,
            persisted_program_markers=persisted_markers,
        )

    def mode(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleProgramMode:
        if not isinstance(session, CampaignSession):
            message = "MuMu12 campaign program mode requires a CampaignSession"
            raise TypeError(message)
        if not isinstance(state, CampaignSessionState):
            message = "MuMu12 campaign program mode requires CampaignSessionState"
            raise TypeError(message)
        session.validate_state(state)
        return self._units.battle_program_mode(session, cancellation)
