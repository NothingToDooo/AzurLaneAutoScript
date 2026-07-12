from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypedDict, Unpack, override

import module.freebies.battle_pass as battle_pass_module
from module.freebies.assets import REWARD_RECEIVE, REWARD_RECEIVE_SP, REWARD_RECEIVE_WHITE
from module.freebies.battle_pass import BattlePass
from module.ui.assets import BATTLE_PASS_CHECK

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import pytest

    from module.base.button import Button, MatchOffset


class _FakeTimer:
    default_reached_results: tuple[bool, ...] = ()

    def __init__(self, limit: float, count: int = 0) -> None:
        del limit, count
        self.reached_results: list[bool] = list(self.__class__.default_reached_results)

    def start(self) -> _FakeTimer:
        return self

    def reset(self) -> _FakeTimer:
        return self

    def reached(self) -> bool:
        if self.reached_results:
            return self.reached_results.pop(0)
        return True


class _FakeDevice:
    def __init__(self) -> None:
        self.clicked: list[Button] = []
        self.screenshot_count = 0

    def click(self, button: Button) -> None:
        self.clicked.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


@dataclass(frozen=True, slots=True)
class _FakeBattlePassOptions:
    appear_results: Mapping[Button, Iterable[bool]] | None = None
    appear_then_click_results: Mapping[Button, Iterable[bool]] | None = None
    match_results: Mapping[Button, Iterable[bool]] | None = None
    popup_results: Iterable[bool] | None = None
    get_items_results: Iterable[bool] = ()
    get_ship_results: Iterable[bool] = ()
    get_skin_results: Iterable[bool] = ()


class _FakeBattlePassSettings(TypedDict, total=False):
    appear_results: Mapping[Button, Iterable[bool]] | None
    appear_then_click_results: Mapping[Button, Iterable[bool]] | None
    match_results: Mapping[Button, Iterable[bool]] | None
    popup_results: Iterable[bool] | None
    get_items_results: Iterable[bool]
    get_ship_results: Iterable[bool]
    get_skin_results: Iterable[bool]


def _fake_battle_pass_options(
    options: _FakeBattlePassOptions | None = None,
    settings: _FakeBattlePassSettings | None = None,
) -> _FakeBattlePassOptions:
    options = _FakeBattlePassOptions() if options is None else options
    if settings:
        options = replace(options, **settings)
    return options


class _FakeBattlePass(BattlePass):
    device: _FakeDevice

    def __init__(
        self,
        options: _FakeBattlePassOptions | None = None,
        **settings: Unpack[_FakeBattlePassSettings],
    ) -> None:
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

    @staticmethod
    def _pop_button_result(results_by_button: dict[int, list[bool]], button: Button) -> bool:
        results = results_by_button.get(id(button), [])
        if results:
            return results.pop(0)
        return False

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
        return self._pop_button_result(self.appear_results, button)

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
        return self._pop_button_result(self.appear_then_click_results, button)

    @override
    def match_template_color(
        self,
        button: Button,
        offset: MatchOffset = (20, 20),
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        del offset, interval, similarity, threshold
        return self._pop_button_result(self.match_results, button)

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del name, offset, interval
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


def test_battle_pass_receive_marks_received_after_get_items(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeTimer.default_reached_results = (True,)
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


def test_battle_pass_receive_returns_false_without_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeTimer.default_reached_results = (True,)
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
