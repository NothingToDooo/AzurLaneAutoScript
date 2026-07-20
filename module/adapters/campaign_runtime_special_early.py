from typing import TYPE_CHECKING, Protocol, cast, override

from module.campaign.assets import EVENT_20221124_ENTRANCE, EVENT_20221124_PT_ICON
from module.campaign.event_destination import EventDestination, EventDestinationHost
from module.combat.assets import GET_ITEMS_1_RYZA
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.handler.assets import MYSTERY_ITEM
from module.logger import logger
from module.ui.page import page_campaign_menu, page_event

from .campaign_event_ui import CampaignEventUiContributor, CampaignEventUiExecutor
from .campaign_map_observer import (
    CameraRepositioningNext,
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
)
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

    from module.map.map_observer import MapObserverRuntime
    from module.map_detection.grid_info import GridInfo

type _Offset = tuple[int, int] | tuple[int, int, int, int]

_T4_IMPLEMENTATION = RuntimeImplementationId("event_20211125_cn/t4/campaign")
_RYZA_IMPLEMENTATION = RuntimeImplementationId("event_20221124_cn/campaign_base/campaign_base")


class _Device(Protocol):
    def click(self, button: object) -> object: ...

    def sleep(self, seconds: float) -> None: ...

    def screenshot(self) -> object: ...


class _T4ObservationHost(Protocol):
    device: _Device
    map_is_clear_mode: bool


class _RyzaRuntimeHost(Protocol):
    device: _Device

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object: ...

    def appear(self, button: object, *, offset: _Offset) -> bool: ...

    def ui_page_appear(self, page: object) -> bool: ...

    def ui_ensure(self, page: object) -> object: ...

    def is_event_entrance_available(self) -> bool: ...

    def ui_click(
        self,
        button: object,
        *,
        check_button: object,
        appear_button: object,
    ) -> object: ...


def _operations(
    options: Mapping[str, RuntimeTuningValue],
    *,
    label: str,
) -> tuple[str, ...]:
    value = options["operations"]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = f"{label} operations must contain non-empty strings"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[str, ...]", value)


def _require_operations(
    options: Mapping[str, RuntimeTuningValue],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    operations = _operations(options, label=label)
    actual = frozenset(operations)
    if len(actual) != len(operations) or actual != expected:
        message = f"{label} operations mismatch: expected={sorted(expected)}, actual={sorted(operations)}"
        raise CampaignRuntimeProfileError(message)


def _build_t4_observation(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    del context

    def camera_repositioning(
        runtime: MapObserverRuntime,
        destination: GridInfo,
        next_handler: CameraRepositioningNext,
    ) -> bool:
        host = cast("_T4ObservationHost", runtime)
        if next_handler(runtime, destination):
            return True
        if not host.map_is_clear_mode and destination.is_fortress:
            logger.info("Catch camera re-positioning after fortress cleared")
            host.device.sleep(3)
            return True
        return False

    return CampaignMapObserverExecutor(CampaignMapObserverContributor(camera_repositioning=camera_repositioning))


class _RyzaEventDestination(EventDestination):
    @override
    def open(self, runtime: EventDestinationHost) -> bool:
        host = cast("_RyzaRuntimeHost", runtime)
        if host.appear(EVENT_20221124_PT_ICON, offset=(20, 20)) and host.ui_page_appear(page_event):
            logger.info("Already at EVENT_20221124")
            return True
        host.ui_ensure(page_campaign_menu)
        if not host.is_event_entrance_available():
            return False
        host.ui_click(
            EVENT_20221124_ENTRANCE,
            check_button=EVENT_20221124_PT_ICON,
            appear_button=EVENT_20221124_ENTRANCE,
        )
        return True


def _build_ryza_campaign(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    mechanic_options = context.options(RuntimeExecutorKind.MAP_MECHANIC)
    _require_operations(
        mechanic_options,
        frozenset({"handle_mystery_items"}),
        label="event_20221124 map mechanic",
    )

    def handle_mystery_items(runtime: object, button: object = None) -> bool:
        host = cast("_RyzaRuntimeHost", runtime)
        if host.runtime_super(RuntimeOperation.HANDLE_MYSTERY_ITEMS, button):
            return True
        if not host.appear(GET_ITEMS_1_RYZA, offset=(-20, -100, 20, 20)):
            return False
        logger.attr("Mystery", "Get item")
        host.device.click(MYSTERY_ITEM)
        host.device.sleep(0.5)
        host.device.screenshot()
        return True

    return CampaignEventUiExecutor(
        {RuntimeExecutorKind.EVENT_UI, RuntimeExecutorKind.MAP_MECHANIC},
        CampaignEventUiContributor(destination=_RyzaEventDestination()),
        other_methods={
            RuntimeExecutorKind.MAP_MECHANIC: {
                RuntimeOperation.HANDLE_MYSTERY_ITEMS: handle_mystery_items,
            },
        },
    )


def special_early_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    operations_only = RuntimeExecutorOptionsSchema(required=frozenset({"operations"}))
    empty_options = RuntimeExecutorOptionsSchema()
    return (
        RuntimeExecutorFactoryDescriptor(
            _T4_IMPLEMENTATION,
            {RuntimeExecutorKind.MAP_OBSERVATION: empty_options},
            _build_t4_observation,
        ),
        RuntimeExecutorFactoryDescriptor(
            _RYZA_IMPLEMENTATION,
            {
                RuntimeExecutorKind.EVENT_UI: empty_options,
                RuntimeExecutorKind.MAP_MECHANIC: operations_only,
            },
            _build_ryza_campaign,
        ),
    )
