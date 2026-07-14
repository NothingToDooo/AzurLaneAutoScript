from dataclasses import replace

from module.adapters.campaign_mumu12 import compile_campaign_map
from module.content import CampaignRunVariant, CellId, CompiledCampaignSessionSource, ContentCatalog, StageRef
from module.content.manifest import load_default_event_manifests
from module.content.mechanic_rules import MapMutationRules
from module.content.stage_loader import StageSpecLoader, load_default_stage

_NORMAL_MAP_DATA = """ME -- ++ ++ -- ME ME ME ++ ++ ++
-- ME ME ME ME ME ME -- SP SP --
MB -- __ -- -- -- -- -- ME -- --
MB ME -- Me Me -- Me ++ ++ -- ME
MM -- Me ME -- Me -- MA ++ -- ME
++ ME ME -- ++ -- ME -- ME -- --
++ -- ME Me Me ME -- -- -- -- ++
-- ME -- -- -- __ -- ME ME -- ME
-- -- ++ MB MB ++ ++ MM ME ME ME"""

_LOOP_MAP_DATA = """ME -- ++ ++ -- ME ME ME ++ ++ ++
-- ME ME ME ME ME ME -- SP SP --
MB -- __ -- -- -- -- -- ME -- --
MB ME -- Me Me -- Me ++ ++ -- ME
MM -- Me ME -- Me -- MA ++ -- ME
++ ME ME -- ++ -- ME -- ME -- --
++ -- ME Me Me ME -- -- -- -- ++
-- -- -- -- -- __ -- ME ME -- ME
-- -- ++ MB MB ++ ++ MM ME ME ME"""


def test_campaign_hard_14_4_resolves_to_its_complete_declarative_override() -> None:
    catalog = ContentCatalog(load_default_event_manifests())
    hard_ref = StageRef("campaign_hard", "14-4")
    source = CompiledCampaignSessionSource(
        catalog,
        StageSpecLoader(),
        stage_refs=(hard_ref,),
    )

    assert source.resolve_hard_stage_ref("14-4") == hard_ref
    assert catalog.resolve_stage(StageRef("campaign_hard", "campaign_14_4")).ref == hard_ref
    hard = source.resolve(hard_ref, CampaignRunVariant.LOOP).definition
    main = load_default_stage(StageRef("campaign_main", "14-4"))
    compiled = compile_campaign_map(hard)

    assert hard.runtime_profile.profile_id == main.runtime_profile.profile_id
    assert hard.rules == main.rules
    assert hard.enemy_filter == main.enemy_filter
    assert hard.mechanics == replace(main.mechanics, map_mutations=MapMutationRules())
    assert hard.battle_programs == main.battle_programs
    assert compiled.shape == (10, 8)
    assert [str(grid) for grid in compiled.camera_data] == ["D2", "D6", "D7", "H2", "H6", "H7"]
    assert [str(grid) for grid in compiled.camera_data_spawn_point] == ["H2"]
    assert [str(grid) for grid in compiled.manual_map_covered] == ["A4"]
    assert compiled.map_data == _NORMAL_MAP_DATA
    assert compiled.map_data_loop == _LOOP_MAP_DATA
    assert tuple(cell.weight for cell in hard.map.normal.cells) == tuple(cell.weight for cell in main.map.normal.cells)
    assert compiled.spawn_data == [
        {"battle": 0, "enemy": 4},
        {"battle": 1, "enemy": 3},
        {"battle": 2, "enemy": 2},
        {"battle": 3, "enemy": 2},
        {"battle": 4, "enemy": 1},
        {"battle": 5, "enemy": 1},
        {"battle": 6},
        {"battle": 7, "boss": 1},
    ]
    assert compiled.spawn_data_loop == [{"battle": 0, "boss": 1}]


def test_campaign_main_14_4_preserves_the_shared_manual_covered_cell() -> None:
    definition = load_default_stage(StageRef("campaign_main", "14-4"))

    assert definition.map.map_covered == (CellId(0, 3),)
    assert [str(grid) for grid in compile_campaign_map(definition).manual_map_covered] == ["A4"]
