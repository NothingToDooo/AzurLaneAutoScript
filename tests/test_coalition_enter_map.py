from typing import TYPE_CHECKING, override

import numpy as np
import pytest

from module.coalition import assets as coalition_assets
from module.coalition import ui as coalition_ui
from module.coalition.profile import COALITION_CLIENT_PROFILES, CoalitionClientSession
from module.coalition.ui import CoalitionUI
from module.combat.assets import BATTLE_PREPARATION
from module.content.activity_catalog import ActivityCatalog
from module.content.activity_profile import CoalitionFleetMode, CoalitionStageId
from module.content.manifest import load_default_event_manifests
from module.exception import HumanTakeoverRequiredError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray


def _session(content_id: str, stage_id: str, fleet: CoalitionFleetMode) -> CoalitionClientSession:
    catalog = ActivityCatalog(load_default_event_manifests())
    return COALITION_CLIENT_PROFILES.resolve(
        catalog.resolve_coalition(content_id),
        CoalitionStageId(stage_id),
        fleet,
    )


class _Timer:
    def __init__(self, results: Iterable[bool] | None = None) -> None:
        self.results = list(results or [])
        self.reset_count = 0

    def reached(self) -> bool:
        return self.results.pop(0) if self.results else False

    def reset(self) -> None:
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.clicks: list[Button] = []

    def click(self, button: Button) -> None:
        self.clicks.append(button)


class _Coalition(CoalitionUI):
    device: _Device

    def __init__(self, client: CoalitionClientSession) -> None:
        self.client = client
        self.device = _Device()
        self.loop_count = 8
        self.battle_results: list[bool] = []
        self.fleet_results: list[bool] = []
        self.in_coalition_results: list[bool] = []
        self.in_difficulty_results: list[bool] = []
        self.fleet_preparation_calls = 0
        self.guild_results: list[bool] = []
        self.auto_search_results: list[bool] = []
        self.retirement_results: list[bool] = []
        self.low_emotion_results: list[bool] = []
        self.urgent_results: list[bool] = []
        self.story_results: list[bool] = []
        self.automation_confirm_results: list[bool] = []
        self.popup_results: list[bool] = []

    @staticmethod
    def _next(results: list[bool]) -> bool:
        return results.pop(0) if results else False

    @override
    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        del skip_first, timeout
        for _ in range(self.loop_count):
            yield np.zeros((1, 1, 3), dtype=np.uint8)

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
        if button == BATTLE_PREPARATION:
            return self._next(self.battle_results)
        if button == self.client.profile.preparation.enter:
            return self._next(self.fleet_results)
        return False

    def in_coalition(self) -> bool:
        return self._next(self.in_coalition_results)

    def in_difficulty_selection(self) -> bool:
        return self._next(self.in_difficulty_results)

    @override
    def handle_fleet_preparation(self) -> bool:
        self.fleet_preparation_calls += 1
        return False

    def handle_guild_popup_cancel(self) -> bool:
        return self._next(self.guild_results)

    def handle_auto_search_continue(self) -> bool:
        return self._next(self.auto_search_results)

    def handle_retirement(self) -> bool:
        return self._next(self.retirement_results)

    def handle_combat_low_emotion(self) -> bool:
        return self._next(self.low_emotion_results)

    def handle_urgent_commission(self) -> bool:
        return self._next(self.urgent_results)

    def handle_story_skip(self) -> bool:
        return self._next(self.story_results)

    def handle_combat_automation_confirm(self) -> bool:
        return self._next(self.automation_confirm_results)

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del offset, interval
        assert name == "COALITION"
        return self._next(self.popup_results)


def _patch_timers(monkeypatch: pytest.MonkeyPatch, timers: Iterable[_Timer]) -> None:
    timer_queue = list(timers)
    monkeypatch.setattr(coalition_ui, "Timer", lambda *_args, **_kwargs: timer_queue.pop(0))


def test_enter_coalition_map_clicks_stage_then_fleet_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([True, False]), _Timer(), _Timer([True])])
    coalition = _Coalition(_session("coalition_20230323", "tc3", CoalitionFleetMode.MULTI))
    coalition.battle_results = [False, False, True]
    coalition.in_coalition_results = [True, False]
    coalition.fleet_results = [True]

    coalition.enter_coalition_map()

    assert coalition.device.clicks == [
        coalition_assets.FROSTFALL_TC3,
        coalition_assets.FROSTFALL_FLEET_PREPARATION,
    ]
    assert coalition.fleet_preparation_calls == 1


def test_enter_coalition_map_clicks_profile_difficulty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([False]), _Timer([True]), _Timer()])
    coalition = _Coalition(_session("coalition_20251120", "area1-hard", CoalitionFleetMode.SINGLE))
    coalition.battle_results = [False, True]
    coalition.in_difficulty_results = [True]

    coalition.enter_coalition_map()

    assert coalition.device.clicks == [coalition_assets.DAL_HARD]


def test_enter_coalition_map_raises_after_stage_click_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([True] * 6), _Timer(), _Timer()])
    coalition = _Coalition(_session("coalition_20230323", "tc3", CoalitionFleetMode.MULTI))
    coalition.battle_results = [False] * 7
    coalition.in_coalition_results = [True] * 6

    with pytest.raises(HumanTakeoverRequiredError):
        coalition.enter_coalition_map()
