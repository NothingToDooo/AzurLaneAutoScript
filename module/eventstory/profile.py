from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from module.content.activity_profile import EventStoryProfileId


class EventStoryLandingPage(StrEnum):
    EVENT = "event"
    SP = "sp"


class EventStoryModeStrategy(StrEnum):
    STORY_COMBAT_SWITCH = "story_combat_switch"


class EventStorySpecialEntryProbe(StrEnum):
    NONE = "none"
    ALCHEMIST = "alchemist"


class EventStoryPopupHandler(StrEnum):
    NONE = "none"
    RPG_STATUS = "rpg_status"


@dataclass(frozen=True, slots=True)
class EventStoryClientProfile:
    """活动剧情的客户端交互变体。

    这些选项只描述 EventStory 已知的四个交互切面，不承载活动日期、
    调度策略或任意可编程行为。
    """

    profile_id: EventStoryProfileId
    landing_page: EventStoryLandingPage
    mode_strategy: EventStoryModeStrategy
    special_entry_probe: EventStorySpecialEntryProbe
    popup_handler: EventStoryPopupHandler

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, EventStoryProfileId):
            message = "profile_id must be an EventStoryProfileId"
            raise TypeError(message)
        if not isinstance(self.landing_page, EventStoryLandingPage):
            message = "landing_page must be an EventStoryLandingPage"
            raise TypeError(message)
        if not isinstance(self.mode_strategy, EventStoryModeStrategy):
            message = "mode_strategy must be an EventStoryModeStrategy"
            raise TypeError(message)
        if not isinstance(self.special_entry_probe, EventStorySpecialEntryProbe):
            message = "special_entry_probe must be an EventStorySpecialEntryProbe"
            raise TypeError(message)
        if not isinstance(self.popup_handler, EventStoryPopupHandler):
            message = "popup_handler must be an EventStoryPopupHandler"
            raise TypeError(message)


class UnknownEventStoryProfileError(LookupError):
    pass


class EventStoryClientProfileRegistry:
    """将 manifest 中的 profile id 解析为不可变客户端 profile。"""

    __slots__ = ("_profiles",)

    def __init__(self, profiles: Iterable[EventStoryClientProfile]) -> None:
        if not isinstance(profiles, Iterable):
            message = "profiles must be iterable"
            raise TypeError(message)
        indexed: dict[EventStoryProfileId, EventStoryClientProfile] = {}
        for profile in profiles:
            if not isinstance(profile, EventStoryClientProfile):
                message = "profiles must contain EventStoryClientProfile values"
                raise TypeError(message)
            if profile.profile_id in indexed:
                message = f"duplicate event story profile: {profile.profile_id.value}"
                raise ValueError(message)
            indexed[profile.profile_id] = profile
        self._profiles = MappingProxyType(indexed)

    @property
    def profile_ids(self) -> frozenset[EventStoryProfileId]:
        return frozenset(self._profiles)

    def resolve(self, profile_id: EventStoryProfileId) -> EventStoryClientProfile:
        if not isinstance(profile_id, EventStoryProfileId):
            message = "profile_id must be an EventStoryProfileId"
            raise TypeError(message)
        try:
            return self._profiles[profile_id]
        except KeyError:
            message = f"unknown event story profile: {profile_id.value}"
            raise UnknownEventStoryProfileError(message) from None


STANDARD_EVENT_STORY_PROFILE = EventStoryClientProfile(
    profile_id=EventStoryProfileId("standard"),
    landing_page=EventStoryLandingPage.EVENT,
    mode_strategy=EventStoryModeStrategy.STORY_COMBAT_SWITCH,
    special_entry_probe=EventStorySpecialEntryProbe.NONE,
    popup_handler=EventStoryPopupHandler.NONE,
)
ALCHEMIST_EVENT_STORY_PROFILE = EventStoryClientProfile(
    profile_id=EventStoryProfileId("alchemist"),
    landing_page=EventStoryLandingPage.EVENT,
    mode_strategy=EventStoryModeStrategy.STORY_COMBAT_SWITCH,
    special_entry_probe=EventStorySpecialEntryProbe.ALCHEMIST,
    popup_handler=EventStoryPopupHandler.NONE,
)
RPG_STATUS_EVENT_STORY_PROFILE = EventStoryClientProfile(
    profile_id=EventStoryProfileId("rpg_status"),
    landing_page=EventStoryLandingPage.EVENT,
    mode_strategy=EventStoryModeStrategy.STORY_COMBAT_SWITCH,
    special_entry_probe=EventStorySpecialEntryProbe.NONE,
    popup_handler=EventStoryPopupHandler.RPG_STATUS,
)
SP_EVENT_STORY_PROFILE = EventStoryClientProfile(
    profile_id=EventStoryProfileId("sp"),
    landing_page=EventStoryLandingPage.SP,
    mode_strategy=EventStoryModeStrategy.STORY_COMBAT_SWITCH,
    special_entry_probe=EventStorySpecialEntryProbe.NONE,
    popup_handler=EventStoryPopupHandler.NONE,
)

EVENT_STORY_CLIENT_PROFILES = EventStoryClientProfileRegistry(
    (
        STANDARD_EVENT_STORY_PROFILE,
        ALCHEMIST_EVENT_STORY_PROFILE,
        RPG_STATUS_EVENT_STORY_PROFILE,
        SP_EVENT_STORY_PROFILE,
    )
)
