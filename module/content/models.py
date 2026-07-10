from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from module.content.campaign_policy import CampaignPolicy
from module.content.errors import ContentValidationError
from module.content.validation import require_non_empty_identifier

EVENT_KINDS = ("event", "raid", "coalition", "war_archives")
EVENT_UI_PROFILES = ("legacy_python",)


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
class AssetRef:
    asset_id: ContentId
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True, slots=True)
class StageSpec:
    ref: StageRef
    source: str
    assets: tuple[AssetRef, ...] = ()
    strategy: str | None = None

    def __post_init__(self) -> None:
        require_non_empty_identifier(self.source, field_name="source")
        if self.strategy is not None:
            if not isinstance(self.strategy, str):
                message = "strategy must be a string or None"
                raise TypeError(message)
            if not self.strategy.strip():
                message = "strategy must not be empty or whitespace"
                raise ContentValidationError(message)
        object.__setattr__(self, "assets", tuple(self.assets))


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
    ui_profile: str = "legacy_python"
    releases: tuple[EventRelease, ...] = ()
    policy: CampaignPolicy = field(default_factory=CampaignPolicy)

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
        if self.ui_profile not in EVENT_UI_PROFILES:
            message = f"ui_profile must be one of {EVENT_UI_PROFILES}"
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

        object.__setattr__(self, "stages", stages)
        object.__setattr__(self, "releases", releases)
