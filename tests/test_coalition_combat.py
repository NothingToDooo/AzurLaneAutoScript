from typing import TYPE_CHECKING, Literal, override
from unittest.mock import Mock

from module.coalition.combat import CoalitionCombat
from module.combat.auto_search_combat import AutoSearchCombat
from module.os_ash.assets import BATTLE_STATUS

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.device.control import ButtonTarget


class _AutoSearchDevice:
    def __init__(self, screenshot_interval_set: Mock) -> None:
        self._screenshot_interval_set = screenshot_interval_set

    def screenshot_interval_set(self) -> None:
        self._screenshot_interval_set()


class _AutoSearchEndProbe(AutoSearchCombat):
    device: _AutoSearchDevice

    def __init__(self, *, get_ship: bool = False, generic_end: bool = False) -> None:
        self.screenshot_interval_set = Mock()
        self.device = _AutoSearchDevice(self.screenshot_interval_set)
        self.custom_end_calls = 0
        self.get_ship = get_ship
        self.generic_end = generic_end

    @override
    def is_in_auto_search_menu(self) -> bool:
        return False

    @override
    def _handle_auto_search_menu_missing(self) -> bool:
        return False

    @override
    def is_combat_executing(self) -> Literal[False]:
        return False

    def handle_get_ship(self) -> bool:
        return self.get_ship

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del button, offset, interval, similarity, threshold
        return self.generic_end

    @override
    def is_auto_search_running(self) -> bool:
        return False

    def auto_search_combat_end(self) -> bool:
        self.custom_end_calls += 1
        return True

    def execute_end(self) -> tuple[bool, bool]:
        return self._handle_auto_search_combat_execute_end()


class _CoalitionDevice:
    def __init__(self, *, screenshot_error: AssertionError | None = None) -> None:
        self.screenshot_mock = Mock(side_effect=screenshot_error)
        self.click_mock = Mock()

    def screenshot(self) -> None:
        self.screenshot_mock()

    def click(self, button: ButtonTarget) -> None:
        self.click_mock(button)


class _CoalitionReEnterProbe(CoalitionCombat):
    device: _CoalitionDevice

    def __init__(
        self, *, loading: bool = False, executing: bool = False, screenshot_error: AssertionError | None = None
    ) -> None:
        self.device = _CoalitionDevice(screenshot_error=screenshot_error)
        self.is_combat_loading_mock = Mock(return_value=loading)
        self.is_combat_executing_mock = Mock(return_value=BATTLE_STATUS if executing else False)
        self.in_coalition_mock = Mock(return_value=False)
        self.appear_then_click_mock = Mock(return_value=False)
        self.handle_get_ship_mock = Mock(return_value=False)
        self.handle_battle_status_mock = Mock(return_value=False)

    @override
    def is_combat_loading(self) -> bool:
        return self.is_combat_loading_mock()

    @override
    def is_combat_executing(self) -> Button | Literal[False]:
        return self.is_combat_executing_mock()

    @override
    def in_coalition(self) -> bool:
        return self.in_coalition_mock()

    @override
    def appear_then_click(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        return self.appear_then_click_mock(button, offset, interval, similarity, threshold)

    @override
    def handle_get_ship(self) -> bool:
        return self.handle_get_ship_mock()

    @override
    def handle_battle_status(self) -> bool:
        return self.handle_battle_status_mock()


class _CoalitionEndProbe(CoalitionCombat):
    def __init__(self) -> None:
        self.appear_mock = Mock(return_value=True)

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        return self.appear_mock(button, offset=offset, interval=interval, similarity=similarity, threshold=threshold)


def test_coalition_re_enter_accepts_already_executing_state() -> None:
    combat = _CoalitionReEnterProbe(
        executing=True,
        screenshot_error=AssertionError("续战已经执行时不应再截图"),
    )

    combat.coalition_combat_re_enter()

    combat.device.screenshot_mock.assert_not_called()
    combat.in_coalition_mock.assert_not_called()
    combat.appear_then_click_mock.assert_not_called()
    combat.handle_get_ship_mock.assert_not_called()
    combat.handle_battle_status_mock.assert_not_called()


def test_coalition_re_enter_checks_loading_before_executing() -> None:
    combat = _CoalitionReEnterProbe(loading=True, executing=True)

    combat.coalition_combat_re_enter()

    combat.is_combat_loading_mock.assert_called_once_with()
    combat.is_combat_executing_mock.assert_not_called()
    combat.in_coalition_mock.assert_not_called()


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
    combat = _CoalitionEndProbe()

    assert combat.auto_search_combat_end() is True
    combat.appear_mock.assert_called_once_with(
        BATTLE_STATUS,
        offset=(80, 20),
        interval=0,
        similarity=0.85,
        threshold=10,
    )
