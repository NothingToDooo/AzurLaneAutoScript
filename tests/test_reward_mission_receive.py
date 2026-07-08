import module.reward.reward as reward_module
from module.combat import assets as combat_assets
from module.reward import assets as reward_assets
from module.reward.reward import Reward


class _FakeTimer:
    reached_results = ()

    def __init__(self, *_args, **_kwargs) -> None:
        self.reached_results = list(self.__class__.reached_results)

    def start(self):
        return self

    def reset(self):
        return self

    def reached(self) -> bool:
        if self.reached_results:
            return self.reached_results.pop(0)
        return False


class _FakeReward(Reward):
    def __init__(
        self,
        *,
        page_results=(),
        state_results=(),
        appear_then_click_results=None,
        mission_popup_results=(),
    ) -> None:
        self.page_results = list(page_results)
        self.state_results = list(state_results)
        self.appear_then_click_results = {
            id(button): list(results) for button, results in (appear_then_click_results or {}).items()
        }
        self.mission_popup_results = list(mission_popup_results)

    def receive(self):
        return self._reward_mission_claim_receive()

    def loop(self):
        return range(6)

    def ui_page_appear(self, _page) -> bool:
        if self.page_results:
            return self.page_results.pop(0)
        return False

    def _reward_get_state(self):
        if self.state_results:
            return self.state_results.pop(0)
        return None

    def appear_then_click(self, button, **_kwargs) -> bool:
        results = self.appear_then_click_results.get(id(button), [])
        if results:
            return results.pop(0)
        return False

    def handle_mission_popup_ack(self) -> bool:
        if self.mission_popup_results:
            return self.mission_popup_results.pop(0)
        return False

    def handle_vote_popup(self) -> bool:
        return False

    def handle_story_skip(self) -> bool:
        return False

    def handle_popup_confirm(self, _name) -> bool:
        return False


def test_reward_mission_claim_receive_returns_current_state(monkeypatch) -> None:
    _FakeTimer.reached_results = ()
    monkeypatch.setattr(reward_module, "Timer", _FakeTimer)
    reward = _FakeReward(page_results=[True], state_results=[reward_assets.MISSION_EMPTY])

    assert reward.receive() == reward_assets.MISSION_EMPTY


def test_reward_mission_claim_receive_handles_reward_popup(monkeypatch) -> None:
    _FakeTimer.reached_results = ()
    monkeypatch.setattr(reward_module, "Timer", _FakeTimer)
    reward = _FakeReward(
        page_results=[False, True],
        state_results=[reward_assets.MISSION_UNFINISH],
        appear_then_click_results={
            combat_assets.GET_ITEMS_1: [True],
        },
    )

    assert reward.receive() == reward_assets.MISSION_UNFINISH


def test_reward_mission_claim_receive_times_out_on_empty_mission_page(monkeypatch) -> None:
    _FakeTimer.reached_results = (True,)
    monkeypatch.setattr(reward_module, "Timer", _FakeTimer)
    reward = _FakeReward(page_results=[True], state_results=[None])

    assert reward.receive() == "timeout"
