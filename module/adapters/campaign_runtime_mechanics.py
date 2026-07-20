from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, cast, override

from module.base.mask import Mask
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.logger import logger
from module.map.assets import FLEET_SUPPORT_EMPTY
from module.map_detection.utils_assets import ASSETS

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
    RuntimeSessionContext,
    RuntimeSessionEntryKind,
    RuntimeSessionOutcome,
    RuntimeStateSeed,
)

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig

_SUPPORT_SWIPE_BOX = (239, 159, 1175, 628)
_UI_MASK_CACHE_KEYS = ("ui_mask", "ui_mask_stroke", "ui_mask_in_map")
_MASKS = {
    "support_fleet": Mask(file="./assets/mask/MASK_MAP_UI_SUPPORT.png"),
    "event_20211125": Mask(file="./assets/mask/MASK_MAP_UI_20211125.png"),
}


class _MechanicRuntimeHost(Protocol):
    FUNCTION_NAME_BASE: str
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

    def handle_popup_confirm(self, name: str) -> bool: ...

    def combat(
        self,
        *,
        balance_hp: bool,
        emotion_reduce: bool,
        expected_end: str,
    ) -> object: ...


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

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        _require_operations(options, frozenset({"_map_swipe", "fleet_preparation"}))
        if _strings(options, "state") != ("use_support_fleet",):
            message = "support-fleet executor must own use_support_fleet state"
            raise CampaignRuntimeProfileError(message)
        super().__init__(
            {RuntimeExecutorKind.MAP_MECHANIC},
            methods={
                RuntimeExecutorKind.MAP_MECHANIC: {
                    RuntimeOperation.FLEET_PREPARATION: self._fleet_preparation,
                    RuntimeOperation.MAP_SWIPE: self._map_swipe,
                }
            },
            state_seed=RuntimeStateSeed(use_support_fleet=True),
        )

    def _fleet_preparation(self, runtime: object) -> object:
        host = _host(runtime)
        self.set_use_support_fleet(
            enabled=not host.appear(FLEET_SUPPORT_EMPTY, offset=(5, 5)),
        )
        logger.attr("use_support_fleet", self.current_use_support_fleet())
        return host.runtime_super(RuntimeOperation.FLEET_PREPARATION)

    @staticmethod
    def _map_swipe(
        runtime: object,
        vector: object,
        box: object = _SUPPORT_SWIPE_BOX,
    ) -> object:
        return _host(runtime).runtime_super(RuntimeOperation.MAP_SWIPE, vector, box=box)


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


class SubmarineFreshEntryExecutor(RuntimeExecutorInstance):
    """只在真正的新进图边界处理支援潜艇的开场战斗。"""

    __slots__ = ("_fresh_entry",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        _require_operations(
            options,
            frozenset({"handle_submarine_support_popup", "map_init"}),
        )
        self._fresh_entry = False
        super().__init__(
            {RuntimeExecutorKind.MAP_MECHANIC},
            methods={
                RuntimeExecutorKind.MAP_MECHANIC: {
                    RuntimeOperation.HANDLE_SUBMARINE_SUPPORT_POPUP: self._handle_submarine_support_popup,
                    RuntimeOperation.MAP_INIT: self._map_init,
                }
            },
        )

    @override
    def begin_session(self, context: RuntimeSessionContext) -> None:
        super().begin_session(context)
        self._fresh_entry = context.entry_kind is RuntimeSessionEntryKind.FRESH

    def _map_init(self, runtime: object, map_: object) -> object:
        host = _host(runtime)
        if self._fresh_entry and self.current_use_support_fleet():
            logger.hr(f"{host.FUNCTION_NAME_BASE}SUBMARINE", level=2)
            host.combat(
                balance_hp=False,
                emotion_reduce=False,
                expected_end="no_searching",
            )
        return host.runtime_super(RuntimeOperation.MAP_INIT, map_)

    def _handle_submarine_support_popup(self, runtime: object) -> object:
        return self.current_use_support_fleet() and _host(runtime).handle_popup_confirm("SUBMARINE_SUPPORT")


class MobMoveStrategyStateExecutor(RuntimeExecutorInstance):
    """把十五图的可移动敌舰策略状态投影到 typed session state。"""

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        _require_operations(options, frozenset({"strategy_set_execute"}))
        if _strings(options, "state") != ("map_has_mob_move",):
            message = "mob-move strategy executor must own map_has_mob_move state"
            raise CampaignRuntimeProfileError(message)
        super().__init__(
            {RuntimeExecutorKind.MAP_MECHANIC},
            methods={
                RuntimeExecutorKind.MAP_MECHANIC: {
                    RuntimeOperation.STRATEGY_SET_EXECUTE: self._strategy_set_execute,
                }
            },
            state_seed=RuntimeStateSeed(map_has_mob_move=True),
        )

    @staticmethod
    def _strategy_set_execute(runtime: object, *args: object, **kwargs: object) -> object:
        host = _host(runtime)
        result = host.runtime_super(RuntimeOperation.STRATEGY_SET_EXECUTE, *args, **kwargs)
        logger.attr("Map has mob move", host.strategy_has_mob_move())
        return result


class SessionStatePolicyExecutor(RuntimeExecutorInstance):
    """在 MAP_INIT 后从本次地图运行事实计算十六图的 typed session state。"""

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        _require_operations(options, frozenset({"map_init"}))
        if frozenset(_strings(options, "state")) != {"map_has_mob_move", "use_single_fleet"}:
            message = "session-state policy must own map_has_mob_move and use_single_fleet"
            raise CampaignRuntimeProfileError(message)
        self._validate_rules(options["rules"])
        super().__init__(
            {RuntimeExecutorKind.MAP_MECHANIC},
            methods={
                RuntimeExecutorKind.MAP_MECHANIC: {
                    RuntimeOperation.MAP_INIT: self._map_init,
                }
            },
            state_seed=RuntimeStateSeed(
                map_has_mob_move=False,
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
        self.set_map_has_mob_move(
            enabled=self.current_use_support_fleet() and host.map_is_clear_mode,
        )
        self.set_use_single_fleet_override(
            enabled="standby" in host.config.Fleet_FleetOrder,
        )
        return result


def _build_support_fleet(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return SupportFleetExecutor(context)


def _build_ui_mask(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return RuntimeUiMaskExecutor(context)


def _build_submarine_fresh_entry(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return SubmarineFreshEntryExecutor(context)


def _build_mob_move_strategy_state(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return MobMoveStrategyStateExecutor(context)


def _build_session_state_policy(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return SessionStatePolicyExecutor(context)


def mechanic_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    mechanic_schema = RuntimeExecutorOptionsSchema(
        required=frozenset({"operations", "state"}),
    )
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/support_fleet"),
            {RuntimeExecutorKind.MAP_MECHANIC: mechanic_schema},
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
            RuntimeImplementationId("map_mechanic/submarine_fresh_entry"),
            {
                RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations"}),
                )
            },
            _build_submarine_fresh_entry,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/mob_move_strategy_state"),
            {RuntimeExecutorKind.MAP_MECHANIC: mechanic_schema},
            _build_mob_move_strategy_state,
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
