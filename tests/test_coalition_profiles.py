from pathlib import Path

import pytest

from module.coalition import assets as coalition_assets
from module.coalition.coalition import CoalitionPtOcr
from module.coalition.profile import (
    ACADEMY_COALITION_PROFILE,
    COALITION_CLIENT_PROFILES,
    DAL_COALITION_PROFILE,
    FASHION_COALITION_PROFILE,
    FROSTFALL_COALITION_PROFILE,
    NEONCITY_COALITION_PROFILE,
    CoalitionClientProfile,
    CoalitionEntryStrategy,
    CoalitionModeDriver,
    CoalitionOilReadLocation,
    CoalitionPtOcrStrategy,
)
from module.content.activity_catalog import ActivityCatalog
from module.content.activity_profile import (
    CoalitionDefinition,
    CoalitionFleetMode,
    CoalitionProfileId,
    CoalitionStageId,
)
from module.content.manifest import load_default_event_manifests


@pytest.fixture(scope="module")
def catalog() -> ActivityCatalog:
    return ActivityCatalog(load_default_event_manifests())


def test_builtin_profiles_cover_every_coalition_manifest_and_allowed_session(catalog: ActivityCatalog) -> None:
    coalition_packs = [
        (pack, activity)
        for pack in load_default_event_manifests()
        if isinstance((activity := pack.activity), CoalitionDefinition)
    ]

    assert {definition.profile_id for _, definition in coalition_packs} == COALITION_CLIENT_PROFILES.profile_ids
    assert COALITION_CLIENT_PROFILES.profile_ids == {
        CoalitionProfileId("frostfall"),
        CoalitionProfileId("academy"),
        CoalitionProfileId("neoncity"),
        CoalitionProfileId("dal"),
        CoalitionProfileId("fashion"),
    }
    for pack, _ in coalition_packs:
        activity = catalog.resolve_coalition(str(pack.pack_id))
        for stage in activity.definition.stages:
            for fleet in CoalitionFleetMode:
                if stage.fleet_rule.allows(fleet):
                    session = COALITION_CLIENT_PROFILES.resolve(activity, stage.stage_id, fleet)
                    assert session.stage is stage
                    assert session.fleet is fleet


@pytest.mark.parametrize(
    ("profile", "mode", "entry", "ocr", "oil_location"),
    [
        (
            FROSTFALL_COALITION_PROFILE,
            CoalitionModeDriver.STANDARD,
            CoalitionEntryStrategy.DIRECT,
            CoalitionPtOcrStrategy.PLAIN,
            CoalitionOilReadLocation.COALITION,
        ),
        (
            ACADEMY_COALITION_PROFILE,
            CoalitionModeDriver.STANDARD,
            CoalitionEntryStrategy.DIRECT,
            CoalitionPtOcrStrategy.AFTER_COLON,
            CoalitionOilReadLocation.COALITION,
        ),
        (
            NEONCITY_COALITION_PROFILE,
            CoalitionModeDriver.RED_TEXT,
            CoalitionEntryStrategy.DIRECT,
            CoalitionPtOcrStrategy.PLAIN,
            CoalitionOilReadLocation.COALITION,
        ),
        (
            DAL_COALITION_PROFILE,
            CoalitionModeDriver.NONE,
            CoalitionEntryStrategy.AREA_THEN_DIFFICULTY,
            CoalitionPtOcrStrategy.AFTER_X,
            CoalitionOilReadLocation.COALITION,
        ),
        (
            FASHION_COALITION_PROFILE,
            CoalitionModeDriver.STANDARD,
            CoalitionEntryStrategy.DIRECT,
            CoalitionPtOcrStrategy.PLAIN,
            CoalitionOilReadLocation.CAMPAIGN_MENU,
        ),
    ],
)
def test_profiles_select_only_closed_client_strategies(
    profile: CoalitionClientProfile,
    mode: CoalitionModeDriver,
    entry: CoalitionEntryStrategy,
    ocr: CoalitionPtOcrStrategy,
    oil_location: CoalitionOilReadLocation,
) -> None:
    assert profile.mode_driver is mode
    assert profile.entry_strategy is entry
    assert profile.pt_ocr.strategy is ocr
    assert profile.oil_read_location is oil_location


def test_dal_difficulty_and_fashion_preparation_are_asset_bindings() -> None:
    dal_stage = DAL_COALITION_PROFILE.stage_assets(CoalitionStageId("area4-hard"))

    assert dal_stage.entrance is coalition_assets.DAL_AREA4
    assert dal_stage.difficulty is coalition_assets.DAL_HARD
    assert DAL_COALITION_PROFILE.preparation.difficulty_exit is coalition_assets.DAL_DIFFICULTY_EXIT
    assert FASHION_COALITION_PROFILE.preparation.enter is coalition_assets.NEONCITY_FLEET_PREPARATION


def test_profile_resolution_rejects_invalid_selection_before_runtime_construction(catalog: ActivityCatalog) -> None:
    activity = catalog.resolve_coalition("coalition_20260122")

    with pytest.raises(LookupError, match="has no stage missing"):
        COALITION_CLIENT_PROFILES.resolve(activity, CoalitionStageId("missing"), CoalitionFleetMode.MULTI)
    with pytest.raises(ValueError, match="fleet must satisfy"):
        COALITION_CLIENT_PROFILES.resolve(activity, CoalitionStageId("sp"), CoalitionFleetMode.SINGLE)


@pytest.mark.parametrize(
    ("profile", "raw", "expected"),
    [
        (FROSTFALL_COALITION_PROFILE, "1200", 1200),
        (ACADEMY_COALITION_PROFILE, "累计:2300", 2300),
        (DAL_COALITION_PROFILE, "X9100", 9100),
    ],
)
def test_pt_ocr_normalizers_are_selected_by_profile(
    profile: CoalitionClientProfile,
    raw: str,
    expected: int,
) -> None:
    assert CoalitionPtOcr(profile.pt_ocr).after_process(raw) == expected


def test_coalition_domain_has_no_dated_dispatch_or_scheduler_writes() -> None:
    domain = Path("module/coalition")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (domain / "profile.py", domain / "ui.py", domain / "coalition.py", domain / "combat.py")
    )

    for forbidden in (
        "coalition_20",
        "parse_coalition_",
        "task_delay(",
        "task_stop(",
        "cross_set(",
    ):
        assert forbidden not in source
    assert not (domain / "contracts.py").exists()
    assert not (domain / "coalition_sp.py").exists()
