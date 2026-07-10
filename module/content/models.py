from dataclasses import dataclass
from pathlib import Path

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
class EventPack:
    pack_id: ContentId
    stages: tuple[StageSpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stages", tuple(self.stages))
