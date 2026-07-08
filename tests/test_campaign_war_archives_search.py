from campaign.campaign_war_archives import campaign_base as war_archives_base
from campaign.campaign_war_archives.campaign_base import CampaignBase
from module.ui.page import page_archives


class _Device:
    def __init__(self):
        self.click_record = []
        self.screenshot_count = 0

    def screenshot(self):
        self.screenshot_count += 1


class _Scroll:
    def __init__(self, *, appears=True, at_bottom=False):
        self.appears = appears
        self.is_at_bottom = at_bottom
        self.calls = []

    def appear(self, main):
        self.calls.append(("appear", main))
        return self.appears

    def at_bottom(self, main):
        self.calls.append(("at_bottom", main))
        return self.is_at_bottom

    def set_top(self, main):
        self.calls.append(("set_top", main))

    def next_page(self, main, page):
        self.calls.append(("next_page", main, page))


class _Campaign(CampaignBase):
    def __init__(self):
        self.device = _Device()
        self.calls = []
        self.page_results = []
        self.entrance_results = []
        self.loading_results = []

    def appear(self, button):
        self.calls.append(("appear", button))
        return self.page_results.pop(0)

    def ui_ensure(self, destination):
        self.calls.append(("ui_ensure", destination))

    def _get_archives_entrance(self, name):
        self.calls.append(("_get_archives_entrance", name))
        return self.entrance_results.pop(0)

    def _archives_loading_complete(self):
        self.calls.append(("_archives_loading_complete",))
        return self.loading_results.pop(0)

    def search_archives_entrance(self, name):
        return self._search_archives_entrance(name)


def test_search_archives_entrance_uses_remembered_position(monkeypatch) -> None:
    campaign = _Campaign()
    campaign.device.click_record = ["OTHER", "WAR_ARCHIVES_SCROLL", "WAR_ARCHIVES_SCROLL"]
    campaign.page_results = [True]
    campaign.entrance_results = ["entrance"]
    scroll = _Scroll()
    monkeypatch.setattr(war_archives_base, "WAR_ARCHIVES_SCROLL", scroll)

    assert campaign.search_archives_entrance("event") == "entrance"

    assert campaign.device.click_record == ["OTHER"]
    assert campaign.device.screenshot_count == 0
    assert scroll.calls == []


def test_search_archives_entrance_recovers_page_and_waits_for_loading(monkeypatch) -> None:
    campaign = _Campaign()
    campaign.page_results = [False, True]
    campaign.entrance_results = [None, "entrance"]
    campaign.loading_results = [False, True]
    scroll = _Scroll()
    monkeypatch.setattr(war_archives_base, "WAR_ARCHIVES_SCROLL", scroll)

    assert campaign.search_archives_entrance("event") == "entrance"

    assert ("ui_ensure", page_archives) in campaign.calls
    assert campaign.device.screenshot_count == 1
    assert scroll.calls == []


def test_search_archives_entrance_advances_scroll_after_loaded(monkeypatch) -> None:
    campaign = _Campaign()
    campaign.page_results = [True, True]
    campaign.entrance_results = [None, None, "entrance"]
    campaign.loading_results = [True]
    scroll = _Scroll()
    monkeypatch.setattr(war_archives_base, "WAR_ARCHIVES_SCROLL", scroll)

    assert campaign.search_archives_entrance("event") == "entrance"

    assert ("next_page", campaign, 0.66) in scroll.calls
    assert campaign.device.screenshot_count == 1


def test_search_archives_entrance_returns_none_without_scroll(monkeypatch) -> None:
    campaign = _Campaign()
    campaign.page_results = [True]
    campaign.entrance_results = [None, None]
    campaign.loading_results = [True]
    scroll = _Scroll(appears=False)
    monkeypatch.setattr(war_archives_base, "WAR_ARCHIVES_SCROLL", scroll)

    assert campaign.search_archives_entrance("event") is None

    assert scroll.calls == [("appear", campaign)]
