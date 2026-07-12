import importlib
import math
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import yaml
from yaml.resolver import BaseResolver

from module.base.utils import node2location
from module.campaign.campaign_base import CampaignBase
from module.content.battle_policy import BattlePolicy, BattlePolicyName
from module.content.catalog import ContentCatalog
from module.content.errors import ContentValidationError
from module.content.legacy_stage import LoadedStage
from module.content.manifest import DEFAULT_EVENT_MANIFEST_PATH, load_default_event_manifests
from module.content.models import StageRef, StageSpec
from module.map.map_base import CampaignMap

SCHEMA_VERSION = 1
DEFAULT_CAMPAIGN_ROOT = Path(__file__).resolve().parents[2] / "campaign"

_TOP_LEVEL_FIELDS = {"schema_version", "map", "config", "enemy_filter", "battles"}
_MAP_FIELDS = {
    "name",
    "shape",
    "camera_data",
    "camera_data_spawn_point",
    "map_data",
    "map_data_loop",
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
_BATTLE_FIELDS = {"policy", "preserve"}
_CONFIG_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_GRID_NODE = re.compile(r"^[A-Z]+[1-9][0-9]*$")
# SI 是历史关卡由自定义 map_data_init 补状态的已知占位。
_MAP_DATA_TOKENS = frozenset({"--", "++", "SP", "ME", "MB", "MS", "MM", "MA", "__", "SI"})


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _StrictLoader,
    node: yaml.MappingNode,
    *,
    deep: object = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=bool(deep))
        if key in mapping:
            message = f"duplicate YAML key: {key}"
            raise ContentValidationError(message)
        mapping[key] = loader.construct_object(value_node, deep=bool(deep))
    return mapping


_StrictLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


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
    try:
        loader = _StrictLoader(path.read_text(encoding="utf-8"))
        try:
            raw = loader.get_single_data()
        finally:
            loader.dispose()
    except (OSError, yaml.YAMLError, ContentValidationError) as error:
        if isinstance(error, ContentValidationError):
            raise
        raise _fail(path, "$", str(error)) from error
    return _fields_mapping(raw, path, "$", _TOP_LEVEL_FIELDS)


def _grid_node(value: object, path: Path, location: str, shape: tuple[int, int]) -> str:
    node = _string(value, path, location)
    if _GRID_NODE.fullmatch(node) is None:
        raise _fail(path, location, "must be a valid uppercase grid node")
    coordinate = node2location(node)
    if coordinate[0] > shape[0] or coordinate[1] > shape[1]:
        raise _fail(path, location, f"grid node {node} is outside shape")
    return node


def _grid_nodes(value: object, path: Path, location: str, shape: tuple[int, int]) -> list[str]:
    return [
        _grid_node(node, path, f"{location}[{index}]", shape)
        for index, node in enumerate(_sequence(value, path, location))
    ]


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
    unknown = sorted({token for token in text.split() if token.upper() not in _MAP_DATA_TOKENS})
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


def _spawn_data(value: object, path: Path, location: str) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    for index, raw_item in enumerate(_sequence(value, path, location)):
        item_location = f"{location}[{index}]"
        item = _fields_mapping(raw_item, path, item_location, _SPAWN_FIELDS)
        if "battle" not in item:
            raise _fail(path, item_location, "required field is battle")
        battle = _exact_integer(item["battle"], path, f"{item_location}.battle")
        if battle != index:
            raise _fail(path, f"{item_location}.battle", "spawn battles must be contiguous and ordered from zero")
        parsed = {"battle": battle}
        for field in ("enemy", "siren", "mystery", "boss"):
            if field not in item:
                continue
            count = _exact_integer(item[field], path, f"{item_location}.{field}", minimum=1)
            if field == "boss" and count != 1:
                raise _fail(path, f"{item_location}.boss", "boss count must be 1")
            parsed[field] = count
        result.append(parsed)
    if not result:
        raise _fail(path, location, "must not be empty")
    return result


def _portal_data(value: object, path: Path, location: str, shape: tuple[int, int]) -> list[tuple[str, str]]:
    result = []
    for index, raw_item in enumerate(_sequence(value, path, location)):
        item_location = f"{location}[{index}]"
        item = _sequence(raw_item, path, item_location)
        if len(item) != 2:
            raise _fail(path, item_location, "portal must contain exactly two grid nodes")
        result.append(
            (
                _grid_node(item[0], path, f"{item_location}[0]", shape),
                _grid_node(item[1], path, f"{item_location}[1]", shape),
            )
        )
    return result


def _land_based_data(value: object, path: Path, location: str, shape: tuple[int, int]) -> list[tuple[str, str]]:
    result = []
    for index, raw_item in enumerate(_sequence(value, path, location)):
        item_location = f"{location}[{index}]"
        item = _sequence(raw_item, path, item_location)
        if len(item) != 2 or item[1] not in {"up", "down", "left", "right"}:
            raise _fail(path, item_location, "land based entry must contain a grid node and direction")
        result.append((_grid_node(item[0], path, f"{item_location}[0]", shape), cast("str", item[1])))
    return result


def _config_value(value: object, path: Path, location: str) -> object:
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _fail(path, location, "float must be finite")
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_config_value(item, path, f"{location}[{index}]") for index, item in enumerate(value))
    raise _fail(path, location, "must be a safe scalar or sequence")


def _config_values(value: object, path: Path) -> dict[str, object]:
    mapping = _mapping(value, path, "config")
    result = {}
    for raw_name, raw_value in mapping.items():
        if not isinstance(raw_name, str) or _CONFIG_NAME.fullmatch(raw_name) is None or raw_name.startswith("__"):
            raise _fail(path, "config", f"invalid config name: {raw_name!r}")
        result[raw_name] = _config_value(raw_value, path, f"config.{raw_name}")
    return result


def _battle_policies(
    value: object,
    path: Path,
    spawn_battles: set[int],
) -> dict[int, BattlePolicy]:
    mapping = _mapping(value, path, "battles")
    result = {}
    for raw_battle, raw_policy in mapping.items():
        battle = _exact_integer(raw_battle, path, "battles.<key>")
        if battle not in spawn_battles:
            raise _fail(path, f"battles.{battle}", "battle is not declared in map spawn_data")
        item = _fields_mapping(raw_policy, path, f"battles.{battle}", _BATTLE_FIELDS)
        if "policy" not in item:
            raise _fail(path, f"battles.{battle}", "required field is policy")
        name = _string(item["policy"], path, f"battles.{battle}.policy")
        try:
            policy = BattlePolicy(
                cast("BattlePolicyName", name),
                preserve=cast("int | None", item.get("preserve")),
            )
        except ContentValidationError as error:
            raise _fail(path, f"battles.{battle}", str(error)) from error
        result[battle] = policy
    return result


def _validate_battle_handlers(
    path: Path,
    spawn_battles: set[int],
    boss_battles: set[int],
    policies: dict[int, BattlePolicy],
    strategy_base: type[CampaignBase],
) -> None:
    strategy_battles = {
        battle for battle in spawn_battles if callable(getattr(strategy_base, f"battle_{battle}", None))
    }
    for battle in sorted(set(policies) & strategy_battles):
        raise _fail(
            path,
            f"battles.{battle}",
            f"policy and pack-local strategy define the same battle_{battle}",
        )
    for battle in sorted(boss_battles):
        policy = policies.get(battle)
        if policy is not None and policy.name != "fleet_boss":
            raise _fail(path, f"battles.{battle}", "boss battle policy must be fleet_boss")
        if policy is None and battle not in strategy_battles:
            raise _fail(
                path,
                f"battles.{battle}",
                f"boss battle requires fleet_boss policy or pack-local strategy battle_{battle}",
            )
    if not policies and not strategy_battles:
        raise _fail(path, "battles", "stage requires at least one policy or pack-local strategy battle handler")


def _build_map(value: object, path: Path) -> tuple[CampaignMap, set[int], set[int], str]:
    data = _fields_mapping(value, path, "map", _MAP_FIELDS)
    missing = _REQUIRED_MAP_FIELDS - set(data)
    if missing:
        raise _fail(path, "map", f"missing required fields: {sorted(missing)}")
    name = _string(data["name"], path, "map.name")
    shape_name = _string(data["shape"], path, "map.shape")
    if _GRID_NODE.fullmatch(shape_name) is None:
        raise _fail(path, "map.shape", "must be a valid uppercase shape")
    shape = node2location(shape_name)
    map_data = _map_data_text(data["map_data"], path, "map.map_data", shape)
    weight_data = _weight_text(data["weight_data"], path, "map.weight_data", shape)
    spawn_data = _spawn_data(data["spawn_data"], path, "map.spawn_data")
    spawn_data_loop = None
    if "spawn_data_loop" in data:
        spawn_data_loop = _spawn_data(data["spawn_data_loop"], path, "map.spawn_data_loop")

    campaign_map = CampaignMap(name)
    campaign_map.shape = shape_name
    campaign_map.camera_data = _grid_nodes(data["camera_data"], path, "map.camera_data", shape)
    campaign_map.camera_data_spawn_point = _grid_nodes(
        data["camera_data_spawn_point"],
        path,
        "map.camera_data_spawn_point",
        shape,
    )
    if "portal_data" in data:
        campaign_map.portal_data = _portal_data(data["portal_data"], path, "map.portal_data", shape)
    campaign_map.map_data = map_data
    if "map_data_loop" in data:
        campaign_map.map_data_loop = _map_data_text(
            data["map_data_loop"],
            path,
            "map.map_data_loop",
            shape,
        )
    campaign_map.weight_data = weight_data
    if "land_based_data" in data:
        campaign_map.land_based_data = _land_based_data(
            data["land_based_data"],
            path,
            "map.land_based_data",
            shape,
        )
    campaign_map.spawn_data = spawn_data
    if spawn_data_loop is not None:
        campaign_map.spawn_data_loop = spawn_data_loop
    all_spawn_data = [*spawn_data, *(spawn_data_loop or ())]
    return (
        campaign_map,
        {item["battle"] for item in all_spawn_data},
        {item["battle"] for item in all_spawn_data if "boss" in item},
        name,
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


def _strategy_base(spec: StageSpec, campaign_root: Path, path: Path) -> type[CampaignBase]:
    reference = spec.strategy
    if reference is None:
        return CampaignBase
    module_name, separator, export_name = reference.partition(":")
    expected_prefix = f"campaign.{spec.ref.pack_id}."
    module_parts = module_name.split(".")
    if (
        separator != ":"
        or not module_name.startswith(expected_prefix)
        or any(not part.isidentifier() for part in module_parts)
        or not export_name.isidentifier()
        or export_name.startswith("__")
    ):
        raise _fail(path, "strategy", "must reference a class inside the current campaign pack")
    pack_root = _safe_direct_child(campaign_root, spec.ref.pack_id, path, "strategy")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise _fail(path, "strategy", f"cannot import {module_name}: {error}") from error
    if not isinstance(module, ModuleType) or module.__name__ != module_name:
        raise _fail(path, "strategy", "import must return the referenced module")
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        raise _fail(path, "strategy", "module must have a source file")
    try:
        Path(module_file).resolve().relative_to(pack_root)
    except ValueError as error:
        raise _fail(path, "strategy", "module source must stay inside the campaign pack directory") from error
    try:
        export = getattr(module, export_name)
    except AttributeError:
        raise _fail(path, "strategy", f"module is missing export {export_name}") from None
    if not isinstance(export, type) or not issubclass(export, CampaignBase):
        raise _fail(path, "strategy", "strategy export must inherit CampaignBase")
    return export


class StageLoader(Protocol):
    def load(self, spec: StageSpec) -> LoadedStage: ...


class StageSpecLoader:
    __slots__ = ("campaign_root", "content_root")

    def __init__(
        self,
        content_root: Path = DEFAULT_EVENT_MANIFEST_PATH,
        campaign_root: Path = DEFAULT_CAMPAIGN_ROOT,
    ) -> None:
        self.content_root = Path(content_root)
        self.campaign_root = Path(campaign_root)

    def load(self, spec: StageSpec) -> LoadedStage:
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
        campaign_map, spawn_battles, boss_battles, map_name = _build_map(data["map"], path)
        if map_name.casefold() != spec.ref.stage_id.casefold():
            raise _fail(path, "map.name", f"must match manifest stage id {spec.ref.stage_id!r}")
        config_values = _config_values(data["config"], path)
        enemy_filter = _string(data["enemy_filter"], path, "enemy_filter")
        policies = _battle_policies(data["battles"], path, spawn_battles)
        strategy_base = _strategy_base(spec, self.campaign_root, path)
        _validate_battle_handlers(path, spawn_battles, boss_battles, policies, strategy_base)

        module_name = f"campaign.{spec.ref.pack_id}.{spec.ref.stage_id}"
        config_class = cast(
            "type[object]",
            type("Config", (), {"__module__": module_name, **config_values}),
        )
        campaign_attributes: dict[str, object] = {
            "__module__": module_name,
            "MAP": campaign_map,
            "ENEMY_FILTER": enemy_filter,
        }
        for battle, policy in policies.items():
            method = policy.as_method()
            campaign_attributes[f"battle_{battle}"] = method
        campaign_class = cast(
            "type[CampaignBase]",
            type("Campaign", (strategy_base,), campaign_attributes),
        )
        return LoadedStage(config_class=config_class, campaign_class=campaign_class, map=campaign_map)


@lru_cache(maxsize=1)
def _default_catalog() -> ContentCatalog:
    return ContentCatalog(load_default_event_manifests())


@lru_cache
def load_default_stage(ref: StageRef) -> LoadedStage:
    if not isinstance(ref, StageRef):
        message = "default native stage loader requires a StageRef"
        raise TypeError(message)
    spec = _default_catalog().resolve_stage(ref)
    return StageSpecLoader().load(spec)
