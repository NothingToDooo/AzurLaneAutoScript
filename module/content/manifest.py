import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from functools import lru_cache
from operator import itemgetter
from pathlib import Path
from typing import cast

import yaml
from yaml.resolver import BaseResolver

from module.content.activity_profile import (
    ActivityDefinition,
    ActivityKind,
    CoalitionDefinition,
    CoalitionFleetRule,
    CoalitionProfileId,
    CoalitionStageDefinition,
    CoalitionStageId,
    EventStoryDefinition,
    EventStoryProfileId,
    RaidDefinition,
    RaidMode,
    RaidProfileId,
)
from module.content.campaign_policy import (
    MAP_ACHIEVEMENT_VALUES,
    CampaignPolicy,
    StageProgressionRule,
)
from module.content.errors import ContentValidationError
from module.content.models import (
    EVENT_KINDS,
    ContentId,
    EventPack,
    EventRelease,
    StageRef,
    StageSpec,
)
from module.content.runtime_profile import CampaignRuntimeProfileId
from module.content.war_archives_profile import WarArchivesDefinition, WarArchivesProfileId

SCHEMA_VERSION = 1
DEFAULT_EVENT_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "content" / "events"
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "id",
    "kind",
    "releases",
    "stages",
    "policy",
    "activity",
    "war_archives",
}
_RELEASE_FIELDS = {"opened_on", "name_cn", "order"}
_STAGE_FIELDS = {"id", "source", "runtime_profile"}
_POLICY_FIELDS = {
    "aliases",
    "progressions",
    "loops",
    "force_threat_safe_stages",
    "resource_free_stages",
    "map_achievement_fallbacks",
}
_EVENT_STORY_ACTIVITY_FIELDS = {"kind", "profile"}
_RAID_ACTIVITY_FIELDS = {"kind", "profile", "modes", "daily_modes", "ticket_modes"}
_COALITION_ACTIVITY_FIELDS = {"kind", "profile", "stages"}
_COALITION_ACTIVITY_STAGE_FIELDS = {"id", "battles", "fleet"}
_WAR_ARCHIVES_FIELDS = {"profile"}
_CJK_PATTERN = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff、！（）]")
_README_INTRO = (
    "# 活动列表\n\n"
    "`/campaign` 目录用于存放主线、活动和作战档案地图文件。\n\n"
    "新增活动时，编辑 `content/events/*.yaml`，然后运行 "
    "`uv run python -m module.config.config_updater` 重新生成配置。"
    "部分目录日期不等于首发日期，因为它们复用了旧活动地图文件。\n\n"
    "**开放日期**：活动第一次开放的日期。\n\n"
    "**目录**：活动地图文件所在目录。\n\n"
    "**国服名称**：WebUI 中显示的活动名称；未在国服开放时使用 `-`。\n\n"
)


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


def _free_mapping(value: object, path: Path, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _fail(path, location, "must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise _fail(path, location, "field names must be strings")
    return cast("Mapping[str, object]", value)


def _mapping(value: object, path: Path, location: str, fields: set[str]) -> Mapping[str, object]:
    mapping = _free_mapping(value, path, location)
    unknown = set(mapping) - fields
    if unknown:
        raise _fail(path, location, f"unknown fields: {sorted(unknown)}")
    return mapping


def _sequence(value: object, path: Path, location: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _fail(path, location, "must be a list")
    return value


def _string(value: object, path: Path, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(path, location, "must be a non-empty string")
    return value


def _exact_integer(value: object, path: Path, location: str) -> int:
    if type(value) is not int:
        raise _fail(path, location, "must be an integer")
    return value


def _nullable_string(value: object, path: Path, location: str) -> str | None:
    if value is None:
        return None
    return _string(value, path, location)


def _safe_stage_id(value: object, path: Path, location: str) -> str:
    stage_id = _string(value, path, location)
    if stage_id in {".", ".."} or any(character in stage_id for character in ("/", "\\", ":")):
        raise _fail(path, location, "must be a safe stage id without path semantics")
    if stage_id != stage_id.lower():
        raise _fail(path, location, "must use canonical lowercase")
    return stage_id


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
    return _mapping(raw, path, "$", _TOP_LEVEL_FIELDS)


def _load_releases(raw: object, path: Path) -> tuple[EventRelease, ...]:
    releases = []
    for index, value in enumerate(_sequence(raw, path, "releases")):
        location = f"releases[{index}]"
        item = _mapping(value, path, location, _RELEASE_FIELDS)
        if set(item) != _RELEASE_FIELDS:
            raise _fail(path, location, f"required fields are {sorted(_RELEASE_FIELDS)}")
        opened_raw = item["opened_on"]
        if not isinstance(opened_raw, str):
            raise _fail(path, f"{location}.opened_on", "must be a quoted ISO date")
        try:
            opened_on = date.fromisoformat(opened_raw)
        except ValueError as error:
            raise _fail(path, f"{location}.opened_on", "must be a valid ISO date") from error
        if opened_on.isoformat() != opened_raw:
            raise _fail(path, f"{location}.opened_on", "must use YYYY-MM-DD")
        name_cn = item["name_cn"]
        if name_cn is not None:
            name_cn = _string(name_cn, path, f"{location}.name_cn")
        order = _exact_integer(item["order"], path, f"{location}.order")
        releases.append(EventRelease(opened_on=opened_on, name_cn=name_cn, order=order))
    if not releases:
        raise _fail(path, "releases", "must not be empty")
    return tuple(releases)


def _resolve_pack_root(path: Path, pack_id: str) -> Path:
    manifest_root = path.parent.resolve()
    pack_root = (path.parent / pack_id).resolve()
    try:
        relative = pack_root.relative_to(manifest_root)
    except ValueError as error:
        raise _fail(path, "stages", "pack content directory must stay inside the manifest root") from error
    if relative.parts != (pack_id,):
        raise _fail(path, "stages", "pack content directory must be the pack's direct directory")
    return pack_root


def _safe_pack_file(raw: object, path: Path, location: str, pack_root: Path) -> str:
    value = _string(raw, path, location)
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise _fail(path, location, "must stay inside the pack content directory")
    resolved = (pack_root / relative).resolve()
    try:
        resolved.relative_to(pack_root.resolve())
    except ValueError as error:
        raise _fail(path, location, "must stay inside the pack content directory") from error
    if not resolved.is_file():
        raise _fail(path, location, f"file does not exist: {value}")
    return relative.as_posix()


def _load_stages(
    raw: object,
    path: Path,
    pack_id: str,
    pack_root: Path,
    war_archives: WarArchivesDefinition | None,
) -> tuple[StageSpec, ...]:
    stages = []
    seen: set[str] = set()
    for index, value in enumerate(_sequence(raw, path, "stages")):
        location = f"stages[{index}]"
        item = _mapping(value, path, location, _STAGE_FIELDS)
        required = {"id", "runtime_profile", "source"}
        if not required.issubset(item):
            raise _fail(path, location, f"required fields are {sorted(required)}")
        stage_id = _safe_stage_id(item["id"], path, f"{location}.id")
        if stage_id in seen:
            raise _fail(path, f"{location}.id", f"duplicate stage id: {stage_id}")
        seen.add(stage_id)
        source = _safe_pack_file(item["source"], path, f"{location}.source", pack_root)
        stages.append(
            StageSpec(
                ref=StageRef(pack_id=pack_id, stage_id=stage_id),
                source=source,
                runtime_profile_id=CampaignRuntimeProfileId(
                    _string(
                        item["runtime_profile"],
                        path,
                        f"{location}.runtime_profile",
                    )
                ),
                war_archives=war_archives,
            )
        )
    return tuple(stages)


def _string_mapping(raw: object, path: Path, location: str) -> tuple[tuple[str, str], ...]:
    data = _free_mapping(raw, path, location)
    result = []
    for key, value in data.items():
        source = _string(key, path, f"{location}.<key>")
        target = _string(value, path, f"{location}.{source}")
        result.append((source, target))
    return tuple(result)


def _stage_mapping(raw: object, path: Path, location: str) -> tuple[tuple[str, str], ...]:
    data = _free_mapping(raw, path, location)
    result = []
    for key, value in data.items():
        source = _safe_stage_id(key, path, f"{location}.<key>")
        target = _safe_stage_id(value, path, f"{location}.{source}")
        result.append((source, target))
    return tuple(result)


def _stage_progression_mapping(
    raw: object,
    path: Path,
    location: str,
) -> tuple[StageProgressionRule, ...]:
    data = _free_mapping(raw, path, location)
    result = []
    for key, value in data.items():
        stage = _safe_stage_id(key, path, f"{location}.<key>")
        next_stage = None if value is None else _safe_stage_id(value, path, f"{location}.{stage}")
        result.append(StageProgressionRule(stage, next_stage))
    return tuple(result)


def _map_achievement_mapping(raw: object, path: Path, location: str) -> tuple[tuple[str, str], ...]:
    values = _string_mapping(raw, path, location)
    for source, target in values:
        if source not in MAP_ACHIEVEMENT_VALUES:
            raise _fail(path, f"{location}.<key>", "must be a supported MapAchievement value")
        if target not in MAP_ACHIEVEMENT_VALUES:
            raise _fail(path, f"{location}.{source}", "must be a supported MapAchievement value")
    return values


def _stage_list(raw: object, path: Path, location: str) -> tuple[str, ...]:
    values = _sequence(raw, path, location)
    return tuple(_safe_stage_id(value, path, f"{location}[{index}]") for index, value in enumerate(values))


def _load_policy(raw: object, path: Path) -> CampaignPolicy:
    data = _mapping(raw, path, "policy", _POLICY_FIELDS)
    aliases = _stage_mapping(data.get("aliases", {}), path, "policy.aliases")
    progressions = _stage_progression_mapping(
        data.get("progressions", {}),
        path,
        "policy.progressions",
    )
    loops_raw = _free_mapping(data.get("loops", {}), path, "policy.loops")
    loops = tuple(
        (
            _safe_stage_id(alias, path, "policy.loops.<key>"),
            _stage_list(stages, path, f"policy.loops.{alias}"),
        )
        for alias, stages in loops_raw.items()
    )
    if any(not stages for _, stages in loops):
        raise _fail(path, "policy.loops", "loop stages must not be empty")
    return CampaignPolicy(
        aliases=aliases,
        progressions=progressions,
        loops=loops,
        force_threat_safe_stages=_stage_list(
            data.get("force_threat_safe_stages", ()),
            path,
            "policy.force_threat_safe_stages",
        ),
        resource_free_stages=_stage_list(
            data.get("resource_free_stages", ()),
            path,
            "policy.resource_free_stages",
        ),
        map_achievement_fallbacks=_map_achievement_mapping(
            data.get("map_achievement_fallbacks", {}),
            path,
            "policy.map_achievement_fallbacks",
        ),
    )


def _raid_modes(raw: object, path: Path, location: str) -> tuple[RaidMode, ...]:
    result: list[RaidMode] = []
    for index, value in enumerate(_sequence(raw, path, location)):
        mode = _string(value, path, f"{location}[{index}]")
        try:
            result.append(RaidMode(mode))
        except ValueError as error:
            allowed = sorted(item.value for item in RaidMode)
            raise _fail(path, f"{location}[{index}]", f"must be one of {allowed}") from error
    return tuple(result)


def _load_coalition_activity_stages(
    raw: object,
    path: Path,
) -> tuple[CoalitionStageDefinition, ...]:
    result = []
    for index, value in enumerate(_sequence(raw, path, "activity.stages")):
        location = f"activity.stages[{index}]"
        item = _mapping(value, path, location, _COALITION_ACTIVITY_STAGE_FIELDS)
        if set(item) != _COALITION_ACTIVITY_STAGE_FIELDS:
            raise _fail(path, location, f"required fields are {sorted(_COALITION_ACTIVITY_STAGE_FIELDS)}")
        fleet = _string(item["fleet"], path, f"{location}.fleet")
        try:
            fleet_rule = CoalitionFleetRule(fleet)
        except ValueError as error:
            allowed = sorted(rule.value for rule in CoalitionFleetRule)
            raise _fail(path, f"{location}.fleet", f"must be one of {allowed}") from error
        result.append(
            CoalitionStageDefinition(
                stage_id=CoalitionStageId(_safe_stage_id(item["id"], path, f"{location}.id")),
                battle_count=_exact_integer(item["battles"], path, f"{location}.battles"),
                fleet_rule=fleet_rule,
            )
        )
    return tuple(result)


def _load_activity(raw: object, path: Path, pack_kind: str) -> ActivityDefinition:
    base = _free_mapping(raw, path, "activity")
    activity_kind = _string(base.get("kind"), path, "activity.kind")
    expected_kind = {
        "event": ActivityKind.EVENT_STORY,
        "raid": ActivityKind.RAID,
        "coalition": ActivityKind.COALITION,
    }.get(pack_kind)
    if expected_kind is None:
        raise _fail(path, "activity", f"kind {pack_kind!r} must not define an activity")
    if activity_kind != expected_kind.value:
        raise _fail(path, "activity.kind", f"must be {expected_kind.value!r} for pack kind {pack_kind!r}")

    try:
        if expected_kind is ActivityKind.EVENT_STORY:
            item = _mapping(base, path, "activity", _EVENT_STORY_ACTIVITY_FIELDS)
            if set(item) != _EVENT_STORY_ACTIVITY_FIELDS:
                raise _fail(path, "activity", f"required fields are {sorted(_EVENT_STORY_ACTIVITY_FIELDS)}")
            profile = _nullable_string(item["profile"], path, "activity.profile")
            return EventStoryDefinition(None if profile is None else EventStoryProfileId(profile))
        if expected_kind is ActivityKind.RAID:
            item = _mapping(base, path, "activity", _RAID_ACTIVITY_FIELDS)
            if set(item) != _RAID_ACTIVITY_FIELDS:
                raise _fail(path, "activity", f"required fields are {sorted(_RAID_ACTIVITY_FIELDS)}")
            return RaidDefinition(
                profile_id=RaidProfileId(_string(item["profile"], path, "activity.profile")),
                modes=_raid_modes(item["modes"], path, "activity.modes"),
                daily_modes=_raid_modes(item["daily_modes"], path, "activity.daily_modes"),
                ticket_modes=_raid_modes(item["ticket_modes"], path, "activity.ticket_modes"),
            )
        item = _mapping(base, path, "activity", _COALITION_ACTIVITY_FIELDS)
        if set(item) != _COALITION_ACTIVITY_FIELDS:
            raise _fail(path, "activity", f"required fields are {sorted(_COALITION_ACTIVITY_FIELDS)}")
        return CoalitionDefinition(
            profile_id=CoalitionProfileId(_string(item["profile"], path, "activity.profile")),
            stages=_load_coalition_activity_stages(item["stages"], path),
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, ContentValidationError) and str(error).startswith(f"{path}:"):
            raise
        raise _fail(path, "activity", str(error)) from error


def _load_war_archives(raw: object, path: Path) -> WarArchivesDefinition:
    item = _mapping(raw, path, "war_archives", _WAR_ARCHIVES_FIELDS)
    if set(item) != _WAR_ARCHIVES_FIELDS:
        raise _fail(path, "war_archives", f"required fields are {sorted(_WAR_ARCHIVES_FIELDS)}")
    try:
        return WarArchivesDefinition(WarArchivesProfileId(_string(item["profile"], path, "war_archives.profile")))
    except (TypeError, ValueError) as error:
        if isinstance(error, ContentValidationError) and str(error).startswith(f"{path}:"):
            raise
        raise _fail(path, "war_archives", str(error)) from error


def _pack_war_archives(
    data: Mapping[str, object],
    path: Path,
    kind: str,
) -> WarArchivesDefinition | None:
    if kind == "war_archives":
        if "war_archives" not in data:
            raise _fail(path, "war_archives", "is required for war_archives packs")
        return _load_war_archives(data["war_archives"], path)
    if "war_archives" in data:
        raise _fail(path, "war_archives", f"must not be defined for pack kind {kind!r}")
    return None


def _validate_policy_targets(
    policy: CampaignPolicy,
    stages: tuple[StageSpec, ...],
    path: Path,
    pack_id: str,
    repository_root: Path,
) -> None:
    del repository_root, pack_id
    stage_ids = {stage.ref.stage_id for stage in stages}

    targets = [target for _, target in policy.aliases]
    targets.extend(rule.stage for rule in policy.progressions)
    targets.extend(rule.next_stage for rule in policy.progressions if rule.next_stage is not None)
    targets.extend(stage for _, loop in policy.loops for stage in loop)
    targets.extend(policy.force_threat_safe_stages)
    targets.extend(policy.resource_free_stages)
    for target in targets:
        _safe_stage_id(target, path, "policy target")
    dangling = sorted(set(targets) - stage_ids)
    if dangling:
        raise _fail(path, "policy", f"dangling stage targets: {dangling}")


def _load_pack(path: Path, repository_root: Path) -> EventPack:
    data = _load_yaml(path)
    required = {"schema_version", "id", "kind", "releases"}
    if not required.issubset(data):
        raise _fail(path, "$", f"required fields are {sorted(required)}")
    version = _exact_integer(data["schema_version"], path, "schema_version")
    if version != SCHEMA_VERSION:
        raise _fail(path, "schema_version", f"must be {SCHEMA_VERSION}")
    pack_id = _string(data["id"], path, "id")
    if path.stem != pack_id:
        raise _fail(path, "id", "must match the manifest filename")
    kind = _string(data["kind"], path, "kind")
    if kind not in EVENT_KINDS:
        raise _fail(path, "kind", f"must be one of {EVENT_KINDS}")
    if not pack_id.startswith(f"{kind}_"):
        raise _fail(path, "kind", "must match the pack id prefix")
    releases = _load_releases(data["releases"], path)
    war_archives = _pack_war_archives(data, path, kind)
    pack_root = _resolve_pack_root(path, pack_id)
    stages = _load_stages(data.get("stages", ()), path, pack_id, pack_root, war_archives)
    policy = _load_policy(data.get("policy", {}), path)
    _validate_policy_targets(policy, stages, path, pack_id, repository_root)
    activity_kinds = {"event", "raid", "coalition"}
    if kind in activity_kinds and "activity" not in data:
        raise _fail(path, "activity", f"is required for pack kind {kind!r}")
    if kind not in activity_kinds and "activity" in data:
        raise _fail(path, "activity", f"must not be defined for pack kind {kind!r}")
    activity = None if "activity" not in data else _load_activity(data["activity"], path, kind)
    return EventPack(
        pack_id=ContentId(pack_id),
        stages=stages,
        kind=kind,
        releases=releases,
        policy=policy,
        activity=activity,
        war_archives=war_archives,
    )


def load_event_manifests(path: Path) -> tuple[EventPack, ...]:
    """确定性加载并严格校验活动清单目录。"""
    root = Path(path)
    if not root.is_dir():
        message = f"manifest directory does not exist: {root}"
        raise ContentValidationError(message)
    repository_root = root.parent.parent
    files = sorted((*root.glob("*.yaml"), *root.glob("*.yml")), key=lambda item: item.name)
    if not files:
        message = f"manifest directory must contain at least one YAML file: {root}"
        raise ContentValidationError(message)
    packs = tuple(_load_pack(file, repository_root) for file in files)
    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    for pack in packs:
        pack_id = str(pack.pack_id)
        if pack_id in seen_ids:
            message = f"duplicate pack id: {pack_id}"
            raise ContentValidationError(message)
        seen_ids.add(pack_id)
        for release in pack.releases:
            if release.order in seen_orders:
                message = f"duplicate release order: {release.order}"
                raise ContentValidationError(message)
            seen_orders.add(release.order)
    return packs


@lru_cache(maxsize=1)
def load_default_event_manifests() -> tuple[EventPack, ...]:
    return load_event_manifests(DEFAULT_EVENT_MANIFEST_PATH)


def _display_width(text: str) -> int:
    return len(text) + len(_CJK_PATTERN.findall(text))


def render_campaign_readme(packs: Iterable[EventPack]) -> str:
    """从活动清单纯渲染 README，不读取或写入其他文件。"""
    rows = [
        (release.order, release, str(pack.pack_id))
        for pack in packs
        if pack.kind != "campaign"
        for release in pack.releases
    ]
    rows.sort(key=itemgetter(0))
    data = [("开放日期", "目录", "国服名称")]
    data.extend(
        (
            release.opened_on.strftime("%Y%m%d"),
            pack_id.replace("_", " "),
            release.name_cn or "-",
        )
        for _, release, pack_id in rows
    )
    widths = [max(4, *(_display_width(row[index]) for row in data)) for index in range(3)]
    lines = []
    for index, row in enumerate(data):
        lines.append(
            "| "
            + " | ".join(cell + " " * (width - _display_width(cell)) for cell, width in zip(row, widths, strict=True))
            + " |"
        )
        if index == 0:
            lines.append("| " + " | ".join(":" + "-" * (width - 1) for width in widths) + " |")
    return _README_INTRO + "\n".join(lines) + "\n"
