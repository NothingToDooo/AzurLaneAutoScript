from typing import Any, cast

import pytest

from module.adapters.campaign_runtime_tunings import (
    SUPPORTED_RUNTIME_TUNING_KEYS,
    CampaignRuntimeTuningPatch,
    ConfiguredBossFleet,
    RuntimeBehaviorPatch,
    RuntimeThresholdPatch,
    RuntimeTuningValidationError,
    compile_campaign_runtime_tuning_patch,
)
from module.content.runtime_profile import RuntimeTuning, RuntimeTuningKey
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry


def test_empty_tuning_patch_has_no_projection() -> None:
    patch = compile_campaign_runtime_tuning_patch(())

    assert patch == CampaignRuntimeTuningPatch()
    assert patch.config.to_overrides() == {}
    assert patch.config.configured_boss_fleet is None
    assert patch.thresholds == RuntimeThresholdPatch()
    assert patch.behavior == RuntimeBehaviorPatch()


def test_sparse_patch_preserves_explicit_false_zero_and_empty_containers() -> None:
    patch = compile_campaign_runtime_tuning_patch(
        (
            RuntimeTuning(RuntimeTuningKey.MAP_SWIPE_PREDICT, value=False),
            RuntimeTuning(RuntimeTuningKey.FLEET_2, 0),
            RuntimeTuning(RuntimeTuningKey.MAP_ENEMY_TEMPLATE, []),
            RuntimeTuning(RuntimeTuningKey.MAP_ENEMY_GENRE_DETECTION_SCALING, {}),
            RuntimeTuning(RuntimeTuningKey.COMBAT_DISABLE_STUCK_DETECTION_BATTLE, 0),
        )
    )

    assert patch.config.to_overrides() == {
        "MAP_SWIPE_PREDICT": False,
        "Fleet_Fleet2": 0,
        "MAP_ENEMY_TEMPLATE": (),
        "MAP_ENEMY_GENRE_DETECTION_SCALING": {},
    }
    assert patch.behavior.combat_disable_stuck_detection_battle == 0


@pytest.mark.parametrize("value", [1.2, 5])
def test_numeric_config_tuning_is_normalized_to_float(value: float) -> None:
    patch = compile_campaign_runtime_tuning_patch(
        (RuntimeTuning(RuntimeTuningKey.COINCIDENT_POINT_ENCOURAGE_DISTANCE, value),)
    )

    projected = patch.config.to_overrides()["COINCIDENT_POINT_ENCOURAGE_DISTANCE"]
    assert type(projected) is float
    assert projected == pytest.approx(float(value))


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        (RuntimeTuningKey.FLEET_2, True, "fleet_2 must be an integer"),
        (RuntimeTuningKey.SUBMARINE, 3, "submarine must be an integer <= 2"),
        (RuntimeTuningKey.DETECTION_BACKEND, None, "detection_backend"),
        (
            RuntimeTuningKey.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD,
            1.1,
            "between 0 and 1",
        ),
        (RuntimeTuningKey.HOMO_EDGE_COLOR_RANGE, (33, 0), "ordered integer pair"),
        (RuntimeTuningKey.HOMO_TILE, (140,), "pair of integers"),
        (RuntimeTuningKey.DISTANCE_POINT_X_RANGE, (), "non-empty tuple"),
        (RuntimeTuningKey.VANISH_POINT_RANGE, ((1, 2),), "exactly 2 integer ranges"),
        (
            RuntimeTuningKey.EDGE_LINES_FIND_PEAKS_PARAMETERS,
            {"unknown": 1},
            "unknown field 'unknown'",
        ),
        (
            RuntimeTuningKey.INTERNAL_LINES_FIND_PEAKS_PARAMETERS,
            {"width": (2, 1)},
            "ordered non-negative range for width",
        ),
        (
            RuntimeTuningKey.INTERNAL_LINES_FIND_PEAKS_PARAMETERS,
            {"distance": (1, 2)},
            "scalar distance parameter",
        ),
        (
            RuntimeTuningKey.INTERNAL_LINES_FIND_PEAKS_PARAMETERS,
            {"distance": 0.5},
            "distance parameter >= 1",
        ),
        (
            RuntimeTuningKey.INTERNAL_LINES_FIND_PEAKS_PARAMETERS,
            {"wlen": 1},
            "integer wlen parameter >= 2",
        ),
        (
            RuntimeTuningKey.INTERNAL_LINES_FIND_PEAKS_PARAMETERS,
            {"wlen": 2.0},
            "integer wlen parameter",
        ),
        (RuntimeTuningKey.MAP_ENEMY_GENRE_DETECTION_SCALING, {"DD": 0}, "positive number"),
        (RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER, 0, "positive number"),
    ],
)
def test_invalid_tuning_contract_is_rejected(
    key: RuntimeTuningKey,
    value: object,
    match: str,
) -> None:
    with pytest.raises(RuntimeTuningValidationError, match=match):
        compile_campaign_runtime_tuning_patch((RuntimeTuning(key, value),))


def test_patch_value_objects_validate_their_own_ranges_and_types() -> None:
    invalid_index: Any = True
    with pytest.raises(TypeError, match="configured boss fleet must be an integer"):
        ConfiguredBossFleet(invalid_index)
    with pytest.raises(ValueError, match="configured boss fleet must be 1 or 2"):
        ConfiguredBossFleet(3)
    with pytest.raises(ValueError, match="between 0 and 1"):
        RuntimeThresholdPatch(air_raid_overlay_transparency=1.1)
    with pytest.raises(TypeError, match="pair of integers"):
        RuntimeBehaviorPatch(boss_appear_refocus_preset=cast("Any", (1.0, 2)))


def test_runtime_tuning_decoder_is_exhaustive_for_all_47_keys() -> None:
    assert len(SUPPORTED_RUNTIME_TUNING_KEYS) == 47
    assert frozenset(RuntimeTuningKey) == SUPPORTED_RUNTIME_TUNING_KEYS


def test_all_real_runtime_profiles_compile_to_typed_patches() -> None:
    registry = load_default_campaign_runtime_profile_registry()

    patches = [compile_campaign_runtime_tuning_patch(profile.tunings) for profile in registry.profiles.values()]

    assert len(patches) == len(registry.profiles)
    assert all(isinstance(patch, CampaignRuntimeTuningPatch) for patch in patches)
