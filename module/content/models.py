from dataclasses import dataclass, field
from datetime import date

from module.content.activity_profile import (
    ActivityDefinition,
    CoalitionDefinition,
    EventStoryDefinition,
    RaidDefinition,
)
from module.content.campaign_policy import CampaignPolicy
from module.content.errors import ContentValidationError
from module.content.runtime_profile import CampaignRuntimeProfileId
from module.content.validation import require_non_empty_identifier
from module.content.war_archives_profile import WarArchivesDefinition

EVENT_KINDS = ("event", "raid", "coalition", "war_archives", "campaign")


@dataclass(frozen=True, slots=True)
class ContentId:
    value: str

    def __post_init__(self) -> None:
        require_non_empty_identifier(self.value, field_name="value")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class StageRef:
    pack_id: str
    stage_id: str

    def __post_init__(self) -> None:
        require_non_empty_identifier(self.pack_id, field_name="pack_id")
        require_non_empty_identifier(self.stage_id, field_name="stage_id")


@dataclass(frozen=True, slots=True)
class StageSpec:
    ref: StageRef
    source: str
    runtime_profile_id: CampaignRuntimeProfileId = field(default_factory=lambda: CampaignRuntimeProfileId("core"))
    war_archives: WarArchivesDefinition | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ref, StageRef):
            message = "ref must be a StageRef"
            raise TypeError(message)
        require_non_empty_identifier(self.source, field_name="source")
        if not isinstance(self.runtime_profile_id, CampaignRuntimeProfileId):
            message = "runtime_profile_id must be a CampaignRuntimeProfileId"
            raise TypeError(message)
        if self.war_archives is not None and not isinstance(self.war_archives, WarArchivesDefinition):
            message = "war_archives must be a WarArchivesDefinition or None"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class EventRelease:
    opened_on: date
    name_cn: str | None
    order: int

    def __post_init__(self) -> None:
        if type(self.opened_on) is not date:
            message = "opened_on must be a date"
            raise TypeError(message)
        if self.name_cn is not None:
            if not isinstance(self.name_cn, str):
                message = "name_cn must be a string or None"
                raise TypeError(message)
            if not self.name_cn.strip():
                message = "name_cn must not be empty or whitespace"
                raise ContentValidationError(message)
        if type(self.order) is not int or self.order <= 0:
            message = "order must be a positive integer"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class EventPack:
    pack_id: ContentId | str
    stages: tuple[StageSpec, ...] = ()
    kind: str = "event"
    releases: tuple[EventRelease, ...] = ()
    policy: CampaignPolicy = field(default_factory=CampaignPolicy)
    activity: ActivityDefinition | None = None
    war_archives: WarArchivesDefinition | None = None

    def __post_init__(self) -> None:
        pack_id = self.pack_id
        if isinstance(pack_id, str):
            pack_id = ContentId(pack_id)
            object.__setattr__(self, "pack_id", pack_id)
        elif not isinstance(pack_id, ContentId):
            message = "pack_id must be a ContentId or string"
            raise TypeError(message)

        if self.kind not in EVENT_KINDS:
            message = f"kind must be one of {EVENT_KINDS}"
            raise ContentValidationError(message)

        stages = tuple(self.stages)
        if any(not isinstance(stage, StageSpec) for stage in stages):
            message = "stages must contain StageSpec instances"
            raise TypeError(message)
        releases = tuple(self.releases)
        if any(not isinstance(release, EventRelease) for release in releases):
            message = "releases must contain EventRelease instances"
            raise TypeError(message)
        if not isinstance(self.policy, CampaignPolicy):
            message = "policy must be a CampaignPolicy"
            raise TypeError(message)
        self._validate_profiles(stages)

        object.__setattr__(self, "stages", stages)
        object.__setattr__(self, "releases", releases)

    def _validate_profiles(self, stages: tuple[StageSpec, ...]) -> None:
        if self.activity is not None and not isinstance(
            self.activity,
            EventStoryDefinition | RaidDefinition | CoalitionDefinition,
        ):
            message = "activity must be an ActivityDefinition or None"
            raise TypeError(message)
        expected_activity = {
            "event": EventStoryDefinition,
            "raid": RaidDefinition,
            "coalition": CoalitionDefinition,
        }.get(self.kind)
        if self.activity is not None and (
            expected_activity is None or not isinstance(self.activity, expected_activity)
        ):
            message = f"kind {self.kind!r} does not accept {type(self.activity).__name__}"
            raise ContentValidationError(message)
        if self.war_archives is not None and not isinstance(self.war_archives, WarArchivesDefinition):
            message = "war_archives must be a WarArchivesDefinition or None"
            raise TypeError(message)
        if (self.kind == "war_archives") != (self.war_archives is not None):
            message = "war_archives definition must exist exactly for war_archives packs"
            raise ContentValidationError(message)
        if any(stage.war_archives != self.war_archives for stage in stages):
            message = "stage war_archives definition must match its pack"
            raise ContentValidationError(message)
