from typing import TYPE_CHECKING, Protocol, cast

from module.campaign.assets import SWITCH_20241219_COMBAT, SWITCH_20241219_STORY
from module.campaign.campaign_ui import ModeSwitch
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.base.base import ModuleBase
    from module.config.config import AzurLaneConfig


class _NavigationRuntimeHost(Protocol):
    config: AzurLaneConfig

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object: ...


def _operations(options: Mapping[str, RuntimeTuningValue]) -> frozenset[str]:
    value = options["operations"]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = "event 20240912 operations must contain strings"
        raise CampaignRuntimeProfileError(message)
    return frozenset(cast("tuple[str, ...]", value))


class Event20240912NavigationExecutor(RuntimeExecutorInstance):
    """隔离该活动叠加在传统难度开关上的第二个 selector。"""

    __slots__ = ("_mode_switch",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.NAVIGATION)
        expected = {"campaign_ensure_mode", "campaign_set_chapter_20241219"}
        if _operations(options) != expected:
            message = "event 20240912 navigation operations mismatch"
            raise CampaignRuntimeProfileError(message)
        mode_switch = ModeSwitch("Mode_switch_20240912", is_selector=True)
        mode_switch.add_state("combat", SWITCH_20241219_COMBAT, offset=(444, 4))
        mode_switch.add_state("story", SWITCH_20241219_STORY, offset=(444, 4))
        self._mode_switch = mode_switch
        super().__init__(
            {RuntimeExecutorKind.NAVIGATION},
            methods={
                RuntimeExecutorKind.NAVIGATION: {
                    RuntimeOperation.CAMPAIGN_ENSURE_MODE: self._campaign_ensure_mode,
                    RuntimeOperation.CAMPAIGN_SET_CHAPTER_20241219: self._campaign_set_chapter,
                }
            },
        )

    def _campaign_ensure_mode(self, runtime: object, mode: str = "normal") -> object:
        host = cast("_NavigationRuntimeHost", runtime)
        main = cast("ModuleBase", runtime)
        if mode == "story":
            self._mode_switch.set("story", main=main)
        elif mode in {"normal", "hard", "ex"}:
            self._mode_switch.set("combat", main=main)
            host.runtime_super(RuntimeOperation.CAMPAIGN_ENSURE_MODE, mode)
        return None

    @staticmethod
    def _campaign_set_chapter(
        runtime: object,
        chapter: str,
        stage: str,
        mode: str = "combat",
    ) -> object:
        host = cast("_NavigationRuntimeHost", runtime)
        host.config.apply_runtime_overlay(
            MAP_CHAPTER_SWITCH_20241219=False,
            MAP_HAS_MODE_SWITCH=False,
        )
        return host.runtime_super(
            RuntimeOperation.CAMPAIGN_SET_CHAPTER_20241219,
            chapter,
            stage,
            mode,
        )


def _build_event_20240912_navigation(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return Event20240912NavigationExecutor(context)


def special_navigation_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_20240912_cn/campaign_base/campaign_base"),
            {
                RuntimeExecutorKind.NAVIGATION: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations"}),
                )
            },
            _build_event_20240912_navigation,
        ),
    )
