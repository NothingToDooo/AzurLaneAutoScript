from types import SimpleNamespace

from module.combat import assets as combat_assets
from module.os_combat import combat as os_combat


class _FakeDevice:
    image = "image"

    def __init__(self) -> None:
        self.clicks = []
        self.sleeps = []
        self.screenshots = 0
        self.intervals = []
        self.stuck_clears = 0
        self.click_clears = 0

    def click(self, button) -> None:
        self.clicks.append(button)

    def sleep(self, duration) -> None:
        self.sleeps.append(duration)

    def screenshot(self) -> None:
        self.screenshots += 1

    def screenshot_interval_set(self, interval=None) -> None:
        self.intervals.append(interval)

    def stuck_record_clear(self) -> None:
        self.stuck_clears += 1

    def click_record_clear(self) -> None:
        self.click_clears += 1


class _ExpInfoContext(os_combat.Combat):
    battle_status_click_interval = 3

    def __init__(self, *, appearing) -> None:
        self.device = _FakeDevice()
        self.appearing = set(appearing)
        self.appear_then_click_calls = []
        self.appear_calls = []

    def is_combat_executing(self):
        return False

    def appear_then_click(self, button):
        self.appear_then_click_calls.append(button)
        return button in self.appearing

    def appear(self, button, **kwargs):
        self.appear_calls.append((button, kwargs))
        return button in self.appearing


class _AutoSearchCombatContext(os_combat.Combat):
    def __init__(self) -> None:
        self.device = _FakeDevice()
        self.config = SimpleNamespace(Submarine_Fleet=False)
        self.map_option_calls = []
        self.submarine_modes = []
        self.submarine_resets = 0

    def handle_combat_automation_confirm(self):
        return False

    def handle_os_auto_search_map_option(self, enable=True):
        self.map_option_calls.append(enable)
        return len(self.map_option_calls) == 1

    def is_combat_executing(self):
        return False

    def is_in_map(self):
        return len(self.map_option_calls) >= 2

    def submarine_call_reset(self) -> None:
        self.submarine_resets += 1

    def handle_submarine_call(self, mode):
        self.submarine_modes.append(mode)
        return False

    def handle_auto_search_battle_status(self):
        return False

    def handle_auto_search_exp_info(self):
        return False

    def handle_map_event(self):
        return False


def test_handle_exp_info_uses_ordered_os_exp_buttons() -> None:
    context = _ExpInfoContext(appearing=(combat_assets.EXP_INFO_B,))

    assert context.handle_exp_info() is True
    assert context.appear_then_click_calls == [
        combat_assets.EXP_INFO_S,
        combat_assets.EXP_INFO_A,
        combat_assets.EXP_INFO_B,
    ]
    assert context.device.sleeps == [(0.25, 0.5)]


def test_handle_auto_search_battle_status_clicks_first_visible_status() -> None:
    context = _ExpInfoContext(appearing=(combat_assets.BATTLE_STATUS_D,))

    assert context.handle_auto_search_battle_status() is True
    assert context.appear_calls == [
        (combat_assets.BATTLE_STATUS_C, {"interval": 3}),
        (combat_assets.BATTLE_STATUS_D, {"interval": 3}),
    ]
    assert context.device.clicks == [combat_assets.BATTLE_STATUS_D]


def test_auto_search_combat_runs_wait_and_execute_phases() -> None:
    context = _AutoSearchCombatContext()

    assert context.auto_search_combat() is True
    assert context.device.intervals == ["combat", None]
    assert context.device.screenshots == 2
    assert context.map_option_calls == [True, True]
    assert context.submarine_modes == ["do_not_use"]
    assert context.submarine_resets == 1
