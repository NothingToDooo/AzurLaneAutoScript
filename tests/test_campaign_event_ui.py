from dataclasses import dataclass
from typing import TYPE_CHECKING

from module.adapters.campaign_event_ui import (
    CampaignEventUiContributor,
    build_campaign_event_ui_services,
)
from module.campaign.event_navigation import EventCampaignNavigation
from module.ui.page import page_campaign_menu, page_event, page_main
from module.war_archives.assets import WAR_ARCHIVES_CAMPAIGN_CHECK

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.campaign.event_destination import EventDestinationHost
    from module.ui.page import Page


class _Host:
    def __init__(self) -> None:
        self.current_page = page_campaign_menu
        self.archive_visible = False
        self.entrance_available = True
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
        return button is WAR_ARCHIVES_CAMPAIGN_CHECK and self.archive_visible

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

    def is_event_entrance_available(self) -> bool:
        self.calls.append(("available",))
        return self.entrance_available


class _EventNavigationHarness(_Host, EventCampaignNavigation):
    pass


@dataclass(slots=True)
class _Destination:
    name: str
    calls: list[str]

    def open(self, runtime: EventDestinationHost) -> bool:
        del runtime
        self.calls.append(self.name)
        return True


@dataclass(frozen=True, slots=True)
class _ContributorSource:
    event_ui_contributor: CampaignEventUiContributor


def test_standard_destination_short_circuits_on_the_open_event_page() -> None:
    host = _Host()
    host.current_page = page_event

    opened = build_campaign_event_ui_services(()).destination.open(host)

    assert opened
    assert host.calls == [
        ("current",),
        ("appear", WAR_ARCHIVES_CAMPAIGN_CHECK, (20, 20)),
    ]


def test_event_campaign_navigation_uses_the_shared_standard_destination() -> None:
    navigation = _EventNavigationHarness()
    navigation.current_page = page_event

    assert navigation.ui_goto_event()
    assert navigation.calls == [
        ("current",),
        ("appear", WAR_ARCHIVES_CAMPAIGN_CHECK, (20, 20)),
    ]


def test_standard_destination_leaves_archives_before_opening_event() -> None:
    host = _Host()
    host.current_page = page_event
    host.archive_visible = True

    opened = build_campaign_event_ui_services(()).destination.open(host)

    assert opened
    assert host.calls == [
        ("current",),
        ("appear", WAR_ARCHIVES_CAMPAIGN_CHECK, (20, 20)),
        ("main",),
        ("goto", page_campaign_menu),
        ("available",),
        ("goto", page_event),
    ]


def test_standard_destination_stops_when_event_is_unavailable() -> None:
    host = _Host()
    host.entrance_available = False

    opened = build_campaign_event_ui_services(()).destination.open(host)

    assert not opened
    assert host.calls == [
        ("current",),
        ("goto", page_campaign_menu),
        ("available",),
    ]


def test_later_destination_contribution_replaces_the_earlier_one() -> None:
    calls: list[str] = []
    base = _Destination("base", calls)
    derived = _Destination("derived", calls)

    services = build_campaign_event_ui_services(
        (
            _ContributorSource(CampaignEventUiContributor(destination=base)),
            object(),
            _ContributorSource(CampaignEventUiContributor(destination=derived)),
        )
    )

    assert services.destination is derived
    assert services.destination.open(_Host())
    assert calls == ["derived"]
