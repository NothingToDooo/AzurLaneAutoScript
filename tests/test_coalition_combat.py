from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from module.coalition.combat import CoalitionCombat
from module.combat.auto_search_combat import AutoSearchCombat
from module.os_ash.assets import BATTLE_STATUS


class _AutoSearchEndProbe(AutoSearchCombat):
    def __init__(self, *, get_ship: bool = False, generic_end: bool = False) -> None:
        self.screenshot_interval_set = Mock()
        cast("Any", self).device = SimpleNamespace(screenshot_interval_set=self.screenshot_interval_set)
        self.custom_end_calls = 0
        self.get_ship = get_ship
        self.generic_end = generic_end

    def is_in_auto_search_menu(self) -> bool:
        return False

    def _handle_auto_search_menu_missing(self) -> bool:
        return False

    def is_combat_executing(self) -> bool:
        return False

    def handle_get_ship(self) -> bool:
        return self.get_ship

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10) -> bool:
        _ = (button, offset, interval, similarity, threshold)
        return self.generic_end

    def is_auto_search_running(self) -> bool:
        return False

    def auto_search_combat_end(self) -> bool:
        self.custom_end_calls += 1
        return True

    def execute_end(self) -> tuple[bool, bool]:
        return self._handle_auto_search_combat_execute_end()


def test_coalition_re_enter_accepts_already_executing_state() -> None:
    combat = cast("Any", object.__new__(CoalitionCombat))
    screenshot = Mock(side_effect=AssertionError("续战已经执行时不应再截图"))
    combat.device = SimpleNamespace(screenshot=screenshot, click=Mock())
    combat.is_combat_loading = Mock(return_value=False)
    combat.is_combat_executing = Mock(return_value=True)
    combat.in_coalition = Mock(return_value=False)
    combat.appear_then_click = Mock(return_value=False)
    combat.handle_get_ship = Mock(return_value=False)
    combat.handle_battle_status = Mock(return_value=False)

    combat.coalition_combat_re_enter()

    screenshot.assert_not_called()
    combat.in_coalition.assert_not_called()
    combat.appear_then_click.assert_not_called()
    combat.handle_get_ship.assert_not_called()
    combat.handle_battle_status.assert_not_called()


def test_coalition_re_enter_checks_loading_before_executing() -> None:
    combat = cast("Any", object.__new__(CoalitionCombat))
    combat.device = SimpleNamespace(screenshot=Mock(), click=Mock())
    combat.is_combat_loading = Mock(return_value=True)
    combat.is_combat_executing = Mock(return_value=True)
    combat.in_coalition = Mock(return_value=False)

    combat.coalition_combat_re_enter()

    combat.is_combat_loading.assert_called_once_with()
    combat.is_combat_executing.assert_not_called()
    combat.in_coalition.assert_not_called()


def test_auto_search_custom_end_defaults_to_false() -> None:
    combat = object.__new__(AutoSearchCombat)

    assert combat.auto_search_combat_end() is False


def test_auto_search_execute_end_uses_custom_hook() -> None:
    combat = _AutoSearchEndProbe()

    assert combat.execute_end() == (True, True)
    assert combat.custom_end_calls == 1
    combat.screenshot_interval_set.assert_not_called()


def test_auto_search_execute_end_handles_get_ship_before_custom_hook() -> None:
    combat = _AutoSearchEndProbe(get_ship=True)

    assert combat.execute_end() == (True, False)
    assert combat.custom_end_calls == 0
    combat.screenshot_interval_set.assert_not_called()


def test_auto_search_execute_end_handles_normal_end_before_custom_hook() -> None:
    combat = _AutoSearchEndProbe(generic_end=True)

    assert combat.execute_end() == (True, True)
    assert combat.custom_end_calls == 0
    combat.screenshot_interval_set.assert_called_once_with()


def test_coalition_battle_status_is_custom_auto_search_end() -> None:
    combat = cast("Any", object.__new__(CoalitionCombat))
    combat.appear = Mock(return_value=True)

    assert combat.auto_search_combat_end() is True
    combat.appear.assert_called_once_with(BATTLE_STATUS, offset=(80, 20))
