from pathlib import Path

import pytest
import yaml

from module.content.errors import ContentValidationError
from module.content.manifest import load_default_event_manifests
from module.content.models import StageRef, StageSpec
from module.content.stage_loader import StageSpecLoader, load_default_stage

PACK_ID = "event_20260625_cn"
_NATIVE_STAGE = Path("content/events") / PACK_ID / "stages" / "t1.yaml"


def _native_stage_body() -> str:
    return _NATIVE_STAGE.read_text(encoding="utf-8")


def _write_stage(root: Path, body: str) -> tuple[StageSpecLoader, StageSpec]:
    stage_path = root / PACK_ID / "stages" / "t1.yaml"
    stage_path.parent.mkdir(parents=True)
    stage_path.write_text(body, encoding="utf-8", newline="\n")
    return StageSpecLoader(content_root=root), StageSpec(StageRef(PACK_ID, "t1"), "stages/t1.yaml")


def test_default_loader_loads_every_stage_declared_by_the_real_manifest() -> None:
    pack = next(pack for pack in load_default_event_manifests() if str(pack.pack_id) == PACK_ID)

    definitions = [load_default_stage(spec.ref) for spec in pack.stages]

    assert [definition.ref for definition in definitions] == [spec.ref for spec in pack.stages]
    assert all(definition.map.name == definition.ref.stage_id.upper() for definition in definitions)


def test_real_stage_preserves_distinct_normal_loop_and_mechanics() -> None:
    definition = load_default_stage(StageRef("campaign_main", "16-4"))

    assert len(definition.map.normal.spawn_waves) == 9
    assert definition.map.normal.boss_battles == frozenset({8})
    assert len(definition.map.loop.spawn_waves) == 5
    assert definition.map.loop.boss_battles == frozenset({4})
    assert len(definition.mechanics.enemy_movement.moves) == 5
    assert definition.mechanics.procedures[0].battle == 4
    assert set(definition.battle_programs) == {0, 1, 3, 4}


def test_loader_rejects_a_decoded_cell_outside_the_real_map(tmp_path: Path) -> None:
    body = _native_stage_body().replace(
        "    - tag: clear_siren",
        "    - tag: clear_selected_enemy\n      candidates: [Z99]\n      excluded_genres: []\n      expected: enemy",
        1,
    )
    loader, spec = _write_stage(tmp_path / "events", body)

    with pytest.raises(ContentValidationError, match="outside the map shape"):
        loader.load(spec)


def test_loader_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    body = _native_stage_body().replace("  name: T1", "  name: T1\n  name: OTHER", 1)
    loader, spec = _write_stage(tmp_path / "events", body)

    with pytest.raises(ContentValidationError) as caught:
        loader.load(spec)

    assert str(caught.value) == "duplicate YAML key: name"
    assert caught.value.__cause__ is None


def test_loader_wraps_yaml_parse_errors_with_the_source_path(tmp_path: Path) -> None:
    content_root = tmp_path / "events"
    loader, spec = _write_stage(content_root, "schema_version: [")
    path = content_root / PACK_ID / "stages" / "t1.yaml"

    with pytest.raises(ContentValidationError) as caught:
        loader.load(spec)

    assert str(caught.value).startswith(f"{path}:$: ")
    assert isinstance(caught.value.__cause__, yaml.YAMLError)
