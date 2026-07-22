from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_program_capabilities import (
    CampaignProgramCapabilities,
    CampaignProgramCapabilityReader,
)
from module.adapters.campaign_program_mumu12 import (
    Mumu12BattleProgramRuntime,
    Mumu12CampaignBattleProgramExecutor,
    Mumu12CommittedBattleProgramUnit,
    build_mumu12_battle_program_port,
    read_mumu12_battle_program_mode,
)
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
from module.gameplay.battle_program import BattleProgramReducer

if TYPE_CHECKING:
    from module.adapters.battle_program_read_mumu12 import Mumu12ProgramReadSource
    from module.application import CancellationSource


class _Config:
    fleet_2 = 0
    MAP_CLEAR_ALL_THIS_TIME = False
    POOR_MAP_DATA = False
    MAP_HAS_MOVABLE_ENEMY = True
    MAP_HAS_MOVABLE_NORMAL_ENEMY = False


@dataclass(frozen=True, slots=True)
class _NavigationSnapshot:
    fleet_1: tuple[int, int] | tuple[()] = (0, 0)
    fleet_2: tuple[int, int] | tuple[()] = ()
    current_index: int = 1


class _Navigation:
    snapshot = _NavigationSnapshot()
    fleet_step = 0
    boss_index = 1


class _Runtime:
    map_is_clear_mode = True
    config = _Config()
    battle_count = 0
    mystery_count = 0
    configured_boss_fleet = 1
    navigation = _Navigation()

    def __init__(self) -> None:
        self.single_fleet_state_reads = 0
        self.support_state_reads = 0

    def use_support_fleet(self, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        self.support_state_reads += 1
        return True

    def use_single_fleet_override(self, cancellation: CancellationSource) -> bool | None:
        cancellation.raise_if_requested()
        self.single_fleet_state_reads += 1
        return None


class _MobMoveOverride:
    def __init__(self, *, value: bool | None) -> None:
        self.value = value
        self.reads = 0

    def map_has_mob_move_override(
        self,
        cancellation: CancellationSource,
    ) -> bool | None:
        cancellation.raise_if_requested()
        self.reads += 1
        return self.value


class _Units:
    def __init__(
        self,
        runtime: _Runtime,
        *,
        mob_move: bool | None = True,
        static_mob_move: bool = False,
        request_after_commit: bool = False,
    ) -> None:
        self.runtime = runtime
        self.request_after_commit = request_after_commit
        self.calls = 0
        self.active_calls = 0
        self.mob_move_override = _MobMoveOverride(value=mob_move)
        self.program_capabilities = CampaignProgramCapabilityReader(
            CampaignProgramCapabilities(map_has_mob_move=static_mob_move),
            self.mob_move_override,
        )

    def battle_program_mode(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> BattleProgramMode:
        del session
        self.active_calls += 1
        runtime = cast("Mumu12ProgramReadSource", self.runtime)
        return read_mumu12_battle_program_mode(
            runtime,
            self.runtime,
            self.program_capabilities,
            cancellation,
        )

    def commit_battle_program_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> Mumu12CommittedBattleProgramUnit:
        del session
        self.calls += 1
        gate = SafeUnitCancellation(cancellation)
        gate.commit()
        if self.request_after_commit:
            cast("AbortToken", cancellation).request("defer until program checkpoint")
        runtime = cast("Mumu12BattleProgramRuntime", self.runtime)
        return Mumu12CommittedBattleProgramUnit(
            build_mumu12_battle_program_port(
                runtime,
                self.runtime,
                self.program_capabilities,
            ),
            gate,
        )


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
    assert units.mob_move_override.reads == 1
    assert runtime.single_fleet_state_reads == 1
    assert runtime.support_state_reads == 1
    assert cancellation.is_requested


def test_executor_keeps_explicit_empty_persisted_flags_without_querying_static_capability() -> None:
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
        program_flags=frozenset(),
    )
    units = _Units(runtime, static_mob_move=True)

    execution = Mumu12CampaignBattleProgramExecutor(units).execute(
        program,
        session,
        state,
        AbortToken(),
    )

    assert execution.true_flags == frozenset()
    assert units.mob_move_override.reads == 0
    assert runtime.single_fleet_state_reads == 0
    assert runtime.support_state_reads == 0


@pytest.mark.parametrize(
    ("initial_override", "changed_override"),
    [(False, True), (True, False)],
)
def test_first_capability_sample_is_persisted_and_live_changes_do_not_rewrite_flags(
    *,
    initial_override: bool,
    changed_override: bool,
) -> None:
    program = BattleProgram(
        0,
        frozenset({BattleProgramMode.NORMAL}),
        (ReturnProgramContinue(),),
    )
    session = _session(program)
    runtime = _Runtime()
    units = _Units(runtime, mob_move=initial_override)
    executor = Mumu12CampaignBattleProgramExecutor(units)
    initial_state = session.initial_state()

    first = executor.execute(program, session, initial_state, AbortToken())
    persisted = BattleProgramReducer.reduce(session, initial_state, first)
    units.mob_move_override.value = changed_override
    second = executor.execute(program, session, persisted, AbortToken())

    assert persisted.program_state_initialized
    assert (ProgramFlag.MAP_HAS_MOB_MOVE in first.true_flags) is initial_override
    assert second.true_flags == first.true_flags
    assert units.mob_move_override.reads == 1
    assert runtime.single_fleet_state_reads == 1
    assert runtime.support_state_reads == 1


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
