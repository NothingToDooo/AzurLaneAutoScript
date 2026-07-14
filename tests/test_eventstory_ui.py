from typing import cast, override

import pytest

from module.eventstory.profile import (
    ALCHEMIST_EVENT_STORY_PROFILE,
    RPG_STATUS_EVENT_STORY_PROFILE,
    SP_EVENT_STORY_PROFILE,
    STANDARD_EVENT_STORY_PROFILE,
    EventStoryClientProfile,
    EventStoryModeStrategy,
)
from module.eventstory.ui import EventStoryMode, EventStoryUiCapability


class _EventStoryUiContext(EventStoryUiCapability):
    def __init__(self, profile: EventStoryClientProfile) -> None:
        self._client_profile = profile
        self.primitive_modes: list[str] = []

    @override
    def campaign_ensure_mode_20241219(self, mode: str = "combat") -> None:
        self.primitive_modes.append(mode)


@pytest.mark.parametrize(
    "profile",
    [
        STANDARD_EVENT_STORY_PROFILE,
        ALCHEMIST_EVENT_STORY_PROFILE,
        RPG_STATUS_EVENT_STORY_PROFILE,
        SP_EVENT_STORY_PROFILE,
    ],
)
def test_mode_capability_uses_profile_selected_story_combat_switch(
    profile: EventStoryClientProfile,
) -> None:
    context = _EventStoryUiContext(profile)

    context.ensure_event_story_mode(EventStoryMode.STORY)
    context.ensure_event_story_mode(EventStoryMode.COMBAT)

    assert profile.mode_strategy is EventStoryModeStrategy.STORY_COMBAT_SWITCH
    assert context.primitive_modes == ["story", "combat"]


def test_mode_capability_rejects_untyped_mode() -> None:
    context = _EventStoryUiContext(STANDARD_EVENT_STORY_PROFILE)

    with pytest.raises(TypeError, match="mode must be an EventStoryMode"):
        context.ensure_event_story_mode(cast("EventStoryMode", "story"))
