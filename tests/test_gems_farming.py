from typing import TYPE_CHECKING, TypeVar, cast

import pytest

from module.campaign import gems_farming as gems_module
from module.campaign.campaign_base import CampaignBase
from module.campaign.gems_farming import GemsCampaignOverride, GemsFarming
from module.campaign.run import CampaignRun
from module.content import LoadedStage
from module.exception import CampaignEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF
from module.map.map_base import CampaignMap
from module.ui.assets import BACK_ARROW

if TYPE_CHECKING:
    from typing import Any

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
    config: _Config
    device: _Device

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

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.confirm_results, default=False)

    def handle_popup_cancel(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_cancel", name))
        return self._next_result(self.cancel_results, default=False)

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button))

    def handle_story_skip(self) -> bool:
        self.calls.append(("handle_story_skip",))
        return self._next_result(self.story_results, default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
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

    def withdraw(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("withdraw",))

    def enter_map_cancel(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("enter_map_cancel",))


class _TestGemsOverride(CampaignBase):
    pass


class _TestLoadedCampaign(CampaignBase):
    def __init__(self, *, config: object, device: object) -> None:
        self.test_config = config
        self.test_device = device
        vars(self)["config"] = config
        vars(self)["device"] = device


class _MergedCampaignConfig:
    def __init__(self) -> None:
        self.overrides: list[dict[str, object]] = []

    def override(self, **kwargs: object) -> None:
        self.overrides.append(kwargs)


def test_gems_farming_uses_loaded_stage_campaign_class(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(GemsFarming)
    merged_config = _MergedCampaignConfig()
    device = object()
    runner.module = None

    def load_stage(self: object, name: str, folder: str = "campaign_main") -> bool:
        _ = (name, folder)
        runner_state = cast("Any", self)
        runner_state.loaded_stage = LoadedStage(_Config, _TestLoadedCampaign, CampaignMap("TEST"))
        runner_state.campaign = _TestLoadedCampaign(config=merged_config, device=device)
        return True

    monkeypatch.setattr(CampaignRun, "load_campaign", load_stage)
    monkeypatch.setattr(gems_module, "GemsCampaignOverride", _TestGemsOverride)

    runner.load_campaign("t1", folder="event_test")

    assert isinstance(runner.campaign, _TestLoadedCampaign)
    assert runner.campaign.test_device is device
    assert runner.campaign.test_config is merged_config
    assert merged_config.overrides == [
        {"Emotion_Mode": "ignore"},
        {"EnemyPriority_EnemyScaleBalanceWeight": "S1_enemy_first"},
    ]


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

    with pytest.raises(CampaignEnd, match=gems_module.EMOTION_WITHDRAW_MESSAGE):
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

    with pytest.raises(CampaignEnd, match=gems_module.EMOTION_WITHDRAW_MESSAGE):
        campaign.handle_combat_low_emotion()

    assert campaign.device.clicks == [BACK_ARROW]
    assert ("withdraw",) in campaign.calls
