from typing import TYPE_CHECKING

import pytest

from module.adapters.campaign_event_ui import CampaignEventUiServices, build_campaign_event_ui_services
from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    build_campaign_map_observer,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
)
from module.adapters.campaign_runtime_special_early import special_early_runtime_executor_descriptors
from module.campaign.assets import EVENT_20221124_ENTRANCE, EVENT_20221124_PT_ICON
from module.combat.assets import GET_ITEMS_1_RYZA
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
)
from module.handler.assets import MYSTERY_ITEM
from module.map.map_base import CampaignMap
from module.map_detection.grid_info import GridInfo
from module.ui.page import page_campaign_menu, page_event, page_main

if TYPE_CHECKING:
    from module.adapters.campaign_map_observer import CameraRepositioningNext
    from module.base.button import Button, MatchOffset
    from module.map.map_observer import MapObserverRuntime
    from module.ui.page import Page

_T4_IMPLEMENTATION = "event_20211125_cn/t4/campaign"
_RYZA_IMPLEMENTATION = "event_20221124_cn/campaign_base/campaign_base"


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.sleeps: list[float] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Runtime:
    def __init__(self, manager: CampaignRuntimeProfileManager) -> None:
        self.manager = manager
        self.device = _Device()
        self.map = CampaignMap("special-early-test")
        self.map.spawn_data = []
        self.battle_count = 0
        self.map_is_clear_mode = False
        self.visible_asset: object | None = None
        self.visible_page: object | None = None
        self.current_page = page_campaign_menu
        self.event_entrance_available = False
        self.appear_calls: list[tuple[object, tuple[object, ...]]] = []
        self.ensured_pages: list[object] = []
        self.ui_clicks: list[tuple[object, object, object]] = []

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self.manager.invoke_super(operation, self, *args, **kwargs)

    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del interval, similarity, threshold
        recorded_offset = offset if isinstance(offset, tuple) else ()
        self.appear_calls.append((button, recorded_offset))
        return button is self.visible_asset

    def ui_get_current_page(self, *, skip_first_screenshot: bool = True) -> Page:
        del skip_first_screenshot
        return self.current_page

    def ui_page_appear(self, page: object) -> bool:
        return page is self.visible_page

    def ui_ensure(self, page: object) -> None:
        self.ensured_pages.append(page)

    def ui_goto_main(self) -> bool:
        self.current_page = page_main
        return True

    def ui_goto(
        self,
        destination: Page,
        *,
        get_ship: bool = True,
        offset: MatchOffset | None = (30, 30),
        skip_first_screenshot: bool = True,
    ) -> None:
        del get_ship, offset, skip_first_screenshot
        self.current_page = destination

    def is_event_entrance_available(self) -> bool:
        return self.event_entrance_available

    def ui_click(
        self,
        button: object,
        *,
        check_button: object,
        appear_button: object,
    ) -> None:
        self.ui_clicks.append((button, check_button, appear_button))


def _binding(
    implementation: str,
    kind: RuntimeExecutorKind,
    operations: list[str] | None,
    **extra_options: object,
) -> RuntimeExecutorBinding:
    options = dict(extra_options)
    if operations is not None:
        options["operations"] = operations
    return RuntimeExecutorBinding(
        kind,
        RuntimeImplementationId(implementation),
        options,
    )


def _manager(*bindings: RuntimeExecutorBinding) -> CampaignRuntimeProfileManager:
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("special-early-test"),
        bindings,
    )
    return CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(
            CampaignRuntimeProfileId("special-early-test"),
            (extension,),
        ),
        CampaignRuntimeExecutorRegistry(special_early_runtime_executor_descriptors()),
    )


def _t4_manager(**extra_options: object) -> CampaignRuntimeProfileManager:
    return _manager(
        _binding(
            _T4_IMPLEMENTATION,
            RuntimeExecutorKind.MAP_OBSERVATION,
            None,
            **extra_options,
        )
    )


def _ryza_manager() -> CampaignRuntimeProfileManager:
    return _manager(
        _binding(
            _RYZA_IMPLEMENTATION,
            RuntimeExecutorKind.EVENT_UI,
            None,
        ),
        _binding(
            _RYZA_IMPLEMENTATION,
            RuntimeExecutorKind.MAP_MECHANIC,
            ["handle_mystery_items"],
        ),
    )


def _event_ui_services(manager: CampaignRuntimeProfileManager) -> CampaignEventUiServices:
    return build_campaign_event_ui_services(manager.executor_instances(RuntimeExecutorKind.EVENT_UI))


def test_t4_observation_preserves_base_result_and_destination_identity() -> None:
    manager = _t4_manager()
    runtime = _Runtime(manager)
    destination = GridInfo()
    observed: list[tuple[MapObserverRuntime, GridInfo]] = []

    def base_result(
        observed_runtime: MapObserverRuntime,
        observed_destination: GridInfo,
        next_handler: CameraRepositioningNext,
    ) -> bool:
        del next_handler
        observed.append((observed_runtime, observed_destination))
        return True

    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(CampaignMapObserverContributor(camera_repositioning=base_result)),
            *manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION),
        )
    )
    result = observer.combat.camera_repositioned_after_combat(runtime, destination)

    assert result is True
    assert observed == [(runtime, destination)]
    assert runtime.device.sleeps == []


@pytest.mark.parametrize(
    "scenario",
    [
        (False, False, False, []),
        (False, True, False, []),
        (True, True, False, []),
        (True, False, True, [3]),
    ],
)
def test_t4_observation_only_waits_for_a_fortress_camera_move(
    scenario: tuple[bool, bool, bool, list[float]],
) -> None:
    is_fortress, is_clear_mode, expected, expected_sleeps = scenario
    manager = _t4_manager()
    runtime = _Runtime(manager)
    runtime.map_is_clear_mode = is_clear_mode
    destination = GridInfo()
    destination.is_fortress = is_fortress

    observer = build_campaign_map_observer(manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION))
    result = observer.combat.camera_repositioned_after_combat(runtime, destination)

    assert result is expected
    assert runtime.device.sleeps == expected_sleeps


def test_ryza_event_ui_recognizes_the_existing_event_page() -> None:
    manager = _ryza_manager()
    runtime = _Runtime(manager)
    runtime.visible_asset = EVENT_20221124_PT_ICON
    runtime.visible_page = page_event

    result = _event_ui_services(manager).destination.open(runtime)

    assert result is True
    assert runtime.appear_calls == [(EVENT_20221124_PT_ICON, (20, 20))]
    assert runtime.ensured_pages == []
    assert runtime.ui_clicks == []


def test_ryza_event_ui_uses_the_closed_event_assets() -> None:
    manager = _ryza_manager()
    runtime = _Runtime(manager)
    runtime.event_entrance_available = True

    result = _event_ui_services(manager).destination.open(runtime)

    assert result is True
    assert runtime.ensured_pages == [page_campaign_menu]
    assert runtime.ui_clicks == [
        (
            EVENT_20221124_ENTRANCE,
            EVENT_20221124_PT_ICON,
            EVENT_20221124_ENTRANCE,
        )
    ]


def test_ryza_event_ui_stops_when_the_event_entrance_is_unavailable() -> None:
    manager = _ryza_manager()
    runtime = _Runtime(manager)

    result = _event_ui_services(manager).destination.open(runtime)

    assert result is False
    assert runtime.ensured_pages == [page_campaign_menu]
    assert runtime.ui_clicks == []


def test_ryza_mystery_handler_preserves_the_base_handler() -> None:
    manager = _ryza_manager()
    runtime = _Runtime(manager)
    mystery = object()

    result = manager.mechanic.invoke(
        RuntimeOperation.HANDLE_MYSTERY_ITEMS,
        runtime,
        lambda button=None: button is mystery,
        mystery,
    )

    assert result is True
    assert runtime.appear_calls == []
    assert runtime.device.clicks == []


def test_ryza_mystery_handler_uses_the_closed_item_assets() -> None:
    manager = _ryza_manager()
    runtime = _Runtime(manager)
    runtime.visible_asset = GET_ITEMS_1_RYZA

    result = manager.mechanic.invoke(
        RuntimeOperation.HANDLE_MYSTERY_ITEMS,
        runtime,
        lambda _button=None: False,
    )

    assert result is True
    assert runtime.appear_calls == [(GET_ITEMS_1_RYZA, (-20, -100, 20, 20))]
    assert runtime.device.clicks == [MYSTERY_ITEM]
    assert runtime.device.sleeps == [0.5]
    assert runtime.device.screenshot_count == 1


def test_ryza_mystery_handler_returns_false_without_a_special_popup() -> None:
    manager = _ryza_manager()
    runtime = _Runtime(manager)

    result = manager.mechanic.invoke(
        RuntimeOperation.HANDLE_MYSTERY_ITEMS,
        runtime,
        lambda _button=None: False,
    )

    assert result is False
    assert runtime.device.clicks == []


def test_special_early_descriptors_reject_unknown_options() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="unknown option: unexpected"):
        _t4_manager(unexpected=True)


def test_t4_observer_rejects_obsolete_operations_field() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="unknown option: operations"):
        _manager(
            _binding(
                _T4_IMPLEMENTATION,
                RuntimeExecutorKind.MAP_OBSERVATION,
                ["catch_camera_repositioning"],
            )
        )


def test_ryza_executor_requires_both_facets() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="requires exactly one map_mechanic binding"):
        _manager(
            _binding(
                _RYZA_IMPLEMENTATION,
                RuntimeExecutorKind.EVENT_UI,
                None,
            )
        )


def test_ryza_event_ui_rejects_obsolete_operations_field() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="unknown option: operations"):
        _manager(
            _binding(
                _RYZA_IMPLEMENTATION,
                RuntimeExecutorKind.EVENT_UI,
                [],
            ),
            _binding(
                _RYZA_IMPLEMENTATION,
                RuntimeExecutorKind.MAP_MECHANIC,
                ["handle_mystery_items"],
            ),
        )
