from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, cast, override

from module.base.mask import Mask
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.logger import logger
from module.map.assets import FLEET_SUPPORT_EMPTY
from module.map.map_swipe import MapSwipePolicy
from module.map.support_fleet import SupportFleetAttemptState, SupportFleetStatus
from module.map_detection.utils_assets import ASSETS

from .campaign_fleet_preparation import CampaignFleetPreparationContributor
from .campaign_program_capabilities import (
    CampaignProgramCapabilityContribution,
)
from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
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

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object: ...

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool: ...

    def strategy_has_mob_move(self) -> bool: ...


def _host(runtime: object) -> _MechanicRuntimeHost:
    return cast("_MechanicRuntimeHost", runtime)


def _strings(options: Mapping[str, RuntimeTuningValue], name: str) -> tuple[str, ...]:
    value = options[name]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = f"runtime mechanic option {name} must contain strings"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[str, ...]", value)


def _require_operations(
    options: Mapping[str, RuntimeTuningValue],
    expected: frozenset[str],
) -> None:
    operations = frozenset(_strings(options, "operations"))
    if operations != expected:
        message = f"runtime mechanic operations mismatch: expected={sorted(expected)}, actual={sorted(operations)}"
        raise CampaignRuntimeProfileError(message)


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

    __slots__ = ("_condition", "_mask", "_saved_cache")

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.ENGINE_EXTENSION)
        _require_operations(options, frozenset({"map_data_init"}))
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
        super().__init__(
            {RuntimeExecutorKind.ENGINE_EXTENSION},
            methods={
                RuntimeExecutorKind.ENGINE_EXTENSION: {
                    RuntimeOperation.MAP_DATA_INIT: self._map_data_init,
                }
            },
        )

    def _map_data_init(self, runtime: object, map_: object) -> object:
        host = _host(runtime)
        result = host.runtime_super(RuntimeOperation.MAP_DATA_INIT, map_)
        if self._condition == "use_support_fleet" and not self.current_use_support_fleet():
            return result
        self._install_mask()
        return result

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


class SessionStatePolicyExecutor(RuntimeExecutorInstance):
    """在 MAP_INIT 后从本次地图运行事实计算十六图的 typed session state。"""

    __slots__ = ("_map_has_mob_move_override",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        _require_operations(options, frozenset({"map_init"}))
        if _strings(options, "state") != ("use_single_fleet",):
            message = "session-state policy must own use_single_fleet state"
            raise CampaignRuntimeProfileError(message)
        self._validate_rules(options["rules"])
        self._map_has_mob_move_override = False
        super().__init__(
            {RuntimeExecutorKind.MAP_MECHANIC},
            methods={
                RuntimeExecutorKind.MAP_MECHANIC: {
                    RuntimeOperation.MAP_INIT: self._map_init,
                }
            },
            state_seed=RuntimeStateSeed(
                use_single_fleet_override=False,
            ),
        )

    @staticmethod
    def _validate_rules(raw: RuntimeTuningValue) -> None:
        if not isinstance(raw, tuple) or len(raw) != 2:
            message = "session-state policy requires exactly two rules"
            raise CampaignRuntimeProfileError(message)
        mob_move, single_fleet = raw
        if not isinstance(mob_move, Mapping) or dict(mob_move) != {
            "target": "map_has_mob_move",
            "all": ("use_support_fleet", "clear_mode"),
        }:
            message = "unsupported session-state map_has_mob_move rule"
            raise CampaignRuntimeProfileError(message)
        if not isinstance(single_fleet, Mapping) or dict(single_fleet) != {
            "target": "use_single_fleet",
            "fleet_order_contains": "standby",
        }:
            message = "unsupported session-state use_single_fleet rule"
            raise CampaignRuntimeProfileError(message)

    def _map_init(self, runtime: object, map_: object) -> object:
        host = _host(runtime)
        result = host.runtime_super(RuntimeOperation.MAP_INIT, map_)
        self._map_has_mob_move_override = self.current_use_support_fleet() and host.map_is_clear_mode
        self.set_use_single_fleet_override(
            enabled="standby" in host.config.Fleet_FleetOrder,
        )
        return result

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


def _build_session_state_policy(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return SessionStatePolicyExecutor(context)


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
                    required=frozenset({"operations", "asset", "condition"}),
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
            RuntimeImplementationId("map_mechanic/session_state_policy"),
            {
                RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "rules", "state"}),
                )
            },
            _build_session_state_policy,
        ),
    )
