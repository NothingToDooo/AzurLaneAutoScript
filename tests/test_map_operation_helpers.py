from typing import TYPE_CHECKING, override

import pytest

from module.base.button import Button
from module.exception import CampaignEnd
from module.map import assets as map_assets
from module.map.map_operation import MapOperation

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.base.button import MatchOffset
    from module.handler.map_transition_ui import (
        MapTransitionCombatRuntime,
        MapTransitionRuntime,
        MapTransitionUi,
    )


type _Call = (
    tuple[str]
    | tuple[str, str]
    | tuple[str, bool, float]
    | tuple[str, str, MatchOffset | None]
    | tuple[str, str, MatchOffset, float]
)


class _Config:
    MAP_HAS_MODE_SWITCH = True
    MAP_HAS_CLEAR_PERCENTAGE = True
    MAP_IS_ONE_TIME_STAGE = False


class _Device:
    def __init__(self, calls: list[_Call]) -> None:
        self.calls = calls

    def click(self, button: Button) -> None:
        self.calls.append(("click", button.name))


class _Timer:
    def __init__(self, *, reached: bool = False) -> None:
        self.is_reached = reached
        self.reset_count = 0

    def reached(self) -> bool:
        return self.is_reached

    def reset(self) -> _Timer:
        self.reset_count += 1
        return self


class _MapOperation(MapOperation):
    config: _Config
    device: _Device
    map_clear_percentage_prev: float
    map_clear_percentage: float
    map_clear_percentage_timer: _Timer

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self.config = _Config()
        self.device = _Device(self.calls)
        self.normal_switch_visible = False
        self.hard_switch_visible = False
        self.hard_switch_active = False
        self.map_preparation_visible = False
        self.info_bar_visible = False
        self.map_clear_percentage_prev = -1
        self.map_clear_percentage = 0
        self.map_clear_percentage_timer = _Timer()

    @override
    def match_template_color(
        self,
        button: Button,
        offset: MatchOffset = (20, 20),
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 30,
    ) -> bool:
        del similarity, threshold
        self.calls.append(("match_template_color", button.name, offset, interval))
        return self.normal_switch_visible

    @override
    def _is_mod_switch_hard_appear(self, *, active: bool = True, interval: float = 0) -> bool:
        self.calls.append(("hard_switch_appear", active, interval))
        if active:
            return self.hard_switch_active
        return self.hard_switch_visible

    @override
    def interval_reset(
        self,
        button: Button | list[Button] | tuple[Button, ...] | None,
        interval: float = 3,
    ) -> None:
        del interval
        if button is None:
            return
        if isinstance(button, Button):
            self.calls.append(("interval_reset", button.name))
            return
        for item in button:
            self.calls.append(("interval_reset", item.name))

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del interval, similarity, threshold
        self.calls.append(("appear", button.name, offset))
        return self.map_preparation_visible

    @override
    def info_bar_count(self) -> int:
        self.calls.append(("info_bar_count",))
        return int(self.info_bar_visible)

    @override
    def get_map_clear_percentage(self) -> float:
        self.calls.append(("get_map_clear_percentage",))
        return self.map_clear_percentage


class _MapTransitionProbe:
    def __init__(self, *, stage_return_results: tuple[bool, ...]) -> None:
        self.stage_return_results = list(stage_return_results)
        self.stage_return_calls: list[MapTransitionRuntime] = []

    def handle_stage_return(self, runtime: MapTransitionRuntime) -> bool:
        self.stage_return_calls.append(runtime)
        return self.stage_return_results.pop(0)

    @staticmethod
    def stage_page_ready(runtime: MapTransitionRuntime) -> bool:
        del runtime
        raise AssertionError

    @staticmethod
    def event_animation_visible(runtime: MapTransitionRuntime) -> bool:
        del runtime
        raise AssertionError

    @staticmethod
    def combat_end_override(runtime: MapTransitionCombatRuntime) -> Callable[[], bool] | None:
        del runtime
        raise AssertionError


class _TransitionDevice:
    @staticmethod
    def screenshot() -> None:
        raise AssertionError

    @staticmethod
    def click(button: Button) -> None:
        del button
        raise AssertionError


class _MapOperationTransitionContext(MapOperation):
    device: _TransitionDevice

    def __init__(self, transition: MapTransitionUi) -> None:
        self.device = _TransitionDevice()
        self._map_transition_ui = transition

    @override
    def handle_story_skip(self) -> bool:
        del self
        return False

    @override
    def handle_in_stage(self) -> bool:
        raise AssertionError

    @override
    def get_fleet_show_index(self) -> int:
        del self
        return 1

    @override
    def get_fleet_current_index(self) -> int:
        del self
        return 1

    @override
    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        del self, name, offset, interval
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
        del self, button, offset, interval, similarity, threshold
        return False

    @override
    def handle_auto_search_exit(self) -> bool:
        del self
        return False

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del self, button, offset, interval, similarity, threshold
        return False


def test_handle_map_mode_switch_normal_clicks_when_hard_visible() -> None:
    operation = _MapOperation()
    operation.hard_switch_visible = True

    assert operation.handle_map_mode_switch("normal") is False

    assert ("click", map_assets.MAP_MODE_SWITCH_NORMAL.name) in operation.calls
    assert ("interval_reset", map_assets.MAP_MODE_SWITCH_HARD.name) in operation.calls


def test_handle_map_mode_switch_hard_is_satisfied_when_active() -> None:
    operation = _MapOperation()
    operation.hard_switch_active = True

    assert operation.handle_map_mode_switch("hard") is True

    assert operation.calls == [("hard_switch_appear", True, 0)]


def test_handle_map_preparation_resets_percentage_when_button_absent() -> None:
    operation = _MapOperation()
    operation.map_clear_percentage_prev = 0.5
    timer = _Timer()
    operation.map_clear_percentage_timer = timer

    assert operation.handle_map_preparation() is False

    assert operation.map_clear_percentage_prev == -1
    assert timer.reset_count == 1


def test_handle_map_preparation_returns_true_without_percentage() -> None:
    operation = _MapOperation()
    operation.map_preparation_visible = True
    operation.config.MAP_HAS_CLEAR_PERCENTAGE = False

    assert operation.handle_map_preparation() is True


def test_handle_map_preparation_waits_for_stable_percentage() -> None:
    operation = _MapOperation()
    operation.map_preparation_visible = True
    operation.map_clear_percentage_prev = 0.4
    operation.map_clear_percentage = 0.41
    operation.map_clear_percentage_timer = _Timer(reached=True)

    assert operation.handle_map_preparation() is True
    assert operation.map_clear_percentage_prev == 0.41


def test_handle_map_preparation_accepts_final_percentage_jump() -> None:
    operation = _MapOperation()
    operation.map_preparation_visible = True
    operation.map_clear_percentage_prev = 0.6
    operation.map_clear_percentage = 0.99

    assert operation.handle_map_preparation() is True


def test_fleet_set_uses_injected_map_transition_service() -> None:
    transition = _MapTransitionProbe(stage_return_results=(False,))
    operation = _MapOperationTransitionContext(transition)

    assert not operation.fleet_set(1)
    assert transition.stage_return_calls == [operation]


def test_withdraw_uses_injected_map_transition_service() -> None:
    transition = _MapTransitionProbe(stage_return_results=(True,))
    operation = _MapOperationTransitionContext(transition)

    with pytest.raises(CampaignEnd):
        operation.withdraw()

    assert transition.stage_return_calls == [operation]
