import inspect
import textwrap
from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import pytest

from module.content import CampaignStageDefinition, CellId, GridShape, LandBasedDirection, LandBasedSpec, PortalSpec
from module.content import stage_loader as stage_loader_module
from module.content.battle_policy import (
    BossStrategy,
    ClearBoss,
    ClearBossRoadblock,
    ClearFilteredEnemy,
    ClearSiren,
    DefaultBattle,
)
from module.content.campaign_session import CampaignRunVariant, CampaignSession
from module.content.errors import ContentValidationError
from module.content.manifest import load_default_event_manifests
from module.content.models import StageRef, StageSpec
from module.content.stage_definition import SpawnWave
from module.content.stage_loader import StageSpecLoader, load_default_stage
from module.content.stage_rules import (
    ChapterSwitch,
    EdgeInsightCorner,
    OneTimeCompletion,
    RepeatableCompletion,
    StageEntrance,
    StageEntrancePosition,
    StageEntranceRevision,
)

if TYPE_CHECKING:
    from pathlib import Path

PACK_ID = "event_20260625_cn"
NATIVE_STAGE_EXPECTATIONS = {
    "t1": (GridShape(9, 7), 5, frozenset({4}), frozenset({0, 4})),
    "t2": (GridShape(9, 7), 5, frozenset({4}), frozenset({0, 4})),
    "t3": (GridShape(9, 8), 6, frozenset({5}), frozenset({0, 5})),
    "ht1": (GridShape(9, 7), 6, frozenset({5}), frozenset({0, 5})),
    "ht2": (GridShape(9, 7), 7, frozenset({6}), frozenset({0, 5, 6})),
    "ht3": (GridShape(9, 8), 7, frozenset({6}), frozenset({0, 5, 6})),
    "sp": (GridShape(7, 10), 8, frozenset({7}), frozenset({0, 5, 7})),
}


def _native_stage_spec(stage_id: str) -> StageSpec:
    pack = next(pack for pack in load_default_event_manifests() if str(pack.pack_id) == PACK_ID)
    return next(spec for spec in pack.stages if spec.ref.stage_id == stage_id)


def _assign_attribute(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


def _write_stage(root: Path, body: str) -> tuple[StageSpecLoader, StageSpec]:
    stage_path = root / PACK_ID / "stages" / "t1.yaml"
    stage_path.parent.mkdir(parents=True)
    stage_path.write_text(inspect.cleandoc(body) + "\n", encoding="utf-8", newline="\n")
    return (
        StageSpecLoader(content_root=root),
        StageSpec(StageRef(PACK_ID, "t1"), "stages/t1.yaml"),
    )


def _minimal_stage(**replacements: str) -> str:
    body = inspect.cleandoc(
        """
        schema_version: 4
        map:
          name: T1
          shape: A1
          camera_data: [A1]
          camera_data_spawn_point: [A1]
          map_data: |-
            --
          weight_data: |-
            50
          spawn_data:
          - battle: 0
            boss: 1
        config:
          MAP_HAS_MAP_STORY: false
          MAP_HAS_FLEET_STEP: false
          MAP_HAS_AMBUSH: false
          MAP_HAS_MYSTERY: false
        enemy_filter: 1L
        battles:
          0:
            steps:
            - tag: clear_boss
              strategy: fleet_boss
        mechanics:
          roadblocks: []
          fleet_coordination: []
          pickups: []
          map_interactions: []
          map_mutations: []
          moving_enemies:
            turns: []
            wait_until_clear: false
            initial_enemy_cells: []
            initial_siren_cells: []
          map_structures:
            walls: []
            maze_groups: []
            fortress_enemy_cells: []
            fortress_block_cells: []
            bouncing_enemy_routes: []
          enemy_movement: []
          procedures: []
          preset_routes: []
          fixed_target_sequences: []
        programs: []
        boss_approaches: []
        hard_mode: null
        """
    )
    if "shape" in replacements:
        body = body.replace("  shape: A1", f"  shape: {replacements['shape']}")
    if "map_data" in replacements:
        rendered = textwrap.indent(replacements["map_data"], "    ")
        body = body.replace("  map_data: |-\n    --", f"  map_data: |-\n{rendered}")
    if "weight_data" in replacements:
        rendered = textwrap.indent(replacements["weight_data"], "    ")
        body = body.replace("  weight_data: |-\n    50", f"  weight_data: |-\n{rendered}")
    if "spawn_data" in replacements:
        rendered = textwrap.indent(replacements["spawn_data"], "  ")
        body = body.replace("  spawn_data:\n  - battle: 0\n    boss: 1", f"  spawn_data:\n{rendered}")
    if "config" in replacements:
        rendered = textwrap.indent(replacements["config"], "  ")
        body = body.replace(
            "config:\n"
            "  MAP_HAS_MAP_STORY: false\n"
            "  MAP_HAS_FLEET_STEP: false\n"
            "  MAP_HAS_AMBUSH: false\n"
            "  MAP_HAS_MYSTERY: false",
            f"config:\n{rendered}",
        )
    if "battles" in replacements:
        rendered = textwrap.indent(replacements["battles"], "  ")
        body = body.replace(
            "battles:\n  0:\n    steps:\n    - tag: clear_boss\n      strategy: fleet_boss",
            f"battles:\n{rendered}",
        )
    return body


@pytest.mark.parametrize("stage_id", tuple(NATIVE_STAGE_EXPECTATIONS))
def test_default_loader_returns_typed_definition_for_every_native_stage(stage_id: str) -> None:
    definition = load_default_stage(StageRef(PACK_ID, stage_id))

    assert isinstance(definition, CampaignStageDefinition)
    assert definition.ref == StageRef(PACK_ID, stage_id)
    assert definition.map.name == stage_id.upper()
    assert not hasattr(definition, "config_class")
    assert not hasattr(definition, "campaign_class")


def test_load_and_load_definition_share_the_same_typed_contract() -> None:
    loader = StageSpecLoader()
    spec = _native_stage_spec("t3")

    assert loader.load(spec) == loader.load_definition(spec)


@pytest.mark.parametrize(
    ("stage_id", "shape", "wave_count", "boss_battles", "policy_battles"),
    [(stage_id, *expected) for stage_id, expected in NATIVE_STAGE_EXPECTATIONS.items()],
)
def test_loader_compiles_complete_normal_and_loop_variants(
    stage_id: str,
    shape: GridShape,
    wave_count: int,
    boss_battles: frozenset[int],
    policy_battles: frozenset[int],
) -> None:
    definition = StageSpecLoader().load(_native_stage_spec(stage_id))
    map_definition = definition.map

    assert map_definition.shape == shape
    assert len(map_definition.normal.cells) == shape.cell_count
    assert map_definition.normal.cells[0].cell_id == CellId(0, 0)
    assert map_definition.normal.cells[-1].cell_id == shape.last_cell
    assert all(cell.weight == 50.0 for cell in map_definition.normal.cells)
    assert len(map_definition.normal.spawn_waves) == wave_count
    assert tuple(wave.battle for wave in map_definition.normal.spawn_waves) == tuple(range(wave_count))
    assert map_definition.normal.boss_battles == boss_battles
    assert map_definition.boss_battles == boss_battles
    assert set(definition.battle_policies) == policy_battles
    assert map_definition.loop == map_definition.normal


def test_compiled_definition_is_deeply_immutable() -> None:
    definition = StageSpecLoader().load(_native_stage_spec("t1"))

    assert isinstance(definition.battle_policies, MappingProxyType)
    assert isinstance(definition.rules.completion, RepeatableCompletion)
    for target, name, value in (
        (definition, "enemy_filter", "changed"),
        (definition.rules.features, "has_ambush", True),
        (definition.rules.navigation, "has_mode_switch", False),
        (definition.map, "name", "changed"),
        (definition.map.normal, "cells", ()),
        (definition.map.normal.cells[0], "token", "++"),
        (definition.map.normal.spawn_waves[0], "enemy", 99),
    ):
        with pytest.raises(FrozenInstanceError):
            _assign_attribute(target, name, value)
    with pytest.raises(TypeError):
        definition.battle_policies[99] = definition.battle_policies[0]


def test_native_loader_has_no_dynamic_or_legacy_materialization_path() -> None:
    source = inspect.getsource(stage_loader_module)
    definition = StageSpecLoader().load(_native_stage_spec("t1"))

    assert 'type("Config"' not in source
    assert 'type("Campaign"' not in source
    assert "legacy_stage" not in source
    assert "legacy_battle_policy" not in source
    assert "CampaignMap" not in source
    assert not isinstance(definition, type)


def test_normal_stage_compiles_config_into_typed_rule_groups() -> None:
    rules = StageSpecLoader().load(_native_stage_spec("t1")).rules

    assert rules.features.siren_templates == ("MeowfficerBust_Hobbies",)
    assert rules.features.movable_enemy_turns == (2,)
    assert rules.features.has_siren
    assert rules.features.has_movable_enemy
    assert not rules.features.has_map_story
    assert rules.features.has_fleet_step
    assert not rules.features.has_ambush
    assert not rules.features.has_mystery
    assert rules.navigation is not None
    assert rules.navigation.chapter_switch is ChapterSwitch.SP_20241219
    assert isinstance(rules.navigation.entrance, StageEntrance)
    assert rules.navigation.entrance.position is StageEntrancePosition.HALF
    assert rules.navigation.entrance.revision is StageEntranceRevision.EVENT_20240725
    assert rules.navigation.has_mode_switch
    assert rules.calibration is not None
    assert rules.calibration.swipe.horizontal == 1.144
    assert rules.calibration.swipe.vertical == 1.165
    assert rules.calibration.homography is None


def test_one_time_stage_has_typed_completion_homography_and_edge_insight() -> None:
    rules = StageSpecLoader().load(_native_stage_spec("sp")).rules

    assert isinstance(rules.completion, OneTimeCompletion)
    assert rules.completion.star_requirements.first == 0
    assert rules.completion.star_requirements.second == 0
    assert rules.completion.star_requirements.third == 0
    assert rules.calibration is not None
    assert rules.calibration.homography is not None
    assert rules.calibration.homography.reference_columns == 8
    assert rules.calibration.homography.reference_rows == 6
    assert len(rules.calibration.homography.corners) == 4
    assert rules.calibration.edge_insight_corner is EdgeInsightCorner.BOTTOM


def test_native_session_uses_typed_policies_and_explicit_boss_strategy() -> None:
    definition = load_default_stage(StageRef(PACK_ID, "t1"))
    session = CampaignSession(definition, CampaignRunVariant.NORMAL)

    assert session.battle_plan(0).intents == (
        ClearSiren(),
        ClearFilteredEnemy(preserve=0),
        DefaultBattle(),
    )
    assert session.battle_plan(4).intents == (
        ClearBossRoadblock(BossStrategy.MAP_SEARCH),
        ClearBoss(BossStrategy.MAP_SEARCH),
    )


@pytest.mark.parametrize(
    ("replacement", "value", "message"),
    [
        ("shape", "not-a-shape", "shape"),
        ("map_data", "-- --", "map_data"),
        ("spawn_data", "- battle: true", "battle"),
        ("spawn_data", "- battle: 0\n  arbitrary: 1", "unknown"),
        ("config", "lowercase: true", "config"),
        ("config", "DANGEROUS: {call: value}", "unknown"),
        (
            "battles",
            "1:\n  steps:\n  - tag: clear_boss\n    strategy: fleet_boss",
            "spawn",
        ),
        ("battles", "0:\n  steps:\n  - tag: arbitrary_expression", "unknown tag"),
        ("battles", "0:\n  policy: fleet_boss", "unknown"),
    ],
)
def test_loader_rejects_invalid_stage_contract_at_load_time(
    tmp_path: Path,
    replacement: str,
    value: str,
    message: str,
) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(**{replacement: value}))

    with pytest.raises(ContentValidationError, match=message):
        loader.load(spec)


def test_loader_rejects_registered_but_undecoded_battle_step_at_its_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fields = {"tag"}
    monkeypatch.setitem(
        stage_loader_module._BATTLE_STEP_FIELDS,  # noqa: SLF001 - 测试扩展表与解码器必须同步。
        "future_step",
        fields,
    )
    monkeypatch.setitem(
        stage_loader_module._BATTLE_STEP_REQUIRED_FIELDS,  # noqa: SLF001 - 测试扩展表与解码器必须同步。
        "future_step",
        fields,
    )
    loader, spec = _write_stage(
        tmp_path / "events",
        _minimal_stage(battles="0:\n  steps:\n  - tag: future_step"),
    )

    with pytest.raises(
        ContentValidationError,
        match=r"battles\.0\.steps\[0\]\.tag: unknown tag: 'future_step'",
    ):
        loader.load(spec)


def test_loader_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    body = _minimal_stage().replace("  name: T1", "  name: T1\n  name: OTHER")
    loader, spec = _write_stage(tmp_path / "events", body)

    with pytest.raises(ContentValidationError, match="duplicate YAML key"):
        loader.load(spec)


def test_loader_rejects_unknown_mechanic_tags_and_removed_extension_field(tmp_path: Path) -> None:
    unknown_mechanic = _minimal_stage().replace(
        "  roadblocks: []",
        "  roadblocks:\n  - tag: call_python",
    )
    loader, spec = _write_stage(tmp_path / "mechanic", unknown_mechanic)
    with pytest.raises(ContentValidationError, match=r"unknown tag.*call_python"):
        loader.load(spec)

    stale_extension_field = _minimal_stage().replace(
        "hard_mode: null",
        "extensions: []\nhard_mode: null",
    )
    loader, spec = _write_stage(tmp_path / "extension", stale_extension_field)
    with pytest.raises(ContentValidationError, match=r"extensions|unknown"):
        loader.load(spec)


def test_loader_compiles_advanced_mechanics_directly_from_the_stage(tmp_path: Path) -> None:
    body = _minimal_stage(
        shape="B1",
        map_data="-- MB",
        weight_data="50 50",
    )
    body = (
        body.replace(
            "  enemy_movement: []",
            "  enemy_movement:\n  - battle: 0\n    source: A1\n    target: B1",
        )
        .replace(
            "  procedures: []",
            "  procedures:\n  - battle: 0\n    operations: [check_accessibility]",
        )
        .replace(
            "  preset_routes: []",
            "  preset_routes:\n"
            "  - start_column: 0\n"
            "    battles:\n"
            "    - battle: 0\n"
            "      steps:\n"
            "      - fleet: fleet_1\n"
            "        delta_x: 1\n"
            "        delta_y: 0\n"
            "        clear_enemy: false",
        )
        .replace(
            "  fixed_target_sequences: []",
            "  fixed_target_sequences:\n  - battles: [0]\n    targets: [B1]\n    fleet: active",
        )
    )
    loader, spec = _write_stage(tmp_path / "advanced", body)

    mechanics = loader.load(spec).mechanics

    assert mechanics.enemy_movement.moves[0].target == CellId(1, 0)
    assert mechanics.procedures[0].battle == 0
    assert mechanics.preset_routes[0].battles[0].battle == 0
    assert mechanics.fixed_target_sequences[0].targets == (CellId(1, 0),)


def test_loader_requires_the_exact_unified_mechanics_shape(tmp_path: Path) -> None:
    body = _minimal_stage().replace("  procedures: []\n", "")
    loader, spec = _write_stage(tmp_path / "missing-mechanic", body)

    with pytest.raises(ContentValidationError, match=r"mechanics.*required fields"):
        loader.load(spec)


@pytest.mark.parametrize("token", ["--", "++", "SP", "ME", "Me", "me", "MB", "MS", "MM", "MA", "__", "SI"])
def test_loader_accepts_every_repository_map_token(tmp_path: Path, token: str) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(map_data=token))

    definition = loader.load(spec)

    assert definition.map.normal.cells[0].token == token


@pytest.mark.parametrize(
    ("field", "body", "message"),
    [
        ("map_data", _minimal_stage(map_data="??"), r"map\.map_data:.*unknown.*\?\?"),
        (
            "map_data_loop",
            _minimal_stage().replace(
                "  weight_data: |-\n    50",
                "  map_data_loop: |-\n    ??\n  weight_data: |-\n    50",
            ),
            r"map\.map_data_loop:.*unknown.*\?\?",
        ),
    ],
)
def test_loader_rejects_unknown_map_tokens(
    tmp_path: Path,
    field: str,
    body: str,
    message: str,
) -> None:
    _ = field
    loader, spec = _write_stage(tmp_path / "events", body)

    with pytest.raises(ContentValidationError, match=message):
        loader.load(spec)


def test_native_loader_requires_explicit_boss_strategy_and_rejects_non_boss_step(tmp_path: Path) -> None:
    loader, spec = _write_stage(tmp_path / "implicit", _minimal_stage(battles="{}"))

    with pytest.raises(ContentValidationError, match="explicit stage policy"):
        loader.load(spec)

    loader, spec = _write_stage(
        tmp_path / "wrong-policy",
        _minimal_stage(
            battles="""0:
  steps:
  - tag: clear_filtered_enemy
    preserve: 0
  - tag: default_battle""",
        ),
    )
    with pytest.raises(ContentValidationError, match=r"boss battle 0 policy must end with ClearBoss"):
        loader.load(spec)


def test_loader_preserves_distinct_loop_portal_and_land_based_data(tmp_path: Path) -> None:
    body = """
        schema_version: 4
        map:
          name: T1
          shape: B2
          camera_data: [A1]
          camera_data_spawn_point: [B2]
          map_covered: [B1]
          portal_data: [[A1, B2]]
          map_data: |-
            -- ++
            SP MB
          map_data_loop: |-
            -- --
            SP MB
          weight_data: |-
            50 50
            50 50
          land_based_data: [[A1, right]]
          spawn_data:
          - battle: 0
            boss: 1
          spawn_data_loop:
          - battle: 0
          - battle: 1
            boss: 1
        config:
          MAP_HAS_MAP_STORY: false
          MAP_HAS_FLEET_STEP: false
          MAP_HAS_AMBUSH: false
          MAP_HAS_MYSTERY: false
          MAP_HAS_PORTAL: true
          MAP_HAS_LAND_BASED: true
        enemy_filter: 1L
        battles:
          0:
            steps:
            - tag: clear_boss
              strategy: fleet_boss
          1:
            steps:
            - tag: clear_boss
              strategy: fleet_boss
        mechanics:
          roadblocks: []
          fleet_coordination: []
          pickups: []
          map_interactions: []
          map_mutations: []
          moving_enemies:
            turns: []
            wait_until_clear: false
            initial_enemy_cells: []
            initial_siren_cells: []
          map_structures:
            walls: []
            maze_groups: []
            fortress_enemy_cells: []
            fortress_block_cells: []
            bouncing_enemy_routes: []
          enemy_movement: []
          procedures: []
          preset_routes: []
          fixed_target_sequences: []
        programs: []
        boss_approaches: []
        hard_mode: null
    """
    loader, spec = _write_stage(tmp_path / "events", body)

    definition = loader.load(spec)

    assert tuple(cell.token for cell in definition.map.normal.cells) == ("--", "++", "SP", "MB")
    assert tuple(cell.token for cell in definition.map.loop.cells) == ("--", "--", "SP", "MB")
    assert definition.map.map_covered == (CellId(1, 0),)
    assert definition.map.portals == (PortalSpec(CellId(0, 0), CellId(1, 1)),)
    assert definition.map.land_based == (LandBasedSpec(CellId(0, 0), LandBasedDirection.RIGHT),)
    assert definition.map.normal.spawn_waves == (SpawnWave(0, boss=1),)
    assert definition.map.loop.spawn_waves == (SpawnWave(0), SpawnWave(1, boss=1))


def test_loader_rejects_manifest_stage_bound_to_another_map(tmp_path: Path) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage().replace("name: T1", "name: HT1"))

    with pytest.raises(ContentValidationError, match=r"map\.name.*stage|stage.*map\.name"):
        loader.load(spec)


def test_loader_rejects_foreign_input_types() -> None:
    with pytest.raises(TypeError, match="StageSpec"):
        StageSpecLoader().load(cast("StageSpec", object()))
    with pytest.raises(TypeError, match="StageRef"):
        load_default_stage(cast("StageRef", object()))
