from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_live import CampaignMapRuntime, CommittedCampaignUnit
from module.adapters.campaign_program_mumu12 import Mumu12CampaignBattleProgramExecutor
from module.application import AbortToken, SafeUnitCancellation
from module.content.battle_program import (
    BattleProgram,
    BattleProgramMode,
    ProgramContinue,
    ProgramFlag,
    ReturnProgramContinue,
)
from module.content.campaign_session import CampaignRunVariant, CampaignSession
from module.content.cell import CellId
from module.content.models import StageRef
from module.content.stage_definition import (
    CampaignStageDefinition,
    CellSpec,
    GridShape,
    MapDefinition,
    RunVariant,
    SpawnWave,
)
from module.content.stage_rules import MapFeatures, RepeatableCompletion, StageRules, StarRequirements

if TYPE_CHECKING:
    from module.interaction import CancellationSignal


class _Config:
    fleet_2 = 0
    MAP_CLEAR_ALL_THIS_TIME = False
    POOR_MAP_DATA = False
    MAP_HAS_MOVABLE_ENEMY = True
    MAP_HAS_MOVABLE_NORMAL_ENEMY = False


class _Runtime:
    map_is_clear_mode = True
    config = _Config()

    def __init__(self) -> None:
        self.map_state_reads = 0
        self.single_fleet_state_reads = 0
        self.support_state_reads = 0

    def map_has_mob_move(self, cancellation: CancellationSignal) -> bool:
        cancellation.raise_if_requested()
        self.map_state_reads += 1
        return True

    def use_support_fleet(self, cancellation: CancellationSignal) -> bool:
        cancellation.raise_if_requested()
        self.support_state_reads += 1
        return True

    def use_single_fleet_override(self, cancellation: CancellationSignal) -> bool | None:
        cancellation.raise_if_requested()
        self.single_fleet_state_reads += 1
        return None


class _Units:
    def __init__(self, runtime: _Runtime, *, request_after_commit: bool = False) -> None:
        self.runtime = runtime
        self.request_after_commit = request_after_commit
        self.calls = 0
        self.active_calls = 0

    def active_runtime(
        self,
        session: CampaignSession,
        cancellation: CancellationSignal,
    ) -> CampaignMapRuntime:
        del session
        cancellation.raise_if_requested()
        self.active_calls += 1
        return cast("CampaignMapRuntime", self.runtime)

    def commit_active_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSignal,
    ) -> CommittedCampaignUnit:
        del session
        self.calls += 1
        gate = SafeUnitCancellation(cancellation)
        gate.commit()
        if self.request_after_commit:
            cast("AbortToken", cancellation).request("defer until program checkpoint")
        return CommittedCampaignUnit(cast("CampaignMapRuntime", self.runtime), gate)


def _session(program: BattleProgram) -> CampaignSession:
    variant = RunVariant(
        cells=(CellSpec(CellId(0, 0), "SP", 1.0),),
        spawn_waves=(SpawnWave(0, enemy=1),),
    )
    definition = CampaignStageDefinition(
        ref=StageRef("event_test", "t1"),
        map=MapDefinition("T1", GridShape(1, 1), (), (), variant, variant),
        rules=StageRules(
            MapFeatures(
                siren_templates=(),
                movable_enemy_turns=(),
                has_siren=False,
                has_movable_enemy=False,
                has_map_story=False,
                has_fleet_step=False,
                has_ambush=False,
                has_mystery=False,
            ),
            RepeatableCompletion(StarRequirements()),
        ),
        enemy_filter="1L",
        battle_policies={},
        battle_programs={0: program},
    )
    return CampaignSession(definition, CampaignRunVariant.NORMAL)


def test_executor_initializes_dynamic_flags_inside_committed_unit() -> None:
    program = BattleProgram(
        0,
        frozenset({BattleProgramMode.NORMAL}),
        (ReturnProgramContinue(),),
    )
    session = _session(program)
    runtime = _Runtime()
    units = _Units(runtime, request_after_commit=True)
    cancellation = AbortToken()

    execution = Mumu12CampaignBattleProgramExecutor(units).execute(
        program,
        session,
        session.initial_state(),
        cancellation,
    )

    assert execution.result == ProgramContinue()
    assert execution.true_flags == frozenset(
        {
            ProgramFlag.CLEAR_MODE,
            ProgramFlag.MAP_HAS_MOB_MOVE,
            ProgramFlag.USE_SINGLE_FLEET,
            ProgramFlag.USE_SUPPORT_FLEET,
            ProgramFlag.MOVABLE_ENEMY,
        }
    )
    assert runtime.map_state_reads == 1
    assert runtime.single_fleet_state_reads == 1
    assert runtime.support_state_reads == 1
    assert cancellation.is_requested


def test_executor_uses_persisted_flags_without_reinferring_runtime_state() -> None:
    program = BattleProgram(
        0,
        frozenset({BattleProgramMode.NORMAL}),
        (ReturnProgramContinue(),),
    )
    session = _session(program)
    runtime = _Runtime()
    state = replace(
        session.initial_state(),
        program_state_initialized=True,
        program_flags=frozenset({ProgramFlag.MAP_HAS_MOB_MOVE}),
    )

    execution = Mumu12CampaignBattleProgramExecutor(_Units(runtime)).execute(
        program,
        session,
        state,
        AbortToken(),
    )

    assert execution.true_flags == frozenset({ProgramFlag.MAP_HAS_MOB_MOVE})
    assert runtime.map_state_reads == 0
    assert runtime.single_fleet_state_reads == 0
    assert runtime.support_state_reads == 0


def test_executor_rejects_program_from_another_battle_before_commit() -> None:
    program = BattleProgram(
        0,
        frozenset({BattleProgramMode.NORMAL}),
        (ReturnProgramContinue(),),
    )
    other = BattleProgram(
        1,
        frozenset({BattleProgramMode.CLEAR_ALL}),
        (ReturnProgramContinue(),),
    )
    session = _session(program)
    units = _Units(_Runtime())

    with pytest.raises(ValueError, match="does not match"):
        Mumu12CampaignBattleProgramExecutor(units).execute(
            other,
            session,
            session.initial_state(),
            AbortToken(),
        )

    assert units.calls == 0


def test_executor_accepts_a_generic_program_for_the_active_battle() -> None:
    stage_program = BattleProgram(
        0,
        frozenset({BattleProgramMode.NORMAL}),
        (ReturnProgramContinue(),),
    )
    generic_program = BattleProgram(
        0,
        frozenset({BattleProgramMode.CLEAR_ALL}),
        (ReturnProgramContinue(),),
    )
    session = _session(stage_program)
    units = _Units(_Runtime())

    execution = Mumu12CampaignBattleProgramExecutor(units).execute(
        generic_program,
        session,
        session.initial_state(),
        AbortToken(),
    )

    assert execution.result == ProgramContinue()
    assert units.calls == 1


@pytest.mark.parametrize(
    ("clear_all", "poor_map_data", "expected"),
    [
        (False, False, BattleProgramMode.NORMAL),
        (False, True, BattleProgramMode.POOR_MAP_DATA),
        (True, False, BattleProgramMode.CLEAR_ALL),
        (True, True, BattleProgramMode.CLEAR_ALL),
    ],
)
def test_mode_reads_the_active_runtime_without_committing(
    *,
    clear_all: bool,
    poor_map_data: bool,
    expected: BattleProgramMode,
) -> None:
    program = BattleProgram(
        0,
        frozenset({BattleProgramMode.NORMAL}),
        (ReturnProgramContinue(),),
    )
    session = _session(program)
    runtime = _Runtime()
    runtime.config.MAP_CLEAR_ALL_THIS_TIME = clear_all
    runtime.config.POOR_MAP_DATA = poor_map_data
    units = _Units(runtime)

    mode = Mumu12CampaignBattleProgramExecutor(units).mode(
        session,
        session.initial_state(),
        AbortToken(),
    )

    assert mode is expected
    assert units.active_calls == 1
    assert units.calls == 0
