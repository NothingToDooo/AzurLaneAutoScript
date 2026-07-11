from typing import TYPE_CHECKING, override

from module.combat.assets import GET_SHIP
from module.handler.assets import BATTLE_PASS_NEW_SEASON
from module.ui import assets as ui_assets
from module.ui.ui import UI

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.base.button import Button, MatchOffset


class _FakeDevice:
    def __init__(self) -> None:
        self.clicked = []

    def click(self, button: Button) -> None:
        self.clicked.append(button)


class _FakeUI(UI):
    device: _FakeDevice

    def __init__(
        self,
        *,
        appear_buttons: Iterable[Button] = (),
        appear_then_click_buttons: Iterable[Button] = (),
        guild_popup: bool = False,
    ) -> None:
        self.device = _FakeDevice()
        self.appear_buttons = list(appear_buttons)
        self.appear_then_click_buttons = list(appear_then_click_buttons)
        self.guild_popup = guild_popup
        self.appear_calls = []
        self.appear_then_click_calls = []

    @staticmethod
    def _has_button(buttons: list[Button], button: Button) -> bool:
        return any(button == item for item in buttons)

    def handle_guild_popup_cancel(self) -> bool:
        return self.guild_popup

    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        self.appear_then_click_calls.append(button)
        return self._has_button(self.appear_then_click_buttons, button)

    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        self.appear_calls.append(button)
        return self._has_button(self.appear_buttons, button)

    @override
    def handle_popup_single(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del name, offset, interval
        return False

    @override
    def handle_popup_single_white(self, *_args: object, **_kwargs: object) -> bool:
        return False


def test_ui_page_main_popups_guild_popup_short_circuits() -> None:
    ui = _FakeUI(guild_popup=True, appear_then_click_buttons=[GET_SHIP])

    assert ui.ui_page_main_popups()
    assert ui.appear_then_click_calls == []


def test_ui_page_main_popups_can_skip_get_ship() -> None:
    ui = _FakeUI(appear_then_click_buttons=[GET_SHIP])

    assert not ui.ui_page_main_popups(get_ship=False)
    assert GET_SHIP not in ui.appear_then_click_calls


def test_ui_page_main_popups_routes_event_list_back_to_main() -> None:
    ui = _FakeUI(appear_buttons=[ui_assets.EVENT_LIST_CHECK], appear_then_click_buttons=[ui_assets.GOTO_MAIN])

    assert ui.ui_page_main_popups()
    assert ui.appear_calls == [ui_assets.EVENT_LIST_CHECK]
    assert ui.appear_then_click_calls[-1] == ui_assets.GOTO_MAIN


def test_ui_page_main_popups_closes_new_battle_pass_season() -> None:
    ui = _FakeUI(appear_buttons=[BATTLE_PASS_NEW_SEASON])

    assert ui.ui_page_main_popups()
    assert ui.device.clicked == [ui_assets.BACK_ARROW]


def test_ui_page_main_popups_falls_back_to_back_arrow_from_player_page() -> None:
    ui = _FakeUI(appear_buttons=[ui_assets.PLAYER_CHECK], appear_then_click_buttons=[ui_assets.BACK_ARROW])

    assert ui.ui_page_main_popups()
    assert ui.appear_then_click_calls[-2:] == [ui_assets.GOTO_MAIN, ui_assets.BACK_ARROW]
