from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, override

from module.combat import assets as combat_assets
from module.os_combat import combat as os_combat

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.device.control import ButtonTarget
    from module.device.control_options import Duration


class _FakeDevice:
    image = "image"

    def __init__(self) -> None:
        self.clicks = []
        self.sleeps = []
        self.screenshots = 0
        self.intervals = []
        self.stuck_clears = 0
        self.click_clears = 0

    def click(self, button: ButtonTarget) -> None:
        self.clicks.append(button)

    def sleep(self, duration: Duration) -> None:
        self.sleeps.append(duration)

    def screenshot(self) -> None:
        self.screenshots += 1

    def screenshot_interval_set(self, interval: float | Literal["combat"] | None = None) -> None:
        self.intervals.append(interval)

    def stuck_record_clear(self) -> None:
        self.stuck_clears += 1

    def click_record_clear(self) -> None:
        self.click_clears += 1


class _ExpInfoContext(os_combat.Combat):
    battle_status_click_interval = 3
    device: _FakeDevice

    def __init__(self, *, appearing: tuple[Button, ...]) -> None:
        self.device = _FakeDevice()
        self.appearing = set(appearing)
        self.appear_then_click_calls = []
        self.appear_calls = []

    @override
    def is_combat_executing(self) -> Literal[False]:
        return False

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
        self.appear_then_click_calls.append(button)
        return button in self.appearing

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del offset, similarity, threshold
        self.appear_calls.append((button, {"interval": interval}))
        return button in self.appearing


class _AutoSearchCombatContext(os_combat.Combat):
    config: SimpleNamespace
    device: _FakeDevice

    def __init__(self) -> None:
        self.device = _FakeDevice()
        self.config = SimpleNamespace(Submarine_Fleet=False)
        self.map_option_calls = []
        self.submarine_modes = []
        self.submarine_resets = 0

    @override
    def handle_combat_automation_confirm(self) -> bool:
        return False

    @override
    def handle_os_auto_search_map_option(self, *, enable: bool | None = True) -> bool:
        self.map_option_calls.append(enable)
        return len(self.map_option_calls) == 1

    @override
    def is_combat_executing(self) -> Literal[False]:
        return False

    @override
    def is_in_map(self) -> bool:
        return len(self.map_option_calls) >= 2

    def submarine_call_reset(self) -> None:
        self.submarine_resets += 1

    @override
    def handle_submarine_call(self, submarine: str = "do_not_use") -> bool:
        self.submarine_modes.append(submarine)
        return False

    @override
    def handle_auto_search_battle_status(self) -> bool:
        return False

    @override
    def handle_auto_search_exp_info(self) -> bool:
        return False

    @override
    def handle_map_event(self) -> str:
        return ""


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
