import math
from dataclasses import dataclass
from enum import StrEnum

from module.content.errors import ContentValidationError


class ChapterSwitch(StrEnum):
    EVENT_20241219 = "20241219"
    SP_20241219 = "20241219_sp"
    SPEX_20241219 = "20241219_spex"


class StageEntrancePosition(StrEnum):
    HALF = "half"


class StageEntranceRevision(StrEnum):
    EVENT_20240725 = "20240725"


class StageEntrancePreset(StrEnum):
    BLUE = "blue"
    GREEN = "green"
    NORMAL_HALF = "normal_half"


class EdgeInsightCorner(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    TOP_LEFT = "top-left"
    TOP_RIGHT = "top-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_RIGHT = "bottom-right"


@dataclass(frozen=True, slots=True)
class MapFeatures:
    siren_templates: tuple[str, ...]
    movable_enemy_turns: tuple[int, ...]
    has_siren: bool
    has_movable_enemy: bool
    has_map_story: bool
    has_fleet_step: bool
    has_ambush: bool
    has_mystery: bool
    has_portal: bool = False
    has_land_based: bool = False
    movable_normal_enemy_turns: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        templates = tuple(self.siren_templates)
        turns = tuple(self.movable_enemy_turns)
        normal_turns = tuple(self.movable_normal_enemy_turns)
        flags = (
            self.has_siren,
            self.has_movable_enemy,
            self.has_map_story,
            self.has_fleet_step,
            self.has_ambush,
            self.has_mystery,
            self.has_portal,
            self.has_land_based,
        )
        if any(type(flag) is not bool for flag in flags):
            message = "map feature flags must be booleans"
            raise TypeError(message)
        if any(not isinstance(template, str) or not template.strip() for template in templates):
            message = "siren templates must be non-empty strings"
            raise ContentValidationError(message)
        if len(set(templates)) != len(templates):
            message = "siren templates must be unique"
            raise ContentValidationError(message)
        if any(type(turn) is not int or turn <= 0 for turn in turns):
            message = "movable enemy turns must be positive integers"
            raise ContentValidationError(message)
        if len(set(turns)) != len(turns):
            message = "movable enemy turns must be unique"
            raise ContentValidationError(message)
        if any(type(turn) is not int or turn <= 0 for turn in normal_turns):
            message = "movable normal enemy turns must be positive integers"
            raise ContentValidationError(message)
        if len(set(normal_turns)) != len(normal_turns):
            message = "movable normal enemy turns must be unique"
            raise ContentValidationError(message)
        if templates and not self.has_siren:
            message = "siren_templates require has_siren"
            raise ContentValidationError(message)
        if self.has_movable_enemy != bool(turns):
            message = "has_movable_enemy must agree with movable_enemy_turns"
            raise ContentValidationError(message)
        object.__setattr__(self, "siren_templates", templates)
        object.__setattr__(self, "movable_enemy_turns", turns)
        object.__setattr__(self, "movable_normal_enemy_turns", normal_turns)


@dataclass(frozen=True, slots=True)
class StageEntrance:
    position: StageEntrancePosition
    revision: StageEntranceRevision

    def __post_init__(self) -> None:
        if not isinstance(self.position, StageEntrancePosition):
            message = "stage entrance position must be a StageEntrancePosition"
            raise TypeError(message)
        if not isinstance(self.revision, StageEntranceRevision):
            message = "stage entrance revision must be a StageEntranceRevision"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class StageNavigation:
    chapter_switch: ChapterSwitch | None
    entrance: StageEntrance | StageEntrancePreset
    has_mode_switch: bool

    def __post_init__(self) -> None:
        if self.chapter_switch is not None and not isinstance(self.chapter_switch, ChapterSwitch):
            message = "chapter_switch must be a ChapterSwitch or None"
            raise TypeError(message)
        if not isinstance(self.entrance, StageEntrance | StageEntrancePreset):
            message = "entrance must be a StageEntrance or StageEntrancePreset"
            raise TypeError(message)
        if type(self.has_mode_switch) is not bool:
            message = "has_mode_switch must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class SwipeScale:
    horizontal: float
    vertical: float

    def __post_init__(self) -> None:
        if (
            type(self.horizontal) is not float
            or not math.isfinite(self.horizontal)
            or self.horizontal <= 0
            or type(self.vertical) is not float
            or not math.isfinite(self.vertical)
            or self.vertical <= 0
        ):
            message = "swipe scale values must be positive finite floats"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class CalibrationPoint:
    x: float
    y: float

    def __post_init__(self) -> None:
        if type(self.x) is not float or not math.isfinite(self.x):
            message = "calibration point x must be a finite float"
            raise ContentValidationError(message)
        if type(self.y) is not float or not math.isfinite(self.y):
            message = "calibration point y must be a finite float"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class Homography:
    reference_columns: int
    reference_rows: int
    corners: tuple[CalibrationPoint, ...]

    def __post_init__(self) -> None:
        if type(self.reference_columns) is not int or self.reference_columns <= 0:
            message = "homography reference columns must be a positive integer"
            raise ContentValidationError(message)
        if type(self.reference_rows) is not int or self.reference_rows <= 0:
            message = "homography reference rows must be a positive integer"
            raise ContentValidationError(message)
        corners = tuple(self.corners)
        if len(corners) != 4 or any(not isinstance(point, CalibrationPoint) for point in corners):
            message = "homography must contain exactly four calibration points"
            raise ContentValidationError(message)
        object.__setattr__(self, "corners", corners)


@dataclass(frozen=True, slots=True)
class MapCalibration:
    swipe: SwipeScale
    minitouch_swipe: SwipeScale
    homography: Homography | None = None
    edge_insight_corner: EdgeInsightCorner | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.swipe, SwipeScale) or not isinstance(self.minitouch_swipe, SwipeScale):
            message = "map calibration requires swipe scales"
            raise TypeError(message)
        if self.homography is not None and not isinstance(self.homography, Homography):
            message = "homography must be a Homography or None"
            raise TypeError(message)
        if self.edge_insight_corner is not None and not isinstance(self.edge_insight_corner, EdgeInsightCorner):
            message = "edge_insight_corner must be an EdgeInsightCorner or None"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class StarRequirements:
    first: int = 1
    second: int = 2
    third: int = 3

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in (self.first, self.second, self.third)):
            message = "star requirements must be non-negative integers"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class RepeatableCompletion:
    star_requirements: StarRequirements

    def __post_init__(self) -> None:
        if not isinstance(self.star_requirements, StarRequirements):
            message = "star_requirements must be StarRequirements"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class OneTimeCompletion:
    star_requirements: StarRequirements

    def __post_init__(self) -> None:
        if not isinstance(self.star_requirements, StarRequirements):
            message = "star_requirements must be StarRequirements"
            raise TypeError(message)


type StageCompletion = RepeatableCompletion | OneTimeCompletion


@dataclass(frozen=True, slots=True)
class StageRules:
    features: MapFeatures
    completion: StageCompletion
    navigation: StageNavigation | None = None
    calibration: MapCalibration | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.features, MapFeatures):
            message = "features must be MapFeatures"
            raise TypeError(message)
        if not isinstance(self.completion, (RepeatableCompletion, OneTimeCompletion)):
            message = "completion must be a supported stage completion policy"
            raise TypeError(message)
        if self.navigation is not None and not isinstance(self.navigation, StageNavigation):
            message = "navigation must be StageNavigation or None"
            raise TypeError(message)
        if self.calibration is not None and not isinstance(self.calibration, MapCalibration):
            message = "calibration must be MapCalibration or None"
            raise TypeError(message)
