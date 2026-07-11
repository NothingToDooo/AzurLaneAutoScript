from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Unpack, override

from module.tactical import tactical_class as tactical_module
from module.tactical.assets import BOOK_EMPTY_POPUP
from module.tactical.tactical_class import RewardTacticalClass
from module.ui.assets import BACK_ARROW, REWARD_CHECK

if TYPE_CHECKING:
    from datetime import datetime

    import pytest

    from module.base.button import Button, MatchOffset
    from module.retire.dock import DockFilterOptions, DockFilterSettings
    from module.ui.page import Page


class _Timer:
    def start(self) -> _Timer:
        return self

    @staticmethod
    def reached() -> bool:
        return False

    def reset(self) -> None:
        pass


class _Device:
    def __init__(self) -> None:
        self.clicks = []
        self.screenshot_count = 0

    def click(self, button: Button) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Tactical(RewardTacticalClass):
    _popup_offset = (0, 0)
    config: SimpleNamespace
    device: _Device

    def __init__(self, *, add_new_student: bool = False) -> None:
        self.config = SimpleNamespace(
            AddNewStudent_Enable=add_new_student,
            Scheduler_ServerUpdate="server_update",
        )
        self.device = _Device()
        self.interval_timer = {}
        self.dock_select_index = 0
        self.appear_results = {}
        self.game_tips_results = []
        self.dock_selected_results = []
        self.interval_resets = []
        self.interval_clears = []
        self.tactical_finish = []

    @staticmethod
    def _next(results: list[bool]) -> bool:
        if results:
            return results.pop(0)
        return False

    def set_appear(self, button: Button, *, results: list[bool]) -> None:
        self.appear_results[button.name] = results

    @override
    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return self._next(self.appear_results.setdefault(button.name, []))

    @override
    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        del button
        return False

    @override
    def handle_rapid_training(self) -> bool:
        return False

    @override
    def _tactical_get_finish(self) -> list[datetime | str]:
        return []

    @override
    def ui_main_appear_then_click(
        self,
        page: Page,
        offset: MatchOffset | None = (30, 30),
        interval: float = 3,
    ) -> bool:
        del page, offset, interval
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

    @override
    def handle_urgent_commission(self) -> bool:
        return False

    @override
    def ui_page_main_popups(self, *_args: object, **_kwargs: object) -> bool:
        return False

    @override
    def _tactical_books_choose(self) -> bool:
        return False

    @override
    def handle_game_tips(self) -> bool:
        return self._next(self.game_tips_results)

    @override
    def dock_selected(self, *_args: object, **_kwargs: object) -> bool:
        return self._next(self.dock_selected_results)

    @override
    def select_suitable_ship(self) -> bool:
        return False

    @override
    def _tactical_skill_choose(self) -> bool:
        return False

    @override
    def interval_reset(
        self,
        button: Button | list[Button] | tuple[Button, ...] | None,
        interval: float = 0,
    ) -> None:
        self.interval_resets.append((button, interval))

    @override
    def interval_clear(
        self,
        button: Button | list[Button] | tuple[Button, ...] | None,
        interval: float = 0,
    ) -> None:
        self.interval_clears.append((button, interval))


@dataclass
class _FactionConfig:
    AddNewStudent_Favorite: bool = False


class _DockFilterProbe:
    def __init__(self) -> None:
        self.settings = {
            ("faction", "all"): None,
            ("faction", "eagle"): None,
            ("faction", "meta"): None,
            ("faction", "not_available"): None,
        }


class _TacticalFactionProbe(RewardTacticalClass):
    config: _FactionConfig
    dock_filter: _DockFilterProbe

    def __init__(self) -> None:
        self.config = _FactionConfig()
        self.dock_filter = _DockFilterProbe()
        self.selected_factions: list[str] = []

    def dock_favourite_set(self, *_args: object, **_kwargs: object) -> None:
        pass

    def dock_filter_set(
        self,
        options: DockFilterOptions | None = None,
        **settings: Unpack[DockFilterSettings],
    ) -> None:
        del options
        faction = settings["faction"]
        assert isinstance(faction, list)
        self.selected_factions = faction

    @override
    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        del button
        return True


def test_tactical_receive_delays_to_tomorrow_when_books_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tactical_module, "Timer", lambda *_args, **_kwargs: _Timer())
    monkeypatch.setattr(tactical_module, "get_server_next_update", lambda _server_update: "tomorrow")
    tactical = _Tactical()
    tactical.set_appear(BOOK_EMPTY_POPUP, results=[True])
    tactical.set_appear(REWARD_CHECK, results=[True])

    assert tactical.tactical_class_receive() is True

    assert tactical.device.clicks == [BOOK_EMPTY_POPUP]
    assert tactical.tactical_finish == ["tomorrow"]


def test_tactical_receive_reenters_when_ship_is_preselected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tactical_module, "Timer", lambda *_args, **_kwargs: _Timer())
    tactical = _Tactical()
    tactical.set_appear(tactical_module.DOCK_CHECK, results=[True])
    tactical.dock_selected_results = [True]
    tactical.game_tips_results = [False, True]

    assert tactical.tactical_class_receive() is True

    assert tactical.device.clicks == [BACK_ARROW]


def test_select_suitable_ship_excludes_unavailable_faction_slots() -> None:
    tactical = _TacticalFactionProbe()

    assert tactical.select_suitable_ship() is False
    assert tactical.selected_factions == ["eagle"]
