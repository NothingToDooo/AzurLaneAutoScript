from module.combat.assets import GET_SHIP
from module.handler.assets import GAME_TIPS
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION_CANCEL, WITHDRAW
from module.meowfficer.assets import MEOWFFICER_BUY
from module.ui import assets as ui_assets
from module.ui.ui import UI
from module.ui_white import assets as ui_white_assets


class _FakeDevice:
    def __init__(self) -> None:
        self.clicked = []
        self.sleep_calls = []
        self.screenshot_count = 0

    def click(self, button) -> None:
        self.clicked.append(button)

    def sleep(self, seconds) -> None:
        self.sleep_calls.append(seconds)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeUI(UI):
    def __init__(
        self,
        *,
        appear_buttons=(),
        appear_then_click_buttons=(),
        os_popups=False,
        popup_confirm=False,
        urgent_commission=False,
        main_popups=False,
        story_skip=False,
        idle_page=False,
    ) -> None:
        self.device = _FakeDevice()
        self.appear_buttons = list(appear_buttons)
        self.appear_then_click_buttons = list(appear_then_click_buttons)
        self.os_popups = os_popups
        self.popup_confirm = popup_confirm
        self.urgent_commission = urgent_commission
        self.main_popups = main_popups
        self.story_skip = story_skip
        self.idle_page = idle_page
        self.main_popup_get_ship_values = []
        self.popup_confirm_names = []
        self.reset_buttons = []

    def _has_button(self, buttons, button) -> bool:
        return any(button == item for item in buttons)

    def ui_page_os_popups(self) -> bool:
        return self.os_popups

    def handle_popup_confirm(self, name) -> bool:
        self.popup_confirm_names.append(name)
        return self.popup_confirm

    def handle_urgent_commission(self) -> bool:
        return self.urgent_commission

    def ui_page_main_popups(self, get_ship=True) -> bool:
        self.main_popup_get_ship_values.append(get_ship)
        return self.main_popups

    def handle_story_skip(self) -> bool:
        return self.story_skip

    def handle_idle_page(self) -> bool:
        return self.idle_page

    def appear(self, button, **_kwargs) -> bool:
        return self._has_button(self.appear_buttons, button)

    def appear_then_click(self, button, **_kwargs) -> bool:
        return self._has_button(self.appear_then_click_buttons, button)

    def interval_reset(self, button) -> None:
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
