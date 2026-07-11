from typing import TYPE_CHECKING, override

from campaign.campaign_war_archives import campaign_base as war_archives_base
from campaign.campaign_war_archives.campaign_base import CampaignBase
from module.ui.page import page_archives

if TYPE_CHECKING:
    import pytest

    from module.base.button import Button, MatchOffset
    from module.ui.page import Page


class _Device:
    def __init__(self) -> None:
        self.click_record: list[str] = []
        self.screenshot_count = 0

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Scroll:
    def __init__(self, *, appears: bool = True, at_bottom: bool = False) -> None:
        self.appears = appears
        self.is_at_bottom = at_bottom
        self.calls: list[tuple[str, _Campaign] | tuple[str, _Campaign, float]] = []

    def appear(self, main: _Campaign) -> bool:
        self.calls.append(("appear", main))
        return self.appears

    def at_bottom(self, main: _Campaign) -> bool:
        self.calls.append(("at_bottom", main))
        return self.is_at_bottom

    def set_top(self, main: _Campaign) -> None:
        self.calls.append(("set_top", main))

    def next_page(self, main: _Campaign, page: float) -> None:
        self.calls.append(("next_page", main, page))


class _Campaign(CampaignBase):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls = []
        self.page_results: list[bool] = []
        self.entrance_results: list[Button | None] = []
        self.loading_results: list[bool] = []

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del offset, interval, similarity, threshold
        self.calls.append(("appear", button))
        return self.page_results.pop(0)

    @override
    def ui_ensure(self, destination: Page, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("ui_ensure", destination))
        return True

    @override
    def _get_archives_entrance(self, name: str) -> Button | None:
        self.calls.append(("_get_archives_entrance", name))
        return self.entrance_results.pop(0)

    @override
    def _archives_loading_complete(self) -> bool:
        self.calls.append(("_archives_loading_complete",))
        return self.loading_results.pop(0)

    def search_archives_entrance(self, name: str) -> Button | None:
        return self._search_archives_entrance(name)


def test_search_archives_entrance_uses_remembered_position(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign = _Campaign()
    entrance = page_archives.check_button
    campaign.device.click_record = ["OTHER", "WAR_ARCHIVES_SCROLL", "WAR_ARCHIVES_SCROLL"]
    campaign.page_results = [True]
    campaign.entrance_results = [entrance]
    scroll = _Scroll()
    monkeypatch.setattr(war_archives_base, "WAR_ARCHIVES_SCROLL", scroll)

    assert campaign.search_archives_entrance("event") is entrance

    assert campaign.device.click_record == ["OTHER"]
    assert campaign.device.screenshot_count == 0
    assert scroll.calls == []


def test_search_archives_entrance_recovers_page_and_waits_for_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign = _Campaign()
    entrance = page_archives.check_button
    campaign.page_results = [False, True]
    campaign.entrance_results = [None, entrance]
    campaign.loading_results = [False, True]
    scroll = _Scroll()
    monkeypatch.setattr(war_archives_base, "WAR_ARCHIVES_SCROLL", scroll)

    assert campaign.search_archives_entrance("event") is entrance

    assert ("ui_ensure", page_archives) in campaign.calls
    assert campaign.device.screenshot_count == 1
    assert scroll.calls == []


def test_search_archives_entrance_advances_scroll_after_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign = _Campaign()
    entrance = page_archives.check_button
    campaign.page_results = [True, True]
    campaign.entrance_results = [None, None, entrance]
    campaign.loading_results = [True]
    scroll = _Scroll()
    monkeypatch.setattr(war_archives_base, "WAR_ARCHIVES_SCROLL", scroll)

    assert campaign.search_archives_entrance("event") is entrance

    assert ("next_page", campaign, 0.66) in scroll.calls
    assert campaign.device.screenshot_count == 1


def test_search_archives_entrance_returns_none_without_scroll(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign = _Campaign()
    campaign.page_results = [True]
    campaign.entrance_results = [None, None]
    campaign.loading_results = [True]
    scroll = _Scroll(appears=False)
    monkeypatch.setattr(war_archives_base, "WAR_ARCHIVES_SCROLL", scroll)

    assert campaign.search_archives_entrance("event") is None

    assert scroll.calls == [("appear", campaign)]
