from typing import TYPE_CHECKING, override

import numpy as np
import pytest

from module.coalition import assets as coalition_assets
from module.coalition import ui as coalition_ui
from module.coalition.ui import CoalitionUI
from module.combat.assets import BATTLE_PREPARATION
from module.exception import RequestHumanTakeover

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray
    from module.coalition.contracts import CoalitionEvent, CoalitionFleetMode, CoalitionStage


class _Timer:
    def __init__(self, results: Iterable[bool] | None = None) -> None:
        self.results = list(results or [])
        self.reset_count = 0

    def reached(self) -> bool:
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self) -> None:
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.clicks: list[Button] = []

    def click(self, button: Button) -> None:
        self.clicks.append(button)


class _Coalition(CoalitionUI):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.loop_count = 8
        self.battle_results: list[bool] = []
        self.fleet_results: list[bool] = []
        self.in_coalition_results: list[bool] = []
        self.in_difficulty_results: list[bool] = []
        self.fleet_preparation_calls: list[tuple[CoalitionEvent, CoalitionStage, CoalitionFleetMode]] = []
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
        if results:
            return results.pop(0)
        return False

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
        if button in {
            coalition_assets.FROSTFALL_FLEET_PREPARATION,
            coalition_assets.DAL_FLEET_PREPARATION,
        }:
            return self._next(self.fleet_results)
        return False

    def in_coalition(self) -> bool:
        return self._next(self.in_coalition_results)

    def in_coalition_20251120_difficulty_selection(self) -> bool:
        return self._next(self.in_difficulty_results)

    @override
    def handle_fleet_preparation(
        self,
        event: CoalitionEvent,
        stage: CoalitionStage,
        mode: CoalitionFleetMode,
    ) -> bool:
        self.fleet_preparation_calls.append((event, stage, mode))
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


def test_coalition_enter_map_clicks_stage_then_fleet_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([True, False]), _Timer(), _Timer([True])])
    coalition = _Coalition()
    coalition.battle_results = [False, False, True]
    coalition.in_coalition_results = [True, False]
    coalition.fleet_results = [True]

    coalition.enter_map("coalition_20230323", "tc3", "multi")

    assert coalition.device.clicks == [
        coalition_assets.FROSTFALL_TC3,
        coalition_assets.FROSTFALL_FLEET_PREPARATION,
    ]
    assert coalition.fleet_preparation_calls == [("coalition_20230323", "tc3", "multi")]


def test_coalition_enter_map_clicks_dal_difficulty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([False]), _Timer([True]), _Timer()])
    coalition = _Coalition()
    coalition.battle_results = [False, True]
    coalition.in_difficulty_results = [True]

    coalition.enter_map("coalition_20251120", "area1-hard", "single")

    assert coalition.device.clicks == [coalition_assets.DAL_HARD]


def test_coalition_enter_map_raises_after_campaign_click_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_timers(monkeypatch, [_Timer([True] * 6), _Timer(), _Timer()])
    coalition = _Coalition()
    coalition.battle_results = [False] * 7
    coalition.in_coalition_results = [True] * 6

    with pytest.raises(RequestHumanTakeover):
        coalition.enter_map("coalition_20230323", "tc3", "multi")
