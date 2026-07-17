from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, assert_never, cast

from module.base.decorator import del_cached_property
from module.base.timer import Timer
from module.content import battle_program as program_model
from module.content.battle_policy import (
    AllConditions,
    AnyCondition,
    BattleFlag,
    BattleStep,
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
from module.content.mechanic_rules import (
    AirStrike,
    BreakSirenCaught,
    ClearAllMystery,
    ClearChosenMystery,
    ClearMapItems,
    ClearMechanism,
    EncounterExpectation,
    EnsureFleet,
    EnsureFleetAt,
    FleetClearTarget,
    FleetRole,
    MapItemKind,
    MechanicOperation,
    MechanicProcedure,
    MoveEnemy,
    MoveFleet,
    MoveFleetToBestCandidate,
    PickupAmmo,
    PickupMapItem,
    ProtectFleet,
    PushFleetForward,
    RescueFleet,
    RoadblockAction,
    RoadblockMode,
    RoadblockSelection,
    RoadPath,
    StepFleetOn,
    SwitchFleet,
)
from module.exception import MapEnemyMoved
from module.gameplay.battle_program import (
    BattleActionOutcome,
    MechanicActionOutcome,
    MechanicApplied,
    MechanicFailed,
    MechanicNotApplied,
    MechanicSettled,
)
from module.handler.assets import AIR_STRIKE_CONFIRM, STRATEGY_OPENED
from module.handler.strategy import AIR_STRIKE_OFFSET, MOB_MOVE_OFFSET
from module.map.map_grids import RoadGrids, SelectedGrids

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.adapters.campaign_live import CampaignMapRuntime
    from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
    from module.application import CancellationSource
    from module.content.cell import CellId
    from module.map_detection.grid import Grid
    from module.map_detection.grid_info import GridInfo


_UNCONFIRMED_BATTLE = "battle primitive reported success without advancing battle_count"
_PRIORITY_ENEMIES = (
    ((2,), ("LightInvertedOrthant", "MainInvertedOrthant")),
    ((3,), ("LightInvertedOrthant", "MainInvertedOrthant")),
    ((2,), ("Enemy", "CarrierInvertedOrthant")),
    ((3,), ("Enemy", "CarrierInvertedOrthant")),
)


@dataclass(frozen=True, slots=True)
class _BattlePrimitiveOutcome:
    applied: bool
    target: program_model.ProgramBattleTarget = program_model.ProgramBattleTarget.ENEMY
    advances_wave: bool = True


@dataclass(frozen=True, slots=True)
class _NoBattleTarget:
    pass


@dataclass(frozen=True, slots=True)
class _MechanicActionContext:
    settled_target: program_model.ProgramBattleTarget
    resolved_grid: GridInfo | None = None


type _BattleHandlerOutcome = _BattlePrimitiveOutcome | _NoBattleTarget
type _FleetMechanicAction = (
    BreakSirenCaught
    | PushFleetForward
    | ProtectFleet
    | RescueFleet
    | StepFleetOn
    | MoveFleet
    | MoveFleetToBestCandidate
    | SwitchFleet
    | EnsureFleet
    | EnsureFleetAt
    | FleetClearTarget
)
type _PickupMechanicAction = PickupAmmo | PickupMapItem
type _MapInteractionMechanicAction = ClearAllMystery | ClearChosenMystery | ClearMechanism | ClearMapItems | AirStrike


class BattleProgramMumu12AdapterError(RuntimeError):
    """声明式战斗程序与 MuMu12 地图运行时之间的固定适配错误。"""


class RuntimeProgramState(Protocol):
    """不能从静态 profile 推断的当前地图运行事实。"""

    def map_has_mob_move(self, cancellation: CancellationSource) -> bool: ...

    def use_single_fleet_override(self, cancellation: CancellationSource) -> bool | None: ...

    def use_support_fleet(self, cancellation: CancellationSource) -> bool: ...


class Mumu12BattleProgramPort:
    """把封闭的 BattleProgram AST 显式投影到固定 CampaignMapRuntime 原语。"""

    __slots__ = ("_program_state", "_runtime")

    def __init__(self, runtime: CampaignMapRuntime, program_state: RuntimeProgramState) -> None:
        self._runtime = cast("DeclarativeCampaignMapRuntime", runtime)
        self._program_state = program_state

    def initial_flags(self, cancellation: CancellationSource) -> frozenset[program_model.ProgramFlag]:
        cancellation.raise_if_requested()
        runtime = self._runtime
        single_fleet_override = self._program_state.use_single_fleet_override(cancellation)
        if single_fleet_override is not None and type(single_fleet_override) is not bool:
            message = "runtime program state use_single_fleet_override() must return bool or None"
            raise BattleProgramMumu12AdapterError(message)
        use_single_fleet = not bool(runtime.config.fleet_2) if single_fleet_override is None else single_fleet_override
        flags = {
            flag
            for enabled, flag in (
                (runtime.map_is_clear_mode, program_model.ProgramFlag.CLEAR_MODE),
                (runtime.config.MAP_CLEAR_ALL_THIS_TIME, program_model.ProgramFlag.CLEAR_ALL),
                (runtime.config.POOR_MAP_DATA, program_model.ProgramFlag.POOR_MAP_DATA),
                (use_single_fleet, program_model.ProgramFlag.USE_SINGLE_FLEET),
                (runtime.config.MAP_HAS_MOVABLE_ENEMY, program_model.ProgramFlag.MOVABLE_ENEMY),
                (
                    runtime.config.MAP_HAS_MOVABLE_NORMAL_ENEMY,
                    program_model.ProgramFlag.MOVABLE_NORMAL_ENEMY,
                ),
            )
            if enabled
        }
        cancellation.raise_if_requested()
        map_has_mob_move = self._program_state.map_has_mob_move(cancellation)
        if type(map_has_mob_move) is not bool:
            message = "runtime program state map_has_mob_move() must return bool"
            raise BattleProgramMumu12AdapterError(message)
        if map_has_mob_move:
            flags.add(program_model.ProgramFlag.MAP_HAS_MOB_MOVE)
        cancellation.raise_if_requested()
        use_support_fleet = self._program_state.use_support_fleet(cancellation)
        if type(use_support_fleet) is not bool:
            message = "runtime program state use_support_fleet() must return bool"
            raise BattleProgramMumu12AdapterError(message)
        if use_support_fleet:
            flags.add(program_model.ProgramFlag.USE_SUPPORT_FLEET)
        return frozenset(flags)

    def read_metric(
        self,
        metric: program_model.ProgramMetric,
        cancellation: CancellationSource,
    ) -> int:
        cancellation.raise_if_requested()
        runtime = self._runtime
        if metric is program_model.ProgramMetric.BATTLE_COUNT:
            return runtime.battle_count
        if metric is program_model.ProgramMetric.FLEET_STEP:
            return runtime.fleet_step
        if metric is program_model.ProgramMetric.MYSTERY_COUNT:
            return runtime.mystery_count
        if metric is program_model.ProgramMetric.FLEET_BOSS_INDEX:
            return runtime.fleet_boss_index
        if metric is program_model.ProgramMetric.CONFIGURED_BOSS_FLEET:
            return runtime.config.fleet_boss
        assert_never(metric)

    def read_cell_property(
        self,
        cell: CellId,
        cell_property: program_model.CellProperty,
        cancellation: CancellationSource,
    ) -> program_model.CellPropertyValue:
        cancellation.raise_if_requested()
        grid = self._grid(cell)
        if cell_property is program_model.CellProperty.ACCESSIBLE:
            return bool(grid.is_accessible)
        if cell_property is program_model.CellProperty.ENEMY_SCALE:
            value = grid.enemy_scale
            if type(value) is not int:
                message = f"{cell}.enemy_scale is not an integer"
                raise BattleProgramMumu12AdapterError(message)
            return value
        if cell_property is program_model.CellProperty.ENEMY_GENRE:
            value = grid.enemy_genre
            if value is None:
                return ""
            if not isinstance(value, str):
                message = f"{cell}.enemy_genre is not a string"
                raise BattleProgramMumu12AdapterError(message)
            return value
        if cell_property is program_model.CellProperty.IS_MYSTERY:
            return bool(grid.is_mystery)
        assert_never(cell_property)

    def is_fleet_at(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        return self._runtime.fleet_at(self._grid(cell), fleet=self._fleet_index(fleet))

    def has_map_presence(
        self,
        presence: program_model.MapPresence,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        if presence is program_model.MapPresence.BOSS:
            return bool(self._runtime.map.select(is_boss=True))
        if presence is program_model.MapPresence.SIREN:
            return bool(self._runtime.map.select(is_siren=True))
        if presence is program_model.MapPresence.ENEMY:
            return bool(self._runtime.map.select(is_enemy=True))
        if presence is program_model.MapPresence.NON_BOSS_TARGET:
            remain = (
                self._runtime.map.select(is_enemy=True)
                .add(self._runtime.map.select(is_siren=True))
                .add(self._runtime.map.select(is_fortress=True))
                .delete(self._runtime.map.select(is_boss=True))
            )
            return bool(remain)
        assert_never(presence)

    def is_boss_at(self, cell: CellId, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        return bool(self._grid(cell).is_boss)

    def is_boss_accessible(
        self,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        boss = self._runtime.map.select(is_boss=True)
        if not boss:
            return False
        return self._runtime.check_accessibility(boss[0], fleet=self._fleet_argument(fleet))

    def is_cell_accessible_for_fleet(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        return self._runtime.check_accessibility(
            self._grid(cell),
            fleet=self._fleet_argument(fleet),
        )

    def has_candidate_enemy(
        self,
        candidates: tuple[CellId, ...],
        excluded_genres: tuple[str, ...],
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        return any(
            grid.is_enemy and grid.enemy_genre not in excluded_genres
            for grid in (self._grid(cell) for cell in candidates)
        )

    def execute_battle(
        self,
        action: BattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        cancellation.raise_if_requested()
        before = self._runtime.battle_count
        if isinstance(action, GuardedBattleStep):
            if not self._battle_condition(action.condition, cancellation):
                return program_model.ProgramNoTarget()
            action = action.step
        target = self._battle_action_target(action)
        try:
            return self._execute_unguarded_battle(action, cancellation)
        except Exception:
            delta = self._runtime.battle_count - before
            if delta == 1:
                return program_model.ProgramBattleSettled(
                    target,
                    advances_wave=not isinstance(action, ClearBossRoadblock),
                )
            if delta != 0:
                return program_model.ProgramFailed(
                    f"one battle action changed battle_count by {delta}, expected zero or one"
                )
            raise

    def execute_mechanic(
        self,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        before = self._runtime.battle_count
        # 运行时原语可能在抛出终止异常前清空网格标记，结算事实必须使用调用前快照。
        context = self._mechanic_action_context(action)
        try:
            return self._dispatch_mechanic_action(action, context, cancellation)
        except Exception:
            delta = self._runtime.battle_count - before
            if delta == 1:
                return MechanicSettled(context.settled_target)
            if delta != 0:
                return MechanicFailed(f"mechanic action changed battle_count by {delta}, expected zero or one")
            raise

    def _dispatch_mechanic_action(
        self,
        action: program_model.ProgramMechanicAction,
        context: _MechanicActionContext,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        if isinstance(action, RoadblockAction):
            return self._roadblock(action, cancellation)
        if isinstance(
            action,
            BreakSirenCaught
            | PushFleetForward
            | ProtectFleet
            | RescueFleet
            | StepFleetOn
            | MoveFleet
            | MoveFleetToBestCandidate
            | SwitchFleet
            | EnsureFleet
            | EnsureFleetAt
            | FleetClearTarget,
        ):
            return self._dispatch_fleet_mechanic_action(action, context, cancellation)
        if isinstance(action, PickupAmmo | PickupMapItem):
            return self._dispatch_pickup_mechanic_action(action, cancellation)
        if isinstance(action, ClearAllMystery | ClearChosenMystery | ClearMechanism | ClearMapItems | AirStrike):
            return self._dispatch_map_interaction_action(action, cancellation)
        if isinstance(action, MoveEnemy):
            return self._move_enemy(action, cancellation)
        if isinstance(action, MechanicProcedure):
            return self._procedure(action, cancellation)
        assert_never(action)

    def _dispatch_fleet_mechanic_action(  # ruff:ignore[complex-structure] - 封闭的舰队机制联合类型必须在单一边界穷举。
        self,
        action: _FleetMechanicAction,
        context: _MechanicActionContext,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        if isinstance(action, BreakSirenCaught):
            outcome = self._break_siren_caught(action, cancellation)
        elif isinstance(action, PushFleetForward):
            outcome = self._push_forward(action, cancellation)
        elif isinstance(action, ProtectFleet):
            outcome = self._protect(action, cancellation)
        elif isinstance(action, RescueFleet):
            outcome = self._rescue(action, cancellation)
        elif isinstance(action, StepFleetOn):
            outcome = self._step_on(action, cancellation)
        elif isinstance(action, MoveFleet | MoveFleetToBestCandidate):
            outcome = self._move_fleet(action, context, cancellation)
        elif isinstance(action, SwitchFleet):
            outcome = self._switch_fleet(action, cancellation)
        elif isinstance(action, EnsureFleet):
            outcome = self._ensure_fleet(action, cancellation)
        elif isinstance(action, EnsureFleetAt):
            outcome = self._ensure_fleet_at(action, cancellation)
        elif isinstance(action, FleetClearTarget):
            outcome = self._fleet_clear_target(action, context, cancellation)
        else:
            assert_never(action)
        return outcome

    def _dispatch_pickup_mechanic_action(
        self,
        action: _PickupMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        if isinstance(action, PickupAmmo):
            return self._pickup_ammo(action, cancellation)
        if isinstance(action, PickupMapItem):
            return self._pickup_map_item(action, cancellation)
        assert_never(action)

    def _dispatch_map_interaction_action(
        self,
        action: _MapInteractionMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        if isinstance(action, ClearAllMystery):
            return self._clear_all_mystery(action, cancellation)
        if isinstance(action, ClearChosenMystery):
            return self._clear_chosen_mystery(action, cancellation)
        if isinstance(action, ClearMechanism):
            return self._clear_mechanism(action, cancellation)
        if isinstance(action, ClearMapItems):
            return self._clear_map_items(action, cancellation)
        if isinstance(action, AirStrike):
            return self._air_strike(action, cancellation)
        assert_never(action)

    def execute_preset_route(  # ruff:ignore[complex-structure] - 固定路线的重试与事实闭合必须同处一个状态机。
        self,
        action: program_model.ExecutePresetRoute,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        self._require_current_battle(action.battle, operation="preset route")
        start = self._fleet_location(FleetRole.FLEET_1)
        route = next((item for item in action.routes if item.start_column == start[0]), None)
        if route is None:
            message = f"no preset route for fleet_1 start column {start[0]}"
            raise BattleProgramMumu12AdapterError(message)
        route_battle = next((item for item in route.battles if item.battle == action.battle), None)
        if route_battle is None:
            return MechanicNotApplied()

        before = self._runtime.battle_count
        moved = False
        settled_target = program_model.ProgramBattleTarget.ENEMY
        for step in route_battle.steps:
            origin = self._fleet_location(step.fleet)
            destination = (origin[0] + step.delta_x, origin[1] + step.delta_y)
            target = self._runtime.map[destination]
            settled_target = self._target_for_grid(target)
            executor = self._fleet_runtime(step.fleet, cancellation)
            for _ in range(3):
                cancellation.raise_if_requested()
                try:
                    if step.clear_enemy:
                        executor.clear_chosen_enemy(target, expected=self._expected_for_grid(target))
                    else:
                        executor.goto(target)
                except Exception:
                    delta = self._runtime.battle_count - before
                    if delta == 1:
                        return MechanicSettled(settled_target)
                    if delta != 0:
                        return MechanicFailed(f"preset route changed battle_count by {delta}, expected zero or one")
                    raise
                current = self._fleet_location(step.fleet)
                if current not in (origin, destination):
                    message = (
                        f"preset route {step.fleet.value} moved outside its contract: "
                        f"{origin} -> {destination}, actual={current}"
                    )
                    raise BattleProgramMumu12AdapterError(message)
                if current == destination:
                    moved = True
                    break
            else:
                message = f"preset route failed to move {step.fleet.value}: {origin} -> {destination}"
                raise BattleProgramMumu12AdapterError(message)
        return self._mechanic_fact(
            before,
            applied=moved,
            target=settled_target,
            operation="preset route",
        )

    def execute_fixed_target(
        self,
        action: program_model.ExecuteFixedTarget,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        self._require_current_battle(action.battle, operation="fixed target")
        for sequence in action.sequences:
            if action.battle not in sequence.battles:
                continue
            for cell in sequence.targets:
                grid = self._grid(cell)
                if not (grid.is_enemy or grid.is_siren or grid.is_boss):
                    continue
                executor = self._fleet_runtime(sequence.fleet, cancellation)
                before = self._runtime.battle_count
                target = self._target_for_grid(grid)
                cancellation.raise_if_requested()
                try:
                    executor.clear_chosen_enemy(grid, expected=self._expected_for_grid(grid))
                except Exception:
                    delta = self._runtime.battle_count - before
                    if delta == 1:
                        return MechanicSettled(target)
                    if delta != 0:
                        return MechanicFailed(f"fixed target changed battle_count by {delta}, expected zero or one")
                    raise
                return self._mechanic_fact(
                    before,
                    applied=True,
                    target=target,
                    operation="fixed target",
                )
        return MechanicNotApplied()

    def mark_all_siren_candidates(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        for grid in self._runtime.map:
            grid.may_siren = True

    def set_map_weights(
        self,
        rows: tuple[tuple[int, ...], ...],
        cancellation: CancellationSource,
    ) -> None:
        cancellation.raise_if_requested()
        shape = self._runtime.definition.map.shape
        if len(rows) != shape.rows or any(len(row) != shape.columns for row in rows):
            message = f"map weight matrix must be {shape.rows}x{shape.columns}, got {len(rows)} rows"
            raise BattleProgramMumu12AdapterError(message)
        for y, row in enumerate(rows):
            for x, weight in enumerate(row):
                self._runtime.map[(x, y)].weight = weight

    def _execute_unguarded_battle(
        self,
        action: UnguardedBattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        before = self._runtime.battle_count
        outcome = self._dispatch_battle_action(action, cancellation)
        if isinstance(outcome, _NoBattleTarget):
            return program_model.ProgramNoTarget()
        return self._battle_fact(
            before,
            applied=outcome.applied,
            target=outcome.target,
            advances_wave=outcome.advances_wave,
        )

    def _dispatch_battle_action(  # ruff:ignore[complex-structure] - 封闭 union 在单一边界穷举，新增成员会触发静态检查。
        self,
        action: UnguardedBattleStep,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        if isinstance(action, ClearSiren):
            outcome = self._handle_clear_siren(action, cancellation)
        elif isinstance(action, ClearFilteredEnemy):
            outcome = self._handle_clear_filtered_enemy(action, cancellation)
        elif isinstance(action, ClearEnemy):
            outcome = self._handle_clear_enemy(action, cancellation)
        elif isinstance(action, ClearAnyEnemy):
            outcome = self._handle_clear_any_enemy(action, cancellation)
        elif isinstance(action, ClearChosenEnemy):
            outcome = self._handle_clear_chosen_enemy(action, cancellation)
        elif isinstance(action, ClearSelectedEnemy):
            outcome = self._handle_clear_selected_enemy(action, cancellation)
        elif isinstance(action, ClearPriorityEnemy):
            outcome = self._handle_clear_priority_enemy(action, cancellation)
        elif isinstance(action, DefaultBattle):
            outcome = self._handle_default_battle(cancellation)
        elif isinstance(action, ClearBossRoadblock):
            outcome = self._handle_clear_boss_roadblock(action, cancellation)
        elif isinstance(action, ClearBoss):
            outcome = self._handle_clear_boss(action, cancellation)
        else:
            assert_never(action)
        return outcome

    def _handle_clear_siren(
        self,
        action: ClearSiren,
        cancellation: CancellationSource,
    ) -> _BattlePrimitiveOutcome:
        if action.include_hidden_candidates:
            self.mark_all_siren_candidates(cancellation)
        cancellation.raise_if_requested()
        return _BattlePrimitiveOutcome(
            applied=bool(self._runtime.clear_siren(genre=action.genres)),
            target=program_model.ProgramBattleTarget.SIREN,
        )

    def _handle_clear_filtered_enemy(
        self,
        action: ClearFilteredEnemy,
        cancellation: CancellationSource,
    ) -> _BattlePrimitiveOutcome:
        enemy_filter = action.enemy_filter or self._runtime.definition.enemy_filter
        cancellation.raise_if_requested()
        return _BattlePrimitiveOutcome(
            applied=bool(self._runtime.clear_filter_enemy(enemy_filter, preserve=action.preserve)),
        )

    def _handle_clear_enemy(
        self,
        action: ClearEnemy,
        cancellation: CancellationSource,
    ) -> _BattlePrimitiveOutcome:
        cancellation.raise_if_requested()
        return _BattlePrimitiveOutcome(
            applied=bool(
                self._runtime.clear_enemy(
                    scale=action.scales,
                    genre=action.genres,
                    sort=action.sort,
                    strongest=action.strongest,
                )
            ),
        )

    def _handle_clear_any_enemy(
        self,
        action: ClearAnyEnemy,
        cancellation: CancellationSource,
    ) -> _BattlePrimitiveOutcome:
        cancellation.raise_if_requested()
        return _BattlePrimitiveOutcome(
            applied=bool(
                self._runtime.clear_any_enemy(
                    genre=action.genres,
                    sort=action.sort,
                    strongest=action.strongest,
                )
            ),
        )

    def _handle_clear_chosen_enemy(
        self,
        action: ClearChosenEnemy,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        grid = self._grid(action.target)
        if not grid.is_accessible:
            return _NoBattleTarget()
        cancellation.raise_if_requested()
        return _BattlePrimitiveOutcome(
            applied=bool(
                self._runtime.clear_chosen_enemy(
                    grid,
                    expected=self._target_expected(action.expected),
                )
            ),
            target=self._target_from_expectation(action.expected),
        )

    def _handle_clear_selected_enemy(
        self,
        action: ClearSelectedEnemy,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        grid = next(
            (
                self._grid(cell)
                for cell in action.candidates
                if self._candidate_is_clearable(
                    self._grid(cell),
                    action.excluded_genres,
                    action.expected,
                )
            ),
            None,
        )
        if grid is None:
            return _NoBattleTarget()
        cancellation.raise_if_requested()
        return _BattlePrimitiveOutcome(
            applied=bool(
                self._runtime.clear_chosen_enemy(
                    grid,
                    expected=self._target_expected(action.expected),
                )
            ),
            target=self._target_from_expectation(action.expected),
        )

    def _handle_clear_priority_enemy(
        self,
        action: ClearPriorityEnemy,
        cancellation: CancellationSource,
    ) -> _BattlePrimitiveOutcome:
        return _BattlePrimitiveOutcome(
            applied=self._clear_priority_enemy(action, cancellation),
        )

    def _handle_default_battle(
        self,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        grid = self._default_target()
        if grid is None:
            return _NoBattleTarget()
        target = self._target_for_grid(grid)
        expected = self._expected_for_grid(grid)
        cancellation.raise_if_requested()
        return _BattlePrimitiveOutcome(
            applied=bool(
                self._runtime.clear_chosen_enemy(
                    grid,
                    expected=expected,
                )
            ),
            target=target,
        )

    def _handle_clear_boss_roadblock(
        self,
        action: ClearBossRoadblock,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        runtime = self._runtime
        boss = runtime.map.select(is_boss=True)
        if not boss:
            return _NoBattleTarget()
        cancellation.raise_if_requested()
        roadblocks = runtime.brute_find_roadblocks(boss[0], fleet=runtime.fleet_boss_index)
        grids = roadblocks.select(is_enemy=True, is_accessible=True).sort("weight", "cost")
        if not grids:
            return _NoBattleTarget()
        cancellation.raise_if_requested()
        if action.strategy is BossStrategy.MAP_SEARCH:
            applied = bool(runtime.fleet_1.clear_chosen_enemy(grids[0]))
        elif action.strategy is BossStrategy.BRUTE_FORCE:
            applied = bool(runtime.clear_chosen_enemy(grids[0]))
        else:
            message = f"unsupported boss roadblock strategy: {action.strategy.value}"
            raise BattleProgramMumu12AdapterError(message)
        return _BattlePrimitiveOutcome(
            applied=applied,
            target=program_model.ProgramBattleTarget.ENEMY,
            advances_wave=False,
        )

    def _handle_clear_boss(
        self,
        action: ClearBoss,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        runtime = self._runtime
        bosses = runtime.map.select(is_boss=True, is_accessible=True).sort("weight", "cost")
        if not bosses:
            return _NoBattleTarget()
        cancellation.raise_if_requested()
        if action.strategy in (BossStrategy.FLEET_BOSS, BossStrategy.BRUTE_FORCE):
            executor = runtime.fleet_boss
        elif action.strategy is BossStrategy.FLEET_1:
            executor = runtime.fleet_1
        elif action.strategy is BossStrategy.MAP_SEARCH:
            executor = runtime
        else:
            assert_never(action.strategy)
        return _BattlePrimitiveOutcome(
            applied=bool(executor.clear_chosen_enemy(bosses[0], expected="boss")),
            target=program_model.ProgramBattleTarget.BOSS,
        )

    def _roadblock(
        self,
        action: RoadblockAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        runtime = self._runtime
        roads = tuple(self._road_group(road.paths) for road in action.roads)
        selection = self._selection_keywords(action.selection)
        before = runtime.battle_count
        cancellation.raise_if_requested()
        if action.mode is RoadblockMode.CLEAR:
            applied = bool(runtime.clear_roadblocks(roads, **selection))
        elif action.mode is RoadblockMode.CLEAR_POTENTIAL:
            applied = bool(runtime.clear_potential_roadblocks(roads, **selection))
        elif action.mode is RoadblockMode.CLEAR_FIRST:
            applied = bool(runtime.clear_first_roadblocks(roads, **selection))
        elif action.mode is RoadblockMode.CLEAR_FOR_FASTER:
            grids = SelectedGrids([self._grid(cell) for road in action.roads for cell in road.referenced_cells])
            applied = bool(runtime.clear_grids_for_faster(grids, **selection))
        else:
            assert_never(action.mode)
        return self._mechanic_fact(
            before,
            applied=applied,
            target=program_model.ProgramBattleTarget.ENEMY,
            operation=f"roadblock {action.mode.value}",
        )

    def _push_forward(
        self,
        action: PushFleetForward,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        self._require_fleet_2(action.fleet, operation="push forward")
        before = self._runtime.battle_count
        cancellation.raise_if_requested()
        applied = bool(self._runtime.fleet_2_push_forward())
        return self._mechanic_fact(before, applied=applied, operation="push forward")

    def _break_siren_caught(
        self,
        action: BreakSirenCaught,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        self._require_current_battle(action.battle, operation="break siren caught")
        self._require_fleet_2(action.fleet, operation="break siren caught")
        before = self._runtime.battle_count
        cancellation.raise_if_requested()
        try:
            applied = bool(self._runtime.fleet_2_break_siren_caught())
        except Exception:
            delta = self._runtime.battle_count - before
            if delta == 1:
                return MechanicSettled(program_model.ProgramBattleTarget.SIREN)
            if delta != 0:
                return MechanicFailed(f"break siren caught changed battle_count by {delta}, expected zero or one")
            raise
        delta = self._runtime.battle_count - before
        if delta == 1:
            return MechanicSettled(program_model.ProgramBattleTarget.SIREN)
        if delta != 0:
            return MechanicFailed(f"break siren caught changed battle_count by {delta}, expected zero or one")
        if applied:
            return MechanicFailed("break siren caught reported success without advancing battle_count")
        return MechanicNotApplied()

    def _protect(
        self,
        action: ProtectFleet,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        self._require_fleet_2(action.fleet, operation="protect fleet")
        before = self._runtime.battle_count
        cancellation.raise_if_requested()
        applied = bool(self._runtime.fleet_2_protect())
        return self._mechanic_fact(
            before,
            applied=applied,
            target=program_model.ProgramBattleTarget.SIREN,
            operation="protect fleet",
        )

    def _rescue(
        self,
        action: RescueFleet,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        self._require_fleet_2(action.fleet, operation="rescue fleet")
        before = self._runtime.battle_count
        cancellation.raise_if_requested()
        applied = bool(self._runtime.fleet_2_rescue(self._grid(action.target)))
        return self._mechanic_fact(
            before,
            applied=applied,
            target=program_model.ProgramBattleTarget.ENEMY,
            operation="rescue fleet",
        )

    def _step_on(
        self,
        action: StepFleetOn,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        self._require_fleet_2(action.fleet, operation="step fleet on")
        candidates = SelectedGrids([self._grid(cell) for cell in action.candidates])
        roads = tuple(self._road_group(road.paths) for road in action.roadblocks)
        before = self._runtime.battle_count
        cancellation.raise_if_requested()
        applied = bool(self._runtime.fleet_2_step_on(candidates, roads))
        return self._mechanic_fact(
            before,
            applied=applied,
            target=program_model.ProgramBattleTarget.ENEMY,
            operation="step fleet on",
        )

    def _move_fleet(
        self,
        action: MoveFleet | MoveFleetToBestCandidate,
        context: _MechanicActionContext,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        grid = context.resolved_grid
        if grid is None:
            message = "move fleet mechanic has no resolved target grid"
            raise AssertionError(message)
        return self._move_fleet_to_grid(
            fleet=action.fleet,
            expected=action.expected,
            grid=grid,
            target=context.settled_target,
            cancellation=cancellation,
        )

    def _move_fleet_to_grid(
        self,
        *,
        fleet: FleetRole,
        expected: EncounterExpectation,
        grid: GridInfo,
        target: program_model.ProgramBattleTarget,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        executor = self._fleet_runtime(fleet, cancellation)
        before = self._runtime.battle_count
        origin = self._fleet_location(fleet)
        cancellation.raise_if_requested()
        executor.goto(grid, expected=self._encounter_expected(expected))
        moved = self._fleet_location(fleet) != origin
        return self._mechanic_fact(
            before,
            applied=moved,
            target=target,
            operation="move fleet",
        )

    def _best_fleet_move_candidate(self, action: MoveFleetToBestCandidate) -> GridInfo:
        candidates = SelectedGrids([self._grid(cell) for cell in action.candidates])
        return candidates.sort(*(key.value for key in action.sort))[0]

    def _switch_fleet(
        self,
        action: SwitchFleet,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        before = self._runtime.fleet_current_index
        executor = self._fleet_runtime(action.fleet, cancellation)
        cancellation.raise_if_requested()
        executor.switch_to()
        return MechanicApplied() if self._runtime.fleet_current_index != before else MechanicNotApplied()

    def _ensure_fleet(
        self,
        action: EnsureFleet,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        index = self._fleet_index(action.fleet)
        if index is None:
            return MechanicNotApplied()
        before = self._runtime.fleet_current_index
        cancellation.raise_if_requested()
        changed = bool(self._runtime.fleet_ensure(index))
        if self._runtime.fleet_current_index != index:
            message = f"fleet_ensure({index}) did not select the requested fleet"
            raise BattleProgramMumu12AdapterError(message)
        return MechanicApplied() if changed or before != index else MechanicNotApplied()

    def _ensure_fleet_at(
        self,
        action: EnsureFleetAt,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        if self._runtime.fleet_at(self._grid(action.target), fleet=self._fleet_index(action.fleet)):
            return MechanicApplied()
        return MechanicNotApplied()

    def _fleet_clear_target(
        self,
        action: FleetClearTarget,
        context: _MechanicActionContext,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        executor = self._fleet_runtime(action.fleet, cancellation)
        before = self._runtime.battle_count
        grid = context.resolved_grid
        if grid is None:
            message = "fleet clear target mechanic has no resolved target grid"
            raise AssertionError(message)
        if not grid.is_accessible:
            return MechanicNotApplied()
        cancellation.raise_if_requested()
        applied = bool(executor.clear_chosen_enemy(grid, expected=self._clear_expected(action.expected)))
        return self._mechanic_fact(
            before,
            applied=applied,
            target=context.settled_target,
            operation="fleet clear target",
        )

    def _pickup_ammo(
        self,
        action: PickupAmmo,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        executor = self._fleet_runtime(action.fleet, cancellation)
        cancellation.raise_if_requested()
        return MechanicApplied() if executor.pick_up_ammo() else MechanicNotApplied()

    def _pickup_map_item(
        self,
        action: PickupMapItem,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        grid = self._grid(action.cell)
        if action.kind is MapItemKind.FLARE:
            grid.is_flare = True
        elif action.kind is not MapItemKind.LIGHT_HOUSE:
            assert_never(action.kind)
        if not grid.is_accessible or self.is_fleet_at(action.cell, action.fleet, cancellation):
            return MechanicNotApplied()
        executor = self._fleet_runtime(action.fleet, cancellation)
        origin = self._fleet_location(action.fleet)
        cancellation.raise_if_requested()
        executor.goto(grid)
        if action.kind is MapItemKind.LIGHT_HOUSE:
            cancellation.raise_if_requested()
            executor.ensure_no_info_bar()
        return MechanicApplied() if self._fleet_location(action.fleet) != origin else MechanicNotApplied()

    def _clear_all_mystery(
        self,
        action: ClearAllMystery,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        ignored = SelectedGrids([self._grid(cell) for cell in action.ignored])
        candidates = self._runtime.map.select(is_mystery=True)
        candidates = candidates.delete(ignored)
        if action.nearby:
            candidates = candidates.select(is_nearby=True)
        if not candidates:
            return MechanicNotApplied()
        before = self._runtime.battle_count
        cancellation.raise_if_requested()
        self._runtime.clear_all_mystery(nearby=action.nearby, ignore=ignored)
        return self._mechanic_fact(before, applied=True, operation="clear all mystery")

    def _clear_chosen_mystery(
        self,
        action: ClearChosenMystery,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        grid = self._grid(action.cell)
        if not grid.is_mystery:
            return MechanicNotApplied()
        executor = self._fleet_runtime(action.fleet, cancellation)
        before = self._runtime.battle_count
        cancellation.raise_if_requested()
        executor.clear_chosen_mystery(grid)
        return self._mechanic_fact(before, applied=True, operation="clear chosen mystery")

    def _clear_mechanism(
        self,
        action: ClearMechanism,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        selected = SelectedGrids([self._grid(cell) for cell in action.cells]) if action.cells else None
        limit = len(action.cells) if action.cells else self._runtime.map.select(is_mechanism_trigger=True).count
        applied = False
        for _ in range(limit):
            cancellation.raise_if_requested()
            try:
                changed = bool(self._runtime.clear_mechanism(selected))
            except MapEnemyMoved:
                applied = True
                cancellation.raise_if_requested()
                self._runtime.full_scan()
                cancellation.raise_if_requested()
                self._runtime.find_path_initial()
                continue
            return MechanicApplied() if applied or changed else MechanicNotApplied()
        return MechanicApplied() if applied else MechanicNotApplied()

    def _clear_map_items(
        self,
        action: ClearMapItems,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        grids = SelectedGrids([self._grid(cell) for cell in action.cells]).sort("cost")
        moved = False
        for grid in grids:
            before = self._runtime.fleet_current
            cancellation.raise_if_requested()
            self._runtime.goto(grid)
            moved = moved or self._runtime.fleet_current != before
        return MechanicApplied() if moved else MechanicNotApplied()

    def _air_strike(
        self,
        action: AirStrike,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        grid = self._grid(action.target)
        if grid.is_land:
            return MechanicNotApplied()
        cancellation.raise_if_requested()
        self._runtime.strategy_open()
        if not self._runtime.strategy_has_air_strike():
            cancellation.raise_if_requested()
            self._runtime.strategy_close()
            return MechanicNotApplied()
        cancellation.raise_if_requested()
        self._runtime.strategy_air_strike_enter()
        cancellation.raise_if_requested()
        self._runtime.in_sight(grid)
        attack_grid = self._runtime.convert_global_to_local(grid)
        self._select_air_strike_target(attack_grid, cancellation)
        self._confirm_air_strike(cancellation)
        cancellation.raise_if_requested()
        self._runtime.strategy_close(skip_first_screenshot=False)
        return MechanicApplied()

    def _move_enemy(
        self,
        action: MoveEnemy,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        source = self._grid(action.source)
        target = self._grid(action.target)
        distance = abs(action.source.x - action.target.x) + abs(action.source.y - action.target.y)
        if distance != 1 or not source.is_enemy or not target.is_sea:
            return MechanicNotApplied()
        view_target = SelectedGrids([source, target]).sort_by_camera_distance(self._runtime.camera)[1]
        cancellation.raise_if_requested()
        self._runtime.in_sight(view_target)
        origin_grid = self._runtime.convert_global_to_local(source)
        target_grid = self._runtime.convert_global_to_local(target)
        cancellation.raise_if_requested()
        self._runtime.strategy_open()
        if not self._runtime.strategy_has_mob_move():
            cancellation.raise_if_requested()
            self._runtime.strategy_close()
            return MechanicNotApplied()
        cancellation.raise_if_requested()
        self._runtime.strategy_mob_move_enter()
        self._select_mob_move_origin(origin_grid, cancellation)
        self._select_mob_move_target(target_grid, cancellation)
        cancellation.raise_if_requested()
        self._runtime.strategy_close(skip_first_screenshot=False)
        target.enemy_scale = source.enemy_scale
        source.enemy_scale = 0
        target.enemy_genre = source.enemy_genre
        source.enemy_genre = None
        target.is_boss = source.is_boss
        source.is_boss = False
        target.is_enemy = True
        target.may_enemy = True
        source.is_enemy = False
        self._runtime.find_path_initial()
        return MechanicApplied()

    def _procedure(
        self,
        action: MechanicProcedure,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        applied = False
        before = self._runtime.battle_count
        for operation in action.operations:
            cancellation.raise_if_requested()
            if operation is MechanicOperation.CLEAR_BOUNCING_ENEMY:
                applied = bool(self._runtime.clear_bouncing_enemy()) or applied
            elif operation in (MechanicOperation.FIND_ROADBLOCKS, MechanicOperation.CHECK_ACCESSIBILITY):
                message = (
                    f"mechanic procedure {operation.value} has no target/fleet operand; "
                    "use a typed condition or RoadblockAction"
                )
                raise BattleProgramMumu12AdapterError(message)
            else:
                assert_never(operation)
        return self._mechanic_fact(
            before,
            applied=applied,
            target=program_model.ProgramBattleTarget.ENEMY,
            operation="mechanic procedure",
        )

    def _select_air_strike_target(self, grid: Grid, cancellation: CancellationSource) -> None:
        interval = Timer(5, count=10)
        for index in range(180):
            cancellation.raise_if_requested()
            if index:
                self._runtime.device.screenshot()
            if grid.predict_air_strike_icon():
                return
            if self._runtime.is_in_strategy_air_strike():
                self._runtime.view.update(image=self._runtime.device.image)
                del_cached_property(grid, "image_trans")
            if interval.reached() and self._runtime.is_in_strategy_air_strike():
                cancellation.raise_if_requested()
                self._runtime.device.click(grid)
                interval.reset()
        message = "air strike target did not become selectable"
        raise BattleProgramMumu12AdapterError(message)

    def _confirm_air_strike(self, cancellation: CancellationSource) -> None:
        interval = Timer(3, count=6)
        for index in range(180):
            cancellation.raise_if_requested()
            if index:
                self._runtime.device.screenshot()
            if self._runtime.appear(STRATEGY_OPENED, offset=AIR_STRIKE_OFFSET):
                return
            if interval.reached() and self._runtime.is_in_strategy_air_strike():
                cancellation.raise_if_requested()
                self._runtime.device.click(AIR_STRIKE_CONFIRM)
                interval.reset()
        message = "air strike did not return to the strategy page"
        raise BattleProgramMumu12AdapterError(message)

    def _select_mob_move_origin(self, grid: Grid, cancellation: CancellationSource) -> None:
        interval = Timer(2, count=4)
        for index in range(180):
            cancellation.raise_if_requested()
            if index:
                self._runtime.device.screenshot()
            if self._runtime.is_in_strategy_mob_move():
                self._runtime.view.update(image=self._runtime.device.image)
            if grid.predict_mob_move_icon():
                return
            if interval.reached() and self._runtime.is_in_strategy_mob_move():
                cancellation.raise_if_requested()
                self._runtime.device.click(grid)
                interval.reset()
        message = "movable enemy did not become selectable"
        raise BattleProgramMumu12AdapterError(message)

    def _select_mob_move_target(self, grid: Grid, cancellation: CancellationSource) -> None:
        interval = Timer(2, count=4)
        for index in range(180):
            cancellation.raise_if_requested()
            if index:
                self._runtime.device.screenshot()
            if self._runtime.appear(STRATEGY_OPENED, offset=MOB_MOVE_OFFSET):
                return
            if interval.reached() and self._runtime.is_in_strategy_mob_move():
                cancellation.raise_if_requested()
                self._runtime.device.click(grid)
                interval.reset()
                continue
            if self._runtime.handle_popup_confirm("MOB_MOVE"):
                continue
        message = "movable enemy target was not confirmed"
        raise BattleProgramMumu12AdapterError(message)

    def _battle_condition(self, condition: object, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        if isinstance(condition, FlagCondition):
            value = self._battle_flag(condition.flag, cancellation)
            return value is condition.value
        if isinstance(condition, CellAccessibleCondition):
            return bool(self._grid(condition.cell).is_accessible)
        if isinstance(condition, AllConditions):
            return all(self._battle_condition(item, cancellation) for item in condition.conditions)
        if isinstance(condition, AnyCondition):
            return any(self._battle_condition(item, cancellation) for item in condition.conditions)
        if isinstance(condition, NotCondition):
            return not self._battle_condition(condition.condition, cancellation)
        message = f"unsupported battle condition: {type(condition).__name__}"
        raise BattleProgramMumu12AdapterError(message)

    def _battle_flag(self, flag: BattleFlag, cancellation: CancellationSource) -> bool:
        initial = self.initial_flags(cancellation)
        if flag is BattleFlag.CLEAR_MODE:
            return program_model.ProgramFlag.CLEAR_MODE in initial
        if flag is BattleFlag.MAP_HAS_MOB_MOVE:
            return program_model.ProgramFlag.MAP_HAS_MOB_MOVE in initial
        if flag is BattleFlag.USE_SINGLE_FLEET:
            return program_model.ProgramFlag.USE_SINGLE_FLEET in initial
        assert_never(flag)

    def _grid(self, cell: CellId) -> GridInfo:
        try:
            return self._runtime.map[(cell.x, cell.y)]
        except KeyError:
            message = f"battle program references cell outside the active map: {cell}"
            raise BattleProgramMumu12AdapterError(message) from None

    def _fleet_index(self, fleet: FleetRole) -> int | None:
        if fleet is FleetRole.ACTIVE:
            return None
        if fleet is FleetRole.FLEET_1:
            return 1
        if fleet is FleetRole.FLEET_2:
            return 2
        if fleet is FleetRole.FLEET_BOSS:
            return self._runtime.fleet_boss_index
        if fleet is FleetRole.NON_BOSS:
            return 1 if self._runtime.fleet_boss_index == 2 else 2
        assert_never(fleet)

    def _fleet_argument(self, fleet: FleetRole) -> int | Literal["boss"] | None:
        if fleet is FleetRole.FLEET_BOSS:
            return "boss"
        return self._fleet_index(fleet)

    def _fleet_runtime(
        self,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> DeclarativeCampaignMapRuntime:
        cancellation.raise_if_requested()
        if fleet is FleetRole.ACTIVE:
            return self._runtime
        if fleet is FleetRole.FLEET_1:
            return self._runtime.fleet_1
        if fleet is FleetRole.FLEET_2:
            return self._runtime.fleet_2
        if fleet is FleetRole.FLEET_BOSS:
            return self._runtime.fleet_boss
        if fleet is FleetRole.NON_BOSS:
            return self._runtime.fleet_1 if self._runtime.fleet_boss_index == 2 else self._runtime.fleet_2
        assert_never(fleet)

    def _fleet_location(self, fleet: FleetRole) -> tuple[int, int]:
        if fleet is FleetRole.ACTIVE:
            value = self._runtime.fleet_current
        elif fleet is FleetRole.FLEET_1:
            value = self._runtime.fleet_1_location
        elif fleet is FleetRole.FLEET_2:
            value = self._runtime.fleet_2_location
        elif fleet is FleetRole.FLEET_BOSS:
            value = (
                self._runtime.fleet_1_location
                if self._runtime.fleet_boss_index == 1
                else self._runtime.fleet_2_location
            )
        elif fleet is FleetRole.NON_BOSS:
            value = (
                self._runtime.fleet_2_location
                if self._runtime.fleet_boss_index == 1
                else self._runtime.fleet_1_location
            )
        else:
            assert_never(fleet)
        if len(value) != 2:
            message = f"{fleet.value} has no active map location"
            raise BattleProgramMumu12AdapterError(message)
        return value

    def _road_group(self, paths: Iterable[RoadPath]) -> RoadGrids[GridInfo]:
        return RoadGrids([[self._grid(cell) for cell in path.cells] for path in paths])

    @staticmethod
    def _selection_keywords(selection: RoadblockSelection) -> dict[str, bool]:
        if selection is RoadblockSelection.DEFAULT:
            return {}
        if selection is RoadblockSelection.WEAKEST:
            return {"weakest": True}
        if selection is RoadblockSelection.STRONGEST:
            return {"strongest": True}
        assert_never(selection)

    @staticmethod
    def _expected_for_grid(grid: GridInfo) -> str:
        if grid.is_boss:
            return "boss"
        if grid.is_siren:
            return "siren"
        return ""

    @staticmethod
    def _target_for_grid(grid: GridInfo) -> program_model.ProgramBattleTarget:
        if grid.is_boss:
            return program_model.ProgramBattleTarget.BOSS
        if grid.is_siren:
            return program_model.ProgramBattleTarget.SIREN
        return program_model.ProgramBattleTarget.ENEMY

    @staticmethod
    def _target_from_expectation(
        expected: TargetExpectation,
    ) -> program_model.ProgramBattleTarget:
        if expected is TargetExpectation.ENEMY:
            return program_model.ProgramBattleTarget.ENEMY
        if expected is TargetExpectation.SIREN:
            return program_model.ProgramBattleTarget.SIREN
        assert_never(expected)

    @staticmethod
    def _target_expected(expected: TargetExpectation) -> str:
        if expected is TargetExpectation.ENEMY:
            return ""
        if expected is TargetExpectation.SIREN:
            return "siren"
        assert_never(expected)

    @staticmethod
    def _target_from_encounter(
        expected: EncounterExpectation,
        grid: GridInfo,
    ) -> program_model.ProgramBattleTarget:
        if expected is EncounterExpectation.ENEMY:
            return program_model.ProgramBattleTarget.ENEMY
        if expected is EncounterExpectation.SIREN:
            return program_model.ProgramBattleTarget.SIREN
        if expected is EncounterExpectation.BOSS:
            return program_model.ProgramBattleTarget.BOSS
        return Mumu12BattleProgramPort._target_for_grid(grid)

    @staticmethod
    def _encounter_expected(expected: EncounterExpectation) -> str:
        if expected is EncounterExpectation.ANY:
            return ""
        if expected is EncounterExpectation.ENEMY:
            return "combat"
        if expected is EncounterExpectation.SIREN:
            return "combat_siren"
        if expected is EncounterExpectation.BOSS:
            return "combat_boss"
        if expected is EncounterExpectation.MYSTERY:
            return "mystery"
        if expected is EncounterExpectation.STORY:
            return "story"
        assert_never(expected)

    @staticmethod
    def _clear_expected(expected: EncounterExpectation) -> str:
        if expected in (EncounterExpectation.ANY, EncounterExpectation.ENEMY):
            return ""
        if expected is EncounterExpectation.SIREN:
            return "siren"
        if expected is EncounterExpectation.BOSS:
            return "boss"
        if expected is EncounterExpectation.MYSTERY:
            return "mystery"
        if expected is EncounterExpectation.STORY:
            return "story"
        assert_never(expected)

    def _battle_action_target(
        self,
        action: UnguardedBattleStep,
    ) -> program_model.ProgramBattleTarget:
        if isinstance(action, ClearSiren):
            return program_model.ProgramBattleTarget.SIREN
        if isinstance(action, ClearChosenEnemy | ClearSelectedEnemy):
            return self._target_from_expectation(action.expected)
        if isinstance(action, ClearBoss):
            return program_model.ProgramBattleTarget.BOSS
        if isinstance(action, DefaultBattle):
            grid = self._default_target()
            return self._target_for_grid(grid) if grid is not None else program_model.ProgramBattleTarget.ENEMY
        return program_model.ProgramBattleTarget.ENEMY

    def _mechanic_action_context(
        self,
        action: program_model.ProgramMechanicAction,
    ) -> _MechanicActionContext:
        if isinstance(action, BreakSirenCaught | ProtectFleet):
            return _MechanicActionContext(program_model.ProgramBattleTarget.SIREN)
        if isinstance(action, FleetClearTarget):
            grid = self._grid(action.target)
            return _MechanicActionContext(self._target_from_encounter(action.expected, grid), grid)
        if isinstance(action, MoveFleet):
            grid = self._grid(action.destination)
            return _MechanicActionContext(self._target_from_encounter(action.expected, grid), grid)
        if isinstance(action, MoveFleetToBestCandidate):
            grid = self._best_fleet_move_candidate(action)
            return _MechanicActionContext(self._target_from_encounter(action.expected, grid), grid)
        return _MechanicActionContext(program_model.ProgramBattleTarget.ENEMY)

    @staticmethod
    def _candidate_is_clearable(
        grid: GridInfo,
        excluded_genres: tuple[str, ...],
        expected: TargetExpectation,
    ) -> bool:
        if expected is TargetExpectation.SIREN:
            present = grid.is_siren
        elif expected is TargetExpectation.ENEMY:
            present = grid.is_enemy and not grid.is_boss
        else:
            assert_never(expected)
        return bool(present and grid.is_accessible and grid.enemy_genre not in excluded_genres)

    def _default_target(self) -> GridInfo | None:
        enemies = self._runtime.map.select(is_enemy=True, is_boss=False, is_accessible=True).sort("weight", "cost")
        if enemies:
            return enemies[0]
        sirens = self._runtime.map.select(is_siren=True, is_accessible=True).sort("weight", "cost")
        return sirens[0] if sirens else None

    def _clear_priority_enemy(
        self,
        action: ClearPriorityEnemy,
        cancellation: CancellationSource,
    ) -> bool:
        if action.include_scale_1:
            cancellation.raise_if_requested()
            if self._runtime.clear_enemy(scale=(1,)):
                return True
        for scale, genre in _PRIORITY_ENEMIES:
            cancellation.raise_if_requested()
            if self._runtime.clear_enemy(scale=scale, genre=genre):
                return True
        return False

    def _require_current_battle(self, battle: int, *, operation: str) -> None:
        if battle != self._runtime.battle_count:
            message = f"{operation} belongs to battle {battle}, active battle is {self._runtime.battle_count}"
            raise BattleProgramMumu12AdapterError(message)

    @staticmethod
    def _require_fleet_2(fleet: FleetRole, *, operation: str) -> None:
        if fleet is not FleetRole.FLEET_2:
            message = f"{operation} only has a fleet_2 primitive, got {fleet.value}"
            raise BattleProgramMumu12AdapterError(message)

    def _battle_fact(
        self,
        before: int,
        *,
        applied: bool,
        target: program_model.ProgramBattleTarget,
        advances_wave: bool = True,
    ) -> BattleActionOutcome:
        delta = self._runtime.battle_count - before
        if delta == 1:
            return program_model.ProgramBattleSettled(target, advances_wave=advances_wave)
        if delta != 0:
            return program_model.ProgramFailed(
                f"one battle action changed battle_count by {delta}, expected zero or one"
            )
        if applied:
            return program_model.ProgramFailed(_UNCONFIRMED_BATTLE)
        return program_model.ProgramNoTarget()

    def _mechanic_fact(
        self,
        before: int,
        *,
        applied: bool,
        operation: str,
        target: program_model.ProgramBattleTarget = program_model.ProgramBattleTarget.ENEMY,
        advances_wave: bool = True,
    ) -> MechanicActionOutcome:
        delta = self._runtime.battle_count - before
        if delta == 1:
            return MechanicSettled(target, advances_wave=advances_wave)
        if delta != 0:
            return MechanicFailed(f"{operation} changed battle_count by {delta}, expected zero or one")
        return MechanicApplied() if applied else MechanicNotApplied()
