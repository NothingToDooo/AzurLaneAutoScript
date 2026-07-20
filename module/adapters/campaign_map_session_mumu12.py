from typing import TYPE_CHECKING, Protocol

from module.adapters.campaign_runtime_profile import (
    RuntimeSessionContext,
    RuntimeSessionEntryKind,
    RuntimeSessionOutcome,
)
from module.adapters.campaign_runtime_session import RuntimeProfileLease
from module.adapters.campaign_submarine import (
    CampaignSubmarineFreshCombatService,
    SubmarineFreshCombatRuntime,
)
from module.application import AbortRequested
from module.base.failure import preserve_cleanup_failure
from module.content.campaign_session import CampaignRunVariant, CampaignSessionState
from module.content.mechanic_rules import MapMutationPhase, MapMutationRules, MapMutationVariant

if TYPE_CHECKING:
    from module.content.stage_definition import CampaignStageDefinition
    from module.map.map_base import CampaignMap


class Mumu12CampaignMapSessionRuntime(SubmarineFreshCombatRuntime, Protocol):
    definition: CampaignStageDefinition
    MAP: CampaignMap
    map: CampaignMap
    session_variant: CampaignRunVariant
    map_is_clear_mode: bool

    def map_init(self, map_: CampaignMap | None) -> None: ...


def apply_campaign_map_mutations(
    map_: CampaignMap,
    rules: MapMutationRules,
    variant: CampaignRunVariant,
    phase: MapMutationPhase,
    battle: int | None = None,
) -> None:
    """把已编译的地图修补限制在明确的 phase、variant 与 battle。"""

    for patch in rules.patches:
        if patch.phase is not phase or patch.battle != battle:
            continue
        if patch.variant is MapMutationVariant.NORMAL and variant is not CampaignRunVariant.NORMAL:
            continue
        if patch.variant is MapMutationVariant.LOOP and variant is not CampaignRunVariant.LOOP:
            continue
        grid = map_[(patch.cell.x, patch.cell.y)]
        setattr(grid, patch.attribute.value, patch.value)


class Mumu12CampaignMapSessionOwner:
    """持有一张普通 campaign 地图的 profile session 与地图初始化状态。"""

    __slots__ = ("_fresh_combat", "_lease", "_runtime")

    def __init__(
        self,
        runtime: Mumu12CampaignMapSessionRuntime,
        lease: RuntimeProfileLease,
        fresh_combat: CampaignSubmarineFreshCombatService,
    ) -> None:
        if isinstance(runtime, type) or not callable(getattr(runtime, "map_init", None)):
            message = "campaign map session owner requires a map runtime"
            raise TypeError(message)
        if not isinstance(lease, RuntimeProfileLease):
            message = "campaign map session owner requires a RuntimeProfileLease"
            raise TypeError(message)
        if not isinstance(fresh_combat, CampaignSubmarineFreshCombatService):
            message = "campaign map session owner requires a typed fresh combat service"
            raise TypeError(message)
        self._runtime = runtime
        self._lease = lease
        self._fresh_combat = fresh_combat

    @property
    def active(self) -> bool:
        return self._lease.active

    def initialize(
        self,
        state: CampaignSessionState,
        entry_kind: RuntimeSessionEntryKind,
    ) -> None:
        if not isinstance(state, CampaignSessionState):
            message = "campaign map session initialization requires a CampaignSessionState"
            raise TypeError(message)
        if not isinstance(entry_kind, RuntimeSessionEntryKind):
            message = "campaign map session initialization requires a RuntimeSessionEntryKind"
            raise TypeError(message)
        context = RuntimeSessionContext(state.variant, state.battle_index, entry_kind)
        runtime = self._runtime
        runtime.session_variant = state.variant
        runtime.map_is_clear_mode = state.variant is CampaignRunVariant.LOOP
        self._lease.start(context)
        try:
            if entry_kind is RuntimeSessionEntryKind.FRESH:
                self._fresh_combat.start(runtime)
            runtime.map_init(runtime.MAP)
            apply_campaign_map_mutations(
                runtime.map,
                runtime.definition.mechanics.map_mutations,
                state.variant,
                MapMutationPhase.MAP_INIT,
            )
        except BaseException as error:
            outcome = (
                RuntimeSessionOutcome.INTERRUPTED if isinstance(error, AbortRequested) else RuntimeSessionOutcome.FAILED
            )
            preserve_cleanup_failure(
                error,
                lambda: self.close(outcome),
                message="campaign map session initialization and cleanup both failed",
            )
            raise

    def prepare_battle(self, battle_index: int) -> None:
        if type(battle_index) is not int or battle_index < 0:
            message = "campaign battle_index must be a non-negative integer"
            raise ValueError(message)
        runtime = self._runtime
        apply_campaign_map_mutations(
            runtime.map,
            runtime.definition.mechanics.map_mutations,
            runtime.session_variant,
            MapMutationPhase.BEFORE_BATTLE,
            battle_index,
        )

    def close(self, outcome: RuntimeSessionOutcome) -> None:
        self._lease.close(outcome)

    def discard(self) -> None:
        self._lease.discard()
