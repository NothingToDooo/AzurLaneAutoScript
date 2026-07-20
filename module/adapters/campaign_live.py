import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, assert_never

from module.base.filter import Filter
from module.content.battle_policy import (
    AllConditions,
    AnyCondition,
    BattleCondition,
    BattleFlag,
    BattleIntent,
    BossStrategy,
    CellAccessibleCondition,
    ClearAnyEnemy,
    ClearBoss,
    ClearBossRoadblock,
    ClearChosenEnemy,
    ClearEnemy,
    ClearFilteredEnemy,
    ClearPriorityEnemy,
    ClearSelectedEnemy,
    ClearSiren,
    DefaultBattle,
    FlagCondition,
    GuardedBattleStep,
    NotCondition,
    TargetExpectation,
    UnguardedBattleStep,
)
from module.content.campaign_session import (
    AutoSearchBattle,
    BattleAttempt,
    BattleFailed,
    BattlefieldObservation,
    BattleInterrupted,
    BattleInterruptionReason,
    BattleOutcome,
    BattleSucceeded,
    BattleTarget,
    CampaignSession,
    CampaignSessionState,
    NoBattleTarget,
)
from module.gameplay.campaign_live import (
    CampaignAutoSearchBattleExecutor,
    CampaignBattlefieldObserver,
    CampaignBattleIntentDriver,
    CampaignLiveClock,
    CampaignLiveServices,
    LiveCampaignWorkflow,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from module.application import CancellationSource
    from module.content.cell import CellId


_ENEMY_FILTER_PATTERN = re.compile(r"^(.*?)$")
_UNCONFIRMED_ACTION = "campaign map action returned without exactly one battle_count confirmation"


class CampaignMapAdapterError(RuntimeError):
    pass


class CampaignActionInterrupted(RuntimeError):  # ruff:ignore[error-suffix-on-exception-name] - 表示执行已安全中断并返回编排层。
    """UI primitive 已闭合到非 battle 安全点，需要 workflow 执行显式转移。"""

    def __init__(self, reason: BattleInterruptionReason) -> None:
        if not isinstance(reason, BattleInterruptionReason):
            message = "campaign action interruption requires a BattleInterruptionReason"
            raise TypeError(message)
        super().__init__(reason.value)
        self.reason = reason


class CampaignGrid(Protocol):
    str: str
    is_enemy: bool
    is_siren: bool
    is_boss: bool
    is_accessible: bool
    may_siren: bool
    enemy_scale: int
    enemy_genre: str | None
    location: tuple[int, int] | None
    weight: float
    cost: float
    cost_1: float
    cost_2: float

    def __str__(self) -> str: ...


class CampaignMapView(Protocol):
    def __iter__(self) -> Iterator[CampaignGrid]: ...


class CampaignFleetRuntime(Protocol):
    def clear_chosen_enemy(self, grid: CampaignGrid, expected: str = "") -> object: ...


class CampaignMapRuntime(CampaignFleetRuntime, Protocol):
    map: CampaignMapView
    battle_count: int

    @property
    def fleet_1(self) -> CampaignFleetRuntime: ...

    @property
    def fleet_boss(self) -> CampaignFleetRuntime: ...

    @property
    def fleet_boss_index(self) -> int: ...

    def full_scan(self) -> object: ...

    def find_path_initial(self) -> object: ...

    def read_battle_flag(self, flag: BattleFlag) -> bool: ...

    def brute_find_roadblocks(
        self,
        grid: CampaignGrid,
        fleet: int | None = None,
    ) -> Iterable[CampaignGrid]: ...


class CampaignMapRuntimeSource(Protocol):
    def active_runtime(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CampaignMapRuntime:
        """返回已进入 session 对应地图、且在本次 workflow turn 内稳定的 runtime。"""


@dataclass(frozen=True, slots=True)
class CommittedCampaignUnit:
    runtime: CampaignMapRuntime
    cancellation: CancellationSource


class CampaignSafeUnitSource(Protocol):
    def commit_active_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CommittedCampaignUnit:
        """提交当前安全单元，之后把新取消请求延迟到 checkpoint 闭合。"""


class CampaignRuntimeUnitSource(CampaignMapRuntimeSource, CampaignSafeUnitSource, Protocol):
    """同时提供活动 runtime 与可提交动作单元的生产运行时来源。"""


def _require_method(value: object, method_name: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method_name, None)):
        message = f"{field_name} must implement {method_name}()"
        raise TypeError(message)


def _ordinary_enemy(grid: CampaignGrid) -> bool:
    return grid.is_enemy and not grid.is_siren and not grid.is_boss


def _ordered(grids: Iterable[CampaignGrid]) -> list[CampaignGrid]:
    return sorted(grids, key=lambda grid: (grid.weight, grid.cost, str(grid)))


def _enemy_sort_value(grid: CampaignGrid, key: str) -> float:
    if key == "weight":
        return grid.weight
    if key == "cost":
        return grid.cost
    if key == "cost_1":
        return grid.cost_1
    if key == "cost_2":
        return grid.cost_2
    if key == "enemy_scale":
        return grid.enemy_scale
    message = f"unsupported enemy sort key: {key}"
    raise CampaignMapAdapterError(message)


@dataclass(frozen=True, slots=True)
class _SelectedBattle:
    target: CampaignGrid | None
    cleared: BattleTarget
    expected: str
    executor: CampaignFleetRuntime | None = None


class ExistingCampaignMapAdapter(CampaignBattlefieldObserver, CampaignBattleIntentDriver):
    """在已初始化的 Campaign Map 上执行一个原子 intent，并以 battle_count 确认事实。"""

    __slots__ = ("_auto_search", "_runtimes")

    def __init__(
        self,
        runtimes: CampaignRuntimeUnitSource,
        auto_search: CampaignAutoSearchBattleExecutor,
    ) -> None:
        _require_method(runtimes, "active_runtime", field_name="runtimes")
        _require_method(runtimes, "commit_active_unit", field_name="runtimes")
        _require_method(auto_search, "execute", field_name="auto_search")
        self._runtimes = runtimes
        self._auto_search = auto_search

    def observe(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattlefieldObservation:
        session.validate_state(state)
        runtime = self._runtime(session, cancellation)
        cancellation.raise_if_requested()
        runtime.full_scan()
        cancellation.raise_if_requested()
        runtime.find_path_initial()
        grids = tuple(runtime.map)
        return BattlefieldObservation(
            battle_index=state.battle_index,
            enemy=sum(_ordinary_enemy(grid) for grid in grids),
            siren=sum(grid.is_siren for grid in grids),
            boss=sum(grid.is_boss for grid in grids),
        )

    def issue_and_confirm(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        attempt = self._pending_attempt(session, state)
        if isinstance(attempt.intent, AutoSearchBattle):
            return self._issue_auto_search(session, state, attempt, cancellation)

        runtime = self._runtime(session, cancellation)
        intent = self._eligible_intent(runtime, attempt.intent)
        if intent is None:
            return NoBattleTarget(attempt)

        committed = self._runtimes.commit_active_unit(session, cancellation)
        if committed.runtime is not runtime:
            message = "campaign safe unit changed the active runtime"
            raise CampaignMapAdapterError(message)
        cancellation = committed.cancellation
        if isinstance(intent, ClearSiren):
            outcome = self._issue_search_intent(runtime, attempt, intent, cancellation)
        elif isinstance(intent, ClearFilteredEnemy | ClearEnemy | ClearAnyEnemy | ClearPriorityEnemy):
            selected = self._enemy_search(runtime, session, intent)
            outcome = self._issue(runtime, attempt, selected, cancellation)
        elif isinstance(intent, ClearChosenEnemy | ClearSelectedEnemy):
            outcome = self._issue_targeted(runtime, attempt, intent, cancellation)
        elif isinstance(intent, DefaultBattle):
            target, cleared, expected = self._default_target(runtime)
            selected = _SelectedBattle(target, cleared, expected)
            outcome = self._issue(runtime, attempt, selected, cancellation)
        elif isinstance(intent, ClearBossRoadblock):
            outcome = self._clear_boss_roadblock(runtime, attempt, intent.strategy, cancellation)
        elif isinstance(intent, ClearBoss):
            outcome = self._clear_boss(runtime, attempt, intent.strategy, cancellation)
        else:
            assert_never(intent)
        return outcome

    def _issue_search_intent(
        self,
        runtime: CampaignMapRuntime,
        attempt: BattleAttempt,
        intent: ClearSiren,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        if intent.include_hidden_candidates:
            for grid in runtime.map:
                grid.may_siren = True
        target = self._first(
            runtime,
            lambda grid: (
                grid.is_siren and grid.is_accessible and (not intent.genres or grid.enemy_genre in intent.genres)
            ),
        )
        selected = _SelectedBattle(target, BattleTarget.SIREN, "siren")
        return self._issue(runtime, attempt, selected, cancellation)

    @classmethod
    def _eligible_intent(
        cls,
        runtime: CampaignMapRuntime,
        intent: BattleIntent,
    ) -> UnguardedBattleStep | None:
        if not isinstance(intent, GuardedBattleStep):
            return intent
        if cls._condition_matches(runtime, intent.condition):
            return intent.step
        return None

    def _enemy_search(
        self,
        runtime: CampaignMapRuntime,
        session: CampaignSession,
        intent: ClearFilteredEnemy | ClearEnemy | ClearAnyEnemy | ClearPriorityEnemy,
    ) -> _SelectedBattle:
        if isinstance(intent, ClearFilteredEnemy):
            target = self._filtered_enemy(runtime, session, intent.preserve)
            selected = _SelectedBattle(target, BattleTarget.ENEMY, "")
        elif isinstance(intent, ClearEnemy):
            target = self._enemy(
                runtime,
                intent.scales,
                intent.genres,
                sort=intent.sort,
                strongest=intent.strongest,
            )
            selected = _SelectedBattle(target, BattleTarget.ENEMY, "")
        elif isinstance(intent, ClearAnyEnemy):
            target, cleared, expected = self._any_enemy(
                runtime,
                intent.genres,
                sort=intent.sort,
                strongest=intent.strongest,
            )
            selected = _SelectedBattle(target, cleared, expected)
        else:
            target = self._priority_enemy(runtime, include_scale_1=intent.include_scale_1)
            selected = _SelectedBattle(target, BattleTarget.ENEMY, "")
        return selected

    def _issue_targeted(
        self,
        runtime: CampaignMapRuntime,
        attempt: BattleAttempt,
        intent: ClearChosenEnemy | ClearSelectedEnemy,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        if isinstance(intent, ClearChosenEnemy):
            target = self._cell(runtime, intent.target)
        else:
            target = self._selected_enemy(runtime, intent)
        return self._issue(
            runtime,
            attempt,
            self._expected_selection(target, intent.expected),
            cancellation,
        )

    @classmethod
    def _condition_matches(cls, runtime: CampaignMapRuntime, condition: BattleCondition) -> bool:
        if isinstance(condition, FlagCondition):
            return runtime.read_battle_flag(condition.flag) is condition.value
        if isinstance(condition, CellAccessibleCondition):
            grid = cls._cell(runtime, condition.cell)
            return grid is not None and grid.is_accessible
        if isinstance(condition, AllConditions):
            return all(cls._condition_matches(runtime, item) for item in condition.conditions)
        if isinstance(condition, AnyCondition):
            return any(cls._condition_matches(runtime, item) for item in condition.conditions)
        if isinstance(condition, NotCondition):
            return not cls._condition_matches(runtime, condition.condition)
        assert_never(condition)

    @staticmethod
    def _cell(runtime: CampaignMapRuntime, cell: CellId) -> CampaignGrid | None:
        return next(
            (grid for grid in runtime.map if grid.location == (cell.x, cell.y)),
            None,
        )

    @staticmethod
    def _expected_selection(
        target: CampaignGrid | None,
        expected: TargetExpectation,
    ) -> _SelectedBattle:
        if expected is TargetExpectation.SIREN:
            valid = target is not None and target.is_siren and target.is_accessible
            return _SelectedBattle(target if valid else None, BattleTarget.SIREN, "siren")
        valid = target is not None and _ordinary_enemy(target) and target.is_accessible
        return _SelectedBattle(target if valid else None, BattleTarget.ENEMY, "")

    @staticmethod
    def _enemy(
        runtime: CampaignMapRuntime,
        scales: tuple[int, ...],
        genres: tuple[str, ...],
        *,
        sort: tuple[str, ...] = (),
        strongest: bool,
    ) -> CampaignGrid | None:
        candidates = [
            grid
            for grid in runtime.map
            if _ordinary_enemy(grid)
            and grid.is_accessible
            and (not scales or grid.enemy_scale in scales)
            and (not genres or grid.enemy_genre in genres)
        ]
        ordered = ExistingCampaignMapAdapter._sort_enemies(candidates, sort=sort, strongest=strongest)
        return ordered[0] if ordered else None

    @staticmethod
    def _any_enemy(
        runtime: CampaignMapRuntime,
        genres: tuple[str, ...],
        *,
        sort: tuple[str, ...] = (),
        strongest: bool,
    ) -> tuple[CampaignGrid | None, BattleTarget, str]:
        candidates = [
            grid
            for grid in runtime.map
            if not grid.is_boss
            and (grid.is_enemy or grid.is_siren)
            and grid.is_accessible
            and (not genres or grid.enemy_genre in genres)
        ]
        candidates = ExistingCampaignMapAdapter._sort_enemies(candidates, sort=sort, strongest=strongest)
        target = candidates[0] if candidates else None
        if target is not None and target.is_siren:
            return target, BattleTarget.SIREN, "siren"
        return target, BattleTarget.ENEMY, ""

    @staticmethod
    def _sort_enemies(
        candidates: list[CampaignGrid],
        *,
        sort: tuple[str, ...],
        strongest: bool,
    ) -> list[CampaignGrid]:
        selected = candidates
        if strongest and selected:
            strongest_scale = max(grid.enemy_scale for grid in selected)
            selected = [grid for grid in selected if grid.enemy_scale == strongest_scale]
        if not sort:
            return _ordered(selected)
        return sorted(
            selected,
            key=lambda grid: (*tuple(_enemy_sort_value(grid, key) for key in sort), str(grid)),
        )

    @classmethod
    def _selected_enemy(
        cls,
        runtime: CampaignMapRuntime,
        intent: ClearSelectedEnemy,
    ) -> CampaignGrid | None:
        for cell in intent.candidates:
            grid = cls._cell(runtime, cell)
            if grid is None or grid.enemy_genre in intent.excluded_genres:
                continue
            selected = cls._expected_selection(grid, intent.expected)
            if selected.target is not None:
                return grid
        return None

    @classmethod
    def _priority_enemy(
        cls,
        runtime: CampaignMapRuntime,
        *,
        include_scale_1: bool,
    ) -> CampaignGrid | None:
        if include_scale_1:
            target = cls._enemy(runtime, (1,), (), strongest=False)
            if target is not None:
                return target
        priorities = (
            ((2,), ("LightInvertedOrthant", "MainInvertedOrthant")),
            ((3,), ("LightInvertedOrthant", "MainInvertedOrthant")),
            ((2,), ("Enemy", "CarrierInvertedOrthant")),
            ((3,), ("Enemy", "CarrierInvertedOrthant")),
        )
        for scales, genres in priorities:
            target = cls._enemy(runtime, scales, genres, strongest=False)
            if target is not None:
                return target
        return None

    def _issue_auto_search(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        attempt: BattleAttempt,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        cancellation.raise_if_requested()
        try:
            target = self._auto_search.execute(session, state, cancellation)
        except CampaignActionInterrupted as interruption:
            return BattleInterrupted(attempt, interruption.reason)
        if not isinstance(target, BattleTarget):
            message = "auto-search battle must return a confirmed BattleTarget"
            raise CampaignMapAdapterError(message)
        return BattleSucceeded(attempt, target)

    @staticmethod
    def _pending_attempt(
        session: CampaignSession,
        state: CampaignSessionState,
    ) -> BattleAttempt:
        if not isinstance(session, CampaignSession):
            message = "campaign map adapter requires a CampaignSession"
            raise TypeError(message)
        if not isinstance(state, CampaignSessionState):
            message = "campaign map adapter requires a CampaignSessionState"
            raise TypeError(message)
        session.validate_state(state)
        attempt = state.pending
        if attempt is None:
            message = "campaign battle state has no pending decision"
            raise CampaignMapAdapterError(message)
        return attempt

    def _runtime(
        self,
        session: CampaignSession,
        cancellation: CancellationSource,
    ) -> CampaignMapRuntime:
        cancellation.raise_if_requested()
        runtime = self._runtimes.active_runtime(session, cancellation)
        for method_name in (
            "full_scan",
            "find_path_initial",
            "clear_chosen_enemy",
            "brute_find_roadblocks",
            "read_battle_flag",
        ):
            _require_method(runtime, method_name, field_name="campaign map runtime")
        return runtime

    @staticmethod
    def _first(
        runtime: CampaignMapRuntime,
        predicate: Callable[[CampaignGrid], bool],
    ) -> CampaignGrid | None:
        candidates = _ordered(grid for grid in runtime.map if predicate(grid))
        return candidates[0] if candidates else None

    @staticmethod
    def _filtered_enemy(
        runtime: CampaignMapRuntime,
        session: CampaignSession,
        preserve: int,
    ) -> CampaignGrid | None:
        candidates = _ordered(grid for grid in runtime.map if _ordinary_enemy(grid) and grid.is_accessible)
        enemy_filter = Filter[CampaignGrid](regex=_ENEMY_FILTER_PATTERN, attr=("str",))
        enemy_filter.load(session.definition.enemy_filter)
        filtered = [grid for grid in enemy_filter.apply(candidates) if not isinstance(grid, str)]
        remaining = filtered[preserve:]
        return remaining[0] if remaining else None

    @classmethod
    def _default_target(
        cls,
        runtime: CampaignMapRuntime,
    ) -> tuple[CampaignGrid | None, BattleTarget, str]:
        enemy = cls._first(runtime, lambda grid: _ordinary_enemy(grid) and grid.is_accessible)
        if enemy is not None:
            return enemy, BattleTarget.ENEMY, ""
        siren = cls._first(runtime, lambda grid: grid.is_siren and grid.is_accessible)
        return siren, BattleTarget.SIREN, "siren"

    def _clear_boss_roadblock(
        self,
        runtime: CampaignMapRuntime,
        attempt: BattleAttempt,
        strategy: BossStrategy,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        if strategy not in (BossStrategy.MAP_SEARCH, BossStrategy.BRUTE_FORCE):
            message = f"unsupported boss roadblock strategy: {strategy.value}"
            raise CampaignMapAdapterError(message)
        boss = self._first(runtime, lambda grid: grid.is_boss)
        if boss is None:
            return NoBattleTarget(attempt)
        cancellation.raise_if_requested()
        roadblocks = runtime.brute_find_roadblocks(boss, fleet=runtime.fleet_boss_index)
        target = next(
            iter(_ordered(grid for grid in roadblocks if _ordinary_enemy(grid) and grid.is_accessible)),
            None,
        )
        if target is None:
            return NoBattleTarget(attempt)
        if strategy is BossStrategy.MAP_SEARCH:
            cancellation.raise_if_requested()
            executor = runtime.fleet_1
        elif strategy is BossStrategy.BRUTE_FORCE:
            executor = runtime
        else:
            assert_never(strategy)
        selected = _SelectedBattle(target, BattleTarget.ENEMY, "", executor)
        return self._issue(runtime, attempt, selected, cancellation)

    def _clear_boss(
        self,
        runtime: CampaignMapRuntime,
        attempt: BattleAttempt,
        strategy: BossStrategy,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        cancellation.raise_if_requested()
        if strategy in (BossStrategy.FLEET_BOSS, BossStrategy.BRUTE_FORCE):
            executor = runtime.fleet_boss
        elif strategy is BossStrategy.FLEET_1:
            executor = runtime.fleet_1
        elif strategy is BossStrategy.MAP_SEARCH:
            executor = runtime
        else:
            assert_never(strategy)
        target = self._first(runtime, lambda grid: grid.is_boss and grid.is_accessible)
        selected = _SelectedBattle(target, BattleTarget.BOSS, "boss", executor)
        return self._issue(runtime, attempt, selected, cancellation)

    @staticmethod
    def _issue(
        runtime: CampaignMapRuntime,
        attempt: BattleAttempt,
        selected: _SelectedBattle,
        cancellation: CancellationSource,
    ) -> BattleOutcome:
        if selected.target is None:
            return NoBattleTarget(attempt)
        executor = runtime if selected.executor is None else selected.executor
        before = runtime.battle_count
        action_error: Exception | None = None
        interruption: CampaignActionInterrupted | None = None
        try:
            cancellation.raise_if_requested()
            executor.clear_chosen_enemy(selected.target, expected=selected.expected)
        except CampaignActionInterrupted as error:
            interruption = error
        except Exception as error:  # ruff:ignore[blind-except] - battle_count 可证明异常前动作已经完成。
            action_error = error

        confirmed = runtime.battle_count - before
        if interruption is not None:
            if confirmed != 0:
                message = "interrupted campaign action must not confirm a battle"
                raise CampaignMapAdapterError(message) from interruption
            return BattleInterrupted(attempt, interruption.reason)
        if confirmed == 1:
            return BattleSucceeded(attempt, selected.cleared)
        if confirmed != 0:
            message = f"one campaign intent changed battle_count by {confirmed}, expected exactly one"
            raise CampaignMapAdapterError(message) from action_error
        if action_error is not None:
            raise action_error
        return BattleFailed(attempt, _UNCONFIRMED_ACTION)


def build_existing_campaign_map_workflow(
    runtimes: CampaignRuntimeUnitSource,
    auto_search: CampaignAutoSearchBattleExecutor,
    services: CampaignLiveServices,
    clock: CampaignLiveClock | None = None,
) -> LiveCampaignWorkflow:
    """构造可直接注入 CampaignFactoryDependencies 的完整 live workflow。"""
    if not isinstance(services, CampaignLiveServices) or services.activator is None:
        message = "campaign map workflow services require an activator"
        raise TypeError(message)
    adapter = ExistingCampaignMapAdapter(runtimes, auto_search)
    return LiveCampaignWorkflow(
        adapter,
        adapter,
        clock,
        services=services,
    )
