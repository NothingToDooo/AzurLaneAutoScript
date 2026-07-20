from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from module.adapters.battle_program_mumu12_contracts import (
    BattleProgramMumu12AdapterError,
    FleetActionDriver,
    FleetCoordinationDriver,
    FleetIndex,
    MapMechanicDriver,
    RoadblockPlanner,
    StrategyActionDriver,
)
from module.adapters.battle_program_target_semantics_mumu12 import matches_encounter, target_from_encounter
from module.content import battle_program as program_model
from module.content.mechanic_rules import (
    AirStrike,
    BreakSirenCaught,
    CandidateSortKey,
    ClearAllMystery,
    ClearChosenMystery,
    ClearMapItems,
    ClearMechanism,
    EncounterExpectation,
    EnsureFleet,
    EnsureFleetAt,
    FleetClearSelectedTarget,
    FleetClearTarget,
    FleetRole,
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
    StepFleetOn,
)
from module.gameplay.battle_program import (
    MechanicActionOutcome,
    MechanicApplied,
    MechanicFailed,
    MechanicNotApplied,
    MechanicSettled,
)

if TYPE_CHECKING:
    from module.adapters.battle_program_read_mumu12 import BattleProgramReadModel, ProgramCellFacts
    from module.application import CancellationSource
    from module.content.cell import CellId


@dataclass(frozen=True, slots=True)
class _MechanicActionContext:
    settled_target: program_model.ProgramBattleTarget
    resolved_cell: CellId | None = None
    resolved_fleet: FleetIndex | None = None


type _FleetMechanicAction = (
    BreakSirenCaught
    | PushFleetForward
    | ProtectFleet
    | RescueFleet
    | StepFleetOn
    | MoveFleet
    | MoveFleetToBestCandidate
    | EnsureFleet
    | EnsureFleetAt
    | FleetClearTarget
    | FleetClearSelectedTarget
)
type _PickupMechanicAction = PickupAmmo | PickupMapItem
type _MapInteractionMechanicAction = ClearAllMystery | ClearChosenMystery | ClearMechanism | ClearMapItems | AirStrike


@dataclass(frozen=True, slots=True)
class Mumu12MechanicActionDependencies:
    reads: BattleProgramReadModel
    fleet_actions: FleetActionDriver
    fleet_coordination: FleetCoordinationDriver
    strategy_actions: StrategyActionDriver
    map_mechanics: MapMechanicDriver
    roadblocks: RoadblockPlanner


class Mumu12MechanicActionExecutor:
    """解析并执行一个声明式地图机制动作。"""

    __slots__ = (
        "_fleet_actions",
        "_fleet_coordination",
        "_map_mechanics",
        "_reads",
        "_roadblocks",
        "_strategy_actions",
    )

    def __init__(self, dependencies: Mumu12MechanicActionDependencies) -> None:
        self._reads = dependencies.reads
        self._fleet_actions = dependencies.fleet_actions
        self._fleet_coordination = dependencies.fleet_coordination
        self._strategy_actions = dependencies.strategy_actions
        self._map_mechanics = dependencies.map_mechanics
        self._roadblocks = dependencies.roadblocks

    def execute(
        self,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        cancellation.raise_if_requested()
        before = self._reads.battle_count(cancellation)
        # 运行时原语可能在抛出终止异常前清空网格标记，结算事实必须使用调用前快照。
        context = self._mechanic_action_context(action, cancellation)
        try:
            return self._dispatch_mechanic_action(action, context, cancellation)
        except Exception:
            delta = self._reads.battle_count(cancellation) - before
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
            | EnsureFleet
            | EnsureFleetAt
            | FleetClearTarget
            | FleetClearSelectedTarget,
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

    def _dispatch_fleet_mechanic_action(
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
        elif isinstance(action, EnsureFleet):
            outcome = self._ensure_fleet(action, cancellation)
        elif isinstance(action, EnsureFleetAt):
            outcome = self._ensure_fleet_at(action, cancellation)
        elif isinstance(action, FleetClearTarget | FleetClearSelectedTarget):
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

    def _roadblock(
        self,
        action: RoadblockAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        before = self._reads.battle_count(cancellation)
        fleet_index = self._reads.status(cancellation).fleet_current_index
        target = self._roadblocks.select_target(action, fleet_index, cancellation)
        applied = target is not None
        if target is not None:
            self._fleet_actions.clear_target(
                fleet_index,
                target,
                EncounterExpectation.ENEMY,
                cancellation,
            )
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=applied,
            target=program_model.ProgramBattleTarget.ENEMY,
            operation=f"roadblock {action.mode.value}",
        )

    def _push_forward(
        self,
        action: PushFleetForward,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        self._require_current_battle(action.battle, cancellation, operation="push forward")
        before = self._reads.battle_count(cancellation)
        applied = self._fleet_coordination.push_forward(cancellation)
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=applied,
            operation="push forward",
        )

    def _break_siren_caught(
        self,
        action: BreakSirenCaught,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        self._require_current_battle(action.battle, cancellation, operation="break siren caught")
        before = self._reads.battle_count(cancellation)
        try:
            applied = self._fleet_coordination.break_siren_caught(cancellation)
        except Exception:
            delta = self._reads.battle_count(cancellation) - before
            if delta == 1:
                return MechanicSettled(program_model.ProgramBattleTarget.SIREN)
            if delta != 0:
                return MechanicFailed(f"break siren caught changed battle_count by {delta}, expected zero or one")
            raise
        delta = self._reads.battle_count(cancellation) - before
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
        self._require_current_battle(action.battle, cancellation, operation="protect fleet")
        before = self._reads.battle_count(cancellation)
        applied = self._fleet_coordination.protect(cancellation)
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=applied,
            target=program_model.ProgramBattleTarget.SIREN,
            operation="protect fleet",
        )

    def _rescue(
        self,
        action: RescueFleet,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        before = self._reads.battle_count(cancellation)
        applied = self._fleet_coordination.rescue(action.target, cancellation)
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=applied,
            target=program_model.ProgramBattleTarget.ENEMY,
            operation="rescue fleet",
        )

    def _step_on(
        self,
        action: StepFleetOn,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        before = self._reads.battle_count(cancellation)
        applied = self._fleet_coordination.step_on(action.candidates, action.roadblocks, cancellation)
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
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
        cell = context.resolved_cell
        fleet_index = context.resolved_fleet
        if cell is None or fleet_index is None:
            return MechanicNotApplied()
        return self._move_fleet_to_grid(
            fleet=fleet_index,
            expected=action.expected,
            cell=cell,
            target=context.settled_target,
            cancellation=cancellation,
        )

    def _move_fleet_to_grid(
        self,
        *,
        fleet: FleetIndex,
        expected: EncounterExpectation,
        cell: CellId,
        target: program_model.ProgramBattleTarget,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        before = self._reads.battle_count(cancellation)
        moved = self._fleet_actions.move(
            fleet,
            cell,
            expected,
            cancellation,
        )
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=moved,
            target=target,
            operation="move fleet",
        )

    @staticmethod
    def _candidate_sort_value(
        facts: ProgramCellFacts,
        key: CandidateSortKey,
        fleet_index: FleetIndex,
    ) -> float:
        if key is CandidateSortKey.WEIGHT:
            return facts.weight
        if key is CandidateSortKey.COST:
            return facts.cost_for(fleet_index)
        assert_never(key)

    def _best_fleet_move_candidate(
        self,
        action: MoveFleetToBestCandidate,
        cancellation: CancellationSource,
    ) -> tuple[ProgramCellFacts, FleetIndex] | None:
        status = self._reads.status(cancellation)
        fleet_index = status.fleet_index(action.fleet)
        battlefield = self._reads.battlefield(cancellation)
        candidates = [facts for facts in map(battlefield.cell, action.candidates) if facts.accessible_for(fleet_index)]
        if not candidates:
            return None
        chosen = min(
            candidates,
            key=lambda facts: tuple(self._candidate_sort_value(facts, key, fleet_index) for key in action.sort),
        )
        return chosen, fleet_index

    def _ensure_fleet(
        self,
        action: EnsureFleet,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        fleet_index = self._reads.status(cancellation).fleet_index(action.fleet)
        changed = self._fleet_actions.activate(fleet_index, cancellation)
        return MechanicApplied() if changed else MechanicNotApplied()

    def _ensure_fleet_at(
        self,
        action: EnsureFleetAt,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        at_target = self._reads.is_fleet_at(action.target, action.fleet, cancellation)
        return MechanicApplied() if at_target else MechanicNotApplied()

    def _fleet_clear_target(
        self,
        action: FleetClearTarget | FleetClearSelectedTarget,
        context: _MechanicActionContext,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        before = self._reads.battle_count(cancellation)
        cell = context.resolved_cell
        fleet_index = context.resolved_fleet
        if cell is None or fleet_index is None:
            return MechanicNotApplied()
        applied = self._fleet_actions.clear_target(
            fleet_index,
            cell,
            action.expected,
            cancellation,
        )
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=applied,
            target=context.settled_target,
            operation="fleet clear target",
        )

    def _pickup_ammo(
        self,
        action: PickupAmmo,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        status = self._reads.status(cancellation)
        fleet_index = status.fleet_index(action.fleet)
        target = next(
            (
                facts
                for facts in self._reads.battlefield(cancellation).cells
                if facts.may_ammo and facts.accessible_for(fleet_index)
            ),
            None,
        )
        if target is None:
            return MechanicNotApplied()
        applied = self._fleet_actions.pickup_ammo(fleet_index, target.cell, cancellation)
        return MechanicApplied() if applied else MechanicNotApplied()

    def _pickup_map_item(
        self,
        action: PickupMapItem,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        status = self._reads.status(cancellation)
        fleet_index = status.fleet_index(action.fleet)
        if not self._reads.battlefield(cancellation).cell(action.cell).accessible_for(fleet_index):
            return MechanicNotApplied()
        if status.fleet_location_for(fleet_index) == action.cell:
            return MechanicNotApplied()
        moved = self._fleet_actions.pickup_map_item(
            fleet_index,
            action.cell,
            action.kind,
            cancellation,
        )
        return MechanicApplied() if moved else MechanicNotApplied()

    def _clear_all_mystery(
        self,
        action: ClearAllMystery,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        before = self._reads.battle_count(cancellation)
        ignored = frozenset(action.ignored)
        applied = False
        while True:
            fleet_index = self._reads.status(cancellation).fleet_current_index
            candidates = [
                facts
                for facts in self._reads.battlefield(cancellation).cells
                if facts.is_mystery
                and facts.cell not in ignored
                and facts.accessible_for(fleet_index)
                and (not action.nearby or facts.cost_for(fleet_index) < 20)
            ]
            if not candidates:
                break
            target = min(candidates, key=lambda facts: (facts.cost_for(fleet_index), facts.cell))
            self._fleet_actions.clear_mystery(fleet_index, target.cell, cancellation)
            applied = True
            if self._reads.battlefield(cancellation).cell(target.cell).is_mystery:
                message = f"clear mystery did not remove target from the map projection: {target.cell}"
                raise BattleProgramMumu12AdapterError(message)
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=applied,
            operation="clear all mystery",
        )

    def _clear_chosen_mystery(
        self,
        action: ClearChosenMystery,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        status = self._reads.status(cancellation)
        fleet_index = status.fleet_index(action.fleet)
        facts = self._reads.battlefield(cancellation).cell(action.cell)
        if not facts.is_mystery or not facts.accessible_for(fleet_index):
            return MechanicNotApplied()
        before = self._reads.battle_count(cancellation)
        self._fleet_actions.clear_mystery(fleet_index, action.cell, cancellation)
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=True,
            operation="clear chosen mystery",
        )

    def _clear_mechanism(
        self,
        action: ClearMechanism,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        applied = self._map_mechanics.trigger_mechanisms(action.cells, cancellation)
        return MechanicApplied() if applied else MechanicNotApplied()

    def _clear_map_items(
        self,
        action: ClearMapItems,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        status = self._reads.status(cancellation)
        fleet_index = status.fleet_index(FleetRole.ACTIVE)
        battlefield = self._reads.battlefield(cancellation)
        cells = sorted(
            (battlefield.cell(cell) for cell in action.cells),
            key=lambda facts: facts.cost_for(fleet_index),
        )
        moved = False
        for facts in cells:
            if facts.accessible_for(fleet_index):
                moved = (
                    self._fleet_actions.move(
                        fleet_index,
                        facts.cell,
                        EncounterExpectation.ANY,
                        cancellation,
                    )
                    or moved
                )
        return MechanicApplied() if moved else MechanicNotApplied()

    def _air_strike(
        self,
        action: AirStrike,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        applied = self._strategy_actions.air_strike(action.target, cancellation)
        return MechanicApplied() if applied else MechanicNotApplied()

    def _move_enemy(
        self,
        action: MoveEnemy,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        applied = self._strategy_actions.move_enemy(action.source, action.target, cancellation)
        return MechanicApplied() if applied else MechanicNotApplied()

    def _procedure(
        self,
        action: MechanicProcedure,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        applied = False
        before = self._reads.battle_count(cancellation)
        for operation in action.operations:
            cancellation.raise_if_requested()
            if operation is MechanicOperation.CLEAR_BOUNCING_ENEMY:
                applied = self._map_mechanics.clear_bouncing_enemy(cancellation) or applied
            elif operation in (MechanicOperation.FIND_ROADBLOCKS, MechanicOperation.CHECK_ACCESSIBILITY):
                message = (
                    f"mechanic procedure {operation.value} has no target/fleet operand; "
                    "use a typed condition or RoadblockAction"
                )
                raise BattleProgramMumu12AdapterError(message)
            else:
                assert_never(operation)
        return self._mechanic_fact(
            self._reads.battle_count(cancellation) - before,
            applied=applied,
            target=program_model.ProgramBattleTarget.ENEMY,
            operation="mechanic procedure",
        )

    def _mechanic_action_context(
        self,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> _MechanicActionContext:
        if isinstance(action, BreakSirenCaught | ProtectFleet):
            return _MechanicActionContext(program_model.ProgramBattleTarget.SIREN)
        if isinstance(action, FleetClearTarget | FleetClearSelectedTarget):
            return self._fleet_clear_context(action, cancellation)
        if isinstance(action, MoveFleet | MoveFleetToBestCandidate):
            return self._move_action_context(action, cancellation)
        return _MechanicActionContext(program_model.ProgramBattleTarget.ENEMY)

    def _fleet_clear_context(
        self,
        action: FleetClearTarget | FleetClearSelectedTarget,
        cancellation: CancellationSource,
    ) -> _MechanicActionContext:
        fleet_index = self._reads.status(cancellation).fleet_index(action.fleet)
        battlefield = self._reads.battlefield(cancellation)
        if isinstance(action, FleetClearTarget):
            facts = battlefield.cell(action.target)
        else:
            facts = None
            for cell in action.candidates:
                candidate = battlefield.cell(cell)
                if matches_encounter(candidate, action.expected) and candidate.accessible_for(fleet_index):
                    facts = candidate
                    break
            if facts is None:
                fallback = battlefield.cell(action.candidates[0])
                return _MechanicActionContext(target_from_encounter(action.expected, fallback))
        settled_target = target_from_encounter(action.expected, facts)
        if not facts.accessible_for(fleet_index):
            return _MechanicActionContext(settled_target)
        return _MechanicActionContext(
            settled_target=settled_target,
            resolved_cell=facts.cell,
            resolved_fleet=fleet_index,
        )

    def _move_action_context(
        self,
        action: MoveFleet | MoveFleetToBestCandidate,
        cancellation: CancellationSource,
    ) -> _MechanicActionContext:
        if isinstance(action, MoveFleetToBestCandidate):
            candidate = self._best_fleet_move_candidate(action, cancellation)
            if candidate is None:
                return _MechanicActionContext(program_model.ProgramBattleTarget.ENEMY)
            facts, fleet_index = candidate
            cell = facts.cell
        else:
            cell = action.destination
            fleet_index = self._reads.status(cancellation).fleet_index(action.fleet)
            facts = self._reads.battlefield(cancellation).cell(cell)
            if not facts.accessible_for(fleet_index):
                return _MechanicActionContext(target_from_encounter(action.expected, facts))
        return _MechanicActionContext(
            settled_target=target_from_encounter(action.expected, facts),
            resolved_cell=cell,
            resolved_fleet=fleet_index,
        )

    def _require_current_battle(
        self,
        battle: int,
        cancellation: CancellationSource,
        *,
        operation: str,
    ) -> None:
        current = self._reads.battle_count(cancellation)
        if battle != current:
            message = f"{operation} belongs to battle {battle}, active battle is {current}"
            raise BattleProgramMumu12AdapterError(message)

    @staticmethod
    def _mechanic_fact(
        delta: int,
        *,
        applied: bool,
        operation: str,
        target: program_model.ProgramBattleTarget = program_model.ProgramBattleTarget.ENEMY,
        advances_wave: bool = True,
    ) -> MechanicActionOutcome:
        if delta == 1:
            return MechanicSettled(target, advances_wave=advances_wave)
        if delta != 0:
            return MechanicFailed(f"{operation} changed battle_count by {delta}, expected zero or one")
        return MechanicApplied() if applied else MechanicNotApplied()
