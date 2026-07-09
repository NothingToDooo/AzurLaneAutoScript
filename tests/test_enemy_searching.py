from module.handler import enemy_searching as enemy_searching_module
from module.handler.enemy_searching import EnemySearchingHandler


class _Timer:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.limit = 0
        self.reset_count = 0
        self.start_count = 0

    def start(self):
        self.start_count += 1
        return self

    def reached(self):
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self):
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.image = "screen"
        self.screenshot_count = 0
        self.sleep_calls = []

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def sleep(self, value) -> None:
        self.sleep_calls.append(value)


class _EnemySearching(EnemySearchingHandler):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.in_map_results = []
        self.event_animation_results = []
        self.in_stage_results = []
        self.combat_loading_results = []
        self.auto_search_exit_results = []
        self.vote_results = []
        self.story_results = []
        self.guild_results = []
        self.urgent_results = []
        self.enemy_appear_results = []
        self.ensure_no_story_count = 0
        self.color_initial_count = 0
        self.flashing_count = 0

    @staticmethod
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def is_in_map(self):
        return self._next(self.in_map_results)

    def is_event_animation(self):
        return self._next(self.event_animation_results)

    def handle_in_stage(self):
        return self._next(self.in_stage_results)

    def is_combat_loading(self):
        return self._next(self.combat_loading_results)

    def handle_auto_search_exit(self):
        return self._next(self.auto_search_exit_results)

    def handle_vote_popup(self):
        return self._next(self.vote_results)

    def handle_story_skip(self):
        return self._next(self.story_results)

    def ensure_no_story(self, *_args: object, **_kwargs: object):
        self.ensure_no_story_count += 1

    def handle_guild_popup_cancel(self):
        return self._next(self.guild_results)

    def handle_urgent_commission(self):
        return self._next(self.urgent_results)

    def enemy_searching_appear(self):
        return self._next(self.enemy_appear_results)

    def enemy_searching_color_initial(self):
        self.color_initial_count += 1

    def handle_enemy_flashing(self):
        self.flashing_count += 1


def test_enemy_searching_returns_false_outside_map() -> None:
    handler = _EnemySearching()
    handler.in_map_results = [False]

    assert handler.handle_in_map_with_enemy_searching() is False

    assert handler.device.screenshot_count == 0


def test_enemy_searching_waits_for_overlay_to_disappear(monkeypatch) -> None:
    handler = _EnemySearching()
    handler.in_map_results = [True, True, True]
    handler.enemy_appear_results = [True, False]
    monkeypatch.setattr(enemy_searching_module, "Timer", lambda *_args, **_kwargs: _Timer([False]))

    assert handler.handle_in_map_with_enemy_searching() is True

    assert handler.flashing_count == 1
    assert handler.color_initial_count == 0
    assert handler.device.sleep_calls == [0.3]
    assert handler.device.screenshot_count == 3


def test_enemy_searching_story_skip_keeps_fallthrough_to_timeout(monkeypatch) -> None:
    handler = _EnemySearching()
    handler.in_map_results = [True, True]
    handler.story_results = [True]
    monkeypatch.setattr(enemy_searching_module, "Timer", lambda *_args, **_kwargs: _Timer([True]))

    assert handler.handle_in_map_no_enemy_searching() is True

    assert handler.ensure_no_story_count == 1
    assert handler.device.screenshot_count == 1
