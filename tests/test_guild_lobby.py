from typing import ClassVar, TypeVar

import pytest

from module.combat.assets import GET_ITEMS_1
from module.guild import lobby as lobby_module
from module.guild.assets import GUILD_REPORT_CLAIM, GUILD_REPORT_CLAIMED, GUILD_REPORT_CLOSE
from module.guild.lobby import GuildLobby
from module.ui.assets import GUILD_CHECK

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return getattr(button, "name", repr(button))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}
    reset_counts: ClassVar[dict[int, int]] = {}

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def start(self) -> _Timer:
        return self

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return self.index == 0

    def reset(self) -> None:
        _Timer.reset_counts[self.index] = _Timer.reset_counts.get(self.index, 0) + 1


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _GuildLobby(GuildLobby):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.report_results: list[object | None] = []

    def collect(self) -> None:
        self._guild_lobby_collect()

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def guild_lobby_get_report(self) -> object | None:
        self.calls.append(("guild_lobby_get_report",))
        return self._next_result(self.report_results, default=None)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_counts = {}
    monkeypatch.setattr(lobby_module, "Timer", _Timer)


def test_guild_lobby_collect_opens_available_report() -> None:
    guild = _GuildLobby()
    report_button = object()
    _Timer.reached_results = {1: [True]}
    guild.report_results = [report_button]
    guild.appear_results[button_key(GUILD_CHECK)] = [True, True]

    guild.collect()

    assert guild.device.clicks == [report_button]
    assert _Timer.reset_counts[1] == 1


def test_guild_lobby_collect_handles_report_reward_popups() -> None:
    guild = _GuildLobby()
    _Timer.reached_results = {1: [False, False, False]}
    guild.appear_then_click_results[button_key(GUILD_REPORT_CLAIM)] = [True, False]
    guild.appear_then_click_results[button_key(GET_ITEMS_1)] = [True]
    guild.appear_results[button_key(GUILD_CHECK)] = [True]

    guild.collect()

    assert _Timer.reset_counts[0] == 2
    assert guild.device.screenshot_count == 2


def test_guild_lobby_collect_closes_claimed_report() -> None:
    guild = _GuildLobby()
    _Timer.reached_results = {1: [False, False]}
    guild.appear_results[button_key(GUILD_REPORT_CLAIMED)] = [True, False]
    guild.appear_results[button_key(GUILD_CHECK)] = [True]

    guild.collect()

    assert guild.device.clicks == [GUILD_REPORT_CLOSE]
    assert _Timer.reset_counts[0] == 1
