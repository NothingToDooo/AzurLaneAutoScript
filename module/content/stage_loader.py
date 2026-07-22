import math
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from module.content.battle_policy import BossStrategy
from module.content.battle_program import BattleProgram, BattleProgramMode, BossApproachPlan
from module.content.catalog import ContentCatalog
from module.content.errors import ContentValidationError
from module.content.hard_mode_policy import HardModeEquipmentCleanup, HardModeRuntimePolicy
from module.content.manifest import DEFAULT_EVENT_MANIFEST_PATH, load_default_event_manifests
from module.content.mechanic_rules import (
    AirStrike,
    BreakSirenCaught,
    CandidateSortKey,
    ClearAllMystery,
    ClearChosenMystery,
    ClearMapItems,
    ClearMechanism,
    EncounterExpectation,
    EnsureFleet,
    EnsureFleetAt,
    FleetClearSelectedTarget,
    FleetClearTarget,
    FleetCoordinationAction,
    FleetCoordinationRules,
    FleetRole,
    MapInteractionRules,
    MapItemKind,
    MapStructureRules,
    MoveFleet,
    MoveFleetToBestCandidate,
    MovingEnemyRules,
    PickupAmmo,
    PickupMapItem,
    PickupRules,
    ProtectFleet,
    PushFleetForward,
    RescueFleet,
    RoadblockAction,
    RoadblockMode,
    RoadblockRules,
    RoadblockSelection,
    RoadGroup,
    RoadPath,
    StageMechanicRules,
    StepFleetOn,
    WallEdge,
)
from module.content.models import StageRef, StageSpec
from module.content.runtime_profile import CampaignRuntimeProfileRegistry
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.content.stage_behavior_codec import (
    decode_battle_program,
    decode_enemy_movement_rules,
    decode_mechanic_procedures,
    decode_stage_policy,
)
from module.content.stage_definition import (
    MAP_CELL_TOKENS,
    CampaignStageDefinition,
    CellId,
    CellSpec,
    GridShape,
    LandBasedDirection,
    LandBasedSpec,
    MapDefinition,
    PortalSpec,
    RunVariant,
    SpawnWave,
)
from module.content.stage_rules import (
    CalibrationPoint,
    ChapterSwitch,
    EdgeInsightCorner,
    Homography,
    MapCalibration,
    MapFeatures,
    OneTimeCompletion,
    RepeatableCompletion,
    StageEntrance,
    StageEntrancePosition,
    StageEntrancePreset,
    StageEntranceRevision,
    StageNavigation,
    StageRules,
    StarRequirements,
    SwipeScale,
)
from module.content.yaml_loader import load_strict_yaml_mapping

if TYPE_CHECKING:
    from module.content.battle_policy import StagePolicy

SCHEMA_VERSION = 6

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "map",
    "config",
    "enemy_filter",
    "battles",
    "mechanics",
    "programs",
    "boss_approaches",
    "hard_mode",
}
_MAP_FIELDS = {
    "name",
    "shape",
    "camera_data",
    "camera_data_spawn_point",
    "map_covered",
    "map_data",
    "map_data_loop",
    "normal_enemy_spawn_candidates",
    "weight_data",
    "portal_data",
    "land_based_data",
    "spawn_data",
    "spawn_data_loop",
}
_REQUIRED_MAP_FIELDS = {
    "name",
    "shape",
    "camera_data",
    "camera_data_spawn_point",
    "map_data",
    "weight_data",
    "spawn_data",
}
_SPAWN_FIELDS = {"battle", "enemy", "siren", "mystery", "boss"}
_MECHANIC_FIELDS = {
    "roadblocks",
    "fleet_coordination",
    "pickups",
    "map_interactions",
    "moving_enemies",
    "map_structures",
    "enemy_movement",
    "procedures",
}
_ROADBLOCK_FIELDS = {"tag", "battle", "roads", "selection"}
_FLEET_ACTION_FIELDS = {
    "break_siren_caught": {"tag", "battle", "fleet"},
    "push_forward": {"tag", "battle", "fleet"},
    "protect": {"tag", "battle", "fleet"},
    "rescue": {"tag", "battle", "fleet", "target"},
    "step_on": {"tag", "battle", "fleet", "candidates", "roadblocks"},
    "move": {"tag", "battle", "fleet", "destination", "expected"},
    "ensure": {"tag", "battle", "fleet"},
    "ensure_at": {"tag", "battle", "fleet", "target"},
    "clear_target": {"tag", "battle", "fleet", "target", "expected"},
    "clear_selected_target": {"tag", "battle", "fleet", "candidates", "expected"},
}
_PICKUP_FIELDS = {
    "ammo": {"tag", "battle", "fleet"},
    "map_item": {"tag", "battle", "fleet", "kind", "cell"},
}
_MAP_INTERACTION_FIELDS = {
    "clear_all_mystery": {"tag", "battle", "nearby", "ignored"},
    "clear_chosen_mystery": {"tag", "battle", "fleet", "cell"},
    "clear_mechanism": {"tag", "battle", "cells"},
    "clear_map_items": {"tag", "battle", "cells"},
    "air_strike": {"tag", "battle", "target"},
}
_MOVING_ENEMY_FIELDS = {
    "turns",
    "normal_turns",
    "wait_until_clear",
    "initial_enemy_cells",
    "initial_siren_cells",
}
_REQUIRED_MOVING_ENEMY_FIELDS = _MOVING_ENEMY_FIELDS - {"normal_turns"}
_MAP_STRUCTURE_FIELDS = {
    "walls",
    "maze_groups",
    "fortress_enemy_cells",
    "fortress_block_cells",
    "bouncing_enemy_routes",
}
_BOSS_APPROACH_FIELDS = {"battle", "activation_modes", "actions"}
_BOSS_APPROACH_ACTION_FIELDS = {
    "move_best_candidate": {"tag", "fleet", "candidates", "sort"},
    "move": {"tag", "fleet", "destination"},
}
_HARD_MODE_FIELDS = {"boss_strategy", "equipment_cleanup"}
_BASE_FEATURE_RULE_FIELDS = {
    "MAP_HAS_MAP_STORY",
    "MAP_HAS_FLEET_STEP",
    "MAP_HAS_AMBUSH",
    "MAP_HAS_MYSTERY",
}
_SIREN_RULE_FIELDS = {"MAP_SIREN_TEMPLATE", "MAP_HAS_SIREN"}
_MAP_STRUCTURE_RULE_FIELDS = {"MAP_HAS_PORTAL", "MAP_HAS_LAND_BASED"}
_STAR_RULE_FIELDS = {"STAR_REQUIRE_1", "STAR_REQUIRE_2", "STAR_REQUIRE_3"}
_NAVIGATION_COMMON_FIELDS = {
    "STAGE_ENTRANCE",
    "MAP_HAS_MODE_SWITCH",
}
_CHAPTER_SWITCH_RULE_FIELDS = {
    "MAP_CHAPTER_SWITCH_20241219",
    "MAP_CHAPTER_SWITCH_20241219_SP",
    "MAP_CHAPTER_SWITCH_20241219_SPEX",
}
_CALIBRATION_RULE_FIELDS = {"MAP_SWIPE_MULTIPLY", "MAP_SWIPE_MULTIPLY_MINITOUCH"}
_ONE_TIME_RULE_FIELDS = {"MAP_IS_ONE_TIME_STAGE"}
_OPTIONAL_CALIBRATION_FIELDS = {"HOMO_STORAGE", "MAP_ENSURE_EDGE_INSIGHT_CORNER"}
_STAGE_RULE_FIELDS = (
    _BASE_FEATURE_RULE_FIELDS
    | _SIREN_RULE_FIELDS
    | _MAP_STRUCTURE_RULE_FIELDS
    | _STAR_RULE_FIELDS
    | _NAVIGATION_COMMON_FIELDS
    | _CHAPTER_SWITCH_RULE_FIELDS
    | _CALIBRATION_RULE_FIELDS
    | _ONE_TIME_RULE_FIELDS
    | _OPTIONAL_CALIBRATION_FIELDS
)


def _fail(path: Path, location: str, message: str) -> ContentValidationError:
    return ContentValidationError(f"{path}:{location}: {message}")


def _mapping(value: object, path: Path, location: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise _fail(path, location, "must be a mapping")
    return cast("Mapping[object, object]", value)


def _fields_mapping(
    value: object,
    path: Path,
    location: str,
    fields: set[str],
) -> Mapping[str, object]:
    mapping = _mapping(value, path, location)
    if any(not isinstance(key, str) for key in mapping):
        raise _fail(path, location, "field names must be strings")
    result = cast("Mapping[str, object]", mapping)
    unknown = set(result) - fields
    if unknown:
        raise _fail(path, location, f"unknown fields: {sorted(unknown)}")
    return result


def _sequence(value: object, path: Path, location: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _fail(path, location, "must be a list")
    return value


def _string(value: object, path: Path, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(path, location, "must be a non-empty string")
    return value


def _exact_integer(value: object, path: Path, location: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise _fail(path, location, f"must be an integer greater than or equal to {minimum}")
    return value


def _load_yaml(path: Path) -> Mapping[str, object]:
    return _fields_mapping(load_strict_yaml_mapping(path), path, "$", _TOP_LEVEL_FIELDS)


def _grid_node(value: object, path: Path, location: str, shape: tuple[int, int]) -> CellId:
    node = _string(value, path, location)
    try:
        cell = CellId.parse(node)
    except ContentValidationError as error:
        raise _fail(path, location, str(error)) from error
    if cell.x > shape[0] or cell.y > shape[1]:
        raise _fail(path, location, f"grid node {node} is outside shape")
    return cell


def _grid_nodes(value: object, path: Path, location: str, shape: tuple[int, int]) -> tuple[CellId, ...]:
    return tuple(
        _grid_node(node, path, f"{location}[{index}]", shape)
        for index, node in enumerate(_sequence(value, path, location))
    )


def _map_text(
    value: object,
    path: Path,
    location: str,
    shape: tuple[int, int],
) -> str:
    text = _string(value, path, location)
    rows = [row.split() for row in text.splitlines() if row.strip()]
    expected_height = shape[1] + 1
    expected_width = shape[0] + 1
    if len(rows) != expected_height or any(len(row) != expected_width for row in rows):
        raise _fail(path, location, f"must contain {expected_height} rows of {expected_width} values")
    return text


def _map_data_text(value: object, path: Path, location: str, shape: tuple[int, int]) -> str:
    text = _map_text(value, path, location, shape)
    unknown = sorted({token for token in text.split() if token.upper() not in MAP_CELL_TOKENS})
    if unknown:
        raise _fail(path, location, f"unknown map data tokens: {unknown}")
    return text


def _weight_text(value: object, path: Path, location: str, shape: tuple[int, int]) -> str:
    text = _map_text(value, path, location, shape)
    try:
        numbers = [float(item) for item in text.split()]
    except ValueError as error:
        raise _fail(path, location, "must contain only numeric weights") from error
    if any(not math.isfinite(number) for number in numbers):
        raise _fail(path, location, "must contain only finite weights")
    return text


def _spawn_data(value: object, path: Path, location: str) -> tuple[SpawnWave, ...]:
    result: list[SpawnWave] = []
    for index, raw_item in enumerate(_sequence(value, path, location)):
        item_location = f"{location}[{index}]"
        item = _fields_mapping(raw_item, path, item_location, _SPAWN_FIELDS)
        if "battle" not in item:
            raise _fail(path, item_location, "required field is battle")
        battle = _exact_integer(item["battle"], path, f"{item_location}.battle")
        if battle != index:
            raise _fail(path, f"{item_location}.battle", "spawn battles must be contiguous and ordered from zero")
        counts = {"enemy": 0, "siren": 0, "mystery": 0, "boss": 0}
        for field in ("enemy", "siren", "mystery", "boss"):
            if field not in item:
                continue
            count = _exact_integer(item[field], path, f"{item_location}.{field}", minimum=1)
            if field == "boss" and count != 1:
                raise _fail(path, f"{item_location}.boss", "boss count must be 1")
            counts[field] = count
        result.append(
            SpawnWave(
                battle=battle,
                enemy=counts["enemy"],
                siren=counts["siren"],
                mystery=counts["mystery"],
                boss=counts["boss"],
            )
        )
    return tuple(result)


def _portal_data(value: object, path: Path, location: str, shape: tuple[int, int]) -> tuple[PortalSpec, ...]:
    result: list[PortalSpec] = []
    for index, raw_item in enumerate(_sequence(value, path, location)):
        item_location = f"{location}[{index}]"
        item = _sequence(raw_item, path, item_location)
        if len(item) != 2:
            raise _fail(path, item_location, "portal must contain exactly two grid nodes")
        result.append(
            PortalSpec(
                _grid_node(item[0], path, f"{item_location}[0]", shape),
                _grid_node(item[1], path, f"{item_location}[1]", shape),
            )
        )
    return tuple(result)


def _land_based_data(
    value: object,
    path: Path,
    location: str,
    shape: tuple[int, int],
) -> tuple[LandBasedSpec, ...]:
    result: list[LandBasedSpec] = []
    for index, raw_item in enumerate(_sequence(value, path, location)):
        item_location = f"{location}[{index}]"
        item = _sequence(raw_item, path, item_location)
        if len(item) != 2 or item[1] not in {"up", "down", "left", "right"}:
            raise _fail(path, item_location, "land based entry must contain a grid node and direction")
        result.append(
            LandBasedSpec(
                _grid_node(item[0], path, f"{item_location}[0]", shape),
                LandBasedDirection(cast("str", item[1])),
            )
        )
    return tuple(result)


def _boolean(value: object, path: Path, location: str) -> bool:
    if type(value) is not bool:
        raise _fail(path, location, "must be a boolean")
    return value


def _finite_float(value: object, path: Path, location: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise _fail(path, location, "must be a finite number")
    result = float(cast("int | float", value))
    if not math.isfinite(result) or (positive and result <= 0):
        qualifier = "positive " if positive else ""
        raise _fail(path, location, f"must be a {qualifier}finite number")
    return result


def _complete_field_group(
    mapping: Mapping[str, object],
    path: Path,
    fields: set[str],
    *,
    group: str,
) -> bool:
    present = set(mapping) & fields
    if present and present != fields:
        missing = fields - present
        raise _fail(path, "config", f"{group} fields must be declared together; missing {sorted(missing)}")
    return bool(present)


def _string_tuple(value: object, path: Path, location: str) -> tuple[str, ...]:
    return tuple(
        _string(item, path, f"{location}[{index}]") for index, item in enumerate(_sequence(value, path, location))
    )


def _positive_integer_tuple(value: object, path: Path, location: str) -> tuple[int, ...]:
    return tuple(
        _exact_integer(item, path, f"{location}[{index}]", minimum=1)
        for index, item in enumerate(_sequence(value, path, location))
    )


def _swipe_scale(value: object, path: Path, location: str) -> SwipeScale:
    if type(value) in (int, float):
        scale = _finite_float(value, path, location, positive=True)
        return SwipeScale(scale, scale)
    values = _sequence(value, path, location)
    if len(values) != 2:
        raise _fail(path, location, "must contain exactly two scale values")
    return SwipeScale(
        _finite_float(values[0], path, f"{location}[0]", positive=True),
        _finite_float(values[1], path, f"{location}[1]", positive=True),
    )


def _homography(value: object, path: Path) -> Homography:
    location = "config.HOMO_STORAGE"
    values = _sequence(value, path, location)
    if len(values) != 2:
        raise _fail(path, location, "must contain a reference shape and four corners")
    shape = _sequence(values[0], path, f"{location}[0]")
    if len(shape) != 2:
        raise _fail(path, f"{location}[0]", "reference shape must contain exactly two values")
    columns = _exact_integer(shape[0], path, f"{location}[0][0]", minimum=1)
    rows = _exact_integer(shape[1], path, f"{location}[0][1]", minimum=1)
    raw_corners = _sequence(values[1], path, f"{location}[1]")
    if len(raw_corners) != 4:
        raise _fail(path, f"{location}[1]", "must contain exactly four corners")
    corners: list[CalibrationPoint] = []
    for index, raw_point in enumerate(raw_corners):
        point_location = f"{location}[1][{index}]"
        point = _sequence(raw_point, path, point_location)
        if len(point) != 2:
            raise _fail(path, point_location, "calibration point must contain exactly two coordinates")
        corners.append(
            CalibrationPoint(
                _finite_float(point[0], path, f"{point_location}[0]"),
                _finite_float(point[1], path, f"{point_location}[1]"),
            )
        )
    return Homography(columns, rows, tuple(corners))


def _stage_entrance(value: object, path: Path) -> StageEntrance | StageEntrancePreset:
    location = "config.STAGE_ENTRANCE"
    values = _sequence(value, path, location)
    profile = tuple(_string(item, path, f"{location}[{index}]") for index, item in enumerate(values))
    try:
        if profile == ("half", "20240725"):
            return StageEntrance(StageEntrancePosition.HALF, StageEntranceRevision.EVENT_20240725)
        preset_by_profile = {
            ("blue",): StageEntrancePreset.BLUE,
            ("green",): StageEntrancePreset.GREEN,
            ("normal", "half"): StageEntrancePreset.NORMAL_HALF,
        }
        return preset_by_profile[profile]
    except KeyError as error:
        raise _fail(path, location, f"uses an unsupported entrance profile: {profile!r}") from error
    except ValueError as error:
        raise _fail(path, location, "uses an unsupported position or revision") from error


def _structure_feature(
    mapping: Mapping[str, object],
    path: Path,
    field: str,
    *,
    expected: bool,
) -> bool:
    if field not in mapping:
        if expected:
            raise _fail(path, "config", f"{field} is required by the map structure")
        return False
    value = _boolean(mapping[field], path, f"config.{field}")
    if not value:
        raise _fail(path, f"config.{field}", "must be true when declared")
    if not expected:
        raise _fail(path, f"config.{field}", "requires matching map data")
    return True


def _map_features(
    mapping: Mapping[str, object],
    path: Path,
    map_definition: MapDefinition,
    moving_enemies: MovingEnemyRules,
) -> MapFeatures:
    has_siren_group = _complete_field_group(mapping, path, _SIREN_RULE_FIELDS, group="siren")
    if has_siren_group:
        templates = _string_tuple(mapping["MAP_SIREN_TEMPLATE"], path, "config.MAP_SIREN_TEMPLATE")
        has_siren = _boolean(mapping["MAP_HAS_SIREN"], path, "config.MAP_HAS_SIREN")
    else:
        templates = ()
        has_siren = False
    return MapFeatures(
        siren_templates=templates,
        movable_enemy_turns=moving_enemies.turns,
        movable_normal_enemy_turns=moving_enemies.normal_turns,
        has_siren=has_siren,
        has_movable_enemy=bool(moving_enemies.turns),
        has_map_story=_boolean(mapping["MAP_HAS_MAP_STORY"], path, "config.MAP_HAS_MAP_STORY"),
        has_fleet_step=_boolean(mapping["MAP_HAS_FLEET_STEP"], path, "config.MAP_HAS_FLEET_STEP"),
        has_ambush=_boolean(mapping["MAP_HAS_AMBUSH"], path, "config.MAP_HAS_AMBUSH"),
        has_mystery=_boolean(mapping["MAP_HAS_MYSTERY"], path, "config.MAP_HAS_MYSTERY"),
        has_portal=_structure_feature(
            mapping,
            path,
            "MAP_HAS_PORTAL",
            expected=bool(map_definition.portals),
        ),
        has_land_based=_structure_feature(
            mapping,
            path,
            "MAP_HAS_LAND_BASED",
            expected=bool(map_definition.land_based),
        ),
    )


def _completion(
    mapping: Mapping[str, object], path: Path, *, is_one_time: bool
) -> RepeatableCompletion | OneTimeCompletion:
    stars = StarRequirements(
        first=(
            _exact_integer(mapping["STAR_REQUIRE_1"], path, "config.STAR_REQUIRE_1")
            if "STAR_REQUIRE_1" in mapping
            else 1
        ),
        second=(
            _exact_integer(mapping["STAR_REQUIRE_2"], path, "config.STAR_REQUIRE_2")
            if "STAR_REQUIRE_2" in mapping
            else 2
        ),
        third=(
            _exact_integer(mapping["STAR_REQUIRE_3"], path, "config.STAR_REQUIRE_3")
            if "STAR_REQUIRE_3" in mapping
            else 3
        ),
    )
    return OneTimeCompletion(stars) if is_one_time else RepeatableCompletion(stars)


def _navigation(mapping: Mapping[str, object], path: Path, *, declared: bool) -> StageNavigation | None:
    if not declared:
        return None
    missing = _NAVIGATION_COMMON_FIELDS - set(mapping)
    if missing:
        raise _fail(path, "config", f"navigation fields must be declared together; missing {sorted(missing)}")
    switch_fields = tuple(field for field in _CHAPTER_SWITCH_RULE_FIELDS if field in mapping)
    if len(switch_fields) > 1:
        raise _fail(path, "config", "navigation may declare only one chapter switch")
    chapter_switch = None
    if switch_fields:
        field = switch_fields[0]
        if not _boolean(mapping[field], path, f"config.{field}"):
            raise _fail(path, f"config.{field}", "must be true when declared")
        chapter_switch = {
            "MAP_CHAPTER_SWITCH_20241219": ChapterSwitch.EVENT_20241219,
            "MAP_CHAPTER_SWITCH_20241219_SP": ChapterSwitch.SP_20241219,
            "MAP_CHAPTER_SWITCH_20241219_SPEX": ChapterSwitch.SPEX_20241219,
        }[field]
    return StageNavigation(
        chapter_switch=chapter_switch,
        entrance=_stage_entrance(mapping["STAGE_ENTRANCE"], path),
        has_mode_switch=_boolean(
            mapping["MAP_HAS_MODE_SWITCH"],
            path,
            "config.MAP_HAS_MODE_SWITCH",
        ),
    )


def _map_calibration(
    mapping: Mapping[str, object],
    path: Path,
    *,
    declared: bool,
    is_one_time: bool,
) -> MapCalibration | None:
    if not declared:
        if not is_one_time:
            return None
        raise _fail(path, "config", "one-time stage fields require calibration fields")
    homography = _homography(mapping["HOMO_STORAGE"], path) if "HOMO_STORAGE" in mapping else None
    corner = None
    if "MAP_ENSURE_EDGE_INSIGHT_CORNER" in mapping:
        raw_corner = _string(
            mapping["MAP_ENSURE_EDGE_INSIGHT_CORNER"],
            path,
            "config.MAP_ENSURE_EDGE_INSIGHT_CORNER",
        )
        try:
            corner = EdgeInsightCorner(raw_corner)
        except ValueError as error:
            raise _fail(
                path,
                "config.MAP_ENSURE_EDGE_INSIGHT_CORNER",
                "uses an unsupported edge insight corner",
            ) from error
    return MapCalibration(
        swipe=_swipe_scale(mapping["MAP_SWIPE_MULTIPLY"], path, "config.MAP_SWIPE_MULTIPLY"),
        minitouch_swipe=_swipe_scale(
            mapping["MAP_SWIPE_MULTIPLY_MINITOUCH"],
            path,
            "config.MAP_SWIPE_MULTIPLY_MINITOUCH",
        ),
        homography=homography,
        edge_insight_corner=corner,
    )


def _stage_rules(
    value: object,
    path: Path,
    map_definition: MapDefinition,
    moving_enemies: MovingEnemyRules,
) -> StageRules:
    mapping = _fields_mapping(value, path, "config", _STAGE_RULE_FIELDS)
    missing_base = _BASE_FEATURE_RULE_FIELDS - set(mapping)
    if missing_base:
        raise _fail(path, "config", f"required map feature fields are missing: {sorted(missing_base)}")
    has_navigation = bool(set(mapping) & (_NAVIGATION_COMMON_FIELDS | _CHAPTER_SWITCH_RULE_FIELDS))
    has_calibration = _complete_field_group(mapping, path, _CALIBRATION_RULE_FIELDS, group="calibration")
    is_one_time = "MAP_IS_ONE_TIME_STAGE" in mapping
    if is_one_time and not _boolean(mapping["MAP_IS_ONE_TIME_STAGE"], path, "config.MAP_IS_ONE_TIME_STAGE"):
        raise _fail(path, "config.MAP_IS_ONE_TIME_STAGE", "must be true when declared")

    try:
        return StageRules(
            features=_map_features(mapping, path, map_definition, moving_enemies),
            completion=_completion(mapping, path, is_one_time=is_one_time),
            navigation=_navigation(mapping, path, declared=has_navigation),
            calibration=_map_calibration(
                mapping,
                path,
                declared=has_calibration,
                is_one_time=is_one_time,
            ),
        )
    except ContentValidationError as error:
        raise _fail(path, "config", str(error)) from error


def _tagged_item(
    value: object,
    path: Path,
    location: str,
    fields_by_tag: Mapping[str, set[str]],
) -> tuple[str, Mapping[str, object]]:
    raw = _mapping(value, path, location)
    if "tag" not in raw:
        raise _fail(path, location, "required field is tag")
    tag = _string(raw["tag"], path, f"{location}.tag")
    fields = fields_by_tag.get(tag)
    if fields is None:
        raise _fail(path, f"{location}.tag", f"unknown tag: {tag!r}")
    item = _fields_mapping(value, path, location, fields)
    if set(item) != fields:
        raise _fail(path, location, f"required fields for {tag!r} are {sorted(fields)}")
    return tag, item


def _boss_strategy(value: object, path: Path, location: str) -> BossStrategy:
    raw = _string(value, path, location)
    try:
        return BossStrategy(raw)
    except ValueError as error:
        raise _fail(path, location, f"unknown boss strategy: {raw!r}") from error


def _battle_policies(
    value: object,
    path: Path,
    spawn_battles: AbstractSet[int],
) -> dict[int, StagePolicy]:
    mapping = _mapping(value, path, "battles")
    result: dict[int, StagePolicy] = {}
    for raw_battle, raw_policy in mapping.items():
        battle = _exact_integer(raw_battle, path, "battles.<key>")
        if battle not in spawn_battles:
            raise _fail(path, f"battles.{battle}", "battle is not declared in map spawn_data")
        try:
            result[battle] = decode_stage_policy(raw_policy, f"battles.{battle}")
        except ContentValidationError as error:
            message = f"{path}:{error}"
            raise ContentValidationError(message) from error
    return result


def _enum_value[E: StrEnum](enum: type[E], value: object, path: Path, location: str) -> E:
    raw = _string(value, path, location)
    try:
        return enum(raw)
    except ValueError as error:
        raise _fail(path, location, f"unknown {enum.__name__}: {raw!r}") from error


def _road_group(value: object, path: Path, location: str, shape: tuple[int, int]) -> RoadGroup:
    item = _fields_mapping(value, path, location, {"paths"})
    if set(item) != {"paths"}:
        raise _fail(path, location, "required field is paths")
    paths = tuple(
        RoadPath(_grid_nodes(raw_path, path, f"{location}.paths[{index}]", shape))
        for index, raw_path in enumerate(_sequence(item["paths"], path, f"{location}.paths"))
    )
    try:
        return RoadGroup(paths)
    except ContentValidationError as error:
        raise _fail(path, location, str(error)) from error


def _road_groups(value: object, path: Path, location: str, shape: tuple[int, int]) -> tuple[RoadGroup, ...]:
    return tuple(
        _road_group(raw_group, path, f"{location}[{index}]", shape)
        for index, raw_group in enumerate(_sequence(value, path, location))
    )


def _roadblock_rules(value: object, path: Path, shape: tuple[int, int]) -> RoadblockRules:
    actions: list[RoadblockAction] = []
    fields = {mode.value: _ROADBLOCK_FIELDS for mode in RoadblockMode}
    for index, raw_action in enumerate(_sequence(value, path, "mechanics.roadblocks")):
        location = f"mechanics.roadblocks[{index}]"
        tag, item = _tagged_item(raw_action, path, location, fields)
        actions.append(
            RoadblockAction(
                battle=_exact_integer(item["battle"], path, f"{location}.battle"),
                mode=RoadblockMode(tag),
                roads=_road_groups(item["roads"], path, f"{location}.roads", shape),
                selection=_enum_value(
                    RoadblockSelection,
                    item["selection"],
                    path,
                    f"{location}.selection",
                ),
            )
        )
    return RoadblockRules(tuple(actions))


def _fleet_role(value: object, path: Path, location: str) -> FleetRole:
    return _enum_value(FleetRole, value, path, location)


def _fleet_action(
    value: object,
    path: Path,
    location: str,
    shape: tuple[int, int],
) -> FleetCoordinationAction:
    tag, item = _tagged_item(value, path, location, _FLEET_ACTION_FIELDS)
    battle = _exact_integer(item["battle"], path, f"{location}.battle")
    fleet = _fleet_role(item["fleet"], path, f"{location}.fleet")
    if tag == "break_siren_caught":
        action: FleetCoordinationAction = BreakSirenCaught(battle=battle, fleet=fleet)
    elif tag == "push_forward":
        action = PushFleetForward(battle=battle, fleet=fleet)
    elif tag == "protect":
        action = ProtectFleet(battle=battle, fleet=fleet)
    elif tag == "rescue":
        action = RescueFleet(
            battle=battle,
            fleet=fleet,
            target=_grid_node(item["target"], path, f"{location}.target", shape),
        )
    elif tag == "step_on":
        action = StepFleetOn(
            battle=battle,
            fleet=fleet,
            candidates=_grid_nodes(item["candidates"], path, f"{location}.candidates", shape),
            roadblocks=_road_groups(item["roadblocks"], path, f"{location}.roadblocks", shape),
        )
    elif tag == "move":
        action = MoveFleet(
            battle=battle,
            fleet=fleet,
            destination=_grid_node(item["destination"], path, f"{location}.destination", shape),
            expected=_enum_value(
                EncounterExpectation,
                item["expected"],
                path,
                f"{location}.expected",
            ),
        )
    elif tag == "ensure":
        action = EnsureFleet(battle=battle, fleet=fleet)
    elif tag == "ensure_at":
        action = EnsureFleetAt(
            battle=battle,
            fleet=fleet,
            target=_grid_node(item["target"], path, f"{location}.target", shape),
        )
    elif tag == "clear_target":
        action = FleetClearTarget(
            battle=battle,
            fleet=fleet,
            target=_grid_node(item["target"], path, f"{location}.target", shape),
            expected=_enum_value(
                EncounterExpectation,
                item["expected"],
                path,
                f"{location}.expected",
            ),
        )
    else:
        action = FleetClearSelectedTarget(
            battle=battle,
            fleet=fleet,
            candidates=_grid_nodes(item["candidates"], path, f"{location}.candidates", shape),
            expected=_enum_value(
                EncounterExpectation,
                item["expected"],
                path,
                f"{location}.expected",
            ),
        )
    return action


def _fleet_coordination_rules(value: object, path: Path, shape: tuple[int, int]) -> FleetCoordinationRules:
    location = "mechanics.fleet_coordination"
    actions = tuple(
        _fleet_action(raw_action, path, f"{location}[{index}]", shape)
        for index, raw_action in enumerate(_sequence(value, path, location))
    )
    return FleetCoordinationRules(actions)


def _pickup_rules(value: object, path: Path, shape: tuple[int, int]) -> PickupRules:
    location = "mechanics.pickups"
    actions: list[PickupAmmo | PickupMapItem] = []
    for index, raw_action in enumerate(_sequence(value, path, location)):
        item_location = f"{location}[{index}]"
        tag, item = _tagged_item(raw_action, path, item_location, _PICKUP_FIELDS)
        battle = _exact_integer(item["battle"], path, f"{item_location}.battle")
        fleet = _fleet_role(item["fleet"], path, f"{item_location}.fleet")
        if tag == "ammo":
            actions.append(PickupAmmo(battle=battle, fleet=fleet))
        else:
            actions.append(
                PickupMapItem(
                    battle=battle,
                    fleet=fleet,
                    kind=_enum_value(MapItemKind, item["kind"], path, f"{item_location}.kind"),
                    cell=_grid_node(item["cell"], path, f"{item_location}.cell", shape),
                )
            )
    return PickupRules(tuple(actions))


def _map_interaction_rules(value: object, path: Path, shape: tuple[int, int]) -> MapInteractionRules:
    location = "mechanics.map_interactions"
    actions: list[ClearAllMystery | ClearChosenMystery | ClearMechanism | ClearMapItems | AirStrike] = []
    for index, raw_action in enumerate(_sequence(value, path, location)):
        item_location = f"{location}[{index}]"
        tag, item = _tagged_item(raw_action, path, item_location, _MAP_INTERACTION_FIELDS)
        battle = _exact_integer(item["battle"], path, f"{item_location}.battle")
        if tag == "clear_all_mystery":
            actions.append(
                ClearAllMystery(
                    battle=battle,
                    nearby=_boolean(item["nearby"], path, f"{item_location}.nearby"),
                    ignored=_grid_nodes(item["ignored"], path, f"{item_location}.ignored", shape),
                )
            )
        elif tag == "clear_chosen_mystery":
            actions.append(
                ClearChosenMystery(
                    battle=battle,
                    fleet=_fleet_role(item["fleet"], path, f"{item_location}.fleet"),
                    cell=_grid_node(item["cell"], path, f"{item_location}.cell", shape),
                )
            )
        elif tag == "clear_mechanism":
            actions.append(
                ClearMechanism(
                    battle=battle,
                    cells=_grid_nodes(item["cells"], path, f"{item_location}.cells", shape),
                )
            )
        elif tag == "clear_map_items":
            actions.append(
                ClearMapItems(
                    battle=battle,
                    cells=_grid_nodes(item["cells"], path, f"{item_location}.cells", shape),
                )
            )
        else:
            actions.append(
                AirStrike(
                    battle=battle,
                    target=_grid_node(item["target"], path, f"{item_location}.target", shape),
                )
            )
    return MapInteractionRules(tuple(actions))


def _moving_enemy_rules(value: object, path: Path, shape: tuple[int, int]) -> MovingEnemyRules:
    location = "mechanics.moving_enemies"
    item = _fields_mapping(value, path, location, _MOVING_ENEMY_FIELDS)
    if not set(item) >= _REQUIRED_MOVING_ENEMY_FIELDS:
        raise _fail(path, location, f"required fields are {sorted(_REQUIRED_MOVING_ENEMY_FIELDS)}")
    try:
        return MovingEnemyRules(
            turns=_positive_integer_tuple(item["turns"], path, f"{location}.turns"),
            normal_turns=(
                _positive_integer_tuple(item["normal_turns"], path, f"{location}.normal_turns")
                if "normal_turns" in item
                else ()
            ),
            wait_until_clear=_boolean(item["wait_until_clear"], path, f"{location}.wait_until_clear"),
            initial_enemy_cells=_grid_nodes(
                item["initial_enemy_cells"],
                path,
                f"{location}.initial_enemy_cells",
                shape,
            ),
            initial_siren_cells=_grid_nodes(
                item["initial_siren_cells"],
                path,
                f"{location}.initial_siren_cells",
                shape,
            ),
        )
    except ContentValidationError as error:
        raise _fail(path, location, str(error)) from error


def _map_structure_rules(value: object, path: Path, shape: tuple[int, int]) -> MapStructureRules:
    location = "mechanics.map_structures"
    item = _fields_mapping(value, path, location, _MAP_STRUCTURE_FIELDS)
    if set(item) != _MAP_STRUCTURE_FIELDS:
        raise _fail(path, location, f"required fields are {sorted(_MAP_STRUCTURE_FIELDS)}")
    walls = []
    for index, raw_wall in enumerate(_sequence(item["walls"], path, f"{location}.walls")):
        wall_location = f"{location}.walls[{index}]"
        endpoints = _sequence(raw_wall, path, wall_location)
        if len(endpoints) != 2:
            raise _fail(path, wall_location, "wall must contain two endpoints")
        walls.append(
            WallEdge(
                _grid_node(endpoints[0], path, f"{wall_location}[0]", shape),
                _grid_node(endpoints[1], path, f"{wall_location}[1]", shape),
            )
        )

    def groups(field: str) -> tuple[tuple[CellId, ...], ...]:
        return tuple(
            _grid_nodes(raw_group, path, f"{location}.{field}[{index}]", shape)
            for index, raw_group in enumerate(_sequence(item[field], path, f"{location}.{field}"))
        )

    return MapStructureRules(
        walls=tuple(walls),
        maze_groups=groups("maze_groups"),
        fortress_enemy_cells=_grid_nodes(
            item["fortress_enemy_cells"],
            path,
            f"{location}.fortress_enemy_cells",
            shape,
        ),
        fortress_block_cells=_grid_nodes(
            item["fortress_block_cells"],
            path,
            f"{location}.fortress_block_cells",
            shape,
        ),
        bouncing_enemy_routes=groups("bouncing_enemy_routes"),
    )


def _mechanic_rules(value: object, path: Path, map_definition: MapDefinition) -> StageMechanicRules:
    item = _fields_mapping(value, path, "mechanics", _MECHANIC_FIELDS)
    if set(item) != _MECHANIC_FIELDS:
        raise _fail(path, "mechanics", f"required fields are {sorted(_MECHANIC_FIELDS)}")
    shape = (map_definition.shape.columns - 1, map_definition.shape.rows - 1)
    try:
        enemy_movement = decode_enemy_movement_rules(
            item["enemy_movement"],
            "mechanics.enemy_movement",
        )
        procedures = decode_mechanic_procedures(
            item["procedures"],
            "mechanics.procedures",
        )
    except ContentValidationError as error:
        raise _fail(path, "mechanics", str(error)) from error
    return StageMechanicRules(
        roadblocks=_roadblock_rules(item["roadblocks"], path, shape),
        fleet_coordination=_fleet_coordination_rules(item["fleet_coordination"], path, shape),
        pickups=_pickup_rules(item["pickups"], path, shape),
        map_interactions=_map_interaction_rules(item["map_interactions"], path, shape),
        moving_enemies=_moving_enemy_rules(item["moving_enemies"], path, shape),
        map_structures=_map_structure_rules(item["map_structures"], path, shape),
        enemy_movement=enemy_movement,
        procedures=procedures,
    )


def _battle_programs(
    value: object,
    path: Path,
    mechanics: StageMechanicRules,
) -> dict[int, BattleProgram]:
    programs: dict[int, BattleProgram] = {}
    for index, raw_program in enumerate(_sequence(value, path, "programs")):
        location = f"programs[{index}]"
        try:
            program = decode_battle_program(raw_program, location, mechanics)
        except ContentValidationError as error:
            raise _fail(path, location, str(error)) from error
        if program.battle in programs:
            raise _fail(path, location, f"duplicate battle program {program.battle}")
        programs[program.battle] = program
    return programs


def _boss_approaches(
    value: object,
    path: Path,
    shape: tuple[int, int],
) -> dict[int, BossApproachPlan]:
    approaches: dict[int, BossApproachPlan] = {}
    for index, raw_approach in enumerate(_sequence(value, path, "boss_approaches")):
        location = f"boss_approaches[{index}]"
        item = _fields_mapping(raw_approach, path, location, _BOSS_APPROACH_FIELDS)
        if set(item) != _BOSS_APPROACH_FIELDS:
            raise _fail(path, location, f"required fields are {sorted(_BOSS_APPROACH_FIELDS)}")
        battle = _exact_integer(item["battle"], path, f"{location}.battle")
        modes = tuple(
            _enum_value(
                BattleProgramMode,
                raw_mode,
                path,
                f"{location}.activation_modes[{mode_index}]",
            )
            for mode_index, raw_mode in enumerate(
                _sequence(item["activation_modes"], path, f"{location}.activation_modes")
            )
        )
        if len(set(modes)) != len(modes):
            raise _fail(path, f"{location}.activation_modes", "must not contain duplicates")
        actions = []
        for action_index, raw_action in enumerate(_sequence(item["actions"], path, f"{location}.actions")):
            action_location = f"{location}.actions[{action_index}]"
            free_action = _mapping(raw_action, path, action_location)
            tag = _string(free_action.get("tag"), path, f"{action_location}.tag")
            fields = _BOSS_APPROACH_ACTION_FIELDS.get(tag)
            if fields is None:
                raise _fail(path, f"{action_location}.tag", f"unknown boss approach action {tag!r}")
            action = _fields_mapping(raw_action, path, action_location, fields)
            if set(action) != fields:
                raise _fail(path, action_location, f"required fields are {sorted(fields)}")
            fleet = _fleet_role(action["fleet"], path, f"{action_location}.fleet")
            if tag == "move":
                actions.append(
                    MoveFleet(
                        battle,
                        _grid_node(
                            action["destination"],
                            path,
                            f"{action_location}.destination",
                            shape,
                        ),
                        fleet,
                    )
                )
            else:
                actions.append(
                    MoveFleetToBestCandidate(
                        battle,
                        _grid_nodes(
                            action["candidates"],
                            path,
                            f"{action_location}.candidates",
                            shape,
                        ),
                        fleet,
                        tuple(
                            _enum_value(
                                CandidateSortKey,
                                raw_sort,
                                path,
                                f"{action_location}.sort[{sort_index}]",
                            )
                            for sort_index, raw_sort in enumerate(
                                _sequence(action["sort"], path, f"{action_location}.sort")
                            )
                        ),
                    )
                )
        try:
            approach = BossApproachPlan(battle, frozenset(modes), tuple(actions))
        except ContentValidationError as error:
            raise _fail(path, location, str(error)) from error
        if battle in approaches:
            raise _fail(path, location, f"duplicate boss approach {battle}")
        approaches[battle] = approach
    return approaches


def _hard_mode_policy(value: object, path: Path) -> HardModeRuntimePolicy | None:
    if value is None:
        return None
    item = _fields_mapping(value, path, "hard_mode", _HARD_MODE_FIELDS)
    if set(item) != _HARD_MODE_FIELDS:
        raise _fail(path, "hard_mode", f"required fields are {sorted(_HARD_MODE_FIELDS)}")
    return HardModeRuntimePolicy(
        boss_strategy=_boss_strategy(item["boss_strategy"], path, "hard_mode.boss_strategy"),
        equipment_cleanup=_enum_value(
            HardModeEquipmentCleanup,
            item["equipment_cleanup"],
            path,
            "hard_mode.equipment_cleanup",
        ),
    )


def _cell_specs(map_text: str, weight_text: str) -> tuple[CellSpec, ...]:
    map_rows = tuple(tuple(row.split()) for row in map_text.splitlines() if row.strip())
    weight_rows = tuple(tuple(row.split()) for row in weight_text.splitlines() if row.strip())
    return tuple(
        CellSpec(
            cell_id=CellId(x, y),
            token=token,
            weight=float(weight_rows[y][x]),
        )
        for y, row in enumerate(map_rows)
        for x, token in enumerate(row)
    )


def _build_map_definition(value: object, path: Path) -> MapDefinition:
    data = _fields_mapping(value, path, "map", _MAP_FIELDS)
    missing = _REQUIRED_MAP_FIELDS - set(data)
    if missing:
        raise _fail(path, "map", f"missing required fields: {sorted(missing)}")
    name = _string(data["name"], path, "map.name")
    shape_name = _string(data["shape"], path, "map.shape")
    try:
        max_cell = CellId.parse(shape_name)
    except ContentValidationError as error:
        raise _fail(path, "map.shape", "must be a valid uppercase shape") from error
    max_coordinate = (max_cell.x, max_cell.y)
    shape = GridShape(columns=max_coordinate[0] + 1, rows=max_coordinate[1] + 1)
    map_data = _map_data_text(data["map_data"], path, "map.map_data", max_coordinate)
    weight_data = _weight_text(data["weight_data"], path, "map.weight_data", max_coordinate)
    loop_map_data = map_data
    if "map_data_loop" in data:
        loop_map_data = _map_data_text(
            data["map_data_loop"],
            path,
            "map.map_data_loop",
            max_coordinate,
        )
    spawn_data = _spawn_data(data["spawn_data"], path, "map.spawn_data")
    loop_spawn_data = spawn_data
    if "spawn_data_loop" in data:
        loop_spawn_data = _spawn_data(data["spawn_data_loop"], path, "map.spawn_data_loop")

    return MapDefinition(
        name=name,
        shape=shape,
        camera_data=_grid_nodes(data["camera_data"], path, "map.camera_data", max_coordinate),
        camera_data_spawn_point=_grid_nodes(
            data["camera_data_spawn_point"],
            path,
            "map.camera_data_spawn_point",
            max_coordinate,
        ),
        normal=RunVariant(cells=_cell_specs(map_data, weight_data), spawn_waves=spawn_data),
        loop=RunVariant(cells=_cell_specs(loop_map_data, weight_data), spawn_waves=loop_spawn_data),
        map_covered=(
            _grid_nodes(data["map_covered"], path, "map.map_covered", max_coordinate) if "map_covered" in data else ()
        ),
        portals=(
            _portal_data(data["portal_data"], path, "map.portal_data", max_coordinate) if "portal_data" in data else ()
        ),
        land_based=(
            _land_based_data(data["land_based_data"], path, "map.land_based_data", max_coordinate)
            if "land_based_data" in data
            else ()
        ),
        normal_enemy_spawn_candidates=(
            _grid_nodes(
                data["normal_enemy_spawn_candidates"],
                path,
                "map.normal_enemy_spawn_candidates",
                max_coordinate,
            )
            if "normal_enemy_spawn_candidates" in data
            else None
        ),
    )


def _safe_direct_child(root: Path, child_name: str, path: Path, location: str) -> Path:
    resolved_root = root.resolve()
    resolved = (root / child_name).resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as error:
        raise _fail(path, location, "pack directory must stay inside its root") from error
    if relative.parts != (child_name,):
        raise _fail(path, location, "pack directory must be a direct child of its root")
    return resolved


def _stage_path(spec: StageSpec, content_root: Path) -> tuple[Path, Path]:
    pack_root = _safe_direct_child(content_root, spec.ref.pack_id, Path(spec.source), "source")
    relative = Path(spec.source)
    if relative.is_absolute() or ".." in relative.parts:
        raise _fail(relative, "source", "must stay inside the pack content directory")
    path = (pack_root / relative).resolve()
    try:
        path.relative_to(pack_root)
    except ValueError as error:
        raise _fail(path, "source", "must stay inside the pack content directory") from error
    if not path.is_file():
        raise _fail(path, "source", "file does not exist")
    return path, pack_root


class StageSpecLoader:
    __slots__ = ("content_root", "runtime_profile_registry")

    def __init__(
        self,
        content_root: Path = DEFAULT_EVENT_MANIFEST_PATH,
        runtime_profile_registry: CampaignRuntimeProfileRegistry | None = None,
    ) -> None:
        self.content_root = Path(content_root)
        self.runtime_profile_registry = (
            load_default_campaign_runtime_profile_registry()
            if runtime_profile_registry is None
            else runtime_profile_registry
        )
        if not isinstance(self.runtime_profile_registry, CampaignRuntimeProfileRegistry):
            message = "native stage loader runtime_profile_registry must be a CampaignRuntimeProfileRegistry"
            raise TypeError(message)

    def load(self, spec: StageSpec) -> CampaignStageDefinition:
        if not isinstance(spec, StageSpec):
            message = "native stage loader requires a StageSpec"
            raise TypeError(message)
        path, _pack_root = _stage_path(spec, self.content_root)
        data = _load_yaml(path)
        required = _TOP_LEVEL_FIELDS
        if set(data) != required:
            raise _fail(path, "$", f"required fields are {sorted(required)}")
        version = _exact_integer(data["schema_version"], path, "schema_version", minimum=1)
        if version != SCHEMA_VERSION:
            raise _fail(path, "schema_version", f"must be {SCHEMA_VERSION}")
        map_definition = _build_map_definition(data["map"], path)
        if map_definition.name.casefold() != spec.ref.stage_id.casefold():
            raise _fail(path, "map.name", f"must match manifest stage id {spec.ref.stage_id!r}")
        mechanics = _mechanic_rules(data["mechanics"], path, map_definition)
        programs = _battle_programs(data["programs"], path, mechanics)
        boss_approaches = _boss_approaches(
            data["boss_approaches"],
            path,
            (map_definition.shape.columns - 1, map_definition.shape.rows - 1),
        )
        rules = _stage_rules(data["config"], path, map_definition, mechanics.moving_enemies)
        enemy_filter = _string(data["enemy_filter"], path, "enemy_filter")
        policies = _battle_policies(
            data["battles"],
            path,
            map_definition.battles,
        )
        try:
            return CampaignStageDefinition(
                ref=spec.ref,
                map=map_definition,
                rules=rules,
                enemy_filter=enemy_filter,
                battle_policies=policies,
                runtime_profile=self.runtime_profile_registry.resolve(spec.runtime_profile_id),
                mechanics=mechanics,
                battle_programs=programs,
                boss_approaches=boss_approaches,
                hard_mode=_hard_mode_policy(data["hard_mode"], path),
                war_archives=spec.war_archives,
            )
        except ContentValidationError as error:
            raise _fail(path, "$", str(error)) from error


@lru_cache(maxsize=1)
def _default_catalog() -> ContentCatalog:
    return ContentCatalog(load_default_event_manifests())


@lru_cache
def load_default_stage(ref: StageRef) -> CampaignStageDefinition:
    if not isinstance(ref, StageRef):
        message = "default native stage loader requires a StageRef"
        raise TypeError(message)
    spec = _default_catalog().resolve_stage(ref)
    return StageSpecLoader().load(spec)
