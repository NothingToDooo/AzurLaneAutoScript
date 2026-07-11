from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypedDict, Unpack

from module.combat.assets import GET_SHIP
from module.handler.assets import GAME_TIPS
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION_CANCEL, WITHDRAW
from module.meowfficer.assets import MEOWFFICER_BUY
from module.ui import assets as ui_assets
from module.ui.ui import UI
from module.ui_white import assets as ui_white_assets

if TYPE_CHECKING:
    from module.base.button import Button


class _FakeDevice:
    def __init__(self) -> None:
        self.clicked = []
        self.sleep_calls = []
        self.screenshot_count = 0

    def click(self, button: Button) -> None:
        self.clicked.append(button)

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)

    def screenshot(self) -> None:
        self.screenshot_count += 1


@dataclass(frozen=True, slots=True)
class _FakeUIOptions:
    appear_buttons: tuple[Button, ...] = ()
    appear_then_click_buttons: tuple[Button, ...] = ()
    os_popups: bool = False
    popup_confirm: bool = False
    urgent_commission: bool = False
    main_popups: bool = False
    story_skip: bool = False
    idle_page: bool = False


class _FakeUISettings(TypedDict, total=False):
    appear_buttons: tuple[Button, ...]
    appear_then_click_buttons: tuple[Button, ...]
    os_popups: bool
    popup_confirm: bool
    urgent_commission: bool
    main_popups: bool
    story_skip: bool
    idle_page: bool


def _fake_ui_options(
    options: _FakeUIOptions | None = None,
    settings: _FakeUISettings | None = None,
) -> _FakeUIOptions:
    options = _FakeUIOptions() if options is None else options
    if settings:
        options = replace(options, **settings)
    return options


class _FakeUI(UI):
    device: _FakeDevice

    def __init__(
        self,
        options: _FakeUIOptions | None = None,
        **settings: Unpack[_FakeUISettings],
    ) -> None:
        options = _fake_ui_options(options, settings)
        self.device = _FakeDevice()
        self.appear_buttons = list(options.appear_buttons)
        self.appear_then_click_buttons = list(options.appear_then_click_buttons)
        self.os_popups = options.os_popups
        self.popup_confirm = options.popup_confirm
        self.urgent_commission = options.urgent_commission
        self.main_popups = options.main_popups
        self.story_skip_result = options.story_skip
        self.idle_page = options.idle_page
        self.main_popup_get_ship_values = []
        self.popup_confirm_names = []
        self.reset_buttons = []

    @staticmethod
    def _has_button(buttons: list[Button], button: Button) -> bool:
        return any(button == item for item in buttons)

    def ui_page_os_popups(self) -> bool:
        return self.os_popups

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.popup_confirm_names.append(name)
        return self.popup_confirm

    def handle_urgent_commission(self) -> bool:
        return self.urgent_commission

    def ui_page_main_popups(self, *, get_ship: bool = True) -> bool:
        self.main_popup_get_ship_values.append(get_ship)
        return self.main_popups

    def handle_story_skip(self) -> bool:
        return self.story_skip_result

    def handle_idle_page(self) -> bool:
        return self.idle_page

    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return self._has_button(self.appear_buttons, button)

    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return self._has_button(self.appear_then_click_buttons, button)

    def interval_reset(self, button: Button, *_args: object, **_kwargs: object) -> None:
        self.reset_buttons.append(button)


def test_ui_additional_keeps_os_popups_before_confirm_popups() -> None:
    ui = _FakeUI(os_popups=True, popup_confirm=True)

    assert ui.ui_additional()
    assert ui.popup_confirm_names == []


def test_ui_additional_forwards_get_ship_to_main_popups() -> None:
    ui = _FakeUI(main_popups=True)

    assert ui.ui_additional(get_ship=False)
    assert ui.main_popup_get_ship_values == [False]


def test_ui_additional_closes_game_tips_from_main() -> None:
    ui = _FakeUI(appear_buttons=[GAME_TIPS])

    assert ui.ui_additional()
    assert ui.device.clicked == [ui_assets.GOTO_MAIN]


def test_ui_additional_closes_meowfficer_buy_and_resets_get_ship() -> None:
    ui = _FakeUI(appear_buttons=[MEOWFFICER_BUY])

    assert ui.ui_additional()
    assert ui.device.clicked == [ui_assets.BACK_ARROW]
    assert ui.reset_buttons == [GET_SHIP]


def test_ui_additional_cancels_campaign_preparation() -> None:
    ui = _FakeUI(appear_buttons=[FLEET_PREPARATION])

    assert ui.ui_additional()
    assert ui.device.clicked == [MAP_PREPARATION_CANCEL]


def test_ui_additional_waits_before_confirming_withdraw() -> None:
    ui = _FakeUI(appear_buttons=[WITHDRAW], appear_then_click_buttons=[WITHDRAW])

    assert ui.ui_additional()
    assert ui.device.sleep_calls == [2]
    assert ui.device.screenshot_count == 1
    assert ui.reset_buttons == [WITHDRAW]


def test_ui_additional_switches_white_main_tab_from_memories() -> None:
    ui = _FakeUI(appear_buttons=[ui_white_assets.MAIN_GOTO_MEMORIES_WHITE])

    assert ui.ui_additional()
    assert ui.device.clicked == [ui_white_assets.MAIN_TAB_SWITCH_WHITE]
