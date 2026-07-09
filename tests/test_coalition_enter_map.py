import pytest

from module.coalition import assets as coalition_assets
from module.coalition import ui as coalition_ui
from module.coalition.ui import CoalitionUI
from module.combat.assets import BATTLE_PREPARATION
from module.exception import RequestHumanTakeover


class _Timer:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.reset_count = 0

    def reached(self):
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self):
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.clicks = []

    def click(self, button) -> None:
        self.clicks.append(button)


class _Coalition(CoalitionUI):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.battle_results = []
        self.fleet_results = []
        self.in_coalition_results = []
        self.in_difficulty_results = []
        self.fleet_preparation_calls = []
        self.guild_results = []
        self.auto_search_results = []
        self.retirement_results = []
        self.low_emotion_results = []
        self.urgent_results = []
        self.story_results = []
        self.automation_confirm_results = []
        self.popup_results = []

    @staticmethod
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def loop(self, *_args: object, **_kwargs: object):
        yield from range(8)

    def appear(self, button, *_args: object, **_kwargs):
        if button == BATTLE_PREPARATION:
            return self._next(self.battle_results)
        if button in {
            coalition_assets.FROSTFALL_FLEET_PREPARATION,
            coalition_assets.DAL_FLEET_PREPARATION,
        }:
            return self._next(self.fleet_results)
        return False

    def in_coalition(self):
        return self._next(self.in_coalition_results)

    def in_coalition_20251120_difficulty_selection(self):
        return self._next(self.in_difficulty_results)

    def handle_fleet_preparation(self, event, stage, mode):
        self.fleet_preparation_calls.append((event, stage, mode))
        return False

    def handle_guild_popup_cancel(self):
        return self._next(self.guild_results)

    def handle_auto_search_continue(self):
        return self._next(self.auto_search_results)

    def handle_retirement(self):
        return self._next(self.retirement_results)

    def handle_combat_low_emotion(self):
        return self._next(self.low_emotion_results)

    def handle_urgent_commission(self):
        return self._next(self.urgent_results)

    def handle_story_skip(self):
        return self._next(self.story_results)

    def handle_combat_automation_confirm(self):
        return self._next(self.automation_confirm_results)

    def handle_popup_confirm(self, name="", offset=None, interval=2):
        _ = (name, offset, interval)
        assert name == "COALITION"
        return self._next(self.popup_results)


def _patch_timers(monkeypatch, timers) -> None:
    timer_queue = list(timers)
    monkeypatch.setattr(coalition_ui, "Timer", lambda *_args, **_kwargs: timer_queue.pop(0))


def test_coalition_enter_map_clicks_stage_then_fleet_preparation(monkeypatch) -> None:
    _patch_timers(monkeypatch, [_Timer([True, False]), _Timer(), _Timer([True])])
    coalition = _Coalition()
    coalition.battle_results = [False, False, True]
    coalition.in_coalition_results = [True, False]
    coalition.fleet_results = [True]

    coalition.enter_map("coalition_20230323", "TC3", "multi")

    assert coalition.device.clicks == [
        coalition_assets.FROSTFALL_TC3,
        coalition_assets.FROSTFALL_FLEET_PREPARATION,
    ]
    assert coalition.fleet_preparation_calls == [("coalition_20230323", "TC3", "multi")]


def test_coalition_enter_map_clicks_dal_difficulty(monkeypatch) -> None:
    _patch_timers(monkeypatch, [_Timer([False]), _Timer([True]), _Timer()])
    coalition = _Coalition()
    coalition.battle_results = [False, True]
    coalition.in_difficulty_results = [True]

    coalition.enter_map("coalition_20251120", "area1-hard", "single")

    assert coalition.device.clicks == [coalition_assets.DAL_HARD]


def test_coalition_enter_map_raises_after_campaign_click_limit(monkeypatch) -> None:
    _patch_timers(monkeypatch, [_Timer([True] * 6), _Timer(), _Timer()])
    coalition = _Coalition()
    coalition.battle_results = [False] * 7
    coalition.in_coalition_results = [True] * 6

    with pytest.raises(RequestHumanTakeover):
        coalition.enter_map("coalition_20230323", "TC3", "multi")
