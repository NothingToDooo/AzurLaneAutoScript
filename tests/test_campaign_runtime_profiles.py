import json
from pathlib import Path
from typing import cast

import pytest

from module.content.campaign_session import CampaignRunVariant
from module.content.campaign_session_source import CompiledCampaignSessionSource
from module.content.catalog import ContentCatalog
from module.content.errors import ContentValidationError
from module.content.manifest import load_event_manifests
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeCapabilityKind,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
    RuntimeTuning,
    RuntimeTuningKey,
)
from module.content.runtime_profile_catalog import (
    compile_campaign_runtime_profile_registry,
    load_default_campaign_runtime_profile_registry,
)
from module.content.stage_loader import StageSpecLoader

ROOT = Path(__file__).resolve().parents[1]


def _binding(
    kind: RuntimeExecutorKind = RuntimeExecutorKind.MAP_MECHANIC,
) -> RuntimeExecutorBinding:
    return RuntimeExecutorBinding(
        kind,
        RuntimeImplementationId("campaign_main/chapter_15_mob_move"),
        {"cells": ["A1", "B2"]},
    )


def test_executor_binding_is_typed_and_deeply_immutable() -> None:
    binding = _binding(RuntimeExecutorKind.MAP_GRID_RECOGNITION)

    assert binding.kind.capability is RuntimeCapabilityKind.GRID_RECOGNITION
    assert binding.options["cells"] == ("A1", "B2")
    mutable_options = cast("dict[str, object]", binding.options)
    with pytest.raises(TypeError):
        mutable_options["cells"] = ()


def test_extension_rejects_duplicate_executor_ports() -> None:
    with pytest.raises(
        ContentValidationError,
        match="executor kinds must be unique",
    ):
        CampaignRuntimeExtension(
            CampaignRuntimeExtensionId("duplicate"),
            (_binding(), _binding()),
        )


def test_profile_rejects_duplicate_tuning_keys() -> None:
    tuning = RuntimeTuning(RuntimeTuningKey.MAP_SIREN_MOVE_WAIT, 0.7)

    with pytest.raises(ContentValidationError, match="tuning keys must be unique"):
        CampaignRuntimeProfile(
            CampaignRuntimeProfileId("duplicate_tuning"),
            tunings=(tuning, tuning),
        )


def test_catalog_rejects_unknown_executor_kind(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "extensions": [
                    {
                        "id": "bad",
                        "executors": [
                            {
                                "kind": "python_method",
                                "implementation": "bad/reflection",
                                "options": {},
                            }
                        ],
                    }
                ],
                "profiles": [{"id": "core", "extensions": [], "tunings": []}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContentValidationError, match="RuntimeExecutorKind"):
        compile_campaign_runtime_profile_registry(path)


def test_checked_in_registry_is_exactly_owned_by_manifest_stages() -> None:
    registry = load_default_campaign_runtime_profile_registry()
    stages = tuple(stage for pack in load_event_manifests(ROOT / "content" / "events") for stage in pack.stages)
    referenced_profiles = {stage.runtime_profile_id for stage in stages}
    referenced_extensions = {
        extension.extension_id for profile in registry.profiles.values() for extension in profile.extensions
    }

    assert referenced_profiles == set(registry.profiles)
    assert referenced_extensions == set(registry.extensions)


def test_every_manifest_stage_resolves_an_explicit_profile() -> None:
    registry = load_default_campaign_runtime_profile_registry()
    packs = load_event_manifests(ROOT / "content" / "events")
    specs = tuple(stage for pack in packs for stage in pack.stages)

    assert len(specs) == 1202
    assert all(spec.runtime_profile_id.value != "" for spec in specs)
    assert all(registry.resolve(spec.runtime_profile_id) for spec in specs)


def test_compiled_session_carries_the_resolved_runtime_profile() -> None:
    registry = load_default_campaign_runtime_profile_registry()
    catalog = ContentCatalog(load_event_manifests(ROOT / "content" / "events"))
    spec = catalog.resolve_stage(next(stage.ref for stage in catalog.stages if stage.ref.pack_id == "campaign_main"))
    source = CompiledCampaignSessionSource(
        catalog,
        StageSpecLoader(),
        stage_refs=(spec.ref,),
    )

    session = source.resolve(spec.ref, CampaignRunVariant.NORMAL)

    assert session.definition.runtime_profile is registry.resolve(spec.runtime_profile_id)
