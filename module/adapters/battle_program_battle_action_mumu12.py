from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from module.adapters.battle_program_mumu12_contracts import (
    BattleProgramMumu12AdapterError,
    FleetActionDriver,
    FleetIndex,
    MapMutationDriver,
    RoadblockPlanner,
)
from module.adapters.battle_program_target_semantics_mumu12 import (
    encounter_from_expectation,
    expectation_for_facts,
    is_clearable_candidate,
    target_for_facts,
    target_from_expectation,
)
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
    UnguardedBattleStep,
)
from module.content.mechanic_rules import EncounterExpectation, FleetRole

if TYPE_CHECKING:
    from module.adapters.battle_program_read_mumu12 import BattleProgramReadModel, ProgramCellFacts
    from module.adapters.battle_program_selection_mumu12 import BattleTargetSelection, BattleTargetSelector
    from module.application import CancellationSource
    from module.gameplay.battle_program import BattleActionOutcome


_UNCONFIRMED_BATTLE = "battle primitive reported success without advancing battle_count"


@dataclass(frozen=True, slots=True)
class _BattlePrimitiveOutcome:
    applied: bool
    target: program_model.ProgramBattleTarget = program_model.ProgramBattleTarget.ENEMY
    advances_wave: bool = True


@dataclass(frozen=True, slots=True)
class _NoBattleTarget:
    pass


type _BattleHandlerOutcome = _BattlePrimitiveOutcome | _NoBattleTarget


@dataclass(frozen=True, slots=True)
class Mumu12BattleActionDependencies:
    reads: BattleProgramReadModel
    fleet_actions: FleetActionDriver
    map_mutations: MapMutationDriver
    roadblocks: RoadblockPlanner
    battle_targets: BattleTargetSelector


class Mumu12BattleActionExecutor:
    """选择并执行一个声明式战斗动作。"""

    __slots__ = (
        "_battle_targets",
        "_fleet_actions",
        "_map_mutations",
        "_reads",
        "_roadblocks",
    )

    def __init__(self, dependencies: Mumu12BattleActionDependencies) -> None:
        self._reads = dependencies.reads
        self._fleet_actions = dependencies.fleet_actions
        self._map_mutations = dependencies.map_mutations
        self._roadblocks = dependencies.roadblocks
        self._battle_targets = dependencies.battle_targets

    def execute(
        self,
        action: BattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        cancellation.raise_if_requested()
        before = self._reads.battle_count(cancellation)
        if isinstance(action, GuardedBattleStep):
            if not self._battle_condition(action.condition, cancellation):
                return program_model.ProgramNoTarget()
            action = action.step
        target = self._battle_action_target(action, cancellation)
        try:
            selected_target = self._select_battle_target(action, cancellation)
            if selected_target is not None:
                target = selected_target.program_target
            return self._execute_unguarded_battle(action, selected_target, cancellation)
        except Exception:
            delta = self._reads.battle_count(cancellation) - before
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

    def _execute_unguarded_battle(
        self,
        action: UnguardedBattleStep,
        selected_target: BattleTargetSelection | None,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        before = self._reads.battle_count(cancellation)
        outcome = self._dispatch_battle_action(action, selected_target, cancellation)
        if isinstance(outcome, _NoBattleTarget):
            return program_model.ProgramNoTarget()
        return self._battle_fact(
            before,
            applied=outcome.applied,
            target=outcome.target,
            advances_wave=outcome.advances_wave,
            cancellation=cancellation,
        )

    def _dispatch_battle_action(
        self,
        action: UnguardedBattleStep,
        selected_target: BattleTargetSelection | None,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        if isinstance(action, ClearSiren | ClearFilteredEnemy | ClearEnemy | ClearAnyEnemy):
            outcome = self._handle_selected_battle(selected_target, cancellation)
        elif isinstance(action, ClearChosenEnemy):
            outcome = self._handle_clear_chosen_enemy(action, cancellation)
        elif isinstance(action, ClearSelectedEnemy):
            outcome = self._handle_clear_selected_enemy(action, cancellation)
        elif isinstance(action, ClearPriorityEnemy):
            outcome = self._handle_selected_battle(selected_target, cancellation)
        elif isinstance(action, DefaultBattle):
            outcome = self._handle_default_battle(cancellation)
        elif isinstance(action, ClearBossRoadblock):
            outcome = self._handle_clear_boss_roadblock(action, cancellation)
        elif isinstance(action, ClearBoss):
            outcome = self._handle_clear_boss(action, cancellation)
        else:
            assert_never(action)
        return outcome

    def _select_battle_target(
        self,
        action: UnguardedBattleStep,
        cancellation: CancellationSource,
    ) -> BattleTargetSelection | None:
        if not isinstance(action, ClearSiren | ClearFilteredEnemy | ClearEnemy | ClearAnyEnemy | ClearPriorityEnemy):
            return None
        if isinstance(action, ClearSiren) and action.include_hidden_candidates:
            self._map_mutations.mark_all_siren_candidates(cancellation)
        context = self._reads.selection_context(cancellation)
        battlefield = self._reads.battlefield(cancellation)
        return self._battle_targets.select(action, battlefield, context)

    def _handle_selected_battle(
        self,
        selected: BattleTargetSelection | None,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        if selected is None:
            return _NoBattleTarget()
        self._fleet_actions.clear_target(
            selected.fleet,
            selected.cell,
            selected.encounter,
            cancellation,
        )
        # clear_* primitive 的 True 表示“已选中并执行目标”，不是底层战斗确认；确认统一由 battle_count 闭合。
        return _BattlePrimitiveOutcome(applied=True, target=selected.program_target)

    def _handle_clear_chosen_enemy(
        self,
        action: ClearChosenEnemy,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        status = self._reads.status(cancellation)
        fleet_index = status.fleet_index(FleetRole.ACTIVE)
        facts = self._reads.battlefield(cancellation).cell(action.target)
        if not facts.accessible_for(fleet_index):
            return _NoBattleTarget()
        return _BattlePrimitiveOutcome(
            applied=self._fleet_actions.clear_target(
                fleet_index,
                action.target,
                encounter_from_expectation(action.expected),
                cancellation,
            ),
            target=target_from_expectation(action.expected),
        )

    def _handle_clear_selected_enemy(
        self,
        action: ClearSelectedEnemy,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        status = self._reads.status(cancellation)
        fleet_index = status.fleet_index(FleetRole.ACTIVE)
        battlefield = self._reads.battlefield(cancellation)
        target = next(
            (
                cell
                for cell in action.candidates
                if is_clearable_candidate(
                    battlefield.cell(cell),
                    fleet_index,
                    action.excluded_genres,
                    action.expected,
                )
            ),
            None,
        )
        if target is None:
            return _NoBattleTarget()
        return _BattlePrimitiveOutcome(
            applied=self._fleet_actions.clear_target(
                fleet_index,
                target,
                encounter_from_expectation(action.expected),
                cancellation,
            ),
            target=target_from_expectation(action.expected),
        )

    def _handle_default_battle(
        self,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        selected = self._default_target(cancellation)
        if selected is None:
            return _NoBattleTarget()
        facts, fleet_index = selected
        target = target_for_facts(facts)
        expected = expectation_for_facts(facts)
        return _BattlePrimitiveOutcome(
            applied=self._fleet_actions.clear_target(fleet_index, facts.cell, expected, cancellation),
            target=target,
        )

    def _handle_clear_boss_roadblock(
        self,
        action: ClearBossRoadblock,
        cancellation: CancellationSource,
    ) -> _BattleHandlerOutcome:
        if action.strategy is BossStrategy.MAP_SEARCH:
            executor_fleet = FleetRole.FLEET_1
        elif action.strategy is BossStrategy.BRUTE_FORCE:
            executor_fleet = FleetRole.ACTIVE
        else:
            message = f"unsupported boss roadblock strategy: {action.strategy.value}"
            raise BattleProgramMumu12AdapterError(message)
        status = self._reads.status(cancellation)
        boss_fleet_index = status.fleet_index(FleetRole.FLEET_BOSS)
        executor_index = status.fleet_index(executor_fleet)
        bosses = [cell for cell in self._reads.battlefield(cancellation).cells if cell.is_boss]
        if not bosses:
            return _NoBattleTarget()
        boss = min(bosses, key=lambda cell: (cell.weight, cell.cost_for(boss_fleet_index)))
        roadblocks = self._roadblocks.find_blockers(boss.cell, boss_fleet_index, cancellation)
        battlefield = self._reads.battlefield(cancellation)
        candidates = [
            facts
            for cell in roadblocks
            if (facts := battlefield.cell(cell)).is_enemy and facts.accessible_for(executor_index)
        ]
        if not candidates:
            return _NoBattleTarget()
        chosen = min(candidates, key=lambda cell: (cell.weight, cell.cost_for(executor_index)))
        applied = self._fleet_actions.clear_target(
            executor_index,
            chosen.cell,
            EncounterExpectation.ENEMY,
            cancellation,
        )
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
        if action.strategy in (BossStrategy.FLEET_BOSS, BossStrategy.BRUTE_FORCE):
            executor_fleet = FleetRole.FLEET_BOSS
        elif action.strategy is BossStrategy.FLEET_1:
            executor_fleet = FleetRole.FLEET_1
        elif action.strategy is BossStrategy.MAP_SEARCH:
            executor_fleet = FleetRole.ACTIVE
        else:
            assert_never(action.strategy)
        status = self._reads.status(cancellation)
        executor_index = status.fleet_index(executor_fleet)
        bosses = [
            cell
            for cell in self._reads.battlefield(cancellation).cells
            if cell.is_boss and cell.accessible_for(executor_index)
        ]
        if not bosses:
            return _NoBattleTarget()
        boss = min(bosses, key=lambda cell: (cell.weight, cell.cost_for(executor_index)))
        return _BattlePrimitiveOutcome(
            applied=self._fleet_actions.clear_target(
                executor_index,
                boss.cell,
                EncounterExpectation.BOSS,
                cancellation,
            ),
            target=program_model.ProgramBattleTarget.BOSS,
        )

    def _battle_condition(self, condition: object, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        if isinstance(condition, FlagCondition):
            value = self._battle_flag(condition.flag, cancellation)
            return value is condition.value
        if isinstance(condition, CellAccessibleCondition):
            return self._reads.is_cell_accessible_for_fleet(condition.cell, FleetRole.ACTIVE, cancellation)
        if isinstance(condition, AllConditions):
            return all(self._battle_condition(item, cancellation) for item in condition.conditions)
        if isinstance(condition, AnyCondition):
            return any(self._battle_condition(item, cancellation) for item in condition.conditions)
        if isinstance(condition, NotCondition):
            return not self._battle_condition(condition.condition, cancellation)
        message = f"unsupported battle condition: {type(condition).__name__}"
        raise BattleProgramMumu12AdapterError(message)

    def _battle_flag(self, flag: BattleFlag, cancellation: CancellationSource) -> bool:
        initial = self._reads.initial_flags(cancellation)
        if flag is BattleFlag.CLEAR_MODE:
            return program_model.ProgramFlag.CLEAR_MODE in initial
        if flag is BattleFlag.MAP_HAS_MOB_MOVE:
            return program_model.ProgramFlag.MAP_HAS_MOB_MOVE in initial
        if flag is BattleFlag.USE_SINGLE_FLEET:
            return program_model.ProgramFlag.USE_SINGLE_FLEET in initial
        assert_never(flag)

    def _battle_action_target(
        self,
        action: UnguardedBattleStep,
        cancellation: CancellationSource,
    ) -> program_model.ProgramBattleTarget:
        if isinstance(action, ClearSiren):
            return program_model.ProgramBattleTarget.SIREN
        if isinstance(action, ClearChosenEnemy | ClearSelectedEnemy):
            return target_from_expectation(action.expected)
        if isinstance(action, ClearBoss):
            return program_model.ProgramBattleTarget.BOSS
        if isinstance(action, DefaultBattle):
            selected = self._default_target(cancellation)
            return target_for_facts(selected[0]) if selected is not None else program_model.ProgramBattleTarget.ENEMY
        return program_model.ProgramBattleTarget.ENEMY

    def _default_target(
        self,
        cancellation: CancellationSource,
    ) -> tuple[ProgramCellFacts, FleetIndex] | None:
        status = self._reads.status(cancellation)
        fleet_index = status.fleet_index(FleetRole.ACTIVE)
        cells = self._reads.battlefield(cancellation).cells
        enemies = [cell for cell in cells if cell.is_enemy and not cell.is_boss and cell.accessible_for(fleet_index)]
        if enemies:
            return min(enemies, key=lambda cell: (cell.weight, cell.cost_for(fleet_index))), fleet_index
        sirens = [cell for cell in cells if cell.is_siren and cell.accessible_for(fleet_index)]
        selected = min(sirens, key=lambda cell: (cell.weight, cell.cost_for(fleet_index)), default=None)
        return (selected, fleet_index) if selected is not None else None

    def _battle_fact(
        self,
        before: int,
        *,
        applied: bool,
        target: program_model.ProgramBattleTarget,
        advances_wave: bool = True,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        delta = self._reads.battle_count(cancellation) - before
        if delta == 1:
            return program_model.ProgramBattleSettled(target, advances_wave=advances_wave)
        if delta != 0:
            return program_model.ProgramFailed(
                f"one battle action changed battle_count by {delta}, expected zero or one"
            )
        if applied:
            return program_model.ProgramFailed(_UNCONFIRMED_BATTLE)
        return program_model.ProgramNoTarget()
