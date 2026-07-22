import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, cast

from module.content.runtime_profile import RuntimeTuning, RuntimeTuningKey, RuntimeTuningValue

if TYPE_CHECKING:
    from module.config.config_generated import ConfigOverrides


type RuntimeConfigValue = bool | int | float | str | tuple[RuntimeConfigValue, ...] | Mapping[str, RuntimeConfigValue]
type _ConfigDecoder = Callable[[RuntimeTuningValue, RuntimeTuningKey], RuntimeConfigValue]


class RuntimeTuningValidationError(ValueError):
    """runtime tuning 无法投影到固定生产契约。"""


@dataclass(frozen=True, slots=True)
class ConfiguredBossFleet:
    index: int

    def __post_init__(self) -> None:
        if type(self.index) is not int:
            message = f"configured boss fleet must be an integer; got {type(self.index).__name__}"
            raise TypeError(message)
        if self.index not in (1, 2):
            message = f"configured boss fleet must be 1 or 2; got {self.index}"
            raise ValueError(message)


def _invalid_type(key: RuntimeTuningKey, expected: str, value: object) -> RuntimeTuningValidationError:
    return RuntimeTuningValidationError(f"runtime tuning {key.value} must be {expected}; got {type(value).__name__}")


def _invalid_value(key: RuntimeTuningKey, requirement: str, value: object) -> RuntimeTuningValidationError:
    return RuntimeTuningValidationError(f"runtime tuning {key.value} must be {requirement}; got {value!r}")


def _decode_bool(value: RuntimeTuningValue, key: RuntimeTuningKey) -> bool:
    if type(value) is not bool:
        raise _invalid_type(key, "a boolean", value)
    return value


def _decode_integer(
    value: RuntimeTuningValue,
    key: RuntimeTuningKey,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise _invalid_type(key, "an integer", value)
    if minimum is not None and value < minimum:
        raise _invalid_value(key, f"an integer >= {minimum}", value)
    if maximum is not None and value > maximum:
        raise _invalid_value(key, f"an integer <= {maximum}", value)
    return value


def _decode_non_negative_integer(value: RuntimeTuningValue, key: RuntimeTuningKey) -> int:
    return _decode_integer(value, key, minimum=0)


def _decode_positive_integer(value: RuntimeTuningValue, key: RuntimeTuningKey) -> int:
    return _decode_integer(value, key, minimum=1)


def _decode_fleet_2(value: RuntimeTuningValue, key: RuntimeTuningKey) -> int:
    return _decode_integer(value, key, minimum=0, maximum=6)


def _decode_submarine(value: RuntimeTuningValue, key: RuntimeTuningKey) -> int:
    return _decode_integer(value, key, minimum=0, maximum=2)


def _decode_boss_fleet(value: RuntimeTuningValue, key: RuntimeTuningKey) -> ConfiguredBossFleet:
    index = _decode_integer(value, key)
    if index not in (1, 2):
        raise _invalid_value(key, "1 or 2", value)
    return ConfiguredBossFleet(index)


def _decode_number(value: RuntimeTuningValue, key: RuntimeTuningKey) -> float:
    if type(value) not in (int, float):
        raise _invalid_type(key, "a number", value)
    number = float(cast("int | float", value))
    if not math.isfinite(number):
        raise _invalid_value(key, "a finite number", value)
    return number


def _decode_non_negative_number(value: RuntimeTuningValue, key: RuntimeTuningKey) -> float:
    number = _decode_number(value, key)
    if number < 0:
        raise _invalid_value(key, "a non-negative number", value)
    return number


def _decode_positive_number(value: RuntimeTuningValue, key: RuntimeTuningKey) -> float:
    number = _decode_number(value, key)
    if number <= 0:
        raise _invalid_value(key, "a positive number", value)
    return number


def _decode_ratio(value: RuntimeTuningValue, key: RuntimeTuningKey) -> float:
    number = _decode_number(value, key)
    if not 0 <= number <= 1:
        raise _invalid_value(key, "a number between 0 and 1", value)
    return number


def _decode_campaign_mode(value: RuntimeTuningValue, key: RuntimeTuningKey) -> str:
    if not isinstance(value, str):
        raise _invalid_type(key, "one of 'normal' or 'hard'", value)
    if value not in {"normal", "hard"}:
        raise _invalid_value(key, "one of 'normal' or 'hard'", value)
    return value


def _decode_detection_backend(value: RuntimeTuningValue, key: RuntimeTuningKey) -> str:
    if not isinstance(value, str):
        raise _invalid_type(key, "one of 'homography' or 'perspective'", value)
    if value not in {"homography", "perspective"}:
        raise _invalid_value(key, "one of 'homography' or 'perspective'", value)
    return value


def _decode_integer_pair(
    value: RuntimeTuningValue,
    key: RuntimeTuningKey,
    *,
    minimum: int | None = None,
    ordered: bool = False,
) -> tuple[int, int]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise _invalid_type(key, "a pair of integers", value)
    first, second = value
    if type(first) is not int or type(second) is not int:
        raise _invalid_type(key, "a pair of integers", value)
    if minimum is not None and (first < minimum or second < minimum):
        raise _invalid_value(key, f"a pair of integers >= {minimum}", value)
    if ordered and first > second:
        raise _invalid_value(key, "an ordered integer pair", value)
    return first, second


def _decode_color_range(value: RuntimeTuningValue, key: RuntimeTuningKey) -> tuple[int, int]:
    pair = _decode_integer_pair(value, key, minimum=0, ordered=True)
    if pair[1] > 255:
        raise _invalid_value(key, "an ordered integer pair between 0 and 255", value)
    return pair


def _decode_canny_threshold(value: RuntimeTuningValue, key: RuntimeTuningKey) -> tuple[int, int]:
    return _decode_integer_pair(value, key, minimum=0, ordered=True)


def _decode_center_offset(value: RuntimeTuningValue, key: RuntimeTuningKey) -> tuple[int, int]:
    return _decode_integer_pair(value, key)


def _decode_homo_tile(value: RuntimeTuningValue, key: RuntimeTuningKey) -> tuple[int, int]:
    return _decode_integer_pair(value, key, minimum=1)


def _decode_ordered_integer_pair(value: RuntimeTuningValue, key: RuntimeTuningKey) -> tuple[int, int]:
    return _decode_integer_pair(value, key, ordered=True)


def _decode_integer_ranges(
    value: RuntimeTuningValue,
    key: RuntimeTuningKey,
    *,
    length: int | None = None,
) -> tuple[RuntimeConfigValue, ...]:
    if not isinstance(value, tuple) or not value:
        raise _invalid_type(key, "a non-empty tuple of integer ranges", value)
    if length is not None and len(value) != length:
        raise _invalid_value(key, f"exactly {length} integer ranges", value)
    return tuple(_decode_integer_pair(item, key, ordered=True) for item in value)


def _decode_distance_ranges(value: RuntimeTuningValue, key: RuntimeTuningKey) -> tuple[RuntimeConfigValue, ...]:
    return _decode_integer_ranges(value, key)


def _decode_vanish_ranges(value: RuntimeTuningValue, key: RuntimeTuningKey) -> tuple[RuntimeConfigValue, ...]:
    return _decode_integer_ranges(value, key, length=2)


def _decode_string_tuple(value: RuntimeTuningValue, key: RuntimeTuningKey) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        raise _invalid_type(key, "a tuple of non-empty strings", value)
    return cast("tuple[str, ...]", value)


_FIND_PEAKS_FIELDS: Final = frozenset(
    {"height", "threshold", "distance", "prominence", "width", "wlen", "rel_height", "plateau_size"}
)
_FIND_PEAKS_SCALAR_FIELDS: Final = frozenset({"distance", "wlen"})


def _decode_find_peaks_parameter(
    value: RuntimeTuningValue,
    key: RuntimeTuningKey,
    field_name: str,
) -> int | float | tuple[float, float]:
    if isinstance(value, tuple):
        if field_name in _FIND_PEAKS_SCALAR_FIELDS or len(value) != 2:
            raise _invalid_type(key, f"a scalar {field_name} parameter", value)
        pair = cast("tuple[RuntimeTuningValue, RuntimeTuningValue]", value)
        first = _decode_number(pair[0], key)
        second = _decode_number(pair[1], key)
        if first < 0 or second < 0 or first > second:
            raise _invalid_value(key, f"an ordered non-negative range for {field_name}", value)
        return first, second
    if field_name == "wlen":
        if type(value) is not int:
            raise _invalid_type(key, "an integer wlen parameter", value)
        if value < 2:
            raise _invalid_value(key, "an integer wlen parameter >= 2", value)
        return value
    number = _decode_number(value, key)
    minimum = 1 if field_name == "distance" else 0
    if number < minimum:
        raise _invalid_value(key, f"a {field_name} parameter >= {minimum}", value)
    return number


def _decode_find_peaks_parameters(
    value: RuntimeTuningValue,
    key: RuntimeTuningKey,
) -> Mapping[str, RuntimeConfigValue]:
    if not isinstance(value, Mapping):
        raise _invalid_type(key, "a find_peaks parameter mapping", value)
    parameters = cast("Mapping[str, RuntimeTuningValue]", value)
    unknown = sorted(set(parameters) - _FIND_PEAKS_FIELDS)
    if unknown:
        raise _invalid_value(key, f"a find_peaks mapping without unknown field {unknown[0]!r}", value)
    return MappingProxyType(
        {name: _decode_find_peaks_parameter(parameter, key, name) for name, parameter in parameters.items()}
    )


def _decode_enemy_genre_scaling(
    value: RuntimeTuningValue,
    key: RuntimeTuningKey,
) -> Mapping[str, RuntimeConfigValue]:
    if not isinstance(value, Mapping):
        raise _invalid_type(key, "an enemy-template scaling mapping", value)
    decoded: dict[str, RuntimeConfigValue] = {}
    for name, raw_scaling in cast("Mapping[str, RuntimeTuningValue]", value).items():
        if not name:
            raise _invalid_value(key, "non-empty enemy-template names", value)
        if isinstance(raw_scaling, tuple):
            if not raw_scaling:
                raise _invalid_value(key, f"a non-empty scaling tuple for {name!r}", raw_scaling)
            decoded[name] = tuple(_decode_positive_number(item, key) for item in raw_scaling)
        else:
            decoded[name] = _decode_positive_number(raw_scaling, key)
    return MappingProxyType(decoded)


def _freeze_config_value(value: RuntimeConfigValue, path: str) -> RuntimeConfigValue:
    if type(value) is float and not math.isfinite(value):
        message = f"runtime config patch {path} must contain finite floats; got {value!r}"
        raise ValueError(message)
    if type(value) in (bool, int, float, str):
        return value
    if isinstance(value, tuple):
        return tuple(_freeze_config_value(item, path) for item in value)
    if isinstance(value, Mapping):
        frozen: dict[str, RuntimeConfigValue] = {}
        mapping = cast("Mapping[object, RuntimeConfigValue]", value)
        for key, item in mapping.items():
            if not isinstance(key, str) or not key:
                message = f"runtime config patch {path} contains an invalid mapping key: {key!r}"
                raise TypeError(message)
            frozen[key] = _freeze_config_value(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    message = f"runtime config patch {path} contains unsupported value {type(value).__name__}"
    raise TypeError(message)


def _thaw_config_value(value: RuntimeConfigValue) -> object:
    if isinstance(value, tuple):
        return tuple(_thaw_config_value(item) for item in value)
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, RuntimeConfigValue]", value)
        return {key: _thaw_config_value(item) for key, item in mapping.items()}
    return value


@dataclass(frozen=True, slots=True)
class RuntimeConfigPatch:
    overlay: Mapping[str, RuntimeConfigValue] = field(default_factory=dict)
    configured_boss_fleet: ConfiguredBossFleet | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.overlay, Mapping):
            message = f"runtime config patch overlay must be a mapping; got {type(self.overlay).__name__}"
            raise TypeError(message)
        if self.configured_boss_fleet is not None and not isinstance(self.configured_boss_fleet, ConfiguredBossFleet):
            message = "runtime config patch boss fleet must be ConfiguredBossFleet or None"
            raise TypeError(message)
        frozen = {
            name: _freeze_config_value(value, name)
            for name, value in self.overlay.items()
            if isinstance(name, str) and name
        }
        if len(frozen) != len(self.overlay):
            message = "runtime config patch field names must be non-empty strings"
            raise TypeError(message)
        object.__setattr__(self, "overlay", MappingProxyType(frozen))

    def to_overrides(self) -> ConfigOverrides:
        values = {name: _thaw_config_value(value) for name, value in self.overlay.items()}
        return cast("ConfigOverrides", values)


def _normalize_optional_ratio(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        message = f"runtime threshold {field_name} must be a number or None; got {type(value).__name__}"
        raise TypeError(message)
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        message = f"runtime threshold {field_name} must be between 0 and 1; got {value!r}"
        raise ValueError(message)
    return number


@dataclass(frozen=True, slots=True)
class RuntimeThresholdPatch:
    air_raid_overlay_transparency: float | None = None
    ambush_overlay_transparency: float | None = None
    enemy_searching_overlay_transparency: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "air_raid_overlay_transparency",
            "ambush_overlay_transparency",
            "enemy_searching_overlay_transparency",
        ):
            normalized = _normalize_optional_ratio(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, normalized)


@dataclass(frozen=True, slots=True)
class RuntimeBehaviorPatch:
    boss_appear_refocus_preset: tuple[int, int] | None = None
    map_clear_percentage_multiplier: float | None = None
    combat_disable_stuck_detection_battle: int | None = None

    def __post_init__(self) -> None:
        preset = self.boss_appear_refocus_preset
        if preset is not None and (
            not isinstance(preset, tuple) or len(preset) != 2 or any(type(item) is not int for item in preset)
        ):
            message = "runtime behavior boss_appear_refocus_preset must be a pair of integers or None"
            raise TypeError(message)
        multiplier = self.map_clear_percentage_multiplier
        if multiplier is not None:
            if type(multiplier) not in (int, float):
                message = "runtime behavior map_clear_percentage_multiplier must be a number or None"
                raise TypeError(message)
            normalized = float(multiplier)
            if not math.isfinite(normalized) or normalized <= 0:
                message = "runtime behavior map_clear_percentage_multiplier must be positive"
                raise ValueError(message)
            object.__setattr__(self, "map_clear_percentage_multiplier", normalized)
        battle = self.combat_disable_stuck_detection_battle
        if battle is not None:
            if type(battle) is not int:
                message = "runtime behavior combat_disable_stuck_detection_battle must be an integer or None"
                raise TypeError(message)
            if battle < 0:
                message = "runtime behavior combat_disable_stuck_detection_battle must be non-negative"
                raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CampaignRuntimeTuningPatch:
    config: RuntimeConfigPatch = field(default_factory=RuntimeConfigPatch)
    thresholds: RuntimeThresholdPatch = field(default_factory=RuntimeThresholdPatch)
    behavior: RuntimeBehaviorPatch = field(default_factory=RuntimeBehaviorPatch)

    def __post_init__(self) -> None:
        if not isinstance(self.config, RuntimeConfigPatch):
            message = "campaign runtime tuning config must be RuntimeConfigPatch"
            raise TypeError(message)
        if not isinstance(self.thresholds, RuntimeThresholdPatch):
            message = "campaign runtime tuning thresholds must be RuntimeThresholdPatch"
            raise TypeError(message)
        if not isinstance(self.behavior, RuntimeBehaviorPatch):
            message = "campaign runtime tuning behavior must be RuntimeBehaviorPatch"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class _ConfigFieldDecoder:
    field_name: str
    decode: _ConfigDecoder


_BOOL_CONFIG_FIELDS: Final = {
    RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_SHORT: "MAP_CLEAR_PERCENTAGE_SHORT",
    RuntimeTuningKey.MAP_WALK_USE_CURRENT_FLEET: "MAP_WALK_USE_CURRENT_FLEET",
    RuntimeTuningKey.MAP_SWIPE_PREDICT_WITH_SEA_GRIDS: "MAP_SWIPE_PREDICT_WITH_SEA_GRIDS",
    RuntimeTuningKey.MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET: "MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET",
    RuntimeTuningKey.MAP_SWIPE_PREDICT: "MAP_SWIPE_PREDICT",
    RuntimeTuningKey.MAP_HAS_CLEAR_PERCENTAGE: "MAP_HAS_CLEAR_PERCENTAGE",
    RuntimeTuningKey.MAP_HAS_DECOY_ENEMY: "MAP_HAS_DECOY_ENEMY",
    RuntimeTuningKey.MAP_HAS_MISSILE_ATTACK: "MAP_HAS_MISSILE_ATTACK",
    RuntimeTuningKey.MAP_HAS_WALK_SPEEDUP: "MAP_HAS_WALK_SPEEDUP",
    RuntimeTuningKey.MAP_MYSTERY_HAS_CARRIER: "MAP_MYSTERY_HAS_CARRIER",
    RuntimeTuningKey.MAP_MYSTERY_MAP_CLICK: "MAP_MYSTERY_MAP_CLICK",
    RuntimeTuningKey.MAP_SIREN_HAS_BOSS_ICON: "MAP_SIREN_HAS_BOSS_ICON",
    RuntimeTuningKey.MAP_SIREN_HAS_BOSS_ICON_SMALL: "MAP_SIREN_HAS_BOSS_ICON_SMALL",
    RuntimeTuningKey.POOR_MAP_DATA: "POOR_MAP_DATA",
    RuntimeTuningKey.TRUST_EDGE_LINES: "TRUST_EDGE_LINES",
}

_CONFIG_TUNING_DECODERS: Final[Mapping[RuntimeTuningKey, _ConfigFieldDecoder]] = MappingProxyType(
    {
        **{key: _ConfigFieldDecoder(field_name, _decode_bool) for key, field_name in _BOOL_CONFIG_FIELDS.items()},
        RuntimeTuningKey.CAMPAIGN_MODE: _ConfigFieldDecoder("Campaign_Mode", _decode_campaign_mode),
        RuntimeTuningKey.COINCIDENT_POINT_ENCOURAGE_DISTANCE: _ConfigFieldDecoder(
            "COINCIDENT_POINT_ENCOURAGE_DISTANCE", _decode_non_negative_number
        ),
        RuntimeTuningKey.DETECTION_BACKEND: _ConfigFieldDecoder("DETECTION_BACKEND", _decode_detection_backend),
        RuntimeTuningKey.DISTANCE_POINT_X_RANGE: _ConfigFieldDecoder("DISTANCE_POINT_X_RANGE", _decode_distance_ranges),
        RuntimeTuningKey.HOMO_EDGE_COLOR_RANGE: _ConfigFieldDecoder("HOMO_EDGE_COLOR_RANGE", _decode_color_range),
        RuntimeTuningKey.HOMO_EDGE_HOUGHLINES_THRESHOLD: _ConfigFieldDecoder(
            "HOMO_EDGE_HOUGHLINES_THRESHOLD", _decode_positive_integer
        ),
        RuntimeTuningKey.HOMO_CANNY_THRESHOLD: _ConfigFieldDecoder("HOMO_CANNY_THRESHOLD", _decode_canny_threshold),
        RuntimeTuningKey.HOMO_CENTER_OFFSET: _ConfigFieldDecoder("HOMO_CENTER_OFFSET", _decode_center_offset),
        RuntimeTuningKey.HOMO_TILE: _ConfigFieldDecoder("HOMO_TILE", _decode_homo_tile),
        RuntimeTuningKey.INTERNAL_LINES_FIND_PEAKS_PARAMETERS: _ConfigFieldDecoder(
            "INTERNAL_LINES_FIND_PEAKS_PARAMETERS", _decode_find_peaks_parameters
        ),
        RuntimeTuningKey.INTERNAL_LINES_HOUGHLINES_THRESHOLD: _ConfigFieldDecoder(
            "INTERNAL_LINES_HOUGHLINES_THRESHOLD", _decode_positive_integer
        ),
        RuntimeTuningKey.EDGE_LINES_FIND_PEAKS_PARAMETERS: _ConfigFieldDecoder(
            "EDGE_LINES_FIND_PEAKS_PARAMETERS", _decode_find_peaks_parameters
        ),
        RuntimeTuningKey.EDGE_LINES_HOUGHLINES_THRESHOLD: _ConfigFieldDecoder(
            "EDGE_LINES_HOUGHLINES_THRESHOLD", _decode_positive_integer
        ),
        RuntimeTuningKey.GRID_IMAGE_A_MULTIPLY: _ConfigFieldDecoder("GRID_IMAGE_A_MULTIPLY", _decode_positive_number),
        RuntimeTuningKey.MAP_ENEMY_GENRE_DETECTION_SCALING: _ConfigFieldDecoder(
            "MAP_ENEMY_GENRE_DETECTION_SCALING", _decode_enemy_genre_scaling
        ),
        RuntimeTuningKey.MAP_ENEMY_GENRE_SIMILARITY: _ConfigFieldDecoder("MAP_ENEMY_GENRE_SIMILARITY", _decode_ratio),
        RuntimeTuningKey.MAP_SIREN_MOVE_WAIT: _ConfigFieldDecoder("MAP_SIREN_MOVE_WAIT", _decode_non_negative_number),
        RuntimeTuningKey.MAP_ENEMY_TEMPLATE: _ConfigFieldDecoder("MAP_ENEMY_TEMPLATE", _decode_string_tuple),
        RuntimeTuningKey.MAP_GRID_CENTER_TOLERANCE: _ConfigFieldDecoder("MAP_GRID_CENTER_TOLERANCE", _decode_ratio),
        RuntimeTuningKey.MID_DIFF_RANGE_H: _ConfigFieldDecoder("MID_DIFF_RANGE_H", _decode_ordered_integer_pair),
        RuntimeTuningKey.MID_DIFF_RANGE_V: _ConfigFieldDecoder("MID_DIFF_RANGE_V", _decode_ordered_integer_pair),
        RuntimeTuningKey.TRUST_EDGE_LINES_THRESHOLD: _ConfigFieldDecoder(
            "TRUST_EDGE_LINES_THRESHOLD", _decode_positive_integer
        ),
        RuntimeTuningKey.VANISH_POINT_RANGE: _ConfigFieldDecoder("VANISH_POINT_RANGE", _decode_vanish_ranges),
        RuntimeTuningKey.FLEET_2: _ConfigFieldDecoder("Fleet_Fleet2", _decode_fleet_2),
        RuntimeTuningKey.SUBMARINE: _ConfigFieldDecoder("Submarine_Fleet", _decode_submarine),
    }
)
if len({decoder.field_name for decoder in _CONFIG_TUNING_DECODERS.values()}) != len(_CONFIG_TUNING_DECODERS):
    message = "runtime config tuning decoders must project to unique fields"
    raise AssertionError(message)

_THRESHOLD_TUNING_KEYS: Final = frozenset(
    {
        RuntimeTuningKey.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD,
        RuntimeTuningKey.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD,
        RuntimeTuningKey.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD,
    }
)
_BEHAVIOR_TUNING_KEYS: Final = frozenset(
    {
        RuntimeTuningKey.BOSS_APPEAR_REFOCUS_PRESET,
        RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER,
        RuntimeTuningKey.COMBAT_DISABLE_STUCK_DETECTION_BATTLE,
    }
)
SUPPORTED_RUNTIME_TUNING_KEYS: Final = (
    frozenset(_CONFIG_TUNING_DECODERS) | _THRESHOLD_TUNING_KEYS | _BEHAVIOR_TUNING_KEYS | {RuntimeTuningKey.FLEET_BOSS}
)
_EXPECTED_RUNTIME_TUNING_KEY_COUNT = 47
if len(SUPPORTED_RUNTIME_TUNING_KEYS) != _EXPECTED_RUNTIME_TUNING_KEY_COUNT:
    message = (
        "runtime tuning decoder count changed: "
        f"expected {_EXPECTED_RUNTIME_TUNING_KEY_COUNT}, got {len(SUPPORTED_RUNTIME_TUNING_KEYS)}"
    )
    raise AssertionError(message)
if frozenset(RuntimeTuningKey) != SUPPORTED_RUNTIME_TUNING_KEYS:
    missing = sorted(key.value for key in frozenset(RuntimeTuningKey) - SUPPORTED_RUNTIME_TUNING_KEYS)
    extra = sorted(key.value for key in SUPPORTED_RUNTIME_TUNING_KEYS - frozenset(RuntimeTuningKey))
    message = f"runtime tuning decoder is incomplete: missing={missing}, extra={extra}"
    raise AssertionError(message)


@dataclass(slots=True)
class _PatchAccumulator:
    config_overlay: dict[str, RuntimeConfigValue] = field(default_factory=dict)
    configured_boss_fleet: ConfiguredBossFleet | None = None
    air_raid_threshold: float | None = None
    ambush_threshold: float | None = None
    enemy_searching_threshold: float | None = None
    boss_refocus: tuple[int, int] | None = None
    clear_percentage_multiplier: float | None = None
    disable_stuck_battle: int | None = None


def _decode_non_config_tuning(
    target: _PatchAccumulator,
    tuning: RuntimeTuning,
) -> None:
    key = tuning.key
    if key is RuntimeTuningKey.FLEET_BOSS:
        target.configured_boss_fleet = _decode_boss_fleet(tuning.value, key)
    elif key is RuntimeTuningKey.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD:
        target.air_raid_threshold = _decode_ratio(tuning.value, key)
    elif key is RuntimeTuningKey.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD:
        target.ambush_threshold = _decode_ratio(tuning.value, key)
    elif key is RuntimeTuningKey.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD:
        target.enemy_searching_threshold = _decode_ratio(tuning.value, key)
    elif key is RuntimeTuningKey.BOSS_APPEAR_REFOCUS_PRESET:
        target.boss_refocus = _decode_integer_pair(tuning.value, key)
    elif key is RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER:
        target.clear_percentage_multiplier = _decode_positive_number(tuning.value, key)
    elif key is RuntimeTuningKey.COMBAT_DISABLE_STUCK_DETECTION_BATTLE:
        target.disable_stuck_battle = _decode_non_negative_integer(tuning.value, key)
    else:
        message = f"unreachable runtime tuning key: {key.value}"
        raise AssertionError(message)


def compile_campaign_runtime_tuning_patch(
    tunings: Iterable[RuntimeTuning],
) -> CampaignRuntimeTuningPatch:
    target = _PatchAccumulator()
    seen: set[RuntimeTuningKey] = set()

    for tuning in tunings:
        if not isinstance(tuning, RuntimeTuning):
            message = "runtime tuning patch compiler requires RuntimeTuning items"
            raise TypeError(message)
        key = tuning.key
        if key in seen:
            message = f"runtime tuning {key.value} is duplicated"
            raise RuntimeTuningValidationError(message)
        seen.add(key)

        decoder = _CONFIG_TUNING_DECODERS.get(key)
        if decoder is not None:
            target.config_overlay[decoder.field_name] = decoder.decode(tuning.value, key)
        else:
            _decode_non_config_tuning(target, tuning)

    return CampaignRuntimeTuningPatch(
        config=RuntimeConfigPatch(target.config_overlay, target.configured_boss_fleet),
        thresholds=RuntimeThresholdPatch(
            target.air_raid_threshold,
            target.ambush_threshold,
            target.enemy_searching_threshold,
        ),
        behavior=RuntimeBehaviorPatch(
            target.boss_refocus,
            target.clear_percentage_multiplier,
            target.disable_stuck_battle,
        ),
    )
