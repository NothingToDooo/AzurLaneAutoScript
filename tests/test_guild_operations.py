from typing import ClassVar, TypeVar

import pytest

from module.exception import GameBugError
from module.guild import assets as guild_assets
from module.guild import operations as operations_module
from module.guild.operations import GuildOperations

_T = TypeVar("_T")
_Entrance = tuple[list[object], list[object]]


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
        return False

    def reset(self) -> None:
        _Timer.reset_counts[self.index] = _Timer.reset_counts.get(self.index, 0) + 1


class _Device:
    image = object()

    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Config:
    GuildOperation_SelectNewOperation = False
    GuildOperation_JoinThreshold = 0.5


class _ProgressOcr:
    def __init__(self, values: tuple[int, int, int]) -> None:
        self.values = values

    def ocr(self, _image: object) -> tuple[int, int, int]:
        return self.values


class _GuildOperations(GuildOperations):
    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.entrance_results: list[_Entrance] = []
        self.color_results: list[bool] = []
        self.fund_results: list[bool] = []
        self.start_results: list[bool] = []
        self.popup_confirm_results: list[bool] = []
        self.popup_single_results: list[bool] = []
        self.info_bar_results: list[int] = []

    def ensure(self) -> bool:
        return self._guild_operations_ensure()

    def dispatch_enter(self) -> bool:
        return self._guild_operations_dispatch_enter()

    def _next_result(self, results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def appear(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def _guild_operations_get_entrance(self) -> _Entrance:
        self.calls.append(("_guild_operations_get_entrance",))
        return self._next_result(self.entrance_results, default=([], []))

    def image_color_count(self, button: object, **kwargs: object) -> bool:
        self.calls.append(("image_color_count", button, kwargs))
        return self._next_result(self.color_results, default=False)

    def _guild_operation_fund_insufficient(self) -> bool:
        self.calls.append(("_guild_operation_fund_insufficient",))
        return self._next_result(self.fund_results, default=False)

    def _handle_guild_operations_start(self) -> bool:
        self.calls.append(("_handle_guild_operations_start",))
        return self._next_result(self.start_results, default=False)

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_confirm_results, default=False)

    def handle_popup_single(self, name: str) -> bool:
        self.calls.append(("handle_popup_single", name))
        return self._next_result(self.popup_single_results, default=False)

    def info_bar_count(self) -> int:
        self.calls.append(("info_bar_count",))
        return self._next_result(self.info_bar_results, default=0)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_counts = {}
    monkeypatch.setattr(operations_module, "Timer", _Timer)


def test_guild_operations_ensure_returns_false_when_fund_insufficient() -> None:
    guild = _GuildOperations()
    guild.fund_results = [True]

    result = guild.ensure()

    assert result is False
    assert guild.device.clicks == []


def test_guild_operations_ensure_joins_when_progress_under_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    guild = _GuildOperations()
    guild.appear_results[button_key(guild_assets.GUILD_OPERATIONS_JOIN)] = [True, False]
    guild.appear_results[button_key(guild_assets.GUILD_BOSS_ENTER)] = [False]
    guild.appear_results[button_key(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK)] = [True]
    guild.color_results = [False]
    _Timer.reached_results = {0: [True]}
    monkeypatch.setattr(operations_module, "GUILD_OPERATIONS_PROGRESS", _ProgressOcr((30, 0, 100)))

    result = guild.ensure()

    assert result is True
    assert guild.device.clicks == [guild_assets.GUILD_OPERATIONS_JOIN]
    assert _Timer.reset_counts[0] == 1


def test_guild_operations_ensure_raises_after_repeated_join_popups() -> None:
    guild = _GuildOperations()
    guild.popup_confirm_results = [True, True, True, True, True, True]

    with pytest.raises(GameBugError, match="Unable to start/join guild operation"):
        guild.ensure()


def test_guild_operations_dispatch_enter_returns_false_without_entrance() -> None:
    guild = _GuildOperations()
    guild.appear_results[button_key(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK)] = [True]
    guild.entrance_results = [([], [])]

    result = guild.dispatch_enter()

    assert result is False
    assert guild.device.clicks == []


def test_guild_operations_dispatch_enter_expands_then_enters() -> None:
    guild = _GuildOperations()
    expand_button = object()
    enter_button = object()
    guild.appear_results[button_key(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK)] = [True, True]
    guild.appear_results[button_key(guild_assets.GUILD_DISPATCH_RECOMMEND)] = [True]
    guild.entrance_results = [([expand_button], [enter_button]), ([expand_button], [enter_button])]
    guild.color_results = [True]
    _Timer.reached_results = {0: [True, False], 1: [True]}

    result = guild.dispatch_enter()

    assert result is True
    assert guild.device.clicks == [expand_button, enter_button]
    assert _Timer.reset_counts == {0: 2, 1: 1}


def test_guild_operations_dispatch_enter_handles_quick_dispatch() -> None:
    guild = _GuildOperations()
    guild.appear_then_click_results[button_key(guild_assets.GUILD_DISPATCH_QUICK)] = [True, False]
    guild.appear_results[button_key(guild_assets.GUILD_DISPATCH_RECOMMEND)] = [True]

    result = guild.dispatch_enter()

    assert result is True
    assert _Timer.reset_counts == {0: 1, 1: 1}
    assert guild.device.screenshot_count == 1
