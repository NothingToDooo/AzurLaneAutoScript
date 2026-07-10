from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from module.content.campaign_policy import CampaignPolicy
from module.content.errors import ContentValidationError
from module.content.validation import require_non_empty_identifier


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

    def __post_init__(self) -> None:
        require_non_empty_identifier(self.source, field_name="source")
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
    pack_id: ContentId
    stages: tuple[StageSpec, ...] = ()
    kind: str = "event"
    ui_profile: str = "legacy_python"
    releases: tuple[EventRelease, ...] = ()
    policy: CampaignPolicy = field(default_factory=CampaignPolicy)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stages", tuple(self.stages))
        object.__setattr__(self, "releases", tuple(self.releases))
