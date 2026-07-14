from typing import TYPE_CHECKING, Literal, override

import numpy as np
import pytest

from module.content.activity_profile import EventStoryDefinition, EventStoryProfileId
from module.content.manifest import load_default_event_manifests
from module.eventstory import assets as eventstory_assets
from module.eventstory.eventstory import EventStory, EventStoryState
from module.eventstory.profile import (
    ALCHEMIST_EVENT_STORY_PROFILE,
    EVENT_STORY_CLIENT_PROFILES,
    RPG_STATUS_EVENT_STORY_PROFILE,
    SP_EVENT_STORY_PROFILE,
    STANDARD_EVENT_STORY_PROFILE,
    EventStoryClientProfile,
)
from module.eventstory.ui import EventStoryMode
from module.ui.page import page_event, page_sp

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from module.base.button import Button
    from module.base.timer import Timer
    from module.base.type_alias import ImageArray
    from module.ui.page import Page


class _FakeDevice:
    def __init__(self) -> None:
        self.clicks = []
        self.screenshots = 0
        self.click_record_clears = 0
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)

    def click(self, button: Button) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshots += 1

    def click_record_clear(self) -> None:
        self.click_record_clears += 1


class _EventStoryStateContext(EventStory):
    def __init__(
        self,
        *,
        profile: EventStoryClientProfile = STANDARD_EVENT_STORY_PROFILE,
        matching: Iterable[Button] = (),
        appearing: Iterable[Button] = (),
        clicking: Iterable[Button] = (),
        alchemist: bool = False,
    ) -> None:
        self._client_profile = profile
        self.matching = set(matching)
        self.appearing = set(appearing)
        self.clicking = set(clicking)
        self.alchemist = alchemist

    def match_template_color(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return button in self.matching

    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return button in self.appearing

    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return button in self.clicking

    def _get_alchemist_entry_button(self) -> Button | None:
        return eventstory_assets.STORY_FIRST if self.alchemist else None


class _EventStoryLoopContext(_EventStoryStateContext):
    device: _FakeDevice

    def __init__(self) -> None:
        super().__init__(clicking=(eventstory_assets.STORY_FIRST,))
        self.device = _FakeDevice()
        self.combat_executing_results: list[Button | Literal[False]] = [False, eventstory_assets.STORY_FIRST]
        self.story_skip_clears = 0
        self.popup_clears = 0

    def is_combat_executing(self) -> Button | Literal[False]:
        return self.combat_executing_results.pop(0)

    @override
    def is_combat_loading(self) -> bool:
        return False

    @override
    def handle_story_skip(self) -> bool:
        return False

    @override
    def handle_get_items(self) -> bool:
        return False

    @override
    def _handle_alchemist_entry(self, *_args: object, **_kwargs: object) -> bool:
        return False

    @override
    def interval_clear(
        self,
        button: Button | list[Button] | tuple[Button, ...] | None,
        interval: float = 3,
    ) -> None:
        del button, interval

    def story_skip_interval_clear(self) -> None:
        self.story_skip_clears += 1

    def popup_interval_clear(self) -> None:
        self.popup_clears += 1


class _EventStoryNavigationContext(_EventStoryStateContext):
    device: _FakeDevice

    def __init__(self) -> None:
        super().__init__()
        self.device = _FakeDevice()
        self.landing_page_ensures = 0
        self.mode_ensures: list[EventStoryMode] = []
        self.states: list[EventStoryState] = ["unknown", "story"]

    @override
    def _ensure_landing_page(self) -> None:
        self.landing_page_ensures += 1

    @override
    def ensure_event_story_mode(self, mode: EventStoryMode) -> None:
        self.mode_ensures.append(mode)

    @override
    def loop(
        self,
        *,
        skip_first: bool = True,
        timeout: float | Timer | None = None,
    ) -> Iterator[ImageArray]:
        del skip_first, timeout
        yield self.device.image

    @override
    def get_event_story_state(self) -> EventStoryState:
        return self.states.pop(0)


def test_get_event_story_state_prefers_finished_state() -> None:
    context = _EventStoryStateContext(
        matching=(eventstory_assets.STORY_FINISHED,),
        clicking=(eventstory_assets.STORY_FIRST,),
    )

    assert context.get_event_story_state() == "finish"


def test_get_event_story_state_detects_regular_story_entry() -> None:
    context = _EventStoryStateContext(clicking=(eventstory_assets.STORY_MIDDLE,))

    assert context.get_event_story_state() == "story"


def test_get_event_story_state_detects_alchemist_story_entry() -> None:
    context = _EventStoryStateContext(profile=ALCHEMIST_EVENT_STORY_PROFILE, alchemist=True)

    assert context.get_event_story_state() == "story_alchemist"


def test_event_story_clears_intervals_after_clicking_story_entry() -> None:
    context = _EventStoryLoopContext()

    assert context.event_story() == "battle"
    assert context.story_skip_clears == 1
    assert context.popup_clears == 1
    assert context.device.click_record_clears == 1
    assert context.device.screenshots == 1


def test_event_story_navigation_uses_only_semantic_mode_capability() -> None:
    context = _EventStoryNavigationContext()

    assert context.ui_goto_event_story() == "story"
    assert context.landing_page_ensures == 1
    assert context.mode_ensures == [EventStoryMode.STORY, EventStoryMode.COMBAT, EventStoryMode.STORY]


class _ProfileBehaviorContext(_EventStoryStateContext):
    device: _FakeDevice

    def __init__(self, profile: EventStoryClientProfile) -> None:
        super().__init__(profile=profile)
        self.device = _FakeDevice()
        self.landing_pages: list[Page] = []
        self.alchemist_entry_calls = 0
        self.alchemist_probe_calls = 0
        self.rpg_status_probe_calls = 0

    @override
    def ui_ensure(self, destination: Page, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.landing_pages.append(destination)
        return True

    @override
    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        if button is eventstory_assets.POPUP_RPG_STATUS:
            self.rpg_status_probe_calls += 1
            self.device.click(button)
            return True
        return False

    @override
    def _handle_alchemist_entry(self, interval: float = 2) -> bool:
        del interval
        self.alchemist_entry_calls += 1
        return True

    @override
    def _get_alchemist_entry_button(self) -> Button | None:
        self.alchemist_probe_calls += 1
        return eventstory_assets.STORY_FIRST

    def exercise_landing_page(self) -> None:
        self._ensure_landing_page()

    def exercise_entry_handler(self) -> bool:
        return self._handle_event_story_entry()

    def exercise_popup_handler(self) -> bool:
        return self._handle_profile_popup()


def test_builtin_event_story_profiles_cover_every_available_manifest_profile() -> None:
    configured_profile_ids = {
        activity.profile_id
        for pack in load_default_event_manifests()
        if isinstance((activity := pack.activity), EventStoryDefinition) and activity.profile_id is not None
    }

    assert configured_profile_ids == EVENT_STORY_CLIENT_PROFILES.profile_ids
    assert configured_profile_ids == {
        EventStoryProfileId("standard"),
        EventStoryProfileId("alchemist"),
        EventStoryProfileId("rpg_status"),
        EventStoryProfileId("sp"),
    }


@pytest.mark.parametrize(
    ("profile", "landing_page", "state", "handled_features"),
    [
        (STANDARD_EVENT_STORY_PROFILE, page_event, "unknown", frozenset()),
        (ALCHEMIST_EVENT_STORY_PROFILE, page_event, "story_alchemist", frozenset({"entry"})),
        (RPG_STATUS_EVENT_STORY_PROFILE, page_event, "unknown", frozenset({"popup"})),
        (SP_EVENT_STORY_PROFILE, page_sp, "unknown", frozenset()),
    ],
)
def test_event_story_profile_selects_only_its_declared_client_behavior(
    profile: EventStoryClientProfile,
    landing_page: Page,
    state: str,
    handled_features: frozenset[str],
) -> None:
    context = _ProfileBehaviorContext(profile)

    context.exercise_landing_page()
    assert context.get_event_story_state() == state
    assert context.exercise_entry_handler() is ("entry" in handled_features)
    assert context.exercise_popup_handler() is ("popup" in handled_features)

    assert context.landing_pages == [landing_page]
    assert context.alchemist_probe_calls == (1 if profile is ALCHEMIST_EVENT_STORY_PROFILE else 0)
    assert context.alchemist_entry_calls == (1 if profile is ALCHEMIST_EVENT_STORY_PROFILE else 0)
    assert context.rpg_status_probe_calls == (1 if profile is RPG_STATUS_EVENT_STORY_PROFILE else 0)


def test_standard_event_story_never_probes_or_clicks_special_client_controls() -> None:
    context = _ProfileBehaviorContext(STANDARD_EVENT_STORY_PROFILE)

    assert context.get_event_story_state() == "unknown"
    assert context.exercise_entry_handler() is False
    assert context.exercise_popup_handler() is False
    assert context.alchemist_probe_calls == 0
    assert context.alchemist_entry_calls == 0
    assert context.rpg_status_probe_calls == 0
    assert context.device.clicks == []
