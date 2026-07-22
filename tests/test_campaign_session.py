import pytest

from module.content.battle_policy import (
    BattleIntent,
    BattlePolicy,
    BossStrategy,
    ClearBoss,
    ClearBossRoadblock,
    ClearFilteredEnemy,
    ClearSiren,
    DefaultBattle,
    StagePolicy,
)
from module.content.campaign_session import (
    BattleAttempt,
    BattleFailed,
    BattlefieldObservation,
    BattleSucceeded,
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionError,
    CampaignSessionState,
    CampaignSessionStatus,
    NoBattleTarget,
    RemainingSpawns,
)
from module.content.models import StageRef
from module.content.stage_definition import (
    CampaignStageDefinition,
    CellId,
    CellSpec,
    GridShape,
    MapDefinition,
    RunVariant,
    SpawnWave,
)
from module.content.stage_rules import (
    MapFeatures,
    RepeatableCompletion,
    StageRules,
    StarRequirements,
)

TEST_STAGE_RULES = StageRules(
    features=MapFeatures(
        siren_templates=(),
        movable_enemy_turns=(),
        has_siren=False,
        has_movable_enemy=False,
        has_map_story=False,
        has_fleet_step=False,
        has_ambush=False,
        has_mystery=False,
    ),
    completion=RepeatableCompletion(StarRequirements()),
)


def _definition(
    normal_waves: tuple[SpawnWave, ...],
    *,
    loop_waves: tuple[SpawnWave, ...] | None = None,
    policies: dict[int, BattlePolicy | StagePolicy] | None = None,
) -> CampaignStageDefinition:
    cell = CellSpec(CellId(0, 0), "--", 50.0)
    normal = RunVariant((cell,), normal_waves)
    loop = RunVariant((cell,), normal_waves if loop_waves is None else loop_waves)
    return CampaignStageDefinition(
        ref=StageRef("test_pack", "test_stage"),
        map=MapDefinition(
            name="TEST",
            shape=GridShape(1, 1),
            camera_data=(cell.cell_id,),
            camera_data_spawn_point=(cell.cell_id,),
            normal=normal,
            loop=loop,
        ),
        rules=TEST_STAGE_RULES,
        enemy_filter="1L > 1M",
        battle_policies={} if policies is None else policies,
    )


def _command(decision_state: CampaignSessionState) -> BattleAttempt:
    command = decision_state.pending
    assert command is not None
    return command


@pytest.mark.parametrize(
    ("variant", "expected_remaining", "expected_waves"),
    [
        (CampaignRunVariant.NORMAL, RemainingSpawns(enemy=2), 1),
        (CampaignRunVariant.LOOP, RemainingSpawns(siren=1), 2),
    ],
)
def test_initial_state_selects_the_complete_normal_or_loop_variant(
    variant: CampaignRunVariant,
    expected_remaining: RemainingSpawns,
    expected_waves: int,
) -> None:
    definition = _definition(
        (SpawnWave(0, enemy=2),),
        loop_waves=(SpawnWave(0, siren=1), SpawnWave(1, boss=1)),
        policies={1: BattlePolicy("fleet_boss")},
    )
    session = CampaignSession(definition, variant)

    state = session.initial_state()

    assert state.variant is variant
    assert state.remaining == expected_remaining
    assert len(session.run_variant.spawn_waves) == expected_waves


@pytest.mark.parametrize(
    ("observation", "expected_intent"),
    [
        (BattlefieldObservation(0, enemy=2, siren=1), ClearSiren()),
        (BattlefieldObservation(0, enemy=2), ClearFilteredEnemy(preserve=1)),
        (BattlefieldObservation(0, enemy=1), DefaultBattle()),
    ],
)
def test_siren_filtered_default_policy_decides_the_first_eligible_intent(
    observation: BattlefieldObservation,
    expected_intent: BattleIntent,
) -> None:
    definition = _definition(
        (SpawnWave(0, enemy=2, siren=1),),
        policies={0: BattlePolicy("siren_then_filtered_enemy", preserve=1)},
    )
    session = CampaignSession(definition, CampaignRunVariant.NORMAL)
    initial = session.initial_state()

    decision = session.decide(initial, observation)

    assert decision.command is not None
    assert decision.command.intent == expected_intent
    assert decision.state.pending == decision.command
    assert initial.pending is None
    assert initial.next_attempt_id == 0


def test_boss_spawn_decides_a_typed_clear_boss_intent() -> None:
    session = CampaignSession(
        _definition((SpawnWave(0, boss=1),), policies={0: BattlePolicy("fleet_boss")}),
        CampaignRunVariant.NORMAL,
    )

    decision = session.decide(session.initial_state(), BattlefieldObservation(0, boss=1))

    assert decision.command is not None
    assert decision.command.intent == ClearBoss(BossStrategy.FLEET_BOSS)


def test_boss_roadblock_success_stays_on_the_boss_wave_until_no_target() -> None:
    strategy = BossStrategy.MAP_SEARCH
    session = CampaignSession(
        _definition(
            (SpawnWave(0, enemy=2, boss=1),),
            policies={
                0: StagePolicy(
                    (
                        ClearBossRoadblock(strategy),
                        ClearBoss(strategy),
                    )
                )
            },
        ),
        CampaignRunVariant.NORMAL,
    )
    first = session.decide(session.initial_state(), BattlefieldObservation(0, enemy=2, boss=1))

    after_enemy = session.reduce(first.state, BattleSucceeded(_command(first.state), BattleTarget.ENEMY))
    retry = session.decide(after_enemy, BattlefieldObservation(0, enemy=1, boss=1))
    after_no_roadblock = session.reduce(retry.state, NoBattleTarget(_command(retry.state)))
    boss = session.decide(after_no_roadblock, BattlefieldObservation(0, enemy=1, boss=1))

    assert after_enemy.battle_index == 0
    assert after_enemy.next_intent_index == 0
    assert after_enemy.remaining == RemainingSpawns(enemy=1, boss=1)
    assert isinstance(_command(retry.state).intent, ClearBossRoadblock)
    assert after_no_roadblock.next_intent_index == 1
    assert isinstance(_command(boss.state).intent, ClearBoss)


def test_successes_accumulate_new_waves_and_complete_deterministically() -> None:
    definition = _definition(
        (
            SpawnWave(0, enemy=2, siren=1, mystery=1),
            SpawnWave(1, enemy=2),
            SpawnWave(2, boss=1),
        ),
        policies={
            0: BattlePolicy("siren_then_filtered_enemy", preserve=0),
            2: BattlePolicy("fleet_boss"),
        },
    )
    session = CampaignSession(definition, CampaignRunVariant.NORMAL)
    initial = session.initial_state()

    first = session.decide(initial, BattlefieldObservation(0, enemy=2, siren=1))
    after_first = session.reduce(first.state, BattleSucceeded(_command(first.state), BattleTarget.SIREN))
    second = session.decide(after_first, BattlefieldObservation(1, enemy=4))
    after_second = session.reduce(second.state, BattleSucceeded(_command(second.state), BattleTarget.ENEMY))
    third = session.decide(after_second, BattlefieldObservation(2, enemy=3, boss=1))
    completed = session.reduce(third.state, BattleSucceeded(_command(third.state), BattleTarget.BOSS))

    assert after_first.battle_index == 1
    assert after_first.remaining == RemainingSpawns(enemy=4, mystery=1)
    assert isinstance(_command(second.state).intent, DefaultBattle)
    assert after_second.battle_index == 2
    assert after_second.remaining == RemainingSpawns(enemy=3, mystery=1, boss=1)
    assert isinstance(_command(third.state).intent, ClearBoss)
    assert completed.status is CampaignSessionStatus.COMPLETED
    assert completed.battle_index == 3
    assert completed.remaining == RemainingSpawns(enemy=3, mystery=1)


def test_clearing_an_early_boss_completes_before_later_spawn_rows() -> None:
    session = CampaignSession(
        _definition(
            (
                SpawnWave(0, enemy=1),
                SpawnWave(1, enemy=1, boss=1),
                SpawnWave(2, enemy=3),
            ),
            policies={1: BattlePolicy("fleet_boss")},
        ),
        CampaignRunVariant.NORMAL,
    )
    first = session.decide(session.initial_state(), BattlefieldObservation(0, enemy=1))
    boss_wave = session.reduce(
        first.state,
        BattleSucceeded(_command(first.state), BattleTarget.ENEMY),
    )
    boss = session.decide(boss_wave, BattlefieldObservation(1, enemy=1, boss=1))

    completed = session.reduce(
        boss.state,
        BattleSucceeded(_command(boss.state), BattleTarget.BOSS),
    )

    assert completed.status is CampaignSessionStatus.COMPLETED
    assert completed.battle_index == 2
    assert completed.remaining == RemainingSpawns(enemy=1)
    session.validate_state(completed)


def test_no_target_walks_the_declared_fallbacks_then_blocks() -> None:
    session = CampaignSession(
        _definition(
            (SpawnWave(0, enemy=2, siren=1),),
            policies={0: BattlePolicy("siren_then_filtered_enemy", preserve=0)},
        ),
        CampaignRunVariant.NORMAL,
    )
    observation = BattlefieldObservation(0, enemy=2, siren=1)

    siren = session.decide(session.initial_state(), observation)
    after_siren = session.reduce(siren.state, NoBattleTarget(_command(siren.state)))
    filtered = session.decide(after_siren, observation)
    after_filtered = session.reduce(filtered.state, NoBattleTarget(_command(filtered.state)))
    default = session.decide(after_filtered, observation)
    blocked = session.reduce(default.state, NoBattleTarget(_command(default.state)))

    assert isinstance(_command(siren.state).intent, ClearSiren)
    assert isinstance(_command(filtered.state).intent, ClearFilteredEnemy)
    assert isinstance(_command(default.state).intent, DefaultBattle)
    assert (
        _command(siren.state).attempt_id,
        _command(filtered.state).attempt_id,
        _command(default.state).attempt_id,
    ) == (0, 1, 2)
    assert blocked.status is CampaignSessionStatus.BLOCKED
    assert blocked.pending is None
    assert blocked.reason == "battle 0 exhausted its battle plan"


def test_battle_failure_is_terminal_and_keeps_the_remaining_spawn_facts() -> None:
    session = CampaignSession(
        _definition((SpawnWave(0, enemy=1),)),
        CampaignRunVariant.NORMAL,
    )
    decision = session.decide(session.initial_state(), BattlefieldObservation(0, enemy=1))

    failed = session.reduce(decision.state, BattleFailed(_command(decision.state), "  fleet defeated  "))

    assert failed.status is CampaignSessionStatus.FAILED
    assert failed.reason == "fleet defeated"
    assert failed.remaining == RemainingSpawns(enemy=1)
    with pytest.raises(CampaignSessionError, match="terminal"):
        session.decide(failed, BattlefieldObservation(0, enemy=1))


def test_default_battle_may_report_the_actual_enemy_or_siren_it_cleared() -> None:
    session = CampaignSession(
        _definition((SpawnWave(0, enemy=1, siren=1),)),
        CampaignRunVariant.NORMAL,
    )

    enemy_decision = session.decide(session.initial_state(), BattlefieldObservation(0, enemy=1, siren=1))
    enemy_completed = session.reduce(
        enemy_decision.state,
        BattleSucceeded(_command(enemy_decision.state), BattleTarget.ENEMY),
    )
    siren_decision = session.decide(session.initial_state(), BattlefieldObservation(0, enemy=1, siren=1))
    siren_completed = session.reduce(
        siren_decision.state,
        BattleSucceeded(_command(siren_decision.state), BattleTarget.SIREN),
    )

    assert enemy_completed.remaining == RemainingSpawns(siren=1)
    assert siren_completed.remaining == RemainingSpawns(enemy=1)
