from typing import TYPE_CHECKING, cast

import numpy as np
import pytest

from module.adapters.campaign_map_observer import (
    CampaignMapObserverExecutor,
    build_campaign_map_observer,
)
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
)
from module.content.manifest import load_default_event_manifests
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
)
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.handler.assets import MAP_ENEMY_SEARCHING

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray
    from module.map.map_observer import CampaignMapObserver

_IMPLEMENTATION = RuntimeImplementationId("observation/red_overlay_enemy_search")


class _ThresholdRuntime:
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = 0.5
    MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD = 0.5
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = 0.5


def _real_profile(pack_id: str, stage_id: str) -> CampaignRuntimeProfile:
    pack = next(pack for pack in load_default_event_manifests() if str(pack.pack_id) == pack_id)
    stage = next(stage for stage in pack.stages if stage.ref.stage_id == stage_id)
    return load_default_campaign_runtime_profile_registry().resolve(stage.runtime_profile_id)


def _observer_for(profile: CampaignRuntimeProfile) -> tuple[CampaignRuntimeProfileManager, CampaignMapObserver]:
    manager = CampaignRuntimeProfileManager(profile, load_default_campaign_runtime_executor_registry())
    instances = manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION)
    assert any(isinstance(instance, CampaignMapObserverExecutor) for instance in instances)
    return manager, build_campaign_map_observer(instances)


def _red_overlay_image(red: int) -> ImageArray:
    image = cast("ImageArray", np.full((720, 1280, 3), MAP_ENEMY_SEARCHING.color, dtype=np.uint8))
    x1, y1, x2, y2 = (int(value) for value in MAP_ENEMY_SEARCHING.area)
    image[y1:y2, x1:x2, 0] = red
    return image


@pytest.mark.parametrize(
    ("red", "expected"),
    [
        (241, False),
        (242, False),
        (243, True),
    ],
)
def test_red_overlay_detector_uses_strict_threshold(red: int, *, expected: bool) -> None:
    manager, observer = _observer_for(_real_profile("event_20220915_cn", "c1"))
    runtime = _ThresholdRuntime()
    manager.apply_runtime_tunings(runtime)

    assert pytest.approx(0.5) == runtime.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD
    assert (
        observer.enemy_searching.appears(
            _red_overlay_image(red),
            overlay_transparency_threshold=runtime.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD,
        )
        is expected
    )


def test_real_red_overlay_detector_replaces_standard_luma_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_standard_luma(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        message = "red-overlay replacement must not call the standard luma detector"
        raise AssertionError(message)

    monkeypatch.setattr(type(MAP_ENEMY_SEARCHING), "match_luma", unexpected_standard_luma)
    _, observer = _observer_for(_real_profile("event_20220915_cn", "c1"))

    assert not observer.enemy_searching.appears(
        _red_overlay_image(241),
        overlay_transparency_threshold=0.5,
    )


@pytest.mark.parametrize(
    ("pack_id", "stage_id", "expected_threshold", "expected_visible"),
    [
        ("event_20220915_cn", "a1", 0.65, False),
        ("event_20220915_cn", "c1", 0.5, True),
        ("war_archives_20220915_cn", "a1", 0.65, False),
        ("war_archives_20220915_cn", "c1", 0.5, True),
    ],
)
def test_real_profiles_wire_red_overlay_with_their_effective_threshold(
    pack_id: str,
    stage_id: str,
    expected_threshold: float,
    *,
    expected_visible: bool,
) -> None:
    profile = _real_profile(pack_id, stage_id)
    manager, observer = _observer_for(profile)
    runtime = _ThresholdRuntime()
    manager.apply_runtime_tunings(runtime)
    red_bindings = tuple(
        binding
        for extension in profile.extensions
        for binding in extension.executors
        if binding.implementation_id == _IMPLEMENTATION
    )

    assert len(red_bindings) == 1
    assert dict(red_bindings[0].options) == {}
    assert pytest.approx(expected_threshold) == runtime.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD
    assert (
        observer.enemy_searching.appears(
            _red_overlay_image(243),
            overlay_transparency_threshold=runtime.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD,
        )
        is expected_visible
    )


def test_red_overlay_profile_rejects_obsolete_string_operation() -> None:
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("obsolete-red-overlay-test"),
        (
            RuntimeExecutorBinding(
                RuntimeExecutorKind.MAP_OBSERVATION,
                _IMPLEMENTATION,
                {"operations": ["enemy_searching_appear"]},
            ),
        ),
    )
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("obsolete-red-overlay-test"),
        (extension,),
    )

    with pytest.raises(CampaignRuntimeProfileError, match=r"unknown option: operations"):
        CampaignRuntimeProfileManager(profile, load_default_campaign_runtime_executor_registry())
