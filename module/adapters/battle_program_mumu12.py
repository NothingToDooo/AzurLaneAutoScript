from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from module.adapters.battle_program_battle_action_mumu12 import Mumu12BattleActionExecutor
    from module.adapters.battle_program_mechanic_action_mumu12 import Mumu12MechanicActionExecutor
    from module.adapters.battle_program_mumu12_contracts import MapMutationDriver
    from module.adapters.battle_program_read_mumu12 import BattleProgramReadModel
    from module.application import CancellationSource
    from module.content import battle_program as program_model
    from module.content.battle_policy import BattleStep
    from module.content.cell import CellId
    from module.content.mechanic_rules import FleetRole
    from module.gameplay.battle_program import BattleActionOutcome, MechanicActionOutcome


class Mumu12BattleProgramPort:
    """把 BattleProgram 协议适配到读取模型和独立动作执行器。"""

    __slots__ = ("_battle_actions", "_map_mutations", "_mechanic_actions", "_reads")

    def __init__(
        self,
        reads: BattleProgramReadModel,
        battle_actions: Mumu12BattleActionExecutor,
        mechanic_actions: Mumu12MechanicActionExecutor,
        map_mutations: MapMutationDriver,
    ) -> None:
        self._reads = reads
        self._battle_actions = battle_actions
        self._mechanic_actions = mechanic_actions
        self._map_mutations = map_mutations

    def initial_flags(self, cancellation: CancellationSource) -> frozenset[program_model.ProgramFlag]:
        return self._reads.initial_flags(cancellation)

    def read_metric(
        self,
        metric: program_model.ProgramMetric,
        cancellation: CancellationSource,
    ) -> int:
        return self._reads.read_metric(metric, cancellation)

    def read_cell_property(
        self,
        cell: CellId,
        cell_property: program_model.CellProperty,
        cancellation: CancellationSource,
    ) -> program_model.CellPropertyValue:
        return self._reads.read_cell_property(cell, cell_property, cancellation)

    def is_fleet_at(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        return self._reads.is_fleet_at(cell, fleet, cancellation)

    def has_map_presence(
        self,
        presence: program_model.MapPresence,
        cancellation: CancellationSource,
    ) -> bool:
        return self._reads.has_map_presence(presence, cancellation)

    def is_boss_at(self, cell: CellId, cancellation: CancellationSource) -> bool:
        return self._reads.is_boss_at(cell, cancellation)

    def is_boss_accessible(
        self,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        return self._reads.is_boss_accessible(fleet, cancellation)

    def is_cell_accessible_for_fleet(
        self,
        cell: CellId,
        fleet: FleetRole,
        cancellation: CancellationSource,
    ) -> bool:
        return self._reads.is_cell_accessible_for_fleet(cell, fleet, cancellation)

    def has_candidate_enemy(
        self,
        candidates: tuple[CellId, ...],
        excluded_genres: tuple[str, ...],
        cancellation: CancellationSource,
    ) -> bool:
        return self._reads.has_candidate_enemy(candidates, excluded_genres, cancellation)

    def execute_battle(
        self,
        action: BattleStep,
        cancellation: CancellationSource,
    ) -> BattleActionOutcome:
        return self._battle_actions.execute(action, cancellation)

    def execute_mechanic(
        self,
        action: program_model.ProgramMechanicAction,
        cancellation: CancellationSource,
    ) -> MechanicActionOutcome:
        return self._mechanic_actions.execute(action, cancellation)

    def mark_all_siren_candidates(self, cancellation: CancellationSource) -> None:
        self._map_mutations.mark_all_siren_candidates(cancellation)

    def set_map_weights(
        self,
        rows: tuple[tuple[int, ...], ...],
        cancellation: CancellationSource,
    ) -> None:
        self._map_mutations.set_map_weights(rows, cancellation)
