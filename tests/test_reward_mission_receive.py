from typing import TYPE_CHECKING, override

import numpy as np

import module.reward.reward as reward_module
from module.combat import assets as combat_assets
from module.reward import assets as reward_assets
from module.reward.reward import MissionState, Reward

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    import pytest

    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray
    from module.ui.page import Page


class _FakeTimer:
    default_reached_results: tuple[bool, ...] = ()

    def __init__(self, _limit: float, count: int = 0) -> None:
        del count
        self.reached_results: list[bool] = list(self.__class__.default_reached_results)

    def start(self) -> _FakeTimer:
        return self

    def reset(self) -> _FakeTimer:
        return self

    def reached(self) -> bool:
        if self.reached_results:
            return self.reached_results.pop(0)
        return False


class _FakeReward(Reward):
    def __init__(
        self,
        *,
        page_results: Iterable[bool] = (),
        state_results: Iterable[Button | None] = (),
        appear_then_click_results: Mapping[Button, Iterable[bool]] | None = None,
        mission_popup_results: Iterable[bool] = (),
    ) -> None:
        self.page_results = list(page_results)
        self.state_results = list(state_results)
        self.appear_then_click_results = {
            id(button): list(results) for button, results in (appear_then_click_results or {}).items()
        }
        self.mission_popup_results = list(mission_popup_results)
        self.loop_image = np.zeros((1, 1, 3), dtype=np.uint8)

    def receive(self) -> MissionState:
        return self._reward_mission_claim_receive()

    @override
    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        del skip_first, timeout
        return iter([self.loop_image] * 6)

    @override
    def ui_page_appear(
        self,
        page: Page,
        offset: MatchOffset | None = (30, 30),
        interval: float = 0,
    ) -> bool:
        _ = (page, offset, interval)
        if self.page_results:
            return self.page_results.pop(0)
        return False

    @override
    def _reward_get_state(self) -> Button | None:
        if self.state_results:
            return self.state_results.pop(0)
        return None

    @override
    def appear_then_click(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        del offset, interval, similarity, threshold
        results = self.appear_then_click_results.get(id(button), [])
        if results:
            return results.pop(0)
        return False

    def handle_mission_popup_ack(self) -> bool:
        if self.mission_popup_results:
            return self.mission_popup_results.pop(0)
        return False

    @staticmethod
    def handle_vote_popup() -> bool:
        return False

    @override
    def handle_story_skip(self) -> bool:
        return False

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del name, offset, interval
        return False


def test_reward_mission_claim_receive_returns_current_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeTimer.default_reached_results = ()
    monkeypatch.setattr(reward_module, "Timer", _FakeTimer)
    reward = _FakeReward(page_results=[True], state_results=[reward_assets.MISSION_EMPTY])

    assert reward.receive() == reward_assets.MISSION_EMPTY


def test_reward_mission_claim_receive_handles_reward_popup(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeTimer.default_reached_results = ()
    monkeypatch.setattr(reward_module, "Timer", _FakeTimer)
    reward = _FakeReward(
        page_results=[False, True],
        state_results=[reward_assets.MISSION_UNFINISH],
        appear_then_click_results={
            combat_assets.GET_ITEMS_1: [True],
        },
    )

    assert reward.receive() == reward_assets.MISSION_UNFINISH


def test_reward_mission_claim_receive_times_out_on_empty_mission_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeTimer.default_reached_results = (True,)
    monkeypatch.setattr(reward_module, "Timer", _FakeTimer)
    reward = _FakeReward(page_results=[True], state_results=[None])

    assert reward.receive() == "timeout"
