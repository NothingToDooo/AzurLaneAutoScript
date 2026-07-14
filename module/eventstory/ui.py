from enum import StrEnum

from module.campaign.campaign_ui import CampaignUI
from module.eventstory.profile import EventStoryClientProfile, EventStoryModeStrategy


class EventStoryMode(StrEnum):
    COMBAT = "combat"
    STORY = "story"


class EventStoryUiCapability(CampaignUI):
    """将 EventStory 语义操作翻译为 profile 选定的客户端交互。"""

    _client_profile: EventStoryClientProfile

    def ensure_event_story_mode(self, mode: EventStoryMode) -> None:
        if not isinstance(mode, EventStoryMode):
            message = "mode must be an EventStoryMode"
            raise TypeError(message)

        if self._client_profile.mode_strategy is EventStoryModeStrategy.STORY_COMBAT_SWITCH:
            self.campaign_ensure_mode_20241219(mode.value)
            return

        message = f"unsupported event story mode strategy: {self._client_profile.mode_strategy.value}"
        raise ValueError(message)
