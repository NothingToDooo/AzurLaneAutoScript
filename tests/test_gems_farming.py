from typing import TypeVar

import pytest

from module.campaign import gems_farming as gems_module
from module.campaign.gems_farming import GemsCampaignOverride
from module.exception import CampaignEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF
from module.ui.assets import BACK_ARROW

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Config:
    GemsFarming_ChangeVanguard = "disabled"
    GEMS_EMOTION_TRIGGERED = False


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _GemsCampaign(GemsCampaignOverride):
    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.confirm_results: list[bool] = []
        self.cancel_results: list[bool] = []
        self.story_results: list[bool] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.auto_search_results: list[bool] = []
        self.stage_results: list[bool] = []
        self.map_results: list[bool] = []

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.confirm_results, default=False)

    def handle_popup_cancel(self, name: str) -> bool:
        self.calls.append(("handle_popup_cancel", name))
        return self._next_result(self.cancel_results, default=False)

    def interval_reset(self, button: object) -> None:
        self.calls.append(("interval_reset", button))

    def handle_story_skip(self) -> bool:
        self.calls.append(("handle_story_skip",))
        return self._next_result(self.story_results, default=False)

    def appear(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def handle_auto_search_exit(self) -> bool:
        self.calls.append(("handle_auto_search_exit",))
        return self._next_result(self.auto_search_results, default=False)

    def is_in_stage(self) -> bool:
        self.calls.append(("is_in_stage",))
        return self._next_result(self.stage_results, default=False)

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return self._next_result(self.map_results, default=False)

    def withdraw(self) -> None:
        self.calls.append(("withdraw",))

    def enter_map_cancel(self) -> None:
        self.calls.append(("enter_map_cancel",))


def test_low_emotion_disabled_confirms_ignore() -> None:
    campaign = _GemsCampaign()
    campaign.confirm_results = [True]

    result = campaign.handle_combat_low_emotion()

    assert result is True
    assert ("interval_reset", AUTO_SEARCH_MAP_OPTION_OFF) in campaign.calls


def test_low_emotion_enabled_returns_false_without_cancel_popup() -> None:
    campaign = _GemsCampaign()
    campaign.config.GemsFarming_ChangeVanguard = "enabled"

    result = campaign.handle_combat_low_emotion()

    assert result is False
    assert campaign.config.GEMS_EMOTION_TRIGGERED is False


def test_low_emotion_withdraw_raises_after_stage_return() -> None:
    campaign = _GemsCampaign()
    campaign.config.GemsFarming_ChangeVanguard = "enabled"
    campaign.cancel_results = [True, False]
    campaign.stage_results = [True]

    with pytest.raises(CampaignEnd, match="Emotion withdraw"):
        campaign.handle_combat_low_emotion()

    assert campaign.config.GEMS_EMOTION_TRIGGERED is True
    assert campaign.device.screenshot_count == 1


def test_low_emotion_withdraw_backs_out_then_withdraws_from_map() -> None:
    campaign = _GemsCampaign()
    campaign.config.GemsFarming_ChangeVanguard = "enabled"
    campaign.cancel_results = [True, False, False]
    campaign.appear_results[button_key(gems_module.BATTLE_PREPARATION)] = [True, False]
    campaign.stage_results = [False]
    campaign.map_results = [True]

    with pytest.raises(CampaignEnd, match="Emotion withdraw"):
        campaign.handle_combat_low_emotion()

    assert campaign.device.clicks == [BACK_ARROW]
    assert ("withdraw",) in campaign.calls
