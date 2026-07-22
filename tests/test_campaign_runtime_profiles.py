import json
from typing import TYPE_CHECKING, cast

import pytest

from module.content.campaign_session import CampaignRunVariant
from module.content.campaign_session_source import CompiledCampaignSessionSource
from module.content.catalog import ContentCatalog
from module.content.errors import ContentValidationError
from module.content.manifest import load_default_event_manifests
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
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

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.mark.parametrize(
    "obsolete_key",
    [
        "map_walk_turning_optimize",
        "map_has_dynamic_red_border",
        "map_has_pt_bonus",
        "map_siren_count",
        "map_air_strike_overlay_transparency_threshold",
    ],
)
def test_catalog_rejects_removed_runtime_tuning_keys(
    obsolete_key: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "extensions": [],
                "profiles": [
                    {
                        "id": "core",
                        "extensions": [],
                        "tunings": [{"key": obsolete_key, "value": 1}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContentValidationError, match="unknown RuntimeTuningKey"):
        compile_campaign_runtime_profile_registry(path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"schema_version": 1, "schema_version": 1}', "duplicate JSON key: schema_version"),
        ('{"schema_version": NaN}', "non-finite JSON number: NaN"),
    ],
)
def test_catalog_uses_strict_json_decoding(content: str, message: str, tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ContentValidationError, match=message):
        compile_campaign_runtime_profile_registry(path)


def test_compiled_session_carries_the_resolved_runtime_profile() -> None:
    registry = load_default_campaign_runtime_profile_registry()
    catalog = ContentCatalog(load_default_event_manifests())
    spec = catalog.resolve_stage(next(stage.ref for stage in catalog.stages if stage.ref.pack_id == "campaign_main"))
    source = CompiledCampaignSessionSource(
        catalog,
        StageSpecLoader(),
    )

    session = source.resolve(spec.ref, CampaignRunVariant.NORMAL)

    assert session.definition.runtime_profile is registry.resolve(spec.runtime_profile_id)
