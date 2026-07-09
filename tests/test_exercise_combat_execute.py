from module.combat.assets import BATTLE_PREPARATION, BATTLE_STATUS_S, GET_ITEMS_1
from module.exercise import combat as exercise_combat
from module.exercise.assets import CLICK_SAFE_AREA
from module.exercise.combat import ExerciseCombat
from module.ui.assets import EXERCISE_CHECK


class _Timer:
    def __init__(self) -> None:
        self.reset_count = 0

    def start(self):
        return self

    def reached(self):
        return False

    def reset(self):
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.image = "screen"
        self.clicks = []
        self.screenshot_count = 0
        self.stuck_clear_count = 0
        self.click_clear_count = 0

    def stuck_record_clear(self) -> None:
        self.stuck_clear_count += 1

    def click_record_clear(self) -> None:
        self.click_clear_count += 1

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def click(self, button) -> None:
        self.clicks.append(button)


class _ExerciseCombat(ExerciseCombat):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.exercise_results = []
        self.preparation_results = []
        self.executing_results = []
        self.battle_status_results = []
        self.get_items_results = []

    @staticmethod
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def appear(self, button, *_args: object, **_kwargs):
        if button == EXERCISE_CHECK:
            return self._next(self.exercise_results)
        if button == BATTLE_PREPARATION:
            return self._next(self.preparation_results)
        if button == BATTLE_STATUS_S:
            return self._next(self.battle_status_results)
        if button == GET_ITEMS_1:
            return self._next(self.get_items_results)
        return False

    def is_combat_executing(self):
        return self._next(self.executing_results)

    def appear_then_click(self, button, *_args: object, **_kwargs):
        _ = button
        return False

    def handle_combat_quit(self, *_args: object, **_kwargs: object):
        return False

    def handle_combat_quit_reconfirm(self, *_args: object, **_kwargs: object):
        return False

    def _at_low_hp(self, image: object, pause=None, **_kwargs: object):
        del image, pause
        return False

    def _show_hp(self, *_args: object, **_kwargs: object) -> None:
        pass

    def handle_popup_confirm(self, name="", offset=None, interval=2):
        _ = (name, offset, interval)
        return False

    def handle_urgent_commission(self):
        return False

    def handle_guild_popup_cancel(self):
        return False

    def handle_vote_popup(self):
        return False

    def handle_mission_popup_ack(self):
        return False

    def run_combat_execute(self):
        return self._combat_execute()


def test_exercise_battle_status_is_handled_after_leaving_combat_ui(monkeypatch) -> None:
    monkeypatch.setattr(exercise_combat, "Timer", lambda *_args, **_kwargs: _Timer())
    combat = _ExerciseCombat()
    pause_button = object()
    combat.exercise_results = [False, False, True]
    combat.executing_results = [pause_button, False]
    combat.battle_status_results = [True]

    assert combat.run_combat_execute() is True

    assert combat.device.clicks == [CLICK_SAFE_AREA]


def test_exercise_get_items_waits_for_battle_status(monkeypatch) -> None:
    monkeypatch.setattr(exercise_combat, "Timer", lambda *_args, **_kwargs: _Timer())
    combat = _ExerciseCombat()
    combat.exercise_results = [False, True]
    combat.executing_results = [False]
    combat.get_items_results = [True]

    assert combat.run_combat_execute() is True

    assert combat.device.clicks == []
