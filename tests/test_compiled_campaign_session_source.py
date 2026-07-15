from dataclasses import FrozenInstanceError
from operator import itemgetter
from typing import TYPE_CHECKING, cast

import pytest

from module.content.campaign_session import CampaignRunVariant
from module.content.campaign_session_source import CompiledCampaignSessionSource
from module.content.catalog import ContentCatalog
from module.content.errors import ContentValidationError, UnknownStageError
from module.content.manifest import load_default_event_manifests
from module.content.models import EventPack, StageRef, StageSpec
from module.content.stage_loader import StageSpecLoader

if TYPE_CHECKING:
    from pathlib import Path

    from module.content.stage_definition import CampaignStageDefinition


def _assign_attribute(target: object, name: str, value: object) -> None:
    setattr(target, name, value)


def _minimal_stage(*, step_tag: str = "clear_boss", extra_config: str = "") -> str:
    return f"""schema_version: 4
map:
  name: T1
  shape: A1
  camera_data: [A1]
  camera_data_spawn_point: [A1]
  map_data: |-
    MB
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
{extra_config}enemy_filter: 1L
battles:
  0:
    steps:
    - tag: {step_tag}
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


def _source_for_stage(tmp_path: Path, body: str) -> CompiledCampaignSessionSource:
    content_root = tmp_path / "events"
    stage_path = content_root / "event_test" / "stages" / "t1.yaml"
    stage_path.parent.mkdir(parents=True)
    stage_path.write_text(body, encoding="utf-8", newline="\n")
    spec = StageSpec(StageRef("event_test", "t1"), "stages/t1.yaml")
    catalog = ContentCatalog((EventPack("event_test", stages=(spec,)),))
    return CompiledCampaignSessionSource(catalog, StageSpecLoader(content_root))


def test_resolve_compiles_only_the_requested_stage_and_caches_each_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = ContentCatalog(load_default_event_manifests())
    first, second, *_remaining = catalog.stages
    original_load = StageSpecLoader.load
    loaded: list[StageRef] = []

    def tracked_load(loader: StageSpecLoader, spec: StageSpec) -> CampaignStageDefinition:
        loaded.append(spec.ref)
        return original_load(loader, spec)

    monkeypatch.setattr(StageSpecLoader, "load", tracked_load)

    source = CompiledCampaignSessionSource(catalog, StageSpecLoader())

    assert loaded == []
    assert source.session_count == 0
    normal = source.resolve(first.ref, CampaignRunVariant.NORMAL)
    assert loaded == [first.ref]
    assert source.session_count == 1
    assert source.resolve(first.ref, CampaignRunVariant.NORMAL) is normal
    loop = source.resolve(first.ref, CampaignRunVariant.LOOP)
    assert loaded == [first.ref]
    assert source.session_count == 2
    assert source.resolve(first.ref, CampaignRunVariant.LOOP) is loop
    assert second.ref not in loaded


def test_source_rejects_missing_and_invalid_lookups() -> None:
    catalog = ContentCatalog(load_default_event_manifests())
    first, second, *_remaining = catalog.stages
    source = CompiledCampaignSessionSource(catalog, StageSpecLoader())

    assert source.resolve(first.ref, CampaignRunVariant.NORMAL).definition.ref == first.ref
    assert source.resolve(second.ref, CampaignRunVariant.NORMAL).definition.ref == second.ref
    with pytest.raises(UnknownStageError, match="missing"):
        source.resolve(StageRef(first.ref.pack_id, "missing"), CampaignRunVariant.NORMAL)
    with pytest.raises(TypeError, match="StageRef"):
        source.resolve(cast("StageRef", object()), CampaignRunVariant.NORMAL)
    with pytest.raises(TypeError, match="CampaignRunVariant"):
        source.resolve(first.ref, cast("CampaignRunVariant", "normal"))


def test_content_source_selects_aliases_and_loop_stages_before_resolving_variants() -> None:
    catalog = ContentCatalog(load_default_event_manifests())
    source = CompiledCampaignSessionSource(
        catalog,
        StageSpecLoader(),
        loop_choice=itemgetter(-1),
    )

    alias = source.select(StageRef("campaign_main", "campaign_1_1"), remaining_runs=0)
    assert alias.selected_ref == StageRef("campaign_main", "1-1")
    assert not alias.loop_stage_switch
    assert source.resolve(alias.selected_ref, CampaignRunVariant.NORMAL).definition.ref == alias.selected_ref

    random_loop = source.select(StageRef("event_20221124_cn", "th"), remaining_runs=0)
    assert random_loop.selected_ref == StageRef("event_20221124_cn", "th5")
    assert random_loop.loop_stage_switch

    ordered_loop = source.select(StageRef("event_20221124_cn", "th"), remaining_runs=2)
    assert ordered_loop.selected_ref == StageRef("event_20221124_cn", "th4")
    assert ordered_loop.loop_stage_switch

    resumed_loop = source.select(
        StageRef("event_20221124_cn", "th"),
        remaining_runs=0,
        preferred_ref=StageRef("event_20221124_cn", "th2"),
    )
    assert resumed_loop.selected_ref == StageRef("event_20221124_cn", "th2")
    assert resumed_loop.loop_stage_switch

    with pytest.raises(ContentValidationError, match="preferred_ref"):
        source.select(
            StageRef("event_20221124_cn", "th"),
            remaining_runs=0,
            preferred_ref=StageRef("event_20221124_cn", "a1"),
        )


def test_hard_stage_resolution_prefers_explicit_override_then_main_campaign() -> None:
    catalog = ContentCatalog(load_default_event_manifests())
    hard_override = StageRef("campaign_hard", "12-4")
    ordinary_stage = StageRef("campaign_main", "11-4")
    source = CompiledCampaignSessionSource(
        catalog,
        StageSpecLoader(),
    )

    assert source.resolve_hard_stage_ref("12-4") == hard_override
    assert source.resolve_hard_stage_ref("11-4") == ordinary_stage
    assert (
        source.resolve(
            source.resolve_hard_stage_ref("12-4"),
            CampaignRunVariant.LOOP,
        ).definition.ref
        == hard_override
    )
    assert (
        source.resolve(
            source.resolve_hard_stage_ref("11-4"),
            CampaignRunVariant.LOOP,
        ).definition.ref
        == ordinary_stage
    )


def test_content_source_rejects_invalid_loop_selection() -> None:
    catalog = ContentCatalog(load_default_event_manifests())
    invalid = CompiledCampaignSessionSource(
        catalog,
        StageSpecLoader(),
        loop_choice=lambda _stages: "missing",
    )

    with pytest.raises(ContentValidationError, match="loop_choice"):
        invalid.select(StageRef("event_20221124_cn", "th"), remaining_runs=0)
    with pytest.raises(ValueError, match="remaining_runs"):
        invalid.select(StageRef("campaign_main", "1-1"), remaining_runs=-1)


def test_cached_sessions_remain_immutable() -> None:
    catalog = ContentCatalog(load_default_event_manifests())
    (first, *_remaining) = catalog.stages
    source = CompiledCampaignSessionSource(catalog, StageSpecLoader())
    session = source.resolve(first.ref, CampaignRunVariant.LOOP)

    with pytest.raises(FrozenInstanceError):
        _assign_attribute(session, "variant", CampaignRunVariant.NORMAL)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (_minimal_stage(step_tag="unknown"), "unknown tag"),
        (
            _minimal_stage(extra_config="  MAP_UNKNOWN_MECHANIC: true\n"),
            "unknown fields.*MAP_UNKNOWN_MECHANIC",
        ),
        (
            _minimal_stage(
                extra_config=(
                    "  MAP_CHAPTER_SWITCH_20241219_SP: true\n"
                    "  STAGE_ENTRANCE: [half, future]\n"
                    "  MAP_HAS_MODE_SWITCH: true\n"
                )
            ),
            "unsupported entrance profile",
        ),
    ],
)
def test_explicit_full_validation_fails_for_unknown_policy_mechanic_or_ui_revision(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    source = _source_for_stage(tmp_path, body)
    assert source.session_count == 0
    with pytest.raises(ContentValidationError, match=message):
        source.validate_all()
