from typing import TYPE_CHECKING

import pytest

from module.adapters.campaign_event_ui import CampaignEventUiServices, build_campaign_event_ui_services
from module.adapters.campaign_runtime_implementations import load_default_campaign_runtime_executor_registry
from module.adapters.campaign_runtime_profile import CampaignRuntimeProfileManager, RuntimeOperation
from module.campaign.assets import (
    EVENT_20201126_DETAIL,
    EVENT_20201126_DETAIL_CHECK,
    EVENT_20201126_DETAIL_WHITE,
    EVENT_20201126_ENTRANCE,
    EVENT_20201126_PT_ICON,
    EVENT_20250424_PT_ICON,
    EVENT_20250724_PT_ICON,
)
from module.combat.assets import ALCHEMIST_MATERIAL_CONFIRM
from module.content.runtime_profile import (
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorKind,
)
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.ui.page import Page, page_campaign_menu, page_event, page_main, page_main_white

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.campaign.event_destination import EventDestination


class _Host:
    def __init__(self) -> None:
        self.current_page = page_campaign_menu
        self.visible_buttons: list[object] = []
        self.visible_page: object | None = None
        self.entrance_available = True
        self.exp_info_result = True
        self.exp_info_calls = 0
        self.calls: list[tuple[object, ...]] = []

    def ui_get_current_page(self, *, skip_first_screenshot: bool = True) -> Page:
        del skip_first_screenshot
        self.calls.append(("current",))
        return self.current_page

    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del interval, similarity, threshold
        self.calls.append(("appear", button, offset))
        return any(button is visible for visible in self.visible_buttons)

    def ui_page_appear(self, page: object) -> bool:
        self.calls.append(("page", page))
        return page is self.visible_page

    def ui_ensure(self, page: object) -> None:
        self.calls.append(("ensure", page))

    def ui_goto_main(self) -> bool:
        self.calls.append(("main",))
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
        self.calls.append(("goto", destination))
        self.current_page = destination

    def ui_click(
        self,
        button: object,
        *,
        check_button: object,
        appear_button: object | None = None,
        offset: tuple[int, int] | None = None,
    ) -> None:
        self.calls.append(("click", button, check_button, appear_button, offset))

    def is_event_entrance_available(self) -> bool:
        self.calls.append(("available",))
        return self.entrance_available

    def appear_then_click(
        self,
        button: object,
        *,
        offset: tuple[int, int],
        interval: float,
    ) -> bool:
        self.calls.append(("appear-then-click", button, offset, interval))
        return any(button is visible for visible in self.visible_buttons)

    def handle_exp_info(self) -> bool:
        self.exp_info_calls += 1
        return self.exp_info_result


def _manager(*extension_ids: str) -> CampaignRuntimeProfileManager:
    profiles = load_default_campaign_runtime_profile_registry()
    extensions = tuple(profiles.extensions[CampaignRuntimeExtensionId(value)] for value in extension_ids)
    return CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(CampaignRuntimeProfileId("event-destination-test"), extensions),
        load_default_campaign_runtime_executor_registry(),
    )


def _services(manager: CampaignRuntimeProfileManager) -> CampaignEventUiServices:
    return build_campaign_event_ui_services(manager.executor_instances(RuntimeExecutorKind.EVENT_UI))


def _destination(manager: CampaignRuntimeProfileManager) -> EventDestination:
    return _services(manager).destination


@pytest.mark.parametrize(
    ("white_page", "expected_detail"),
    [
        (False, EVENT_20201126_DETAIL),
        (True, EVENT_20201126_DETAIL_WHITE),
    ],
)
def test_detail_destination_selects_the_visible_detail_theme(
    *,
    white_page: bool,
    expected_detail: object,
) -> None:
    manager = _manager("event_20201126_cn/campaign_base/campaign_base")
    host = _Host()
    host.visible_page = page_main_white if white_page else None

    opened = _destination(manager).open(host)

    assert opened
    assert host.calls == [
        ("appear", EVENT_20201126_PT_ICON, (40, 20)),
        ("ensure", page_campaign_menu),
        ("available",),
        ("main",),
        ("page", page_main_white),
        ("click", expected_detail, EVENT_20201126_DETAIL_CHECK, None, None),
        (
            "click",
            EVENT_20201126_ENTRANCE,
            EVENT_20201126_PT_ICON,
            EVENT_20201126_DETAIL_CHECK,
            (40, 20),
        ),
    ]
    instance = manager.executor_instances(RuntimeExecutorKind.EVENT_UI)[0]
    assert instance.method(RuntimeExecutorKind.EVENT_UI, RuntimeOperation.IS_EVENT_ANIMATION) is not None


def test_detail_destination_stops_before_detail_navigation_when_unavailable() -> None:
    manager = _manager("event_20201126_cn/campaign_base/campaign_base")
    host = _Host()
    host.entrance_available = False

    assert not _destination(manager).open(host)
    assert host.calls == [
        ("appear", EVENT_20201126_PT_ICON, (40, 20)),
        ("ensure", page_campaign_menu),
        ("available",),
    ]


def test_20250424_page_destination_keeps_its_exp_info_guard() -> None:
    manager = _manager("event_20250424_cn/campaign_base/campaign_base")
    services = _services(manager)
    host = _Host()

    assert services.destination.open(host)
    assert host.calls == [
        ("appear", EVENT_20250424_PT_ICON, (20, 20)),
        ("ensure", page_campaign_menu),
        ("available",),
        ("goto", page_event),
    ]
    host.visible_page = page_event
    assert not services.combat_result.handle_experience_result(host)
    assert host.exp_info_calls == 0
    host.visible_page = None
    assert services.combat_result.handle_experience_result(host)
    assert host.exp_info_calls == 1


def test_20250724_t_destination_and_ts_guard_remain_independent() -> None:
    manager = _manager(
        "event_20250724_cn/campaign_base/campaign_base_t",
        "event_20250724_cn/campaign_base/campaign_base_ts",
    )
    instances = manager.executor_instances(RuntimeExecutorKind.EVENT_UI)
    services = build_campaign_event_ui_services(instances)
    host = _Host()

    assert len(instances) == 2
    assert services.destination.open(host)
    assert host.calls[0] == ("appear", EVENT_20250724_PT_ICON, (20, 20))
    host.visible_buttons = [ALCHEMIST_MATERIAL_CONFIRM]
    assert not services.combat_result.handle_experience_result(host)
    assert host.calls[-1] == (
        "appear-then-click",
        ALCHEMIST_MATERIAL_CONFIRM,
        (20, 20),
        1.0,
    )
    assert host.exp_info_calls == 0
