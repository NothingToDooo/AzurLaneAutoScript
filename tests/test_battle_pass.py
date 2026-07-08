from dataclasses import dataclass, replace

import module.freebies.battle_pass as battle_pass_module
from module.freebies.assets import REWARD_RECEIVE, REWARD_RECEIVE_SP, REWARD_RECEIVE_WHITE
from module.freebies.battle_pass import BattlePass
from module.ui.assets import BATTLE_PASS_CHECK


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
        return True


class _FakeDevice:
    def __init__(self) -> None:
        self.clicked = []
        self.screenshot_count = 0

    def click(self, button) -> None:
        self.clicked.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


@dataclass(frozen=True, slots=True)
class _FakeBattlePassOptions:
    appear_results: object = None
    appear_then_click_results: object = None
    match_results: object = None
    popup_results: object = None
    get_items_results: tuple = ()
    get_ship_results: tuple = ()
    get_skin_results: tuple = ()


def _fake_battle_pass_options(options=None, settings=None) -> _FakeBattlePassOptions:
    options = _FakeBattlePassOptions() if options is None else options
    if settings:
        options = replace(options, **settings)
    return options


class _FakeBattlePass(BattlePass):
    def __init__(self, options=None, **settings) -> None:
        options = _fake_battle_pass_options(options, settings)
        self.device = _FakeDevice()
        self.appear_results = {id(button): list(results) for button, results in (options.appear_results or {}).items()}
        self.appear_then_click_results = {
            id(button): list(results) for button, results in (options.appear_then_click_results or {}).items()
        }
        self.match_results = {id(button): list(results) for button, results in (options.match_results or {}).items()}
        self.popup_results = list(options.popup_results or [])
        self.get_items_results = list(options.get_items_results)
        self.get_ship_results = list(options.get_ship_results)
        self.get_skin_results = list(options.get_skin_results)

    def _pop_button_result(self, results_by_button, button) -> bool:
        results = results_by_button.get(id(button), [])
        if results:
            return results.pop(0)
        return False

    def appear(self, button, **_kwargs) -> bool:
        return self._pop_button_result(self.appear_results, button)

    def appear_then_click(self, button, **_kwargs) -> bool:
        return self._pop_button_result(self.appear_then_click_results, button)

    def match_template_color(self, button, **_kwargs) -> bool:
        return self._pop_button_result(self.match_results, button)

    def handle_popup_confirm(self, _name) -> bool:
        if self.popup_results:
            return self.popup_results.pop(0)
        return False

    def handle_get_items(self) -> bool:
        if self.get_items_results:
            return self.get_items_results.pop(0)
        return False

    def handle_get_ship(self) -> bool:
        if self.get_ship_results:
            return self.get_ship_results.pop(0)
        return False

    def handle_get_skin(self) -> bool:
        if self.get_skin_results:
            return self.get_skin_results.pop(0)
        return False


def test_battle_pass_receive_marks_received_after_get_items(monkeypatch) -> None:
    _FakeTimer.reached_results = (True,)
    monkeypatch.setattr(battle_pass_module, "Timer", _FakeTimer)
    battle_pass = _FakeBattlePass(
        appear_results={
            BATTLE_PASS_CHECK: [True],
            REWARD_RECEIVE: [False],
            REWARD_RECEIVE_WHITE: [False],
        },
        appear_then_click_results={
            REWARD_RECEIVE: [True, False, False],
            REWARD_RECEIVE_WHITE: [False, False],
        },
        match_results={
            REWARD_RECEIVE_SP: [False, False],
        },
        get_items_results=[True, False],
    )

    assert battle_pass.battle_pass_receive()
    assert battle_pass.battle_status_click_interval == 2


def test_battle_pass_receive_returns_false_without_rewards(monkeypatch) -> None:
    _FakeTimer.reached_results = (True,)
    monkeypatch.setattr(battle_pass_module, "Timer", _FakeTimer)
    battle_pass = _FakeBattlePass(
        appear_results={
            BATTLE_PASS_CHECK: [True],
            REWARD_RECEIVE: [False],
            REWARD_RECEIVE_WHITE: [False],
        },
        appear_then_click_results={
            REWARD_RECEIVE: [False],
            REWARD_RECEIVE_WHITE: [False],
        },
        match_results={
            REWARD_RECEIVE_SP: [False],
        },
    )

    assert not battle_pass.battle_pass_receive()
