from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, cast

from module.combat.assets import ALCHEMIST_MATERIAL_CONFIRM
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.ui.page import page_campaign, page_event

from .campaign_clear_mode_config import (
    CampaignClearModeConfigContributor,
    CampaignClearModeConfigRuntime,
)
from .campaign_event_ui import (
    CampaignEventCombatResultContributor,
    CampaignEventUiContributor,
    CampaignEventUiExecutor,
    CampaignMapTransitionContributor,
)
from .campaign_map_initialization import (
    CampaignMapInitializationContributor,
    CampaignMapInitializationRuntime,
)
from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)

if TYPE_CHECKING:
    from module.combat.combat_result_ui import CombatResultRuntime
    from module.config.config import AzurLaneConfig
    from module.config.config_generated import ConfigOverrides

    from .campaign_event_ui import EventCombatResultNext


class _SemanticRuntimeHost(Protocol):
    config: AzurLaneConfig

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


def _build_exp_info_page_guard(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _required_options(context, RuntimeExecutorKind.EVENT_UI)
    blocked_page = _string_option(options, "blocked_page")
    if blocked_page == "campaign":
        page = page_campaign
    elif blocked_page == "event":
        page = page_event
    else:
        message = f"unsupported EXP-info blocked page: {blocked_page}"
        raise CampaignRuntimeProfileError(message)

    def handle_experience_result(
        runtime: CombatResultRuntime,
        next_handler: EventCombatResultNext,
    ) -> bool:
        host = _host(runtime)
        if host.ui_page_appear(page):
            return False
        return next_handler(runtime)

    return CampaignEventUiExecutor(
        {RuntimeExecutorKind.EVENT_UI},
        CampaignEventUiContributor(
            combat_result=CampaignEventCombatResultContributor(
                handle_experience_result=handle_experience_result,
            )
        ),
    )


def _build_exp_info_click_guard(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _required_options(context, RuntimeExecutorKind.EVENT_UI)
    asset = _string_option(options, "asset")
    if asset != "ALCHEMIST_MATERIAL_CONFIRM":
        message = f"unsupported EXP-info confirmation asset: {asset}"
        raise CampaignRuntimeProfileError(message)
    offset = _offset_option(options, "offset")
    interval = _number_option(options, "interval")

    def handle_experience_result(
        runtime: CombatResultRuntime,
        next_handler: EventCombatResultNext,
    ) -> bool:
        host = _host(runtime)
        if host.appear_then_click(
            ALCHEMIST_MATERIAL_CONFIRM,
            offset=offset,
            interval=interval,
        ):
            return False
        return next_handler(runtime)

    return CampaignEventUiExecutor(
        {RuntimeExecutorKind.EVENT_UI},
        CampaignEventUiContributor(
            combat_result=CampaignEventCombatResultContributor(
                handle_experience_result=handle_experience_result,
            )
        ),
    )


class CampaignClearModeConfigOverlayExecutor(RuntimeExecutorInstance):
    __slots__ = ("_clear_mode_config_contributor",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = _required_options(context, RuntimeExecutorKind.ENGINE_EXTENSION)
        condition = _string_option(options, "condition")
        if condition not in {"always", "handled"}:
            message = f"unsupported clear-mode overlay condition: {condition}"
            raise CampaignRuntimeProfileError(message)
        raw_overrides = options["overrides"]
        if not isinstance(raw_overrides, Mapping):
            message = "clear-mode overlay overrides must be an object"
            raise CampaignRuntimeProfileError(message)
        overrides = dict(cast("Mapping[str, object]", raw_overrides))

        def apply(runtime: CampaignClearModeConfigRuntime, *, handled: bool) -> None:
            if condition == "always" or handled:
                runtime.config.apply_runtime_overlay(**cast("ConfigOverrides", overrides))

        self._clear_mode_config_contributor = CampaignClearModeConfigContributor(apply)
        super().__init__({RuntimeExecutorKind.ENGINE_EXTENSION})

    @property
    def clear_mode_config_contributor(self) -> CampaignClearModeConfigContributor:
        return self._clear_mode_config_contributor


def _build_clear_mode_config_overlay(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return CampaignClearModeConfigOverlayExecutor(context)


def _build_event_animation_expected_end(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = _required_options(context, RuntimeExecutorKind.EVENT_UI)
    battle = _integer_option(options, "event_animation_end_battle")
    if battle < 0:
        message = "event-animation end battle must be non-negative"
        raise CampaignRuntimeProfileError(message)

    return CampaignEventUiExecutor(
        {RuntimeExecutorKind.EVENT_UI},
        CampaignEventUiContributor(
            map_transition=CampaignMapTransitionContributor(
                event_animation_end_battle=battle,
            ),
        ),
    )


class DefaultEnemyScaleBalanceExecutor(RuntimeExecutorInstance):
    """在地图控制初始化前恢复活动图的默认敌人权重。"""

    __slots__ = ("_map_initialization_contributor",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        _ = context.options(RuntimeExecutorKind.ENGINE_EXTENSION)
        self._map_initialization_contributor = CampaignMapInitializationContributor(
            pre_control=self._apply_default_enemy_scale_balance,
        )
        super().__init__({RuntimeExecutorKind.ENGINE_EXTENSION})

    @staticmethod
    def _apply_default_enemy_scale_balance(runtime: CampaignMapInitializationRuntime) -> None:
        _host(runtime).config.apply_runtime_overlay(
            **cast(
                "ConfigOverrides",
                {"EnemyPriority_EnemyScaleBalanceWeight": "default_mode"},
            )
        )

    @property
    def map_initialization_contributor(self) -> CampaignMapInitializationContributor:
        return self._map_initialization_contributor


def _build_default_enemy_scale_balance(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return DefaultEnemyScaleBalanceExecutor(context)


def semantic_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    """返回跨活动复用、由结构化 options 驱动的 production executors。"""

    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_ui/exp_info_page_guard"),
            {
                RuntimeExecutorKind.EVENT_UI: RuntimeExecutorOptionsSchema(
                    required=frozenset({"blocked_page"}),
                )
            },
            _build_exp_info_page_guard,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_ui/exp_info_click_guard"),
            {
                RuntimeExecutorKind.EVENT_UI: RuntimeExecutorOptionsSchema(
                    required=frozenset({"asset", "interval", "offset"}),
                )
            },
            _build_exp_info_click_guard,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("engine/clear_mode_config_overlay"),
            {
                RuntimeExecutorKind.ENGINE_EXTENSION: RuntimeExecutorOptionsSchema(
                    required=frozenset({"condition", "overrides"}),
                )
            },
            _build_clear_mode_config_overlay,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_ui/event_animation_expected_end"),
            {
                RuntimeExecutorKind.EVENT_UI: RuntimeExecutorOptionsSchema(
                    required=frozenset({"event_animation_end_battle"}),
                )
            },
            _build_event_animation_expected_end,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("engine/default_enemy_scale_balance"),
            {RuntimeExecutorKind.ENGINE_EXTENSION: RuntimeExecutorOptionsSchema()},
            _build_default_enemy_scale_balance,
        ),
    )
