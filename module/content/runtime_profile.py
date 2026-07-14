from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from module.content.errors import ContentValidationError

_PROFILE_ID = re.compile(r"[a-z0-9][a-z0-9_./-]*\Z")


@dataclass(frozen=True, slots=True, order=True)
class CampaignRuntimeProfileId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _PROFILE_ID.fullmatch(self.value) is None:
            message = f"invalid campaign runtime profile id: {self.value!r}"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True, order=True)
class CampaignRuntimeExtensionId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _PROFILE_ID.fullmatch(self.value) is None:
            message = f"invalid campaign runtime extension id: {self.value!r}"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True, order=True)
class RuntimeImplementationId:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _PROFILE_ID.fullmatch(self.value) is None:
            message = f"invalid runtime implementation id: {self.value!r}"
            raise ContentValidationError(message)


class RuntimeCapabilityKind(StrEnum):
    NAVIGATION = "navigation"
    EVENT_UI = "event_ui"
    WAR_ARCHIVES_NAVIGATION = "war_archives_navigation"
    MAP_OBSERVATION = "map_observation"
    GRID_RECOGNITION = "grid_recognition"
    MAP_MECHANIC = "map_mechanic"
    HARD_MODE = "hard_mode"
    ENGINE_EXTENSION = "engine_extension"


class RuntimeExecutorKind(StrEnum):
    """适配器必须显式注册的细粒度执行端口；不允许按 Python 方法名反射。"""

    NAVIGATION = "navigation"
    EVENT_UI = "event_ui"
    WAR_ARCHIVES_NAVIGATION = "war_archives_navigation"
    MAP_OBSERVATION = "map_observation"
    MAP_GRID_RECOGNITION = "map_grid_recognition"
    CAMERA_GRID_RECOGNITION = "camera_grid_recognition"
    MAP_MECHANIC = "map_mechanic"
    HARD_MODE = "hard_mode"
    ENGINE_EXTENSION = "engine_extension"

    @property
    def capability(self) -> RuntimeCapabilityKind:
        if self is RuntimeExecutorKind.MAP_GRID_RECOGNITION:
            return RuntimeCapabilityKind.GRID_RECOGNITION
        if self is RuntimeExecutorKind.CAMERA_GRID_RECOGNITION:
            return RuntimeCapabilityKind.GRID_RECOGNITION
        return RuntimeCapabilityKind(self.value)


class RuntimeTuningKey(StrEnum):
    CAMPAIGN_MODE = "campaign_mode"
    COINCIDENT_POINT_ENCOURAGE_DISTANCE = "coincident_point_encourage_distance"
    DETECTION_BACKEND = "detection_backend"
    DISTANCE_POINT_X_RANGE = "distance_point_x_range"
    HOMO_EDGE_COLOR_RANGE = "homo_edge_color_range"
    HOMO_EDGE_HOUGHLINES_THRESHOLD = "homo_edge_houghlines_threshold"
    HOMO_CANNY_THRESHOLD = "homo_canny_threshold"
    HOMO_CENTER_OFFSET = "homo_center_offset"
    HOMO_TILE = "homo_tile"
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS = "internal_lines_find_peaks_parameters"
    INTERNAL_LINES_HOUGHLINES_THRESHOLD = "internal_lines_houghlines_threshold"
    EDGE_LINES_FIND_PEAKS_PARAMETERS = "edge_lines_find_peaks_parameters"
    EDGE_LINES_HOUGHLINES_THRESHOLD = "edge_lines_houghlines_threshold"
    GRID_IMAGE_A_MULTIPLY = "grid_image_a_multiply"
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = "map_air_raid_overlay_transparency_threshold"
    MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD = "map_air_strike_overlay_transparency_threshold"
    MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD = "map_ambush_overlay_transparency_threshold"
    MAP_CLEAR_PERCENTAGE_SHORT = "map_clear_percentage_short"
    MAP_ENEMY_GENRE_DETECTION_SCALING = "map_enemy_genre_detection_scaling"
    MAP_ENEMY_GENRE_SIMILARITY = "map_enemy_genre_similarity"
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = "map_enemy_searching_overlay_transparency_threshold"
    MAP_WALK_TURNING_OPTIMIZE = "map_walk_turning_optimize"
    MAP_WALK_USE_CURRENT_FLEET = "map_walk_use_current_fleet"
    MAP_SIREN_MOVE_WAIT = "map_siren_move_wait"
    MAP_SWIPE_PREDICT_WITH_SEA_GRIDS = "map_swipe_predict_with_sea_grids"
    MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET = "map_swipe_predict_with_current_fleet"
    MAP_SWIPE_PREDICT = "map_swipe_predict"
    MAP_ENEMY_TEMPLATE = "map_enemy_template"
    MAP_GRID_CENTER_TOLERANCE = "map_grid_center_tolerance"
    MAP_HAS_CLEAR_PERCENTAGE = "map_has_clear_percentage"
    MAP_HAS_DECOY_ENEMY = "map_has_decoy_enemy"
    MAP_HAS_DYNAMIC_RED_BORDER = "map_has_dynamic_red_border"
    MAP_HAS_MISSILE_ATTACK = "map_has_missile_attack"
    MAP_HAS_PT_BONUS = "map_has_pt_bonus"
    MAP_HAS_WALK_SPEEDUP = "map_has_walk_speedup"
    MAP_MYSTERY_HAS_CARRIER = "map_mystery_has_carrier"
    MAP_MYSTERY_MAP_CLICK = "map_mystery_map_click"
    MAP_SIREN_COUNT = "map_siren_count"
    MAP_SIREN_HAS_BOSS_ICON = "map_siren_has_boss_icon"
    MAP_SIREN_HAS_BOSS_ICON_SMALL = "map_siren_has_boss_icon_small"
    MID_DIFF_RANGE_H = "mid_diff_range_h"
    MID_DIFF_RANGE_V = "mid_diff_range_v"
    POOR_MAP_DATA = "poor_map_data"
    TRUST_EDGE_LINES = "trust_edge_lines"
    TRUST_EDGE_LINES_THRESHOLD = "trust_edge_lines_threshold"
    VANISH_POINT_RANGE = "vanish_point_range"
    FLEET_2 = "fleet_2"
    FLEET_BOSS = "fleet_boss"
    SUBMARINE = "submarine"
    BOSS_APPEAR_REFOCUS_PRESET = "boss_appear_refocus_preset"
    MAP_CLEAR_PERCENTAGE_MULTIPLIER = "map_clear_percentage_multiplier"
    COMBAT_DISABLE_STUCK_DETECTION_BATTLE = "combat_disable_stuck_detection_battle"


type RuntimeTuningValue = (
    bool | int | float | str | tuple[RuntimeTuningValue, ...] | Mapping[str, RuntimeTuningValue] | None
)


def freeze_runtime_tuning(value: object) -> RuntimeTuningValue:
    if value is None or type(value) in (bool, int, str):
        return cast("bool | int | str | None", value)
    if type(value) is float:
        if not math.isfinite(value):
            message = "runtime tuning floats must be finite"
            raise ContentValidationError(message)
        return value
    if isinstance(value, list | tuple):
        return tuple(freeze_runtime_tuning(item) for item in value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or not key for key in value):
            message = "runtime tuning object keys must be non-empty strings"
            raise ContentValidationError(message)
        return MappingProxyType({str(key): freeze_runtime_tuning(item) for key, item in value.items()})
    message = f"runtime tuning contains a non-JSON value: {type(value).__name__}"
    raise TypeError(message)


@dataclass(frozen=True, slots=True, init=False)
class RuntimeTuning:
    key: RuntimeTuningKey
    value: RuntimeTuningValue

    def __init__(self, key: RuntimeTuningKey, value: object) -> None:
        if not isinstance(key, RuntimeTuningKey):
            message = "runtime tuning key must be a RuntimeTuningKey"
            raise TypeError(message)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "value", freeze_runtime_tuning(value))


@dataclass(frozen=True, slots=True, init=False)
class RuntimeExecutorBinding:
    kind: RuntimeExecutorKind
    implementation_id: RuntimeImplementationId
    options: Mapping[str, RuntimeTuningValue] = field(default_factory=dict)

    def __init__(
        self,
        kind: RuntimeExecutorKind,
        implementation_id: RuntimeImplementationId,
        options: Mapping[str, object],
    ) -> None:
        if not isinstance(kind, RuntimeExecutorKind):
            message = "runtime executor kind must be a RuntimeExecutorKind"
            raise TypeError(message)
        if not isinstance(implementation_id, RuntimeImplementationId):
            message = "runtime executor implementation_id must be a RuntimeImplementationId"
            raise TypeError(message)
        frozen = freeze_runtime_tuning(options)
        if not isinstance(frozen, Mapping):
            message = "runtime executor options must be an object"
            raise TypeError(message)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "implementation_id", implementation_id)
        object.__setattr__(self, "options", frozen)


@dataclass(frozen=True, slots=True)
class CampaignRuntimeExtension:
    extension_id: CampaignRuntimeExtensionId
    executors: tuple[RuntimeExecutorBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.extension_id, CampaignRuntimeExtensionId):
            message = "runtime extension id must be a CampaignRuntimeExtensionId"
            raise TypeError(message)
        executors = tuple(self.executors)
        if not executors or any(not isinstance(executor, RuntimeExecutorBinding) for executor in executors):
            message = "runtime extension requires typed executor bindings"
            raise ContentValidationError(message)
        if len({executor.kind for executor in executors}) != len(executors):
            message = "runtime extension executor kinds must be unique"
            raise ContentValidationError(message)
        object.__setattr__(self, "executors", executors)

    @property
    def capabilities(self) -> tuple[RuntimeCapabilityKind, ...]:
        return tuple(dict.fromkeys(executor.kind.capability for executor in self.executors))

    @property
    def requires_executor(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class CampaignRuntimeProfile:
    profile_id: CampaignRuntimeProfileId
    extensions: tuple[CampaignRuntimeExtension, ...] = ()
    tunings: tuple[RuntimeTuning, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, CampaignRuntimeProfileId):
            message = "runtime profile id must be a CampaignRuntimeProfileId"
            raise TypeError(message)
        extensions = tuple(self.extensions)
        if any(not isinstance(extension, CampaignRuntimeExtension) for extension in extensions):
            message = "runtime profile extensions must be CampaignRuntimeExtension values"
            raise TypeError(message)
        extension_ids = tuple(extension.extension_id for extension in extensions)
        if len(set(extension_ids)) != len(extension_ids):
            message = "runtime profile extension ids must be unique"
            raise ContentValidationError(message)
        tunings = tuple(self.tunings)
        if any(not isinstance(tuning, RuntimeTuning) for tuning in tunings):
            message = "runtime profile tunings must be RuntimeTuning values"
            raise TypeError(message)
        if len({tuning.key for tuning in tunings}) != len(tunings):
            message = "runtime profile tuning keys must be unique after composition"
            raise ContentValidationError(message)
        object.__setattr__(self, "extensions", extensions)
        object.__setattr__(self, "tunings", tunings)

    @classmethod
    def core(cls) -> CampaignRuntimeProfile:
        return cls(CampaignRuntimeProfileId("core"))

    @property
    def executor_kinds(self) -> frozenset[RuntimeExecutorKind]:
        return frozenset(executor.kind for extension in self.extensions for executor in extension.executors)


class CampaignRuntimeProfileRegistry:
    __slots__ = ("_extensions", "_profiles")

    def __init__(
        self,
        extensions: Iterable[CampaignRuntimeExtension],
        profiles: Iterable[CampaignRuntimeProfile],
    ) -> None:
        extension_map: dict[CampaignRuntimeExtensionId, CampaignRuntimeExtension] = {}
        for extension in extensions:
            if not isinstance(extension, CampaignRuntimeExtension):
                message = "runtime profile registry extensions contain an invalid value"
                raise TypeError(message)
            if extension.extension_id in extension_map:
                message = f"duplicate runtime extension: {extension.extension_id.value}"
                raise ContentValidationError(message)
            extension_map[extension.extension_id] = extension
        profile_map: dict[CampaignRuntimeProfileId, CampaignRuntimeProfile] = {}
        for profile in profiles:
            if not isinstance(profile, CampaignRuntimeProfile):
                message = "runtime profile registry profiles contain an invalid value"
                raise TypeError(message)
            if profile.profile_id in profile_map:
                message = f"duplicate runtime profile: {profile.profile_id.value}"
                raise ContentValidationError(message)
            unknown = tuple(
                extension.extension_id
                for extension in profile.extensions
                if extension.extension_id not in extension_map
            )
            if unknown:
                message = f"runtime profile contains unknown extensions: {[item.value for item in unknown]}"
                raise ContentValidationError(message)
            profile_map[profile.profile_id] = profile
        if CampaignRuntimeProfileId("core") not in profile_map:
            message = "runtime profile registry must define core"
            raise ContentValidationError(message)
        self._extensions = MappingProxyType(extension_map)
        self._profiles = MappingProxyType(profile_map)

    def resolve(self, profile_id: CampaignRuntimeProfileId) -> CampaignRuntimeProfile:
        if not isinstance(profile_id, CampaignRuntimeProfileId):
            message = "runtime profile resolution requires a CampaignRuntimeProfileId"
            raise TypeError(message)
        try:
            return self._profiles[profile_id]
        except KeyError:
            message = f"unknown campaign runtime profile: {profile_id.value}"
            raise ContentValidationError(message) from None

    @property
    def extensions(self) -> Mapping[CampaignRuntimeExtensionId, CampaignRuntimeExtension]:
        return self._extensions

    @property
    def profiles(self) -> Mapping[CampaignRuntimeProfileId, CampaignRuntimeProfile]:
        return self._profiles
