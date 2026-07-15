from typing import TYPE_CHECKING, cast

from module.adapters.battle_program_mumu12 import Mumu12BattleProgramPort, RuntimeProgramState
from module.content.battle_program import BattleProgram, BattleProgramMode
from module.content.campaign_session import CampaignSession, CampaignSessionState
from module.gameplay.battle_program import BattleProgramExecution, BattleProgramInterpreter

if TYPE_CHECKING:
    from module.adapters.campaign_live import CampaignRuntimeUnitSource
    from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
    from module.application import CancellationSource


class Mumu12CampaignBattleProgramExecutor:
    """在一个不可中断的 campaign safe unit 内解释关卡 BattleProgram。"""

    __slots__ = ("_interpreter", "_units")

    def __init__(
        self,
        units: CampaignRuntimeUnitSource,
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

        unit = self._units.commit_active_unit(session, cancellation)
        program_state = cast("RuntimeProgramState", unit.runtime)
        port = Mumu12BattleProgramPort(unit.runtime, program_state)
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
        runtime = cast(
            "DeclarativeCampaignMapRuntime",
            self._units.active_runtime(session, cancellation),
        )
        if runtime.config.MAP_CLEAR_ALL_THIS_TIME:
            return BattleProgramMode.CLEAR_ALL
        if runtime.config.POOR_MAP_DATA:
            return BattleProgramMode.POOR_MAP_DATA
        return BattleProgramMode.NORMAL
