from pathlib import Path
from typing import TYPE_CHECKING, cast, override

import pytest
from config_factory import in_memory_config

from module.adapters.campaign_clear_mode_config import (
    CampaignClearModeConfigContributor,
    CampaignClearModeConfigRuntime,
    CampaignClearModeConfigService,
    build_campaign_clear_mode_config_service,
)
from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.adapters.campaign_runtime_implementations import load_default_campaign_runtime_executor_registry
from module.adapters.campaign_runtime_profile import CampaignRuntimeProfileManager
from module.campaign.campaign_engine import CampaignEngine
from module.config.config import AzurLaneConfig
from module.content.models import StageRef
from module.content.runtime_profile import (
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    CampaignRuntimeProfileRegistry,
)
from module.content.runtime_profile_catalog import compile_campaign_runtime_profile_registry
from module.content.stage_loader import load_default_stage
from module.device.device import Device

if TYPE_CHECKING:
    from typing import Unpack

    from module.config.config_generated import ConfigOverrides

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "content" / "campaign-runtime-profiles.json"


class _Config(AzurLaneConfig):
    def __init__(self) -> None:
        self.overlays: list[dict[str, object]] = []
        self.MAP_HAS_MISSILE_ATTACK = False
        self.MAP_HAS_SIREN = False

    @override
    def apply_runtime_overlay(self, **kwargs: Unpack[ConfigOverrides]) -> None:
        overlay = dict(kwargs)
        self.overlays.append(overlay)
        for name, value in overlay.items():
            setattr(self, name, value)


class _Runtime:
    def __init__(self, service: CampaignClearModeConfigService | None = None) -> None:
        self.config = _Config()
        self._clear_mode_config_service = CampaignClearModeConfigService() if service is None else service


class _ContributorSource:
    def __init__(self, contributor: CampaignClearModeConfigContributor) -> None:
        self._contributor = contributor

    @property
    def clear_mode_config_contributor(self) -> CampaignClearModeConfigContributor:
        return self._contributor


@pytest.fixture(scope="module")
def profile_registry() -> CampaignRuntimeProfileRegistry:
    return compile_campaign_runtime_profile_registry(PROFILE_PATH)


def _real_service(
    profile_registry: CampaignRuntimeProfileRegistry,
    *extension_ids: str,
) -> CampaignClearModeConfigService:
    extensions = tuple(
        profile_registry.extensions[CampaignRuntimeExtensionId(extension_id)] for extension_id in extension_ids
    )
    manager = CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(CampaignRuntimeProfileId("clear-mode-config-test"), extensions),
        load_default_campaign_runtime_executor_registry(),
    )
    return build_campaign_clear_mode_config_service(manager.executor_instances_in_profile_order())


def test_clear_mode_config_contributors_run_in_global_profile_order() -> None:
    calls: list[str] = []

    def apply_base(runtime: CampaignClearModeConfigRuntime, *, handled: bool) -> None:
        del runtime
        assert handled is False
        calls.append("base")

    def apply_stage(runtime: CampaignClearModeConfigRuntime, *, handled: bool) -> None:
        del runtime
        assert handled is False
        calls.append("stage")

    service = build_campaign_clear_mode_config_service(
        (
            _ContributorSource(CampaignClearModeConfigContributor(apply_base)),
            object(),
            _ContributorSource(CampaignClearModeConfigContributor(apply_stage)),
        )
    )

    service.apply(_Runtime(), handled=False)

    assert calls == ["base", "stage"]


def test_war_archives_20211229_base_overlay_enables_missile_attack(
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    service = _real_service(
        profile_registry,
        "war_archives_20211229_cn/campaign_base/campaign_base",
    )
    runtime = _Runtime()

    service.apply(runtime, handled=False)

    assert runtime.config.MAP_HAS_MISSILE_ATTACK is True
    assert runtime.config.overlays == [{"MAP_HAS_MISSILE_ATTACK": True}]


@pytest.mark.parametrize(
    "stage_extension",
    [
        "war_archives_20211229_cn/a1/campaign",
        "war_archives_20211229_cn/c1/campaign",
    ],
)
def test_war_archives_20211229_stage_overlay_disables_base_missile_attack(
    profile_registry: CampaignRuntimeProfileRegistry,
    stage_extension: str,
) -> None:
    service = _real_service(
        profile_registry,
        "war_archives_20211229_cn/campaign_base/campaign_base",
        stage_extension,
    )
    runtime = _Runtime()

    service.apply(runtime, handled=False)

    assert runtime.config.MAP_HAS_MISSILE_ATTACK is False
    assert runtime.config.overlays == [
        {"MAP_HAS_MISSILE_ATTACK": True},
        {"MAP_HAS_MISSILE_ATTACK": False},
    ]


@pytest.mark.parametrize(("handled", "expected_siren"), [(False, False), (True, True)])
def test_event_20220224_overlay_follows_base_handled_result(
    profile_registry: CampaignRuntimeProfileRegistry,
    *,
    handled: bool,
    expected_siren: bool,
) -> None:
    service = _real_service(
        profile_registry,
        "event_20220224_cn/campaign_base/campaign_base",
    )
    runtime = _Runtime()

    service.apply(runtime, handled=handled)

    assert runtime.config.MAP_HAS_SIREN is expected_siren
    assert len(runtime.config.overlays) == int(handled)


def test_runtime_calls_base_once_before_contributors_and_returns_original_bool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def apply(runtime: CampaignClearModeConfigRuntime, *, handled: bool) -> None:
        del runtime
        assert handled is True
        calls.append("contributor")

    service = CampaignClearModeConfigService((CampaignClearModeConfigContributor(apply),))
    runtime = _Runtime(service)

    def base(instance: CampaignEngine) -> bool:
        del instance
        calls.append("base")
        return True

    monkeypatch.setattr(CampaignEngine, "handle_clear_mode_config_cover", base)

    result = DeclarativeCampaignMapRuntime.handle_clear_mode_config_cover(
        cast("DeclarativeCampaignMapRuntime", runtime)
    )

    assert result is True
    assert calls == ["base", "contributor"]


def test_real_war_archives_runtime_wires_base_then_stage_clear_mode_overlays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = in_memory_config("clear-mode-config-real-wiring", {})
    runtime = DeclarativeCampaignMapRuntime(
        config,
        object.__new__(Device),
        load_default_stage(StageRef("war_archives_20211229_cn", "a1")),
    )
    calls: list[str] = []
    apply_runtime_overlay = config.apply_runtime_overlay

    def record_overlay(**kwargs: Unpack[ConfigOverrides]) -> None:
        calls.append(f"overlay:{kwargs['MAP_HAS_MISSILE_ATTACK']}")
        apply_runtime_overlay(**kwargs)

    def base(instance: CampaignEngine) -> bool:
        del instance
        calls.append("base")
        return True

    monkeypatch.setattr(config, "apply_runtime_overlay", record_overlay)
    monkeypatch.setattr(CampaignEngine, "handle_clear_mode_config_cover", base)

    result = runtime.handle_clear_mode_config_cover()

    assert result is True
    assert config.MAP_HAS_MISSILE_ATTACK is False
    assert calls == ["base", "overlay:True", "overlay:False"]
