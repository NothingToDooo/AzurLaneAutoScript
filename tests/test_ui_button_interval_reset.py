from typing import TYPE_CHECKING

import pytest

from module.base.timer import Timer
from module.combat.assets import GET_SHIP
from module.os_handler.assets import EXCHANGE_CHECK
from module.raid import assets as raid_assets
from module.ui import assets as ui_assets
from module.ui.page import page_fleet, page_main
from module.ui.ui import UI
from module.ui_white import assets as ui_white_assets

if TYPE_CHECKING:
    from module.base.button import Button


class _FakeUI(UI):
    def __init__(self) -> None:
        self.reset_buttons = []
        self.interval_timer = {}

    def interval_reset(self, button: Button, *_args: object, **_kwargs: object) -> None:
        self.reset_buttons.append(button)


@pytest.mark.parametrize(
    ("button", "expected"),
    [
        (ui_assets.MEOWFFICER_GOTO_DORMMENU, [GET_SHIP]),
        (ui_assets.DORMMENU_GOTO_DORM, [GET_SHIP]),
        (ui_assets.DORMMENU_GOTO_MEOWFFICER, [GET_SHIP]),
        (ui_assets.SHOP_GOTO_SUPPLY_PACK, [EXCHANGE_CHECK]),
        (ui_assets.REWARD_GOTO_TACTICAL, [ui_white_assets.REWARD_GOTO_TACTICAL_WHITE]),
        (ui_white_assets.REWARD_GOTO_TACTICAL_WHITE, [ui_assets.REWARD_GOTO_TACTICAL]),
    ],
)
def test_ui_button_interval_reset_single_targets(button: Button, expected: list[Button]) -> None:
    ui = _FakeUI()

    UI.ui_button_interval_reset(ui, button)

    assert ui.reset_buttons == expected
    assert ui.interval_timer == {}


@pytest.mark.parametrize(
    ("button", "expected"),
    [
        (ui_assets.MAIN_GOTO_REWARD, [GET_SHIP, GET_SHIP]),
        (ui_assets.MAIN_GOTO_CAMPAIGN, [GET_SHIP, GET_SHIP, ui_assets.RAID_CHECK]),
        (ui_white_assets.MAIN_GOTO_REWARD_WHITE, [GET_SHIP]),
        (ui_white_assets.MAIN_GOTO_CAMPAIGN_WHITE, [GET_SHIP, ui_assets.RAID_CHECK]),
    ],
)
def test_ui_button_interval_reset_keeps_legacy_duplicate_resets(button: Button, expected: list[Button]) -> None:
    ui = _FakeUI()

    UI.ui_button_interval_reset(ui, button)

    assert ui.reset_buttons == expected


def test_ui_button_interval_reset_covers_page_main_links() -> None:
    ui = _FakeUI()
    button = page_main.links[page_fleet]

    UI.ui_button_interval_reset(ui, button)

    assert ui.reset_buttons == [GET_SHIP]


@pytest.mark.parametrize(
    "button",
    [
        raid_assets.RPG_GOTO_STAGE,
        raid_assets.RPG_GOTO_STORY,
        raid_assets.RPG_LEAVE_CITY,
    ],
)
def test_ui_button_interval_reset_replaces_get_ship_timer_for_rpg_buttons(button: Button) -> None:
    ui = _FakeUI()

    UI.ui_button_interval_reset(ui, button)

    timer = ui.interval_timer[GET_SHIP.name]
    assert isinstance(timer, Timer)
    assert timer.limit == 5
