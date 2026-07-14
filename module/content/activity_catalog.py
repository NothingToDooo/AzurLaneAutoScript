from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Never

from module.content.activity_profile import (
    ActivityDefinition,
    CoalitionDefinition,
    EventStoryDefinition,
    RaidDefinition,
)
from module.content.errors import ActivityKindError, ContentCatalogError, UnknownActivityError
from module.content.models import ContentId, EventPack


@dataclass(frozen=True, slots=True)
class EventStoryActivity:
    content_id: ContentId
    definition: EventStoryDefinition

    def __post_init__(self) -> None:
        if not isinstance(self.content_id, ContentId):
            message = "content_id must be a ContentId"
            raise TypeError(message)
        if not isinstance(self.definition, EventStoryDefinition):
            message = "definition must be an EventStoryDefinition"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class RaidActivity:
    content_id: ContentId
    definition: RaidDefinition

    def __post_init__(self) -> None:
        if not isinstance(self.content_id, ContentId):
            message = "content_id must be a ContentId"
            raise TypeError(message)
        if not isinstance(self.definition, RaidDefinition):
            message = "definition must be a RaidDefinition"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CoalitionActivity:
    content_id: ContentId
    definition: CoalitionDefinition

    def __post_init__(self) -> None:
        if not isinstance(self.content_id, ContentId):
            message = "content_id must be a ContentId"
            raise TypeError(message)
        if not isinstance(self.definition, CoalitionDefinition):
            message = "definition must be a CoalitionDefinition"
            raise TypeError(message)


type Activity = EventStoryActivity | RaidActivity | CoalitionActivity


class ActivityCatalog:
    __slots__ = ("_activities", "_packs_by_id")

    def __init__(self, packs: Iterable[EventPack]) -> None:
        if not isinstance(packs, Iterable):
            message = "packs must be iterable"
            raise TypeError(message)
        packs_by_id: dict[str, EventPack] = {}
        activities: list[Activity] = []
        for pack in packs:
            if not isinstance(pack, EventPack):
                message = "packs must contain EventPack instances"
                raise TypeError(message)
            pack_id = str(pack.pack_id)
            if pack_id in packs_by_id:
                message = f"duplicate pack id: {pack_id}"
                raise ContentCatalogError(message)
            packs_by_id[pack_id] = pack
            definition = pack.activity
            if isinstance(definition, EventStoryDefinition):
                activities.append(EventStoryActivity(self._content_id(pack), definition))
            elif isinstance(definition, RaidDefinition):
                activities.append(RaidActivity(self._content_id(pack), definition))
            elif isinstance(definition, CoalitionDefinition):
                activities.append(CoalitionActivity(self._content_id(pack), definition))
        self._packs_by_id = MappingProxyType(packs_by_id)
        self._activities = tuple(activities)

    @property
    def activities(self) -> tuple[Activity, ...]:
        return self._activities

    def resolve_event_story(self, content_id: str) -> EventStoryActivity:
        pack = self._require_pack(content_id)
        definition = pack.activity
        if not isinstance(definition, EventStoryDefinition):
            self._raise_kind_error(content_id, "event_story", definition)
        return EventStoryActivity(self._content_id(pack), definition)

    def resolve_raid(self, content_id: str) -> RaidActivity:
        pack = self._require_pack(content_id)
        definition = pack.activity
        if not isinstance(definition, RaidDefinition):
            self._raise_kind_error(content_id, "raid", definition)
        return RaidActivity(self._content_id(pack), definition)

    def resolve_coalition(self, content_id: str) -> CoalitionActivity:
        pack = self._require_pack(content_id)
        definition = pack.activity
        if not isinstance(definition, CoalitionDefinition):
            self._raise_kind_error(content_id, "coalition", definition)
        return CoalitionActivity(self._content_id(pack), definition)

    def _require_pack(self, content_id: str) -> EventPack:
        if not isinstance(content_id, str):
            message = "content_id must be a string"
            raise TypeError(message)
        try:
            return self._packs_by_id[content_id]
        except KeyError:
            message = f"unknown activity content: {content_id}"
            raise UnknownActivityError(message) from None

    @staticmethod
    def _content_id(pack: EventPack) -> ContentId:
        return pack.pack_id if isinstance(pack.pack_id, ContentId) else ContentId(pack.pack_id)

    @staticmethod
    def _raise_kind_error(
        content_id: str,
        expected: str,
        definition: ActivityDefinition | None,
    ) -> Never:
        actual = "none" if definition is None else definition.kind.value
        message = f"activity content {content_id!r} is {actual}, expected {expected}"
        raise ActivityKindError(message)
