from typing import TYPE_CHECKING, override

import numpy as np

from campaign.campaign_main import campaign_15_base
from campaign.campaign_main.campaign_15_base import CampaignBase
from module.handler.strategy import MOB_MOVE_OFFSET
from module.map_detection.grid import Grid

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pytest

    from module.base.button import Button, MatchOffset
    from module.base.type_alias import ImageArray
    from module.map.type_alias import GridLocation


class _Timer:
    def __init__(self, results: Iterable[bool]) -> None:
        self.results = list(results)
        self.reset_count = 0

    def reached(self) -> bool:
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self) -> None:
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.clicks: list[Grid | Button] = []
        self.screenshot_count = 0

    def click(self, button: Grid | Button) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _View:
    def __init__(self) -> None:
        self.images: list[ImageArray] = []

    def update(self, image: ImageArray) -> None:
        self.images.append(image)


class _Grid(Grid):
    def __init__(self, icon_results: Iterable[bool] | None = None) -> None:
        self.icon_results = list(icon_results or [])

    @override
    def predict_mob_move_icon(self) -> bool:
        return self.icon_results.pop(0)


class _Campaign(CampaignBase):
    device: _Device
    view: _View

    def __init__(self) -> None:
        self.device = _Device()
        self.view = _View()
        self.calls = []
        self.in_mob_move_results: list[bool] = []
        self.strategy_open_results: list[bool] = []
        self.popup_results: list[bool] = []

    def is_in_strategy_mob_move(self) -> bool:
        self.calls.append(("is_in_strategy_mob_move",))
        return self.in_mob_move_results.pop(0)

    @override
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
        return self.strategy_open_results.pop(0)

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del offset, interval
        self.calls.append(("handle_popup_confirm", name))
        return self.popup_results.pop(0)

    def select_mob_move_origin(self, origin_grid: Grid) -> None:
        self._select_mob_move_origin(origin_grid)

    def select_mob_move_target(self, target_grid: Grid) -> None:
        self._select_mob_move_target(target_grid)

    def mob_move_inner(self, location: GridLocation, target: GridLocation) -> None:
        self._mob_move(location, target)


def test_select_mob_move_origin_clicks_until_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    campaign = _Campaign()
    campaign.in_mob_move_results = [True, True, True]
    origin_grid = _Grid(icon_results=[False, True])
    monkeypatch.setattr(campaign_15_base, "Timer", lambda *_args, **_kwargs: _Timer([True]))

    campaign.select_mob_move_origin(origin_grid)

    assert campaign.device.clicks == [origin_grid]
    assert campaign.device.screenshot_count == 1
    assert campaign.view.images == [campaign.device.image, campaign.device.image]


def test_select_mob_move_target_handles_popup_before_click(monkeypatch: pytest.MonkeyPatch) -> None:
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
        def __init__(self) -> None:
            super().__init__()
            self.origin = _Grid()
            self.target = _Grid()

        def _mob_move_grids(
            self,
            location: GridLocation,
            target: GridLocation,
        ) -> tuple[Grid, Grid]:
            self.calls.append(("_mob_move_grids", location, target))
            return self.origin, self.target

        def _select_mob_move_origin(self, origin_grid: Grid) -> None:
            self.calls.append(("_select_mob_move_origin", origin_grid))

        def _select_mob_move_target(self, target_grid: Grid) -> None:
            self.calls.append(("_select_mob_move_target", target_grid))

    campaign = Campaign()

    campaign.mob_move_inner((1, 2), (1, 3))

    assert campaign.calls == [
        ("_mob_move_grids", (1, 2), (1, 3)),
        ("_select_mob_move_origin", campaign.origin),
        ("_select_mob_move_target", campaign.target),
    ]
