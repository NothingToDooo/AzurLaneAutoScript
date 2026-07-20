from typing import TYPE_CHECKING, override

import numpy as np
import pytest

from module.handler import enemy_searching as enemy_searching_module
from module.handler.enemy_searching import EnemySearchingHandler
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER, CampaignMapObserver

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.base.type_alias import ImageArray
    from module.handler.map_transition_ui import (
        MapTransitionCombatRuntime,
        MapTransitionRuntime,
        MapTransitionUi,
    )


class _Timer:
    def __init__(self, results: list[bool] | None = None) -> None:
        self.results = list(results or [])
        self.limit = 0
        self.reset_count = 0
        self.start_count = 0

    def start(self) -> _Timer:
        self.start_count += 1
        return self

    def reached(self) -> bool:
        if not self.results:
            return False
        return self.results.pop(0)

    def reset(self) -> None:
        self.reset_count += 1


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.screenshot_count = 0
        self.sleep_calls = []

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def sleep(self, value: float) -> None:
        self.sleep_calls.append(value)


class _EnemySearching(EnemySearchingHandler):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.in_map_results = []
        self.stage_page_results = []
        self.combat_loading_results = []
        self.auto_search_exit_results = []
        self.vote_results = []
        self.story_results = []
        self.guild_results = []
        self.urgent_results = []
        self.enemy_appear_results = []
        self.ensure_no_story_count = 0
        self.color_initial_count = 0
        self.flashing_count = 0

    @staticmethod
    def _next(results: list[bool]) -> bool:
        if results:
            return results.pop(0)
        return False

    def is_in_map(self) -> bool:
        return self._next(self.in_map_results)

    @override
    def is_event_animation(self) -> bool:
        raise AssertionError

    @override
    def handle_in_stage(self) -> bool:
        raise AssertionError

    @override
    def is_stage_page_has_entrance(self) -> bool:
        raise AssertionError

    @override
    def is_in_stage_page(self) -> bool:
        return self._next(self.stage_page_results)

    def install_map_transition_ui(self, transition: MapTransitionUi) -> None:
        self._map_transition_ui = transition

    def is_combat_loading(self) -> bool:
        return self._next(self.combat_loading_results)

    def handle_auto_search_exit(self) -> bool:
        return self._next(self.auto_search_exit_results)

    def handle_vote_popup(self) -> bool:
        return self._next(self.vote_results)

    def handle_story_skip(self) -> bool:
        return self._next(self.story_results)

    def ensure_no_story(self, *_args: object, **_kwargs: object) -> None:
        self.ensure_no_story_count += 1

    def handle_guild_popup_cancel(self) -> bool:
        return self._next(self.guild_results)

    def handle_urgent_commission(self) -> bool:
        return self._next(self.urgent_results)

    def enemy_searching_appear(self) -> bool:
        return self._next(self.enemy_appear_results)

    def enemy_searching_color_initial(self) -> None:
        self.color_initial_count += 1

    def handle_enemy_flashing(self) -> None:
        self.flashing_count += 1


class _RecordingEnemySearchingObserver:
    def __init__(self, *, result: bool) -> None:
        self.result = result
        self.calls: list[tuple[ImageArray, float]] = []

    def appears(
        self,
        image: ImageArray,
        *,
        overlay_transparency_threshold: float,
    ) -> bool:
        self.calls.append((image, overlay_transparency_threshold))
        return self.result


class _CanonicalEnemySearching(EnemySearchingHandler):
    device: _Device

    def __init__(self, observer: _RecordingEnemySearchingObserver) -> None:
        self.device = _Device()
        self.in_map_results: list[bool] = []
        self._map_observer = CampaignMapObserver(
            combat=STANDARD_CAMPAIGN_MAP_OBSERVER.combat,
            scanner=STANDARD_CAMPAIGN_MAP_OBSERVER.scanner,
            enemy_searching=observer,
            viewport=STANDARD_CAMPAIGN_MAP_OBSERVER.viewport,
            fleet_locator=STANDARD_CAMPAIGN_MAP_OBSERVER.fleet_locator,
            preparation=STANDARD_CAMPAIGN_MAP_OBSERVER.preparation,
        )

    def is_in_map(self) -> bool:
        if self.in_map_results:
            return self.in_map_results.pop(0)
        return False


class _MapTransitionProbe:
    def __init__(
        self,
        *,
        stage_return_results: tuple[bool, ...] = (),
        stage_page_results: tuple[bool, ...] = (),
        animation_results: tuple[bool, ...] = (),
    ) -> None:
        self.stage_return_results = list(stage_return_results)
        self.stage_page_results = list(stage_page_results)
        self.animation_results = list(animation_results)
        self.stage_return_calls: list[MapTransitionRuntime] = []
        self.stage_page_calls: list[MapTransitionRuntime] = []
        self.animation_calls: list[MapTransitionRuntime] = []

    def handle_stage_return(self, runtime: MapTransitionRuntime) -> bool:
        self.stage_return_calls.append(runtime)
        return self.stage_return_results.pop(0)

    def stage_page_ready(self, runtime: MapTransitionRuntime) -> bool:
        self.stage_page_calls.append(runtime)
        return self.stage_page_results.pop(0)

    def event_animation_visible(self, runtime: MapTransitionRuntime) -> bool:
        self.animation_calls.append(runtime)
        return self.animation_results.pop(0)

    @staticmethod
    def combat_end_override(runtime: MapTransitionCombatRuntime) -> Callable[[], bool] | None:
        del runtime
        raise AssertionError


def test_enemy_searching_public_path_gates_before_forwarding_the_same_image_and_threshold() -> None:
    observer = _RecordingEnemySearchingObserver(result=True)
    handler = _CanonicalEnemySearching(observer)
    handler.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = 0.65

    handler.in_map_results = [False]
    assert not handler.enemy_searching_appear()
    assert observer.calls == []

    handler.in_map_results = [True]
    assert handler.enemy_searching_appear()
    assert len(observer.calls) == 1
    image, threshold = observer.calls[0]
    assert image is handler.device.image
    assert threshold == pytest.approx(0.65)


def test_enemy_searching_returns_false_outside_map() -> None:
    handler = _EnemySearching()
    handler.in_map_results = [False]

    assert handler.handle_in_map_with_enemy_searching() is False

    assert handler.device.screenshot_count == 0


def test_enemy_searching_waits_for_overlay_to_disappear(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _EnemySearching()
    handler.in_map_results = [True, True, True]
    handler.enemy_appear_results = [True, False]
    transition = _MapTransitionProbe(
        stage_return_results=(False, False),
        animation_results=(False, False),
    )
    handler.install_map_transition_ui(transition)
    monkeypatch.setattr(enemy_searching_module, "Timer", lambda *_args, **_kwargs: _Timer([False]))

    assert handler.handle_in_map_with_enemy_searching() is True

    assert handler.flashing_count == 1
    assert handler.color_initial_count == 0
    assert handler.device.sleep_calls == [0.3]
    assert handler.device.screenshot_count == 3


def test_enemy_searching_story_skip_keeps_fallthrough_to_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _EnemySearching()
    handler.in_map_results = [True, True]
    handler.story_results = [True]
    transition = _MapTransitionProbe(stage_return_results=(False,))
    handler.install_map_transition_ui(transition)
    monkeypatch.setattr(enemy_searching_module, "Timer", lambda *_args, **_kwargs: _Timer([True]))

    assert handler.handle_in_map_no_enemy_searching() is True

    assert handler.ensure_no_story_count == 1
    assert handler.device.screenshot_count == 1


def test_stage_page_readiness_uses_injected_map_transition() -> None:
    handler = _EnemySearching()
    handler.stage_page_results = [True]
    transition = _MapTransitionProbe(stage_page_results=(True,))
    handler.install_map_transition_ui(transition)

    assert handler.is_in_stage()
    assert transition.stage_page_calls == [handler]


def test_enemy_searching_animation_and_stage_return_use_injected_map_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _EnemySearching()
    handler.in_map_results = [True, True]
    transition = _MapTransitionProbe(
        stage_return_results=(True,),
        animation_results=(True, False),
    )
    handler.install_map_transition_ui(transition)
    monkeypatch.setattr(enemy_searching_module, "Timer", lambda *_args, **_kwargs: _Timer([True]))

    assert handler.handle_in_map_with_enemy_searching()
    assert transition.animation_calls == [handler, handler]
    assert transition.stage_return_calls == [handler]


def test_no_enemy_searching_stage_return_uses_injected_map_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _EnemySearching()
    handler.in_map_results = [True, True]
    transition = _MapTransitionProbe(stage_return_results=(True,))
    handler.install_map_transition_ui(transition)
    monkeypatch.setattr(enemy_searching_module, "Timer", lambda *_args, **_kwargs: _Timer([True]))

    assert handler.handle_in_map_no_enemy_searching()
    assert transition.stage_return_calls == [handler]
