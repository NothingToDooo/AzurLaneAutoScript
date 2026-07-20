from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, assert_never

from module.content import battle_program as program_model
from module.content.battle_policy import (
    ClearAnyEnemy,
    ClearEnemy,
    ClearFilteredEnemy,
    ClearPriorityEnemy,
    ClearSiren,
    EnemyFilterEntry,
    EnemySortKey,
    parse_enemy_filter,
)
from module.content.mechanic_rules import EncounterExpectation
from module.gameplay.campaign import EnemyPriorityMode

if TYPE_CHECKING:
    from module.adapters.battle_program_mumu12_contracts import FleetIndex
    from module.adapters.battle_program_read_mumu12 import (
        ProgramBattlefieldView,
        ProgramBattleSelectionContext,
        ProgramCellFacts,
    )
    from module.content.cell import CellId

type SelectableBattleAction = ClearSiren | ClearFilteredEnemy | ClearEnemy | ClearAnyEnemy | ClearPriorityEnemy
type SelectedEncounter = Literal[
    EncounterExpectation.ENEMY,
    EncounterExpectation.SIREN,
    EncounterExpectation.FORTRESS,
]

_DEFAULT_ORDER = (EnemySortKey.WEIGHT, EnemySortKey.EXECUTOR_COST)
_LARGE_FIRST_FILTER = parse_enemy_filter("3L > 3M > 3E > 3C > 2L > 2M > 2E > 2C > 1L > 1M > 1E > 1C")
_SMALL_FIRST_FILTER = parse_enemy_filter("1L > 1M > 1E > 1C > 2L > 2M > 2E > 2C > 3L > 3M > 3E > 3C")
_PRIORITY_ENEMIES = (
    ((2,), ("LightInvertedOrthant", "MainInvertedOrthant")),
    ((3,), ("LightInvertedOrthant", "MainInvertedOrthant")),
    ((2,), ("Enemy", "CarrierInvertedOrthant")),
    ((3,), ("Enemy", "CarrierInvertedOrthant")),
)


class _StrengthPreference(StrEnum):
    NONE = "none"
    STRONGEST = "strongest"
    WEAKEST = "weakest"


@dataclass(frozen=True, slots=True)
class BattleTargetSelection:
    cell: CellId
    fleet: FleetIndex
    encounter: SelectedEncounter
    program_target: program_model.ProgramBattleTarget


class BattleTargetSelector:
    """只根据不可变地图事实决定单次战斗的舰队、目标格和目标类型。"""

    def select(
        self,
        action: SelectableBattleAction,
        battlefield: ProgramBattlefieldView,
        context: ProgramBattleSelectionContext,
    ) -> BattleTargetSelection | None:
        if isinstance(action, ClearSiren):
            facts = self._select_siren(action, battlefield, context)
        elif isinstance(action, ClearFilteredEnemy):
            facts = self._select_filtered_enemy(action, battlefield, context)
        elif isinstance(action, ClearEnemy):
            facts = self._select_enemy_action(action, battlefield, context)
        elif isinstance(action, ClearAnyEnemy):
            facts = self._select_any_enemy(action, battlefield, context)
        elif isinstance(action, ClearPriorityEnemy):
            facts = self._select_priority_enemy(action, battlefield, context)
        else:
            assert_never(action)
        if facts is None:
            return None
        encounter = self._encounter(facts)
        return BattleTargetSelection(
            cell=facts.cell,
            fleet=context.executor_fleet,
            encounter=encounter,
            program_target=self._program_target(encounter),
        )

    def _select_siren(
        self,
        action: ClearSiren,
        battlefield: ProgramBattlefieldView,
        context: ProgramBattleSelectionContext,
    ) -> ProgramCellFacts | None:
        candidates = [
            facts
            for facts in battlefield.cells
            if (facts.is_siren or facts.is_fortress)
            and facts.accessible_for(context.executor_fleet)
            and self._genre_matches(facts.enemy_genre, action.genres)
        ]
        return self._first(self._ordered(candidates, _DEFAULT_ORDER, context.executor_fleet))

    def _select_filtered_enemy(
        self,
        action: ClearFilteredEnemy,
        battlefield: ProgramBattlefieldView,
        context: ProgramBattleSelectionContext,
    ) -> ProgramCellFacts | None:
        if context.movable_normal_enemy:
            return self._select_any_candidate(
                battlefield,
                context.executor_fleet,
                genres=(),
                sort=(EnemySortKey.FLEET_2_COST,),
                strength=_StrengthPreference.NONE,
            )

        preserve = action.preserve
        if context.enemy_priority is EnemyPriorityMode.LARGE_ENEMY_FIRST:
            enemy_filter = _LARGE_FIRST_FILTER
            preserve = 0
        elif context.enemy_priority is EnemyPriorityMode.SMALL_ENEMY_FIRST:
            enemy_filter = _SMALL_FIRST_FILTER
        else:
            enemy_filter = (
                parse_enemy_filter(action.enemy_filter)
                if action.enemy_filter is not None
                else context.default_enemy_filter
            )
        candidates = self._ordered(
            [
                facts
                for facts in battlefield.cells
                if facts.is_enemy and not facts.is_boss and facts.accessible_for(context.executor_fleet)
            ],
            _DEFAULT_ORDER,
            context.executor_fleet,
        )
        filtered = self._filter_order(candidates, enemy_filter)
        return filtered[preserve] if preserve < len(filtered) else None

    def _select_enemy_action(
        self,
        action: ClearEnemy,
        battlefield: ProgramBattlefieldView,
        context: ProgramBattleSelectionContext,
    ) -> ProgramCellFacts | None:
        strength = self._enemy_strength(strongest=action.strongest, context=context)
        candidates = [
            facts
            for facts in battlefield.cells
            if facts.is_enemy
            and not facts.is_boss
            and facts.accessible_for(context.executor_fleet)
            and (not action.scales or facts.enemy_scale in action.scales)
            and self._genre_matches(facts.enemy_genre, action.genres)
        ]
        candidates = self._apply_strength(candidates, strength)
        return self._first(self._ordered(candidates, action.sort or _DEFAULT_ORDER, context.executor_fleet))

    def _select_any_enemy(
        self,
        action: ClearAnyEnemy,
        battlefield: ProgramBattlefieldView,
        context: ProgramBattleSelectionContext,
    ) -> ProgramCellFacts | None:
        strength = _StrengthPreference.STRONGEST if action.strongest else _StrengthPreference.NONE
        return self._select_any_candidate(
            battlefield,
            context.executor_fleet,
            genres=action.genres,
            sort=action.sort or _DEFAULT_ORDER,
            strength=strength,
        )

    def _select_any_candidate(
        self,
        battlefield: ProgramBattlefieldView,
        executor_fleet: FleetIndex,
        *,
        genres: tuple[str, ...],
        sort: tuple[EnemySortKey, ...],
        strength: _StrengthPreference,
    ) -> ProgramCellFacts | None:
        candidates = [
            facts
            for facts in battlefield.cells
            if not facts.is_boss
            and (facts.is_enemy or facts.is_siren or facts.is_fortress)
            and facts.accessible_for(executor_fleet)
            and self._genre_matches(facts.enemy_genre, genres)
        ]
        candidates = self._apply_strength(candidates, strength)
        return self._first(self._ordered(candidates, sort, executor_fleet))

    def _select_priority_enemy(
        self,
        action: ClearPriorityEnemy,
        battlefield: ProgramBattlefieldView,
        context: ProgramBattleSelectionContext,
    ) -> ProgramCellFacts | None:
        priorities = (((1,), ()), *_PRIORITY_ENEMIES) if action.include_scale_1 else _PRIORITY_ENEMIES
        for scales, genres in priorities:
            candidates = [
                facts
                for facts in battlefield.cells
                if facts.is_enemy
                and not facts.is_boss
                and facts.accessible_for(context.executor_fleet)
                and facts.enemy_scale in scales
                and self._genre_matches(facts.enemy_genre, genres)
            ]
            selected = self._first(self._ordered(candidates, _DEFAULT_ORDER, context.executor_fleet))
            if selected is not None:
                return selected
        return None

    @staticmethod
    def _enemy_strength(
        *,
        strongest: bool,
        context: ProgramBattleSelectionContext,
    ) -> _StrengthPreference:
        if strongest:
            return _StrengthPreference.STRONGEST
        if context.enemy_priority is EnemyPriorityMode.LARGE_ENEMY_FIRST:
            return _StrengthPreference.STRONGEST
        if context.enemy_priority is EnemyPriorityMode.SMALL_ENEMY_FIRST:
            return _StrengthPreference.WEAKEST
        if context.clear_all:
            return _StrengthPreference.STRONGEST
        return _StrengthPreference.NONE

    @staticmethod
    def _apply_strength(
        candidates: list[ProgramCellFacts],
        strength: _StrengthPreference,
    ) -> list[ProgramCellFacts]:
        if strength is _StrengthPreference.NONE:
            return candidates
        if strength is _StrengthPreference.STRONGEST:
            scale_order = (3, 2, 1, 0)
        elif strength is _StrengthPreference.WEAKEST:
            scale_order = (1, 2, 3, 0)
        else:
            assert_never(strength)
        for scale in scale_order:
            selected = [facts for facts in candidates if facts.enemy_scale == scale]
            if selected:
                return selected
        return candidates

    @staticmethod
    def _filter_order(
        candidates: list[ProgramCellFacts],
        enemy_filter: tuple[EnemyFilterEntry, ...],
    ) -> list[ProgramCellFacts]:
        selected: list[ProgramCellFacts] = []
        selected_cells: set[CellId] = set()
        for entry in enemy_filter:
            for facts in candidates:
                if facts.cell in selected_cells or not entry.matches(
                    scale=facts.enemy_scale,
                    genre=facts.enemy_genre,
                ):
                    continue
                selected.append(facts)
                selected_cells.add(facts.cell)
        return selected

    @staticmethod
    def _genre_matches(actual: str, requested: tuple[str, ...]) -> bool:
        if not requested:
            return True
        normalized = tuple(value[0].upper() + value[1:] if value[0].islower() else value for value in requested)
        return actual in normalized

    @staticmethod
    def _ordered(
        candidates: list[ProgramCellFacts],
        order: tuple[EnemySortKey, ...],
        executor_fleet: FleetIndex,
    ) -> list[ProgramCellFacts]:
        return sorted(
            candidates,
            key=lambda facts: tuple(BattleTargetSelector._sort_value(facts, key, executor_fleet) for key in order),
        )

    @staticmethod
    def _sort_value(
        facts: ProgramCellFacts,
        key: EnemySortKey,
        executor_fleet: FleetIndex,
    ) -> float:
        if key is EnemySortKey.WEIGHT:
            return facts.weight
        if key is EnemySortKey.EXECUTOR_COST:
            return facts.cost_for(executor_fleet)
        if key is EnemySortKey.FLEET_1_COST:
            return facts.cost_1
        if key is EnemySortKey.FLEET_2_COST:
            return facts.cost_2
        if key is EnemySortKey.ENEMY_SCALE:
            return facts.enemy_scale
        assert_never(key)

    @staticmethod
    def _encounter(facts: ProgramCellFacts) -> SelectedEncounter:
        if facts.is_fortress:
            return EncounterExpectation.FORTRESS
        if facts.is_siren:
            return EncounterExpectation.SIREN
        return EncounterExpectation.ENEMY

    @staticmethod
    def _program_target(encounter: SelectedEncounter) -> program_model.ProgramBattleTarget:
        if encounter in (EncounterExpectation.SIREN, EncounterExpectation.FORTRESS):
            return program_model.ProgramBattleTarget.SIREN
        if encounter is EncounterExpectation.ENEMY:
            return program_model.ProgramBattleTarget.ENEMY
        assert_never(encounter)

    @staticmethod
    def _first(candidates: list[ProgramCellFacts]) -> ProgramCellFacts | None:
        return candidates[0] if candidates else None
