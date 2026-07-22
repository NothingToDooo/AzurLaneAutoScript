from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import pytest

from dev_tools.campaign_runtime_profile_validator import validate_campaign_content
from module.adapters import campaign_profiles
from module.adapters.campaign_profiles import validate_mumu12_campaign_runtime_profiles
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)
from module.content.errors import ContentValidationError
from module.content.manifest import load_default_event_manifests
from module.content.models import StageRef, StageSpec
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    CampaignRuntimeProfileRegistry,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
    RuntimeTuningKey,
)
from module.content.runtime_profile_catalog import (
    compile_campaign_runtime_profile_registry,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.content.models import EventPack

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "content" / "campaign-runtime-profiles.json"


@pytest.fixture(scope="module")
def packs_by_id() -> Mapping[str, EventPack]:
    return MappingProxyType({str(pack.pack_id): pack for pack in load_default_event_manifests()})


@pytest.fixture(scope="module")
def profile_registry() -> CampaignRuntimeProfileRegistry:
    return compile_campaign_runtime_profile_registry(PROFILE_PATH)


def _stage(packs_by_id: Mapping[str, EventPack], pack_id: str, stage_id: str) -> StageSpec:
    return next(stage for stage in packs_by_id[pack_id].stages if stage.ref.stage_id == stage_id)


def _profile(
    profile_registry: CampaignRuntimeProfileRegistry,
    packs_by_id: Mapping[str, EventPack],
    pack_id: str,
    stage_id: str,
) -> CampaignRuntimeProfile:
    return profile_registry.resolve(_stage(packs_by_id, pack_id, stage_id).runtime_profile_id)


def _executors(
    profile_registry: CampaignRuntimeProfileRegistry,
    extension_id: str,
) -> dict[RuntimeExecutorKind, RuntimeExecutorBinding]:
    extension = next(
        extension for extension in profile_registry.extensions.values() if extension.extension_id.value == extension_id
    )
    return {executor.kind: executor for executor in extension.executors}


def test_current_runtime_profile_sources_are_self_contained_and_valid() -> None:
    validate_campaign_content(ROOT)


def test_registry_validator_compiles_the_same_complete_profile_service_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles = CampaignRuntimeProfileRegistry((), (CampaignRuntimeProfile.core(),))
    stages = (StageSpec(StageRef("campaign_main", "1-1"), "stages/1-1.yaml"),)
    compiled: list[object] = []

    def compile_services(manager: object) -> object:
        compiled.append(manager)
        return object()

    monkeypatch.setattr(campaign_profiles, "compile_campaign_profile_services", compile_services)

    validate_mumu12_campaign_runtime_profiles(
        stages,
        profiles,
        CampaignRuntimeExecutorRegistry(()),
    )

    assert len(compiled) == 1


def test_production_validator_rejects_unselected_profile_with_unknown_executor() -> None:
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("event_test/t1/navigation"),
        (
            RuntimeExecutorBinding(
                RuntimeExecutorKind.NAVIGATION,
                RuntimeImplementationId("navigation/not_registered"),
                {"route": "test"},
            ),
        ),
    )
    profiles = CampaignRuntimeProfileRegistry(
        (extension,),
        (
            CampaignRuntimeProfile.core(),
            CampaignRuntimeProfile(
                CampaignRuntimeProfileId("invalid_unselected"),
                (extension,),
            ),
        ),
    )
    stages = (
        StageSpec(StageRef("campaign_main", "1-1"), "stages/1-1.yaml"),
        StageSpec(
            StageRef("event_test", "t1"),
            "stages/t1.yaml",
            runtime_profile_id=CampaignRuntimeProfileId("invalid_unselected"),
        ),
    )

    with pytest.raises(ContentValidationError, match=r"not executable.*not_registered"):
        validate_mumu12_campaign_runtime_profiles(stages, profiles)


def test_production_validator_rejects_expected_end_policy_without_waitable_animation() -> None:
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("event_test/t1/expected_end"),
        (
            RuntimeExecutorBinding(
                RuntimeExecutorKind.EVENT_UI,
                RuntimeImplementationId("event_ui/event_animation_expected_end"),
                {"event_animation_end_battle": 3},
            ),
        ),
    )
    profiles = CampaignRuntimeProfileRegistry(
        (extension,),
        (
            CampaignRuntimeProfile.core(),
            CampaignRuntimeProfile(
                CampaignRuntimeProfileId("invalid_event_animation_policy"),
                (extension,),
            ),
        ),
    )
    stages = (
        StageSpec(StageRef("campaign_main", "1-1"), "stages/1-1.yaml"),
        StageSpec(
            StageRef("event_test", "t1"),
            "stages/t1.yaml",
            runtime_profile_id=CampaignRuntimeProfileId("invalid_event_animation_policy"),
        ),
    )

    with pytest.raises(ContentValidationError, match=r"not executable.*typed animation wait provider"):
        validate_mumu12_campaign_runtime_profiles(stages, profiles)


def test_production_validator_builds_and_rejects_an_untyped_hard_behavior() -> None:
    implementation_id = RuntimeImplementationId("hard_mode/untyped")
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("event_test/t1/hard"),
        (
            RuntimeExecutorBinding(
                RuntimeExecutorKind.HARD_MODE,
                implementation_id,
                {},
            ),
        ),
    )
    profiles = CampaignRuntimeProfileRegistry(
        (extension,),
        (
            CampaignRuntimeProfile.core(),
            CampaignRuntimeProfile(
                CampaignRuntimeProfileId("invalid_hard_behavior"),
                (extension,),
            ),
        ),
    )
    stages = (
        StageSpec(StageRef("campaign_main", "1-1"), "stages/1-1.yaml"),
        StageSpec(
            StageRef("event_test", "t1"),
            "stages/t1.yaml",
            runtime_profile_id=CampaignRuntimeProfileId("invalid_hard_behavior"),
        ),
    )

    def build_untyped(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        del context
        return RuntimeExecutorInstance({RuntimeExecutorKind.HARD_MODE})

    executors = CampaignRuntimeExecutorRegistry(
        (
            RuntimeExecutorFactoryDescriptor(
                implementation_id,
                {RuntimeExecutorKind.HARD_MODE: RuntimeExecutorOptionsSchema()},
                build_untyped,
            ),
        )
    )

    with pytest.raises(ContentValidationError, match=r"not executable.*must provide CampaignClearModeExecutor"):
        validate_mumu12_campaign_runtime_profiles(stages, profiles, executors)


def test_representative_special_gameplay_is_bound_by_typed_profiles(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    hard = _profile(profile_registry, packs_by_id, "campaign_hard", "12-4")
    assert tuple(extension.extension_id.value for extension in hard.extensions) == (
        "campaign_hard/campaign_hard/campaign",
    )
    hard_executor = hard.extensions[0].executors[0]
    assert hard_executor.kind is RuntimeExecutorKind.HARD_MODE
    assert hard_executor.implementation_id.value == "hard_mode/campaign_clear_mode"
    assert not hard_executor.options

    event_ball = _executors(profile_registry, "event_20200917_cn/campaign_base/campaign_base")[
        RuntimeExecutorKind.NAVIGATION
    ]
    archive_ball = _executors(
        profile_registry,
        "war_archives_20200917_cn/campaign_base/campaign_base",
    )[RuntimeExecutorKind.NAVIGATION]
    assert event_ball.implementation_id.value == "navigation/ball_chapter_route"
    assert archive_ball.implementation_id == event_ball.implementation_id
    ball_options = cast("Mapping[str, object]", event_ball.options["ball"])
    assert ball_options["asset"] == "DREAMWAKER_BALL"

    mob_move = _executors(profile_registry, "campaign_main/campaign_16_3/campaign")[RuntimeExecutorKind.MAP_MECHANIC]
    assert mob_move.implementation_id.value == "map_mechanic/chapter16_session_state"
    assert not mob_move.options

    mob_move_feature = _executors(profile_registry, "campaign_main/campaign_15_base/campaign_base")[
        RuntimeExecutorKind.MAP_MECHANIC
    ]
    assert mob_move_feature.implementation_id.value == "map_mechanic/mob_move_feature"
    assert dict(mob_move_feature.options) == {}

    refocus = {
        tuning.key: tuning.value for tuning in _profile(profile_registry, packs_by_id, "campaign_main", "11-2").tunings
    }
    assert refocus[RuntimeTuningKey.BOSS_APPEAR_REFOCUS_PRESET] == (-3, -2)


def test_grid_recognition_is_owned_only_by_stages_that_need_it(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    grid_kinds = {
        RuntimeExecutorKind.MAP_GRID_RECOGNITION,
        RuntimeExecutorKind.CAMERA_GRID_RECOGNITION,
    }

    def grid_extensions(pack_id: str, stage_id: str) -> tuple[str, ...]:
        return tuple(
            extension.extension_id.value
            for extension in _profile(profile_registry, packs_by_id, pack_id, stage_id).extensions
            if any(executor.kind in grid_kinds for executor in extension.executors)
        )

    assert grid_extensions("event_20231221_cn", "a1") == ("event_20231221_cn/campaign_base/event_grid",)
    assert grid_extensions("event_20231221_cn", "a2") == ()
    assert grid_extensions("event_20240521_cn", "a1") == ("event_20240521_cn/campaign_base/current_fleet_grid",)
    assert grid_extensions("event_20240521_cn", "a2") == ()
