from types import SimpleNamespace

from module.tactical import tactical_class as tactical_module
from module.tactical.assets import BOOK_EMPTY_POPUP
from module.tactical.tactical_class import RewardTacticalClass
from module.ui.assets import BACK_ARROW, REWARD_CHECK


class _Timer:
    def start(self):
        return self

    def reached(self):
        return False

    def reset(self) -> None:
        pass


class _Device:
    def __init__(self) -> None:
        self.clicks = []
        self.screenshot_count = 0

    def click(self, button) -> None:
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
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def set_appear(self, button, *, results: list[bool]) -> None:
        self.appear_results[button.name] = results

    def appear(self, button, **_kwargs):
        return self._next(self.appear_results.setdefault(button.name, []))

    def appear_then_click(self, _button, **_kwargs):
        return False

    def handle_rapid_training(self):
        return False

    def _tactical_get_finish(self):
        return False

    def ui_main_appear_then_click(self, _page, **_kwargs):
        return False

    def handle_popup_confirm(self, _popup):
        return False

    def handle_urgent_commission(self):
        return False

    def ui_page_main_popups(self):
        return False

    def _tactical_books_choose(self):
        return False

    def handle_game_tips(self):
        return self._next(self.game_tips_results)

    def dock_selected(self):
        return self._next(self.dock_selected_results)

    def select_suitable_ship(self):
        return False

    def _tactical_skill_choose(self):
        return False

    def interval_reset(self, button, interval=0) -> None:
        self.interval_resets.append((button, interval))

    def interval_clear(self, button, interval=0) -> None:
        self.interval_clears.append((button, interval))


def test_tactical_receive_delays_to_tomorrow_when_books_empty(monkeypatch) -> None:
    monkeypatch.setattr(tactical_module, "Timer", lambda *_args, **_kwargs: _Timer())
    monkeypatch.setattr(tactical_module, "get_server_next_update", lambda _server_update: "tomorrow")
    tactical = _Tactical()
    tactical.set_appear(BOOK_EMPTY_POPUP, results=[True])
    tactical.set_appear(REWARD_CHECK, results=[True])

    assert tactical.tactical_class_receive() is True

    assert tactical.device.clicks == [BOOK_EMPTY_POPUP]
    assert tactical.tactical_finish == "tomorrow"


def test_tactical_receive_reenters_when_ship_is_preselected(monkeypatch) -> None:
    monkeypatch.setattr(tactical_module, "Timer", lambda *_args, **_kwargs: _Timer())
    tactical = _Tactical()
    tactical.set_appear(tactical_module.DOCK_CHECK, results=[True])
    tactical.dock_selected_results = [True]
    tactical.game_tips_results = [False, True]

    assert tactical.tactical_class_receive() is True

    assert tactical.device.clicks == [BACK_ARROW]
