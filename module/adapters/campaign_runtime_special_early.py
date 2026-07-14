from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from module.campaign.assets import EVENT_20221124_ENTRANCE, EVENT_20221124_PT_ICON
from module.combat.assets import GET_ITEMS_1_RYZA
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.handler.assets import MYSTERY_ITEM
from module.logger import logger
from module.ui.page import page_campaign_menu, page_event

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

type _Offset = tuple[int, int] | tuple[int, int, int, int]

_T4_IMPLEMENTATION = RuntimeImplementationId("event_20211125_cn/t4/campaign")
_RYZA_IMPLEMENTATION = RuntimeImplementationId("event_20221124_cn/campaign_base/campaign_base")


class _Device(Protocol):
    def click(self, button: object) -> object: ...

    def sleep(self, seconds: float) -> None: ...

    def screenshot(self) -> object: ...


class _FortressDestination(Protocol):
    is_fortress: bool


class _T4ObservationHost(Protocol):
    device: _Device
    fleet_destination: _FortressDestination | None
    map_is_clear_mode: bool

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object: ...


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
    options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
    _require_operations(
        options,
        frozenset({"catch_camera_repositioning"}),
        label="event_20211125 T4 observation",
    )

    def catch_camera_repositioning(runtime: object) -> bool:
        host = cast("_T4ObservationHost", runtime)
        if host.runtime_super(RuntimeOperation.CATCH_CAMERA_REPOSITIONING):
            return True
        destination = host.fleet_destination
        if destination is None:
            return False
        if not host.map_is_clear_mode and destination.is_fortress:
            logger.info("Catch camera re-positioning after fortress cleared")
            host.device.sleep(3)
            return True
        return False

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.MAP_OBSERVATION},
        methods={
            RuntimeExecutorKind.MAP_OBSERVATION: {
                RuntimeOperation.CATCH_CAMERA_REPOSITIONING: catch_camera_repositioning,
            }
        },
    )


def _build_ryza_campaign(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    event_ui_options = context.options(RuntimeExecutorKind.EVENT_UI)
    _require_operations(
        event_ui_options,
        frozenset({"ui_goto_event"}),
        label="event_20221124 event UI",
    )
    mechanic_options = context.options(RuntimeExecutorKind.MAP_MECHANIC)
    _require_operations(
        mechanic_options,
        frozenset({"handle_mystery_items"}),
        label="event_20221124 map mechanic",
    )

    def ui_goto_event(runtime: object) -> bool:
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

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.EVENT_UI, RuntimeExecutorKind.MAP_MECHANIC},
        methods={
            RuntimeExecutorKind.EVENT_UI: {
                RuntimeOperation.UI_GOTO_EVENT: ui_goto_event,
            },
            RuntimeExecutorKind.MAP_MECHANIC: {
                RuntimeOperation.HANDLE_MYSTERY_ITEMS: handle_mystery_items,
            },
        },
    )


def special_early_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    operations_only = RuntimeExecutorOptionsSchema(required=frozenset({"operations"}))
    return (
        RuntimeExecutorFactoryDescriptor(
            _T4_IMPLEMENTATION,
            {RuntimeExecutorKind.MAP_OBSERVATION: operations_only},
            _build_t4_observation,
        ),
        RuntimeExecutorFactoryDescriptor(
            _RYZA_IMPLEMENTATION,
            {
                RuntimeExecutorKind.EVENT_UI: operations_only,
                RuntimeExecutorKind.MAP_MECHANIC: operations_only,
            },
            _build_ryza_campaign,
        ),
    )
