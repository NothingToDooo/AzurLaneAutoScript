import ast
import inspect
import re
from datetime import date
from pathlib import Path
from typing import get_type_hints

import pytest

from module.config.config_updater import ConfigGenerator
from module.content.campaign_policy import CampaignPolicy
from module.content.errors import ContentValidationError
from module.content.manifest import load_event_manifests, render_campaign_readme
from module.content.models import ContentId, EventPack, EventRelease

EVENTS_PATH = Path("content/events")
_UNKNOWN_ASSET_FIELD = (
    "\nstages:\n  - id: t1\n    source: stages/t1.yaml\n    assets:\n"
    "      - id: map\n        path: assets/t1.yaml\n        unknown: true"
)
_DANGLING_ASSET = (
    "\nstages:\n  - id: t1\n    source: stages/t1.yaml\n    assets:\n      - id: map\n        path: assets/missing.yaml"
)
_DUPLICATE_ASSET = (
    "\nstages:\n  - id: t1\n    source: stages/t1.yaml\n    assets:\n"
    "      - id: map\n        path: assets/t1.yaml\n"
    "      - id: map\n        path: assets/t1.yaml"
)


def _write_manifest(root: Path, name: str, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(inspect.cleandoc(body) + "\n", encoding="utf-8", newline="\n")
    return path


def _set_attribute(instance: object, name: str, value: object) -> None:
    setattr(instance, name, value)


def _minimal_manifest(**replacements: str) -> str:
    values = {
        "schema_version": "1",
        "id": "event_20260625_cn",
        "kind": "event",
        "ui_profile": "legacy_python",
        "opened_on": '"2026-06-25"',
        "name_cn": "美梦巡演奇妙夜",
        "order": "10",
    }
    values.update(replacements)
    return f"""
        schema_version: {values["schema_version"]}
        id: {values["id"]}
        kind: {values["kind"]}
        ui_profile: {values["ui_profile"]}
        releases:
          - opened_on: {values["opened_on"]}
            name_cn: {values["name_cn"]}
            order: {values["order"]}
    """


def test_event_models_keep_the_old_constructor_and_expose_immutable_manifest_data() -> None:
    release = EventRelease(opened_on=date(2026, 6, 25), name_cn="美梦巡演奇妙夜", order=10)
    policy = CampaignPolicy(aliases=(("vsp", "sp"),))

    compatible = EventPack(pack_id=ContentId("event_compatible"))
    pack = EventPack(
        pack_id=ContentId("event_20260625_cn"),
        kind="event",
        ui_profile="legacy_python",
        releases=(release,),
        policy=policy,
    )

    assert compatible.kind == "event"
    assert compatible.ui_profile == "legacy_python"
    assert compatible.releases == ()
    assert pack.releases == (release,)
    assert pack.policy.aliases == (("vsp", "sp"),)
    with pytest.raises(AttributeError):
        _set_attribute(pack, "kind", "raid")


@pytest.mark.parametrize("model", [EventRelease, EventPack, CampaignPolicy])
def test_public_manifest_model_annotations_are_runtime_resolvable(model: type[object]) -> None:
    assert get_type_hints(model)


def test_load_minimal_manifest(tmp_path: Path) -> None:
    root = tmp_path / "content" / "events"
    _write_manifest(root, "event_20260625_cn.yaml", _minimal_manifest())

    (pack,) = load_event_manifests(root)

    assert str(pack.pack_id) == "event_20260625_cn"
    assert pack.kind == "event"
    assert pack.ui_profile == "legacy_python"
    assert pack.releases == (EventRelease(date(2026, 6, 25), "美梦巡演奇妙夜", 10),)
    assert pack.stages == ()
    assert pack.policy == CampaignPolicy()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "true"),
        ("schema_version", "1.0"),
        ("schema_version", "2"),
        ("opened_on", "2026-06-25"),
        ("opened_on", '"2026-02-30"'),
        ("name_cn", '""'),
        ("name_cn", '"   "'),
        ("order", "true"),
        ("order", "1.0"),
    ],
)
def test_manifest_rejects_implicit_or_invalid_scalar_types(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    root = tmp_path / "content" / "events"
    _write_manifest(root, "event_20260625_cn.yaml", _minimal_manifest(**{field: value}))

    with pytest.raises(ContentValidationError):
        load_event_manifests(root)


@pytest.mark.parametrize(
    ("filename", "replacements"),
    [
        ("wrong.yaml", {}),
        ("event_20260625_cn.yaml", {"kind": "raid"}),
        ("event_20260625_cn.yaml", {"kind": "unknown"}),
        ("event_20260625_cn.yaml", {"ui_profile": "plugin"}),
    ],
)
def test_manifest_rejects_identity_or_profile_mismatches(
    tmp_path: Path,
    filename: str,
    replacements: dict[str, str],
) -> None:
    root = tmp_path / "content" / "events"
    _write_manifest(root, filename, _minimal_manifest(**replacements))

    with pytest.raises(ContentValidationError):
        load_event_manifests(root)


@pytest.mark.parametrize(
    "body",
    [
        _minimal_manifest() + "\nunknown: true",
        _minimal_manifest().replace("            order: 10", "            order: 10\n            unknown: true"),
        _minimal_manifest() + "\npolicy:\n  unknown: true",
        _minimal_manifest() + "\nstages:\n  - id: t1\n    source: stages/t1.yaml\n    unknown: true",
        _minimal_manifest() + _UNKNOWN_ASSET_FIELD,
    ],
)
def test_manifest_rejects_unknown_fields(tmp_path: Path, body: str) -> None:
    root = tmp_path / "content" / "events"
    _write_manifest(root, "event_20260625_cn.yaml", body)

    with pytest.raises(ContentValidationError):
        load_event_manifests(root)


def test_manifest_rejects_duplicate_release_order_across_packs(tmp_path: Path) -> None:
    root = tmp_path / "content" / "events"
    _write_manifest(root, "event_20260625_cn.yaml", _minimal_manifest(order="10"))
    _write_manifest(
        root,
        "raid_20260212.yaml",
        _minimal_manifest(id="raid_20260212", kind="raid", opened_on='"2026-02-12"', order="10"),
    )

    with pytest.raises(ContentValidationError):
        load_event_manifests(root)


def test_manifest_rejects_duplicate_pack_id_across_yaml_extensions(tmp_path: Path) -> None:
    root = tmp_path / "content" / "events"
    body = _minimal_manifest()
    _write_manifest(root, "event_20260625_cn.yaml", body)
    _write_manifest(root, "event_20260625_cn.yml", body.replace("order: 10", "order: 20"))

    with pytest.raises(ContentValidationError, match="duplicate pack id"):
        load_event_manifests(root)


def test_manifest_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    root = tmp_path / "content" / "events"
    body = _minimal_manifest().replace(
        "            name_cn: 美梦巡演奇妙夜",
        "            name_cn: 美梦巡演奇妙夜\n            name_cn: 重复名称",
    )
    _write_manifest(root, "event_20260625_cn.yaml", body)

    with pytest.raises(ContentValidationError, match="duplicate YAML key"):
        load_event_manifests(root)


@pytest.mark.parametrize("unsafe_path", ["../outside.yaml", "C:/outside.yaml", "/outside.yaml"])
def test_manifest_rejects_unsafe_native_paths(tmp_path: Path, unsafe_path: str) -> None:
    root = tmp_path / "content" / "events"
    body = _minimal_manifest() + f"\nstages:\n  - id: t1\n    source: {unsafe_path}"
    _write_manifest(root, "event_20260625_cn.yaml", body)

    with pytest.raises(ContentValidationError):
        load_event_manifests(root)


def test_manifest_loads_native_stage_and_assets_only_from_its_pack_root(tmp_path: Path) -> None:
    root = tmp_path / "content" / "events"
    pack_root = root / "event_20260625_cn"
    (pack_root / "stages").mkdir(parents=True)
    (pack_root / "assets").mkdir()
    (pack_root / "stages" / "t1.yaml").write_text("map: t1\n", encoding="utf-8")
    (pack_root / "assets" / "t1.yaml").write_text("asset: t1\n", encoding="utf-8")
    body = (
        _minimal_manifest()
        + """
        stages:
          - id: t1
            source: stages/t1.yaml
            assets:
              - id: map
                path: assets/t1.yaml
        policy:
          aliases:
            a1: t1
          loops:
            t: [t1]
          force_threat_safe_stages: [t1]
          resource_free_stages: [t1]
          map_achievement_fallbacks:
            threat_safe: map_3_stars
        """
    )
    _write_manifest(root, "event_20260625_cn.yaml", body)

    (pack,) = load_event_manifests(root)

    assert pack.stages[0].source == "stages/t1.yaml"
    assert pack.stages[0].assets[0].path == Path("assets/t1.yaml")
    assert pack.policy.aliases == (("a1", "t1"),)
    assert pack.policy.loops == (("t", ("t1",)),)


@pytest.mark.parametrize(
    "body",
    [
        _minimal_manifest() + "\nstages:\n  - id: t1\n    source: stages/missing.yaml",
        _minimal_manifest() + _DANGLING_ASSET,
        _minimal_manifest()
        + "\nstages:\n  - id: t1\n    source: stages/t1.yaml\n  - id: t1\n    source: stages/t1.yaml",
        _minimal_manifest() + _DUPLICATE_ASSET,
        _minimal_manifest() + "\npolicy:\n  aliases:\n    a1: missing",
        _minimal_manifest() + "\npolicy:\n  loops:\n    t: [missing]",
        _minimal_manifest() + "\npolicy:\n  force_threat_safe_stages: [missing]",
        _minimal_manifest() + "\npolicy:\n  resource_free_stages: [missing]",
    ],
)
def test_manifest_rejects_duplicate_or_dangling_stage_references(tmp_path: Path, body: str) -> None:
    root = tmp_path / "content" / "events"
    pack_root = root / "event_20260625_cn"
    (pack_root / "stages").mkdir(parents=True)
    (pack_root / "assets").mkdir()
    (pack_root / "stages" / "t1.yaml").write_text("map: t1\n", encoding="utf-8")
    (pack_root / "assets" / "t1.yaml").write_text("asset: t1\n", encoding="utf-8")
    _write_manifest(root, "event_20260625_cn.yaml", body)

    with pytest.raises(ContentValidationError):
        load_event_manifests(root)


def test_real_manifests_preserve_all_readme_releases_and_profiles() -> None:
    packs = load_event_manifests(EVENTS_PATH)

    assert len(packs) == 132
    assert sum(len(pack.releases) for pack in packs) == 268
    assert sum(pack.kind == "war_archives" for pack in packs) == 48
    assert sum(pack.kind == "event" for pack in packs) == 68
    assert sum(pack.kind == "raid" for pack in packs) == 11
    assert sum(pack.kind == "coalition" for pack in packs) == 5
    assert sum(len(pack.releases) > 1 for pack in packs) == 77


def test_readme_renderer_matches_checked_in_output() -> None:
    packs = load_event_manifests(EVENTS_PATH)

    assert render_campaign_readme(packs) == Path("campaign/Readme.md").read_text(encoding="utf-8")


def test_config_generator_manifest_annotations_are_runtime_resolvable() -> None:
    event_packs_property = ConfigGenerator.__dict__["event_packs"]
    assert get_type_hints(event_packs_property.func)["return"] == tuple[EventPack, ...]


def test_stable_core_contains_no_dated_event_string_literals() -> None:
    pattern = re.compile(r"(?:event|war_archives)_\d{8}_cn")
    paths = [
        Path("module/campaign/run.py"),
        Path("module/content/campaign_policy.py"),
        Path("module/content/manifest.py"),
        Path("module/config/config_updater.py"),
        Path("module/config/config_manual.py"),
    ]

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and pattern.search(node.value)
        ]
        assert violations == [], f"{path}: {violations}"
