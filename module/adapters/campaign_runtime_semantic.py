from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, cast

from module.combat.assets import ALCHEMIST_MATERIAL_CONFIRM
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.ui.page import page_campaign, page_event

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
)

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.config.config_generated import ConfigOverrides


class _SemanticRuntimeHost(Protocol):
    config: AzurLaneConfig
    battle_count: int
    event_animation_end: object

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object: ...

    def ui_page_appear(self, page: object) -> bool: ...

    def appear_then_click(
        self,
        button: object,
        *,
        offset: tuple[int, int],
        interval: float,
    ) -> bool: ...


def _host(runtime: object) -> _SemanticRuntimeHost:
    return cast("_SemanticRuntimeHost", runtime)


def _required_options(
    context: RuntimeExecutorBuildContext,
    kind: RuntimeExecutorKind,
) -> Mapping[str, RuntimeTuningValue]:
    return context.options(kind)


def _string_option(
    options: Mapping[str, RuntimeTuningValue],
    name: str,
) -> str:
    value = options[name]
    if not isinstance(value, str) or not value:
        message = f"runtime executor option {name} must be a non-empty string"
        raise CampaignRuntimeProfileError(message)
    return value


def _integer_option(
    options: Mapping[str, RuntimeTuningValue],
    name: str,
) -> int:
    value = options[name]
    if type(value) is not int:
        message = f"runtime executor option {name} must be an integer"
        raise CampaignRuntimeProfileError(message)
    return value


def _offset_option(
    options: Mapping[str, RuntimeTuningValue],
    name: str,
) -> tuple[int, int]:
    value = options[name]
    if not isinstance(value, tuple) or len(value) != 2 or any(type(item) is not int for item in value):
        message = f"runtime executor option {name} must contain two integers"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[int, int]", value)


def _number_option(
    options: Mapping[str, RuntimeTuningValue],
    name: str,
) -> float:
    value = options[name]
    if type(value) not in (int, float):
        message = f"runtime executor option {name} must be a number"
        raise CampaignRuntimeProfileError(message)
    return float(cast("int | float", value))


def _require_operations(
    options: Mapping[str, RuntimeTuningValue],
    expected: frozenset[str],
) -> None:
    value = options["operations"]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = "runtime semantic executor operations must contain strings"
        raise CampaignRuntimeProfileError(message)
    actual = frozenset(cast("tuple[str, ...]", value))
    if actual != expected:
        message = f"runtime semantic operations mismatch: expected={sorted(expected)}, actual={sorted(actual)}"
        raise CampaignRuntimeProfileError(message)


def _build_exp_info_page_guard(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _required_options(context, RuntimeExecutorKind.EVENT_UI)
    _require_operations(options, frozenset({"handle_exp_info"}))
    blocked_page = _string_option(options, "blocked_page")
    if blocked_page == "campaign":
        page = page_campaign
    elif blocked_page == "event":
        page = page_event
    else:
        message = f"unsupported EXP-info blocked page: {blocked_page}"
        raise CampaignRuntimeProfileError(message)

    def handle_exp_info(runtime: object) -> object:
        host = _host(runtime)
        if host.ui_page_appear(page):
            return False
        return host.runtime_super(RuntimeOperation.HANDLE_EXP_INFO)

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.EVENT_UI},
        methods={
            RuntimeExecutorKind.EVENT_UI: {
                RuntimeOperation.HANDLE_EXP_INFO: handle_exp_info,
            }
        },
    )


def _build_exp_info_click_guard(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _required_options(context, RuntimeExecutorKind.EVENT_UI)
    _require_operations(options, frozenset({"handle_exp_info"}))
    asset = _string_option(options, "asset")
    if asset != "ALCHEMIST_MATERIAL_CONFIRM":
        message = f"unsupported EXP-info confirmation asset: {asset}"
        raise CampaignRuntimeProfileError(message)
    offset = _offset_option(options, "offset")
    interval = _number_option(options, "interval")

    def handle_exp_info(runtime: object) -> object:
        host = _host(runtime)
        if host.appear_then_click(
            ALCHEMIST_MATERIAL_CONFIRM,
            offset=offset,
            interval=interval,
        ):
            return False
        return host.runtime_super(RuntimeOperation.HANDLE_EXP_INFO)

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.EVENT_UI},
        methods={
            RuntimeExecutorKind.EVENT_UI: {
                RuntimeOperation.HANDLE_EXP_INFO: handle_exp_info,
            }
        },
    )


def _build_clear_mode_config_overlay(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _required_options(context, RuntimeExecutorKind.ENGINE_EXTENSION)
    _require_operations(options, frozenset({"handle_clear_mode_config_cover"}))
    condition = _string_option(options, "condition")
    if condition not in {"always", "handled"}:
        message = f"unsupported clear-mode overlay condition: {condition}"
        raise CampaignRuntimeProfileError(message)
    raw_overrides = options["overrides"]
    if not isinstance(raw_overrides, Mapping):
        message = "clear-mode overlay overrides must be an object"
        raise CampaignRuntimeProfileError(message)
    overrides = dict(cast("Mapping[str, object]", raw_overrides))

    def handle_clear_mode_config_cover(runtime: object) -> object:
        host = _host(runtime)
        handled = host.runtime_super(RuntimeOperation.HANDLE_CLEAR_MODE_CONFIG_COVER)
        if type(handled) is not bool:
            message = "clear-mode config cover must return a boolean"
            raise CampaignRuntimeProfileError(message)
        if condition == "always" or handled:
            host.config.apply_runtime_overlay(**cast("ConfigOverrides", overrides))
        return handled

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.ENGINE_EXTENSION},
        methods={
            RuntimeExecutorKind.ENGINE_EXTENSION: {
                RuntimeOperation.HANDLE_CLEAR_MODE_CONFIG_COVER: handle_clear_mode_config_cover,
            }
        },
    )


def _build_event_animation_expected_end(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _required_options(context, RuntimeExecutorKind.ENGINE_EXTENSION)
    _require_operations(options, frozenset({"_expected_end"}))
    battle = _integer_option(options, "event_animation_end_battle")
    if battle < 0:
        message = "event-animation end battle must be non-negative"
        raise CampaignRuntimeProfileError(message)

    def expected_end(runtime: object, expected: object) -> object:
        host = _host(runtime)
        if host.battle_count == battle:
            return host.event_animation_end
        return host.runtime_super(RuntimeOperation.EXPECTED_END, expected)

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.ENGINE_EXTENSION},
        methods={
            RuntimeExecutorKind.ENGINE_EXTENSION: {
                RuntimeOperation.EXPECTED_END: expected_end,
            }
        },
    )


def _build_runtime_config_overlay(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _required_options(context, RuntimeExecutorKind.ENGINE_EXTENSION)
    _require_operations(options, frozenset({"map_data_init"}))
    phase = _string_option(options, "phase")
    if phase != "map_init":
        message = f"unsupported runtime config overlay phase: {phase}"
        raise CampaignRuntimeProfileError(message)
    raw_overrides = options["overrides"]
    if not isinstance(raw_overrides, Mapping):
        message = "runtime config overlay overrides must be an object"
        raise CampaignRuntimeProfileError(message)
    overrides = dict(cast("Mapping[str, object]", raw_overrides))
    if overrides != {"EnemyPriority_EnemyScaleBalanceWeight": "default_mode"}:
        message = f"unsupported runtime config overlay: {overrides!r}"
        raise CampaignRuntimeProfileError(message)

    def map_data_init(runtime: object, map_: object) -> object:
        host = _host(runtime)
        result = host.runtime_super(RuntimeOperation.MAP_DATA_INIT, map_)
        host.config.apply_runtime_overlay(**cast("ConfigOverrides", overrides))
        return result

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.ENGINE_EXTENSION},
        methods={
            RuntimeExecutorKind.ENGINE_EXTENSION: {
                RuntimeOperation.MAP_DATA_INIT: map_data_init,
            }
        },
    )


def semantic_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    """返回跨活动复用、由结构化 options 驱动的 production executors。"""

    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_ui/exp_info_page_guard"),
            {
                RuntimeExecutorKind.EVENT_UI: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "blocked_page"}),
                )
            },
            _build_exp_info_page_guard,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_ui/exp_info_click_guard"),
            {
                RuntimeExecutorKind.EVENT_UI: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "asset", "interval", "offset"}),
                )
            },
            _build_exp_info_click_guard,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("engine/clear_mode_config_overlay"),
            {
                RuntimeExecutorKind.ENGINE_EXTENSION: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "condition", "overrides"}),
                )
            },
            _build_clear_mode_config_overlay,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("engine/event_animation_expected_end"),
            {
                RuntimeExecutorKind.ENGINE_EXTENSION: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "event_animation_end_battle"}),
                )
            },
            _build_event_animation_expected_end,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("engine/runtime_config_overlay"),
            {
                RuntimeExecutorKind.ENGINE_EXTENSION: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "overrides", "phase"}),
                )
            },
            _build_runtime_config_overlay,
        ),
    )
