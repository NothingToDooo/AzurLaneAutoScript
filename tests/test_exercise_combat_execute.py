from typing import TYPE_CHECKING, Literal, override

import numpy as np

from module.combat.assets import BATTLE_PREPARATION, BATTLE_STATUS_S, GET_ITEMS_1
from module.exercise import combat as exercise_combat
from module.exercise.assets import CLICK_SAFE_AREA
from module.exercise.combat import ExerciseCombat
from module.ui.assets import EXERCISE_CHECK

if TYPE_CHECKING:
    import pytest

    from module.base.button import Button, MatchOffset
    from module.base.type_alias import ImageArray


class _Timer:
    def __init__(self) -> None:
        self.reset_count = 0

    def start(self) -> _Timer:
        return self

    @staticmethod
    def reached() -> bool:
        return False

    def reset(self) -> None:
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.clicks: list[Button] = []
        self.screenshot_count = 0
        self.stuck_clear_count = 0
        self.click_clear_count = 0

    def stuck_record_clear(self) -> None:
        self.stuck_clear_count += 1

    def click_record_clear(self) -> None:
        self.click_clear_count += 1

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def click(self, button: Button) -> None:
        self.clicks.append(button)


class _ExerciseCombat(ExerciseCombat):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.exercise_results: list[bool] = []
        self.preparation_results: list[bool] = []
        self.executing_results: list[Button | Literal[False]] = []
        self.battle_status_results: list[bool] = []
        self.get_items_results: list[bool] = []

    @staticmethod
    def _next[T](results: list[T], *, default: T) -> T:
        if results:
            return results.pop(0)
        return default

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
        if button == EXERCISE_CHECK:
            return self._next(self.exercise_results, default=False)
        if button == BATTLE_PREPARATION:
            return self._next(self.preparation_results, default=False)
        if button == BATTLE_STATUS_S:
            return self._next(self.battle_status_results, default=False)
        if button == GET_ITEMS_1:
            return self._next(self.get_items_results, default=False)
        return False

    def is_combat_executing(self) -> Button | Literal[False]:
        return self._next(self.executing_results, default=False)

    @override
    def appear_then_click(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        del button, offset, interval, similarity, threshold
        return False

    @override
    def handle_combat_quit(self, offset: MatchOffset = (20, 20), interval: float = 3) -> bool:
        del offset, interval
        return False

    @override
    def handle_combat_quit_reconfirm(self, interval: float = 2) -> bool:
        del interval
        return False

    @override
    def _at_low_hp(self, image: ImageArray, pause: Button | None = None) -> bool:
        del image, pause
        return False

    @override
    def _show_hp(self, low_hp_time: float = 0.0) -> None:
        del low_hp_time

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
    def handle_guild_popup_cancel(self) -> bool:
        return False

    @override
    def handle_vote_popup(self) -> bool:
        return False

    @override
    def handle_mission_popup_ack(self) -> bool:
        return False

    def run_combat_execute(self) -> bool:
        return self._combat_execute()


def test_exercise_battle_status_is_handled_after_leaving_combat_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exercise_combat, "Timer", lambda *_args, **_kwargs: _Timer())
    combat = _ExerciseCombat()
    pause_button = BATTLE_PREPARATION
    combat.exercise_results = [False, False, True]
    combat.executing_results = [pause_button, False]
    combat.battle_status_results = [True]

    assert combat.run_combat_execute() is True

    assert combat.device.clicks == [CLICK_SAFE_AREA]


def test_exercise_get_items_waits_for_battle_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exercise_combat, "Timer", lambda *_args, **_kwargs: _Timer())
    combat = _ExerciseCombat()
    combat.exercise_results = [False, True]
    combat.executing_results = [False]
    combat.get_items_results = [True]

    assert combat.run_combat_execute() is True

    assert combat.device.clicks == []
