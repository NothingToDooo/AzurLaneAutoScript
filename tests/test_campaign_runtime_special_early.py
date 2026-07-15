from dataclasses import dataclass

import pytest

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
from module.ui.page import page_campaign_menu, page_event

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


@dataclass(slots=True)
class _Destination:
    is_fortress: bool


class _Runtime:
    def __init__(self, manager: CampaignRuntimeProfileManager) -> None:
        self.manager = manager
        self.device = _Device()
        self.fleet_destination: _Destination | None = None
        self.map_is_clear_mode = False
        self.visible_asset: object | None = None
        self.visible_page: object | None = None
        self.event_entrance_available = False
        self.appear_calls: list[tuple[object, tuple[int, ...]]] = []
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

    def appear(self, button: object, *, offset: tuple[int, ...]) -> bool:
        self.appear_calls.append((button, offset))
        return button is self.visible_asset

    def ui_page_appear(self, page: object) -> bool:
        return page is self.visible_page

    def ui_ensure(self, page: object) -> None:
        self.ensured_pages.append(page)

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
    operations: list[str],
    **extra_options: object,
) -> RuntimeExecutorBinding:
    return RuntimeExecutorBinding(
        kind,
        RuntimeImplementationId(implementation),
        {"operations": operations, **extra_options},
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
            ["catch_camera_repositioning"],
            **extra_options,
        )
    )


def _ryza_manager() -> CampaignRuntimeProfileManager:
    return _manager(
        _binding(
            _RYZA_IMPLEMENTATION,
            RuntimeExecutorKind.EVENT_UI,
            ["ui_goto_event"],
        ),
        _binding(
            _RYZA_IMPLEMENTATION,
            RuntimeExecutorKind.MAP_MECHANIC,
            ["handle_mystery_items"],
        ),
    )


def test_t4_observation_preserves_base_camera_repositioning_result() -> None:
    manager = _t4_manager()
    runtime = _Runtime(manager)

    result = manager.observation.invoke(
        RuntimeOperation.CATCH_CAMERA_REPOSITIONING,
        runtime,
        lambda: True,
    )

    assert result is True
    assert runtime.device.sleeps == []


@pytest.mark.parametrize(
    ("destination", "is_clear_mode", "expected", "expected_sleeps"),
    [
        (None, False, False, []),
        (_Destination(is_fortress=False), False, False, []),
        (_Destination(is_fortress=True), True, False, []),
        (_Destination(is_fortress=True), False, True, [3]),
    ],
)
def test_t4_observation_only_waits_for_a_fortress_camera_move(
    destination: _Destination | None,
    *,
    is_clear_mode: bool,
    expected: bool,
    expected_sleeps: list[float],
) -> None:
    manager = _t4_manager()
    runtime = _Runtime(manager)
    runtime.fleet_destination = destination
    runtime.map_is_clear_mode = is_clear_mode

    result = manager.observation.invoke(
        RuntimeOperation.CATCH_CAMERA_REPOSITIONING,
        runtime,
        lambda: False,
    )

    assert result is expected
    assert runtime.device.sleeps == expected_sleeps


def test_ryza_event_ui_recognizes_the_existing_event_page() -> None:
    manager = _ryza_manager()
    runtime = _Runtime(manager)
    runtime.visible_asset = EVENT_20221124_PT_ICON
    runtime.visible_page = page_event

    result = manager.event_ui.invoke(
        RuntimeOperation.UI_GOTO_EVENT,
        runtime,
        lambda: False,
    )

    assert result is True
    assert runtime.appear_calls == [(EVENT_20221124_PT_ICON, (20, 20))]
    assert runtime.ensured_pages == []
    assert runtime.ui_clicks == []


def test_ryza_event_ui_uses_the_closed_event_assets() -> None:
    manager = _ryza_manager()
    runtime = _Runtime(manager)
    runtime.event_entrance_available = True

    result = manager.event_ui.invoke(
        RuntimeOperation.UI_GOTO_EVENT,
        runtime,
        lambda: False,
    )

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

    result = manager.event_ui.invoke(
        RuntimeOperation.UI_GOTO_EVENT,
        runtime,
        lambda: False,
    )

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


def test_special_early_descriptors_reject_operation_drift() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="event_20211125 T4 observation operations mismatch"):
        _manager(
            _binding(
                _T4_IMPLEMENTATION,
                RuntimeExecutorKind.MAP_OBSERVATION,
                ["full_scan"],
            )
        )


def test_ryza_executor_requires_both_facets() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="requires exactly one map_mechanic binding"):
        _manager(
            _binding(
                _RYZA_IMPLEMENTATION,
                RuntimeExecutorKind.EVENT_UI,
                ["ui_goto_event"],
            )
        )
