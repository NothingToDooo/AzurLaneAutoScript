from typing import TYPE_CHECKING, cast

from module.base.button import Button
from module.base.utils import image_size, load_image
from module.combat import combat, combat_auto, submarine
from module.exercise import hp_daemon

if TYPE_CHECKING:
    import pytest


type _TestButton = _FakeButton | Button


class _FakeButton:
    def __init__(self, name: str, *, luma: bool = False, color: bool = False) -> None:
        self.name = name
        self.luma = luma
        self.color = color
        self.calls: list[tuple[str, object, tuple[int, int]]] = []

    def match_luma(self, image: object, *, offset: tuple[int, int]) -> bool:
        self.calls.append(("match_luma", image, offset))
        return self.luma

    def match_template_color(self, image: object, *, offset: tuple[int, int]) -> bool:
        self.calls.append(("match_template_color", image, offset))
        return self.color

    def __repr__(self) -> str:
        return self.name


class _FakeDevice:
    image: object = "image"

    def __init__(self) -> None:
        self.clicks: list[_TestButton] = []
        self.sleeps: list[tuple[float, float]] = []
        self.stuck_records: list[_TestButton] = []

    def click(self, button: _TestButton) -> None:
        self.clicks.append(button)

    def sleep(self, duration: tuple[float, float]) -> None:
        self.sleeps.append(duration)

    def stuck_record_add(self, button: _TestButton) -> None:
        self.stuck_records.append(button)


class _FakeTimer:
    def __init__(self, *, reached: bool) -> None:
        self._reached = reached
        self.reset_count = 0

    def reached(self) -> bool:
        return self._reached

    def reset(self) -> None:
        self.reset_count += 1


class _FakeCombatContext:
    battle_status_click_interval = 3

    def __init__(self, *, timer_reached: bool = True, appearing: tuple[_TestButton, ...] = ()) -> None:
        self.device = _FakeDevice()
        self.timer = _FakeTimer(reached=timer_reached)
        self.appearing = set(appearing)
        self.appear_calls: list[tuple[_TestButton, dict[str, float]]] = []
        self.interval_resets: list[_TestButton] = []
        self.timer_args: tuple[_TestButton, float] | None = None

    def get_interval_timer(self, button: _TestButton, *, interval: float) -> _FakeTimer:
        self.timer_args = (button, interval)
        return self.timer

    @staticmethod
    def is_combat_executing() -> bool:
        return False

    def appear(self, button: _TestButton, **kwargs: float) -> bool:
        self.appear_calls.append((button, kwargs))
        return button in self.appearing

    def interval_reset(self, button: _TestButton) -> None:
        self.interval_resets.append(button)


def _as_combat(context: _FakeCombatContext) -> combat.Combat:
    return cast("combat.Combat", context)


def _clear_combat_ui_offsets() -> None:
    for resource in vars(combat.combat_ui_assets).values():
        if isinstance(resource, Button):
            resource.clear_offset()


def test_is_combat_executing_uses_ordered_button_table(monkeypatch: pytest.MonkeyPatch) -> None:
    miss = _FakeButton("miss")
    hit = _FakeButton("hit", color=True)
    context = _FakeCombatContext()
    monkeypatch.setattr(combat, "_COMBAT_EXECUTING_BUTTONS", ((miss, "match_luma"), (hit, "match_template_color")))

    assert combat.Combat.is_combat_executing(_as_combat(context)) is hit
    assert context.device.stuck_records == [combat.combat_ui_assets.PAUSE]
    assert miss.calls == [("match_luma", "image", (10, 10))]
    assert hit.calls == [("match_template_color", "image", (10, 10))]


def test_nier_combat_resources_are_registered_and_match_source_images() -> None:
    pause = combat.combat_ui_assets.PAUSE_Nier
    quit_button = combat.combat_ui_assets.QUIT_Nier
    pause_file = pause.file
    quit_file = quit_button.file

    assert pause_file is not None
    assert quit_file is not None
    pause_image = load_image(pause_file)
    quit_image = load_image(quit_file)

    assert image_size(pause_image) == (1280, 720)
    assert image_size(quit_image) == (1280, 720)
    assert hp_daemon.NEW_HP_BAR_PAUSES[-1] is pause

    executing_context = _FakeCombatContext()
    executing_context.device.image = pause_image
    quit_context = _FakeCombatContext()
    quit_context.device.image = quit_image
    try:
        assert combat.Combat.is_combat_executing(_as_combat(executing_context)) is pause
        assert combat.Combat.handle_combat_quit(_as_combat(quit_context)) is True
        assert quit_context.device.clicks == [quit_button]
    finally:
        _clear_combat_ui_offsets()


def test_handle_combat_quit_clicks_first_matching_quit_button(monkeypatch: pytest.MonkeyPatch) -> None:
    miss = _FakeButton("miss")
    hit = _FakeButton("hit", luma=True)
    context = _FakeCombatContext()
    monkeypatch.setattr(combat, "_COMBAT_QUIT_BUTTONS", (miss, hit))

    assert combat.Combat.handle_combat_quit(_as_combat(context), offset=(3, 4), interval=9) is True
    assert context.timer_args == (combat.combat_ui_assets.QUIT, 9)
    assert context.device.clicks == [hit]
    assert context.timer.reset_count == 1


def test_handle_battle_status_clicks_first_visible_status(monkeypatch: pytest.MonkeyPatch) -> None:
    miss = _FakeButton("miss")
    hit = _FakeButton("hit")
    context = _FakeCombatContext(appearing=(hit,))
    monkeypatch.setattr(combat, "_BATTLE_STATUS_BUTTONS", ((miss, ""), (hit, "warn")))

    assert combat.Combat.handle_battle_status(_as_combat(context)) is True
    assert context.device.sleeps == [(0.25, 0.5)]
    assert context.device.clicks == [hit]
    assert context.appear_calls == [
        (miss, {"interval": 3}),
        (hit, {"interval": 3}),
    ]


def test_handle_get_items_resets_battle_status_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    miss = _FakeButton("miss")
    hit = _FakeButton("hit")
    context = _FakeCombatContext(appearing=(hit,))
    monkeypatch.setattr(combat, "_GET_ITEM_CHECKS", (miss, hit))

    assert combat.Combat.handle_get_items(_as_combat(context)) is True
    assert context.device.clicks == [combat.combat_assets.GET_ITEMS_1]
    assert context.interval_resets == [
        combat.combat_assets.BATTLE_STATUS_S,
        combat.combat_assets.BATTLE_STATUS_A,
        combat.combat_assets.BATTLE_STATUS_B,
    ]


class _CombatAutoProbe(combat_auto.CombatAuto):
    device: _FakeDevice
    auto_mode_click_timer: _FakeTimer
    auto_skip_timer: _FakeTimer
    auto_click_interval_timer: _FakeTimer


def _new_combat_auto(
    *, auto_timer: bool = False, skip_timer: bool = True, click_timer: bool = True, joystick: bool = True
) -> _CombatAutoProbe:
    handler = object.__new__(_CombatAutoProbe)
    handler.auto_mode_click_timer = _FakeTimer(reached=auto_timer)
    handler.auto_skip_timer = _FakeTimer(reached=skip_timer)
    handler.auto_click_interval_timer = _FakeTimer(reached=click_timer)
    handler.auto_mode_checked = False
    handler.auto_mode_switched = False
    handler.device = _FakeDevice()
    handler.combat_joystick_appear = lambda: joystick
    return handler


def test_handle_combat_auto_marks_checked_after_timeout() -> None:
    handler = _new_combat_auto(auto_timer=True)

    assert handler.handle_combat_auto("combat_auto") is False
    assert handler.auto_mode_checked is True
    assert handler.device.clicks == []


def test_handle_combat_auto_clicks_when_visible_state_matches_target() -> None:
    handler = _new_combat_auto()

    assert handler.handle_combat_auto("combat_auto") is True
    assert handler.device.clicks == [combat_auto.COMBAT_AUTO_SWITCH]
    assert handler.auto_click_interval_timer.reset_count == 1
    assert handler.auto_mode_switched is True


class _SubmarineCallProbe(submarine.SubmarineCall):
    device: _FakeDevice
    submarine_call_timer: _FakeTimer
    submarine_call_click_timer: _FakeTimer
    appear_then_click_calls: list[Button]


def _new_submarine_call(
    *,
    timer: bool = False,
    click_timer: bool = True,
    appearing: tuple[Button, ...] = (),
    ready_click: bool = True,
) -> _SubmarineCallProbe:
    handler = object.__new__(_SubmarineCallProbe)
    handler.submarine_call_flag = False
    handler.submarine_call_timer = _FakeTimer(reached=timer)
    handler.submarine_call_click_timer = _FakeTimer(reached=click_timer)
    handler.device = _FakeDevice()
    handler.appearing = set(appearing)
    handler.ready_click = ready_click
    handler.appear_calls = []
    handler.appear_then_click_calls = []

    def appear(button: Button) -> bool:
        handler.appear_calls.append(button)
        return button in handler.appearing

    def appear_then_click(button: Button) -> bool:
        handler.appear_then_click_calls.append(button)
        return handler.ready_click

    handler.appear = appear
    handler.appear_then_click = appear_then_click
    return handler


def test_handle_submarine_call_skip_mode_marks_call_finished() -> None:
    handler = _new_submarine_call()

    assert handler.handle_submarine_call("do_not_use") is False
    assert handler.submarine_call_flag is True
    assert handler.device.clicks == []


def test_handle_submarine_call_clicks_ready_icon_when_available() -> None:
    handler = _new_submarine_call(
        appearing=(
            submarine.SUBMARINE_AVAILABLE_CHECK_1,
            submarine.SUBMARINE_AVAILABLE_CHECK_2,
        )
    )

    assert handler.handle_submarine_call("every_combat") is True
    assert handler.appear_then_click_calls == [submarine.SUBMARINE_READY]
    assert handler.submarine_call_click_timer.reset_count == 1
