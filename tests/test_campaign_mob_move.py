from campaign.campaign_main import campaign_15_base
from campaign.campaign_main.campaign_15_base import CampaignBase
from module.handler.strategy import MOB_MOVE_OFFSET


class _Timer:
    def __init__(self, results):
        self.results = list(results)
        self.reset_count = 0

    def reached(self):
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self):
        self.reset_count += 1


class _Device:
    image = "screen"

    def __init__(self):
        self.clicks = []
        self.screenshot_count = 0

    def click(self, button):
        self.clicks.append(button)

    def screenshot(self):
        self.screenshot_count += 1


class _View:
    def __init__(self):
        self.images = []

    def update(self, image):
        self.images.append(image)


class _Grid:
    def __init__(self, icon_results=None):
        self.icon_results = list(icon_results or [])

    def predict_mob_move_icon(self):
        return self.icon_results.pop(0)


class _Campaign(CampaignBase):
    def __init__(self):
        self.device = _Device()
        self.view = _View()
        self.calls = []
        self.in_mob_move_results = []
        self.strategy_open_results = []
        self.popup_results = []

    def is_in_strategy_mob_move(self):
        self.calls.append(("is_in_strategy_mob_move",))
        return self.in_mob_move_results.pop(0)

    def appear(self, button, offset=(0, 0)):
        self.calls.append(("appear", button, offset))
        return self.strategy_open_results.pop(0)

    def handle_popup_confirm(self, name):
        self.calls.append(("handle_popup_confirm", name))
        return self.popup_results.pop(0)

    def select_mob_move_origin(self, origin_grid):
        self._select_mob_move_origin(origin_grid)

    def select_mob_move_target(self, target_grid):
        self._select_mob_move_target(target_grid)

    def mob_move_inner(self, location, target):
        self._mob_move(location, target)


def test_select_mob_move_origin_clicks_until_icon(monkeypatch) -> None:
    campaign = _Campaign()
    campaign.in_mob_move_results = [True, True, True]
    origin_grid = _Grid(icon_results=[False, True])
    monkeypatch.setattr(campaign_15_base, "Timer", lambda *_args, **_kwargs: _Timer([True]))

    campaign.select_mob_move_origin(origin_grid)

    assert campaign.device.clicks == [origin_grid]
    assert campaign.device.screenshot_count == 1
    assert campaign.view.images == ["screen", "screen"]


def test_select_mob_move_target_handles_popup_before_click(monkeypatch) -> None:
    campaign = _Campaign()
    campaign.in_mob_move_results = [True]
    campaign.strategy_open_results = [False, False, True]
    campaign.popup_results = [True]
    target_grid = _Grid()
    monkeypatch.setattr(campaign_15_base, "Timer", lambda *_args, **_kwargs: _Timer([False, True]))

    campaign.select_mob_move_target(target_grid)

    assert campaign.device.clicks == [target_grid]
    assert campaign.device.screenshot_count == 2
    assert ("handle_popup_confirm", "MOB_MOVE") in campaign.calls
    assert ("appear", campaign_15_base.STRATEGY_OPENED, MOB_MOVE_OFFSET) in campaign.calls


def test_mob_move_runs_grid_selection_steps() -> None:
    class Campaign(_Campaign):
        def _mob_move_grids(self, location, target):
            self.calls.append(("_mob_move_grids", location, target))
            return "origin", "target"

        def _select_mob_move_origin(self, origin_grid):
            self.calls.append(("_select_mob_move_origin", origin_grid))

        def _select_mob_move_target(self, target_grid):
            self.calls.append(("_select_mob_move_target", target_grid))

    campaign = Campaign()

    campaign.mob_move_inner((1, 2), (1, 3))

    assert campaign.calls == [
        ("_mob_move_grids", (1, 2), (1, 3)),
        ("_select_mob_move_origin", "origin"),
        ("_select_mob_move_target", "target"),
    ]
