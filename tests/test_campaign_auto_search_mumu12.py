from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_auto_search_mumu12 import (
    Mumu12AutoSearchEvidenceError,
    Mumu12CampaignAutoSearchExecutor,
)
from module.adapters.campaign_live import CampaignMapRuntime, CommittedCampaignUnit
from module.application import AbortRequested, AbortToken
from module.content.battle_policy import BossStrategy, ClearBoss, DefaultBattle, StagePolicy
from module.content.campaign_session import (
    AutoSearchBattle,
    BattleAttempt,
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
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
from module.content.stage_rules import MapFeatures, RepeatableCompletion, StageRules, StarRequirements
from module.exception import CampaignEnd

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.application import CancellationSource
    from module.base.button import Button


@dataclass(slots=True)
class _Grid:
    is_enemy: bool = False
    is_siren: bool = False
    is_boss: bool = False


class _Device:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def click(self, button: Button) -> None:
        self.calls.append(("click", button))

    def screenshot(self) -> None:
        self.calls.append("screenshot")

    def sleep(self, seconds: float) -> None:
        self.calls.append(("sleep", seconds))


class _Navigation:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def rebuild_paths(self) -> None:
        self._calls.append("rebuild_paths")


class _Runtime:
    def __init__(
        self,
        visible_after: tuple[_Grid, ...],
        *,
        confirmed_delta: int = 1,
        ends_campaign: bool = False,
        running: tuple[bool, ...] = (False,),
    ) -> None:
        self.battle_count = 0
        self.device = _Device()
        self.map: tuple[_Grid, ...] = ()
        self.visible_after = visible_after
        self.confirmed_delta = confirmed_delta
        self.ends_campaign = ends_campaign
        self.running = list(running)
        self.calls: list[str] = []
        self.navigation = _Navigation(self.calls)

    def auto_search_execute_a_battle(self) -> None:
        self.calls.append("execute")
        if self.ends_campaign:
            raise CampaignEnd
        self.battle_count += self.confirmed_delta
        self.map = self.visible_after

    def is_auto_search_running(self) -> bool:
        self.calls.append("running")
        if len(self.running) > 1:
            return self.running.pop(0)
        return self.running[0]

    def full_scan(self) -> None:
        self.calls.append("full_scan")


class _UnitSource:
    def __init__(
        self,
        runtime: _Runtime,
        *,
        unit_cancellation: CancellationSource | None = None,
        on_commit: Callable[[], None] | None = None,
    ) -> None:
        self.runtime = runtime
        self.unit_cancellation = AbortToken() if unit_cancellation is None else unit_cancellation
        self.on_commit = on_commit
        self.calls = 0

    def commit_active_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CommittedCampaignUnit:
        del session
        cancellation.raise_if_requested()
        self.calls += 1
        if self.on_commit is not None:
            self.on_commit()
        return CommittedCampaignUnit(
            cast("CampaignMapRuntime", self.runtime),
            self.unit_cancellation,
        )


def _variant(waves: tuple[SpawnWave, ...]) -> RunVariant:
    return RunVariant(
        cells=(CellSpec(CellId(0, 0), "MB", 1.0),),
        spawn_waves=waves,
    )


def _session(
    normal_waves: tuple[SpawnWave, ...],
    *,
    loop_waves: tuple[SpawnWave, ...] | None = None,
    variant: CampaignRunVariant = CampaignRunVariant.NORMAL,
) -> CampaignSession:
    selected_loop_waves = normal_waves if loop_waves is None else loop_waves
    all_battles = {wave.battle for wave in (*normal_waves, *selected_loop_waves)}
    policies = {
        battle: StagePolicy(
            (ClearBoss(BossStrategy.FLEET_BOSS),)
            if any(wave.battle == battle and wave.boss for wave in (*normal_waves, *selected_loop_waves))
            else (DefaultBattle(),)
        )
        for battle in all_battles
    }
    definition = CampaignStageDefinition(
        ref=StageRef("campaign_main", "auto-search"),
        map=MapDefinition(
            name="auto-search",
            shape=GridShape(1, 1),
            camera_data=(),
            camera_data_spawn_point=(),
            normal=_variant(normal_waves),
            loop=_variant(selected_loop_waves),
        ),
        rules=StageRules(
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
        ),
        enemy_filter="1L > 2L > 3L",
        battle_policies=policies,
    )
    return CampaignSession(definition, variant)


def _pending_state(session: CampaignSession) -> CampaignSessionState:
    state = session.initial_state()
    attempt = BattleAttempt(state.battle_index, 0, 0, AutoSearchBattle())
    return replace(state, next_attempt_id=1, pending=attempt)


def test_auto_search_closes_enemy_from_explicit_state_and_definition() -> None:
    session = _session(
        (
            SpawnWave(battle=0, enemy=1, siren=1),
            SpawnWave(battle=1, enemy=2),
        )
    )
    runtime = _Runtime((_Grid(is_enemy=True), _Grid(is_enemy=True), _Grid(is_siren=True)))
    source = _UnitSource(runtime)

    target = Mumu12CampaignAutoSearchExecutor(source).execute(
        session,
        _pending_state(session),
        AbortToken(),
    )

    assert target is BattleTarget.ENEMY
    assert source.calls == 1
    assert runtime.calls == ["execute", "running", "full_scan", "rebuild_paths"]


def test_auto_search_uses_explicit_loop_variant_for_next_wave() -> None:
    session = _session(
        (SpawnWave(battle=0, enemy=1, siren=1), SpawnWave(battle=1, enemy=4)),
        loop_waves=(SpawnWave(battle=0, enemy=1, siren=1), SpawnWave(battle=1, siren=2)),
        variant=CampaignRunVariant.LOOP,
    )
    runtime = _Runtime((_Grid(is_enemy=True), _Grid(is_siren=True), _Grid(is_siren=True)))

    target = Mumu12CampaignAutoSearchExecutor(_UnitSource(runtime)).execute(
        session,
        _pending_state(session),
        AbortToken(),
    )

    assert target is BattleTarget.SIREN


def test_auto_search_boss_prediction_does_not_add_a_later_wave() -> None:
    session = _session(
        (
            SpawnWave(battle=0, boss=1),
            SpawnWave(battle=1, enemy=3),
        )
    )
    runtime = _Runtime(())

    target = Mumu12CampaignAutoSearchExecutor(_UnitSource(runtime)).execute(
        session,
        _pending_state(session),
        AbortToken(),
    )

    assert target is BattleTarget.BOSS


def test_auto_search_campaign_end_confirms_the_pending_boss() -> None:
    session = _session((SpawnWave(battle=0, boss=1),))
    runtime = _Runtime((), confirmed_delta=0, ends_campaign=True)

    target = Mumu12CampaignAutoSearchExecutor(_UnitSource(runtime)).execute(
        session,
        _pending_state(session),
        AbortToken(),
    )

    assert target is BattleTarget.BOSS
    assert runtime.battle_count == 1
    assert runtime.calls == ["execute"]


def test_auto_search_requires_the_pending_attempt_before_committing() -> None:
    session = _session((SpawnWave(battle=0, enemy=1),))
    source = _UnitSource(_Runtime(()))

    with pytest.raises(ValueError, match="pending AutoSearchBattle"):
        Mumu12CampaignAutoSearchExecutor(source).execute(
            session,
            session.initial_state(),
            AbortToken(),
        )

    assert source.calls == 0


def test_auto_search_honors_cancellation_before_committing() -> None:
    session = _session((SpawnWave(battle=0, enemy=1),))
    cancellation = AbortToken()
    cancellation.request("stop before auto-search")
    runtime = _Runtime(())
    source = _UnitSource(runtime)

    with pytest.raises(AbortRequested, match="stop before auto-search"):
        Mumu12CampaignAutoSearchExecutor(source).execute(
            session,
            _pending_state(session),
            cancellation,
        )

    assert source.calls == 0
    assert runtime.calls == []


def test_auto_search_rejects_unconfirmed_action() -> None:
    session = _session((SpawnWave(battle=0, enemy=1),))
    runtime = _Runtime((), confirmed_delta=0)

    with pytest.raises(Mumu12AutoSearchEvidenceError, match="changed battle_count by 0"):
        Mumu12CampaignAutoSearchExecutor(_UnitSource(runtime)).execute(
            session,
            _pending_state(session),
            AbortToken(),
        )


def test_auto_search_uses_the_committed_unit_cancellation() -> None:
    session = _session((SpawnWave(battle=0, enemy=1),))
    outer = AbortToken()
    runtime = _Runtime(())

    def request_outer_cancellation() -> None:
        outer.request("late stop")

    source = _UnitSource(runtime, on_commit=request_outer_cancellation)

    target = Mumu12CampaignAutoSearchExecutor(source).execute(
        session,
        _pending_state(session),
        outer,
    )

    assert target is BattleTarget.ENEMY
    with pytest.raises(AbortRequested, match="late stop"):
        outer.raise_if_requested()
