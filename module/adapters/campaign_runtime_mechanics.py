from typing import TYPE_CHECKING, Protocol, cast, override

from module.base.mask import Mask
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId
from module.logger import logger
from module.map.assets import FLEET_SUPPORT_EMPTY
from module.map.map_swipe import MapSwipePolicy
from module.map.support_fleet import SupportFleetAttemptState, SupportFleetStatus
from module.map_detection.utils_assets import ASSETS

from .campaign_fleet_preparation import CampaignFleetPreparationContributor
from .campaign_map_initialization import (
    CampaignMapInitializationContributor,
    CampaignMapInitializationRuntime,
)
from .campaign_program_capabilities import (
    CampaignProgramCapabilityContribution,
)
from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeSessionOutcome,
    RuntimeStateSeed,
)
from .campaign_strategy_set import CampaignStrategySetObserverContributor

if TYPE_CHECKING:
    from module.adapters.campaign_fleet_preparation import FleetPreparationNext
    from module.application import CancellationSource
    from module.config.config import AzurLaneConfig
    from module.handler.strategy_set import StrategySetRequest, StrategySetRuntime
    from module.map.map_fleet_preparation import FleetPreparationRuntime

_SUPPORT_SWIPE_POLICY = MapSwipePolicy(default_box=(239, 159, 1175, 628))
_UI_MASK_CACHE_KEYS = ("ui_mask", "ui_mask_stroke", "ui_mask_in_map")
_MASKS = {
    "support_fleet": Mask(file="./assets/mask/MASK_MAP_UI_SUPPORT.png"),
    "event_20211125": Mask(file="./assets/mask/MASK_MAP_UI_20211125.png"),
}


class _MechanicRuntimeHost(Protocol):
    config: AzurLaneConfig
    map_is_clear_mode: bool

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool: ...

    def strategy_has_mob_move(self) -> bool: ...


def _host(runtime: object) -> _MechanicRuntimeHost:
    return cast("_MechanicRuntimeHost", runtime)


class SupportFleetExecutor(RuntimeExecutorInstance):
    """维护支援舰队可用性，并限制地图拖动区域。"""

    __slots__ = ("_fleet_preparation_contributor", "_support_fleet_state")

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        _ = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        self._support_fleet_state = SupportFleetAttemptState()
        self._fleet_preparation_contributor = CampaignFleetPreparationContributor(
            self._observe_support_fleet,
        )
        super().__init__({RuntimeExecutorKind.MAP_MECHANIC})

    def _observe_support_fleet(
        self,
        runtime: FleetPreparationRuntime,
        next_handler: FleetPreparationNext,
    ) -> bool:
        host = _host(runtime)
        status = (
            SupportFleetStatus.EMPTY if host.appear(FLEET_SUPPORT_EMPTY, offset=(5, 5)) else SupportFleetStatus.PRESENT
        )
        self._support_fleet_state.observe(status)
        logger.attr("use_support_fleet", self._support_fleet_state.available)
        return next_handler(runtime)

    @property
    def fleet_preparation_contributor(self) -> CampaignFleetPreparationContributor:
        return self._fleet_preparation_contributor

    @property
    def support_fleet_state(self) -> SupportFleetAttemptState:
        return self._support_fleet_state

    @property
    def map_swipe_policy(self) -> MapSwipePolicy:
        return _SUPPORT_SWIPE_POLICY

    @override
    def reset(self) -> None:
        self._support_fleet_state.reset()
        super().reset()


class RuntimeUiMaskExecutor(RuntimeExecutorInstance):
    """在 session 内替换地图 UI mask，并在结束时恢复全局缓存。"""

    __slots__ = ("_condition", "_map_initialization_contributor", "_mask", "_saved_cache")

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.ENGINE_EXTENSION)
        asset = options["asset"]
        if not isinstance(asset, str) or asset not in _MASKS:
            message = f"unsupported runtime UI mask: {asset!r}"
            raise CampaignRuntimeProfileError(message)
        condition = options["condition"]
        if condition not in {"always", "use_support_fleet"}:
            message = f"unsupported runtime UI mask condition: {condition!r}"
            raise CampaignRuntimeProfileError(message)
        self._mask = _MASKS[asset]
        self._condition = cast("str", condition)
        self._saved_cache: dict[str, object] | None = None
        self._map_initialization_contributor = CampaignMapInitializationContributor(
            pre_control=self._install_for_session,
        )
        super().__init__({RuntimeExecutorKind.ENGINE_EXTENSION})

    def _install_for_session(self, runtime: CampaignMapInitializationRuntime) -> None:
        del runtime
        if self._condition == "use_support_fleet" and not self.current_use_support_fleet():
            return
        self._install_mask()

    @property
    def map_initialization_contributor(self) -> CampaignMapInitializationContributor:
        return self._map_initialization_contributor

    def _install_mask(self) -> None:
        if self._saved_cache is not None:
            return
        cache = ASSETS.__dict__
        self._saved_cache = {key: cache[key] for key in _UI_MASK_CACHE_KEYS if key in cache}
        for key in _UI_MASK_CACHE_KEYS:
            cache.pop(key, None)
        cache["ui_mask"] = self._mask.image

    def _restore_mask(self) -> None:
        saved = self._saved_cache
        if saved is None:
            return
        cache = ASSETS.__dict__
        for key in _UI_MASK_CACHE_KEYS:
            cache.pop(key, None)
        cache.update(saved)
        self._saved_cache = None

    @override
    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        self._restore_mask()
        super().end_session(outcome)

    @override
    def reset(self) -> None:
        self._restore_mask()
        super().reset()


class MobMoveFeatureExecutor(RuntimeExecutorInstance):
    """声明十五图敌舰移动能力，并在策略设置成功后记录 UI 事实。"""

    __slots__ = (
        "_program_capability_contribution",
        "_strategy_set_observer_contributor",
    )

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        _ = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        super().__init__({RuntimeExecutorKind.MAP_MECHANIC})
        self._strategy_set_observer_contributor = CampaignStrategySetObserverContributor(
            self._observe_strategy_set,
        )
        self._program_capability_contribution = CampaignProgramCapabilityContribution(
            map_has_mob_move=True,
        )

    @staticmethod
    def _observe_strategy_set(
        runtime: StrategySetRuntime,
        request: StrategySetRequest,
    ) -> None:
        del request
        logger.attr("Map has mob move", _host(runtime).strategy_has_mob_move())

    @property
    def strategy_set_observer_contributor(self) -> CampaignStrategySetObserverContributor:
        return self._strategy_set_observer_contributor

    @property
    def program_capability_contribution(self) -> CampaignProgramCapabilityContribution:
        return self._program_capability_contribution


class Chapter16SessionStateExecutor(RuntimeExecutorInstance):
    """在地图控制初始化后计算十六图的 typed session state。"""

    __slots__ = ("_map_has_mob_move_override", "_map_initialization_contributor")

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        _ = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        self._map_has_mob_move_override = False
        self._map_initialization_contributor = CampaignMapInitializationContributor(
            post_control=self._update_session_state,
        )
        super().__init__(
            {RuntimeExecutorKind.MAP_MECHANIC},
            state_seed=RuntimeStateSeed(
                use_single_fleet_override=False,
            ),
        )

    def _update_session_state(self, runtime: CampaignMapInitializationRuntime) -> None:
        host = _host(runtime)
        self._map_has_mob_move_override = self.current_use_support_fleet() and host.map_is_clear_mode
        self.set_use_single_fleet_override(
            enabled="standby" in host.config.Fleet_FleetOrder,
        )

    @property
    def map_initialization_contributor(self) -> CampaignMapInitializationContributor:
        return self._map_initialization_contributor

    def map_has_mob_move_override(
        self,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        return self._map_has_mob_move_override

    @override
    def reset(self) -> None:
        self._map_has_mob_move_override = False
        super().reset()


def _build_support_fleet(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return SupportFleetExecutor(context)


def _build_ui_mask(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return RuntimeUiMaskExecutor(context)


def _build_mob_move_feature(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return MobMoveFeatureExecutor(context)


def _build_chapter16_session_state(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return Chapter16SessionStateExecutor(context)


def mechanic_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/support_fleet"),
            {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()},
            _build_support_fleet,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("engine/ui_mask"),
            {
                RuntimeExecutorKind.ENGINE_EXTENSION: RuntimeExecutorOptionsSchema(
                    required=frozenset({"asset", "condition"}),
                )
            },
            _build_ui_mask,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/mob_move_feature"),
            {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()},
            _build_mob_move_feature,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/chapter16_session_state"),
            {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()},
            _build_chapter16_session_state,
        ),
    )
