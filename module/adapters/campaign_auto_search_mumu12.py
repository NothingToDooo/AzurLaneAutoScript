from typing import TYPE_CHECKING, Protocol, assert_never, cast

from module.content.campaign_session import (
    AutoSearchBattle,
    BattleAttempt,
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
)
from module.exception import CampaignEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_ON

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.adapters.campaign_live import CampaignSafeUnitSource
    from module.application import CancellationSource
    from module.content.stage_definition import CampaignStageDefinition
    from module.device.device import Device


class Mumu12AutoSearchEvidenceError(RuntimeError):
    pass


class Mumu12AutoSearchGrid(Protocol):
    is_enemy: bool
    is_siren: bool
    is_boss: bool


class _AutoSearchNavigation(Protocol):
    def rebuild_paths(self) -> None: ...


class Mumu12AutoSearchRuntime(Protocol):
    battle_count: int
    device: Device
    map: Iterable[Mumu12AutoSearchGrid]

    @property
    def navigation(self) -> _AutoSearchNavigation: ...

    def auto_search_execute_a_battle(self) -> object: ...

    def is_auto_search_running(self) -> bool: ...

    def full_scan(self) -> object: ...


class Mumu12CampaignAutoSearchExecutor:
    """推进一个已提交的游戏自律 battle，并从地图事实闭合目标类型。"""

    __slots__ = ("_units",)

    def __init__(self, units: CampaignSafeUnitSource) -> None:
        self._units = units

    def execute(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleTarget:
        if not isinstance(session, CampaignSession):
            message = "MuMu12 auto-search executor requires a CampaignSession"
            raise TypeError(message)
        if not isinstance(state, CampaignSessionState):
            message = "MuMu12 auto-search executor requires a CampaignSessionState"
            raise TypeError(message)
        session.validate_state(state)
        attempt = state.pending
        if attempt is None or not isinstance(attempt.intent, AutoSearchBattle):
            message = "MuMu12 auto-search executor requires a pending AutoSearchBattle attempt"
            raise ValueError(message)

        unit = self._units.commit_active_unit(session, cancellation)
        return self._execute(
            cast("Mumu12AutoSearchRuntime", unit.runtime),
            session.definition,
            state,
            attempt,
            unit.cancellation,
        )

    def _execute(
        self,
        runtime: Mumu12AutoSearchRuntime,
        definition: CampaignStageDefinition,
        state: CampaignSessionState,
        attempt: BattleAttempt,
        cancellation: CancellationSource,
    ) -> BattleTarget:
        cancellation.raise_if_requested()
        before = runtime.battle_count
        ended = False
        try:
            runtime.auto_search_execute_a_battle()
        except CampaignEnd:
            ended = True

        confirmed = runtime.battle_count - before
        if ended and confirmed == 0 and state.remaining.boss == 1:
            runtime.battle_count += 1
            return BattleTarget.BOSS
        if confirmed != 1:
            message = f"one auto-search action changed battle_count by {confirmed}, expected exactly one"
            raise Mumu12AutoSearchEvidenceError(message)

        self._pause(runtime, cancellation)
        observed = self._visible_targets(runtime, cancellation)
        available = (
            (BattleTarget.ENEMY, state.remaining.enemy),
            (BattleTarget.SIREN, state.remaining.siren),
            (BattleTarget.BOSS, state.remaining.boss),
        )
        matched = tuple(
            target
            for target, count in available
            if count and self._expected_visible_after(definition, state, attempt, target) == observed
        )
        if len(matched) != 1:
            message = f"auto-search battle target is ambiguous: observed={observed}, candidates={matched}"
            raise Mumu12AutoSearchEvidenceError(message)
        return matched[0]

    @staticmethod
    def _pause(runtime: Mumu12AutoSearchRuntime, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        if not runtime.is_auto_search_running():
            return
        runtime.device.click(AUTO_SEARCH_MAP_OPTION_ON)
        for _ in range(20):
            cancellation.raise_if_requested()
            runtime.device.screenshot()
            if not runtime.is_auto_search_running():
                return
            runtime.device.sleep(0.2)
        message = "auto-search did not reach a paused map safe point"
        raise Mumu12AutoSearchEvidenceError(message)

    @staticmethod
    def _visible_targets(
        runtime: Mumu12AutoSearchRuntime,
        cancellation: CancellationSource,
    ) -> tuple[int, int, int]:
        cancellation.raise_if_requested()
        runtime.full_scan()
        cancellation.raise_if_requested()
        runtime.navigation.rebuild_paths()
        grids = tuple(runtime.map)
        enemy = sum(grid.is_enemy and not grid.is_siren and not grid.is_boss for grid in grids)
        siren = sum(grid.is_siren for grid in grids)
        boss = sum(grid.is_boss for grid in grids)
        return enemy, siren, boss

    @staticmethod
    def _expected_visible_after(
        definition: CampaignStageDefinition,
        state: CampaignSessionState,
        attempt: BattleAttempt,
        target: BattleTarget,
    ) -> tuple[int, int, int]:
        remaining = state.remaining.clear(target)
        if target is BattleTarget.BOSS:
            return remaining.enemy, remaining.siren, remaining.boss
        next_index = attempt.battle_index + 1
        if state.variant is CampaignRunVariant.NORMAL:
            variant = definition.map.normal
        elif state.variant is CampaignRunVariant.LOOP:
            variant = definition.map.loop
        else:
            assert_never(state.variant)
        if next_index < len(variant.spawn_waves):
            remaining = remaining.add_wave(variant.spawn_waves[next_index])
        return remaining.enemy, remaining.siren, remaining.boss
