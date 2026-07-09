from typing import ClassVar

import pytest

from module.exception import GameBugError
from module.guild import logistics as logistics_module
from module.guild.assets import GUILD_MISSION, GUILD_SUPPLY
from module.guild.logistics import GuildLogistics


class _Timer:
    next_index: ClassVar[int] = 0
    confirm_reached: ClassVar[bool] = True
    exchange_reached: ClassVar[bool] = True
    click_reached: ClassVar[bool] = True

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def start(self) -> _Timer:
        return self

    def reached(self) -> bool:
        if self.index == 0:
            return _Timer.confirm_reached
        if self.index == 1:
            return _Timer.exchange_reached
        return _Timer.click_reached

    def reset(self) -> None:
        pass


class _Config:
    GuildLogistics_SelectNewMission = False


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.screenshot_count = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _GuildLogistics(GuildLogistics):
    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.popup_results: list[bool] = []
        self.get_items_results: list[bool] = []
        self.fleet_mission_results: list[bool] = []
        self.in_logistics_results: list[bool] = []
        self.supply_results: list[bool] = []
        self.mission_results: list[bool] = []
        self.exchange_results: list[bool] = []
        self.info_bar_results: list[int] = []
        self._guild_logistics_mission_finished = False

    def collect(self) -> bool:
        return self._guild_logistics_collect()

    def _next_result[T](self, results: list[T], *, default: T) -> T:
        if results:
            return results.pop(0)
        return default

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def appear_then_click(self, button: object, **kwargs: object) -> bool:
        self.calls.append(("appear_then_click", button, kwargs))
        return self._next_result(self.get_items_results, default=False)

    def _handle_guild_fleet_mission_start(self) -> bool:
        self.calls.append(("_handle_guild_fleet_mission_start",))
        return self._next_result(self.fleet_mission_results, default=False)

    def _is_in_guild_logistics(self) -> bool:
        self.calls.append(("_is_in_guild_logistics",))
        return self._next_result(self.in_logistics_results, default=True)

    def _guild_logistics_supply_available(self) -> bool:
        self.calls.append(("_guild_logistics_supply_available",))
        return self._next_result(self.supply_results, default=False)

    def _guild_logistics_mission_available(self) -> bool:
        self.calls.append(("_guild_logistics_mission_available",))
        return self._next_result(self.mission_results, default=False)

    def _guild_exchange(self) -> bool:
        self.calls.append(("_guild_exchange",))
        return self._next_result(self.exchange_results, default=False)

    def info_bar_count(self) -> int:
        self.calls.append(("info_bar_count",))
        return self._next_result(self.info_bar_results, default=0)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.confirm_reached = True
    _Timer.exchange_reached = True
    _Timer.click_reached = True
    monkeypatch.setattr(logistics_module, "Timer", _Timer)


def test_guild_logistics_collect_returns_true_when_all_sections_checked() -> None:
    guild = _GuildLogistics()

    assert guild.collect() is True

    assert guild.device.clicks == []
    assert guild.calls[-4:] == [
        ("_guild_logistics_supply_available",),
        ("_guild_logistics_mission_available",),
        ("_guild_exchange",),
        ("info_bar_count",),
    ]


def test_guild_logistics_collect_clicks_supply_and_mission() -> None:
    guild = _GuildLogistics()
    guild.supply_results = [True, False]
    guild.mission_results = [True, False]

    assert guild.collect() is True

    assert guild.device.clicks == [GUILD_SUPPLY, GUILD_MISSION]
    assert guild.calls.count(("_guild_logistics_supply_available",)) == 2
    assert guild.calls.count(("_guild_logistics_mission_available",)) == 2


def test_guild_logistics_collect_resets_when_not_in_logistics() -> None:
    guild = _GuildLogistics()
    guild.in_logistics_results = [False, True]

    assert guild.collect() is True

    assert guild.device.screenshot_count == 1
    assert guild.calls.count(("_is_in_guild_logistics",)) == 2


def test_guild_logistics_collect_raises_after_repeated_exchange_bug() -> None:
    guild = _GuildLogistics()
    guild.exchange_results = [True, True, True, True, True, False]
    _Timer.confirm_reached = False

    with pytest.raises(GameBugError, match="guild logistics refresh bug"):
        guild.collect()
