from dataclasses import fields
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import pytest
from config_factory import in_memory_config

from module.adapters.campaign_fleet_preparation import build_campaign_fleet_preparation_service
from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileManager,
    RuntimeExecutorInstance,
    RuntimeOperation,
    RuntimeSessionOutcome,
    RuntimeStateSeed,
)
from module.adapters.gems_mumu12 import (
    GemsHardPreparationError,
    GemsHardRetryFleetPreparationService,
)
from module.application import AbortToken
from module.content.manifest import load_default_event_manifests
from module.content.models import StageRef
from module.content.runtime_profile import RuntimeExecutorKind
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.content.stage_loader import load_default_stage
from module.device.device import Device
from module.exception import HardFleetRequirementsError
from module.map.map_base import CampaignMap
from module.map.support_fleet import (
    SupportFleetAttemptState,
    SupportFleetStateError,
    SupportFleetStatus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.campaign.campaign_engine import CampaignEngine
    from module.content.models import EventPack, StageSpec
    from module.content.runtime_profile import CampaignRuntimeProfileRegistry
    from module.map.map_fleet_preparation import FleetPreparationService

_SUPPORT_IMPLEMENTATION = "map_mechanic/support_fleet"
_SUPPORT_STAGES = ("15-1", "15-2", "15-3", "15-4", "15-4-121", "16-1", "16-2", "16-3", "16-4")


class _PreparationRuntime:
    def __init__(
        self,
        *,
        support_empty: list[bool] | None = None,
        standard_outcomes: list[bool | BaseException] | None = None,
    ) -> None:
        self.events: list[str] = []
        self._support_empty = [False] if support_empty is None else list(support_empty)
        self._standard_outcomes = [True] if standard_outcomes is None else list(standard_outcomes)

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool:
        del button, offset
        empty = self._support_empty.pop(0)
        self.events.append("observe:empty" if empty else "observe:present")
        return empty

    def _standard_fleet_preparation(self) -> bool:
        self.events.append("standard")
        outcome = self._standard_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture(scope="module")
def packs_by_id() -> Mapping[str, EventPack]:
    return MappingProxyType({str(pack.pack_id): pack for pack in load_default_event_manifests()})


@pytest.fixture(scope="module")
def profile_registry() -> CampaignRuntimeProfileRegistry:
    return load_default_campaign_runtime_profile_registry()


def _stage(packs_by_id: Mapping[str, EventPack], pack_id: str, stage_id: str) -> StageSpec:
    return next(stage for stage in packs_by_id[pack_id].stages if stage.ref.stage_id == stage_id)


def _manager(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
    pack_id: str,
    stage_id: str,
) -> CampaignRuntimeProfileManager:
    profile = profile_registry.resolve(_stage(packs_by_id, pack_id, stage_id).runtime_profile_id)
    return CampaignRuntimeProfileManager(
        profile,
        load_default_campaign_runtime_executor_registry(),
    )


def _service(manager: CampaignRuntimeProfileManager) -> FleetPreparationService:
    return build_campaign_fleet_preparation_service(manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC))


def _implementation_ids(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
    pack_id: str,
    stage_id: str,
) -> frozenset[str]:
    profile = profile_registry.resolve(_stage(packs_by_id, pack_id, stage_id).runtime_profile_id)
    return frozenset(
        binding.implementation_id.value for extension in profile.extensions for binding in extension.executors
    )


def test_support_fleet_attempt_state_allows_ready_reobservation_then_seals_and_resets() -> None:
    state = SupportFleetAttemptState()

    assert state.status is SupportFleetStatus.UNOBSERVED
    assert state.available is True
    assert state.sealed is False

    state.observe(SupportFleetStatus.EMPTY)
    state.observe(SupportFleetStatus.PRESENT)
    state.seal()

    assert state.status is SupportFleetStatus.PRESENT
    assert state.available is True
    assert state.sealed is True
    with pytest.raises(SupportFleetStateError, match="sealed"):
        state.observe(SupportFleetStatus.EMPTY)

    state.reset()
    assert state.status is SupportFleetStatus.UNOBSERVED
    assert state.available is True
    assert state.sealed is False


def test_support_fleet_attempt_state_rejects_unobserved_as_ui_evidence() -> None:
    state = SupportFleetAttemptState()

    with pytest.raises(ValueError, match="present or empty"):
        state.observe(SupportFleetStatus.UNOBSERVED)


def test_support_observation_runs_before_standard_preparation_and_ready_retry_overwrites(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    manager = _manager(packs_by_id, profile_registry, "campaign_main", "15-1")
    runtime = _PreparationRuntime(support_empty=[True, False], standard_outcomes=[True, True])
    service = _service(manager)

    assert service.prepare(runtime)
    assert manager.support_fleet_status(AbortToken()) is SupportFleetStatus.EMPTY
    assert service.prepare(runtime)

    assert runtime.events == ["observe:empty", "standard", "observe:present", "standard"]
    assert manager.support_fleet_status(AbortToken()) is SupportFleetStatus.PRESENT


def test_begin_seals_support_observation_and_reset_clears_it(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    manager = _manager(packs_by_id, profile_registry, "campaign_main", "15-1")
    runtime = _PreparationRuntime(support_empty=[True, False], standard_outcomes=[True, True])
    service = _service(manager)
    manager.bind(runtime, CampaignMap("support-fleet-lifecycle"))
    assert service.prepare(runtime)
    manager.begin_session()

    with pytest.raises(SupportFleetStateError, match="sealed"):
        service.prepare(runtime)
    assert runtime.events == ["observe:empty", "standard", "observe:present"]

    manager.end_session(RuntimeSessionOutcome.COMPLETED)
    manager.reset()
    assert manager.support_fleet_status(AbortToken()) is SupportFleetStatus.UNOBSERVED
    assert manager.use_support_fleet(AbortToken()) is True


def test_begin_seals_unobserved_support_as_available_and_rejects_late_preparation(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    manager = _manager(packs_by_id, profile_registry, "campaign_main", "15-1")
    runtime = _PreparationRuntime(support_empty=[False])
    service = _service(manager)
    manager.bind(runtime, CampaignMap("support-fleet-unobserved-seal"))

    manager.begin_session()

    assert manager.support_fleet_status(AbortToken()) is SupportFleetStatus.UNOBSERVED
    assert manager.use_support_fleet(AbortToken()) is True
    with pytest.raises(SupportFleetStateError, match="sealed"):
        service.prepare(runtime)
    assert runtime.events == ["observe:present"]


def test_gems_retry_repeats_the_complete_support_observation_chain(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    manager = _manager(packs_by_id, profile_registry, "campaign_main", "15-1")
    runtime = _PreparationRuntime(
        support_empty=[True, False],
        standard_outcomes=[HardFleetRequirementsError(), True],
    )
    inner = _service(manager)

    def replace_hard_fleet(replacement_runtime: CampaignEngine) -> None:
        assert replacement_runtime is cast("CampaignEngine", runtime)
        runtime.events.append("replace")

    service = GemsHardRetryFleetPreparationService(inner, replace_hard_fleet)

    assert service.prepare(runtime)
    assert runtime.events == [
        "observe:empty",
        "standard",
        "replace",
        "observe:present",
        "standard",
    ]
    assert manager.support_fleet_status(AbortToken()) is SupportFleetStatus.PRESENT


def test_gems_second_hard_failure_is_translated_after_two_full_attempts(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    manager = _manager(packs_by_id, profile_registry, "campaign_main", "15-1")
    retry_error = HardFleetRequirementsError()
    runtime = _PreparationRuntime(
        support_empty=[False, True],
        standard_outcomes=[HardFleetRequirementsError(), retry_error],
    )

    def replace_hard_fleet(_runtime: CampaignEngine) -> None:
        runtime.events.append("replace")

    service = GemsHardRetryFleetPreparationService(_service(manager), replace_hard_fleet)

    with pytest.raises(GemsHardPreparationError, match="still does not satisfy") as raised:
        service.prepare(runtime)

    assert raised.value.__cause__ is retry_error
    assert runtime.events == [
        "observe:present",
        "standard",
        "replace",
        "observe:empty",
        "standard",
    ]
    assert manager.support_fleet_status(AbortToken()) is SupportFleetStatus.EMPTY


def test_gems_non_hard_failure_preserves_identity_without_replacement_or_retry(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    manager = _manager(packs_by_id, profile_registry, "campaign_main", "15-1")
    failure = LookupError("standard preparation failed")
    runtime = _PreparationRuntime(
        support_empty=[False],
        standard_outcomes=[failure],
    )
    replacements: list[CampaignEngine] = []

    def replace_hard_fleet(replacement_runtime: CampaignEngine) -> None:
        replacements.append(replacement_runtime)

    service = GemsHardRetryFleetPreparationService(_service(manager), replace_hard_fleet)

    with pytest.raises(LookupError) as raised:
        service.prepare(runtime)

    assert raised.value is failure
    assert replacements == []
    assert runtime.events == ["observe:present", "standard"]


def test_gems_replacement_failure_preserves_identity_without_second_attempt(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    manager = _manager(packs_by_id, profile_registry, "campaign_main", "15-1")
    replacement_failure = RuntimeError("replacement failed")
    runtime = _PreparationRuntime(
        support_empty=[False],
        standard_outcomes=[HardFleetRequirementsError()],
    )

    def replace_hard_fleet(_runtime: CampaignEngine) -> None:
        runtime.events.append("replace")
        raise replacement_failure

    service = GemsHardRetryFleetPreparationService(_service(manager), replace_hard_fleet)

    with pytest.raises(RuntimeError) as raised:
        service.prepare(runtime)

    assert raised.value is replacement_failure
    assert runtime.events == ["observe:present", "standard", "replace"]


@pytest.mark.parametrize("stage_id", _SUPPORT_STAGES)
def test_all_real_support_stages_use_typed_state_and_empty_profile_options(
    stage_id: str,
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    stage = _stage(packs_by_id, "campaign_main", stage_id)
    profile = profile_registry.resolve(stage.runtime_profile_id)
    support_bindings = [
        binding
        for extension in profile.extensions
        for binding in extension.executors
        if binding.implementation_id.value == _SUPPORT_IMPLEMENTATION
    ]
    manager = CampaignRuntimeProfileManager(
        profile,
        load_default_campaign_runtime_executor_registry(),
    )
    runtime = _PreparationRuntime()

    assert len(support_bindings) == 1
    assert dict(support_bindings[0].options) == {}
    assert manager.support_fleet_status(AbortToken()) is SupportFleetStatus.UNOBSERVED
    assert manager.use_support_fleet(AbortToken()) is True
    assert _service(manager).prepare(runtime)
    assert runtime.events == ["observe:present", "standard"]
    assert manager.support_fleet_status(AbortToken()) is SupportFleetStatus.PRESENT


def test_real_non_support_boundary_uses_only_standard_preparation(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    manager = _manager(packs_by_id, profile_registry, "campaign_main", "14-4")
    runtime = _PreparationRuntime()

    assert _SUPPORT_IMPLEMENTATION not in _implementation_ids(
        packs_by_id,
        profile_registry,
        "campaign_main",
        "14-4",
    )
    assert manager.support_fleet_status(AbortToken()) is None
    assert manager.use_support_fleet(AbortToken()) is False
    assert _service(manager).prepare(runtime)
    assert runtime.events == ["standard"]


@pytest.mark.parametrize(
    ("stage_id", "expected_status"),
    [("15-1", SupportFleetStatus.PRESENT), ("14-4", None)],
)
def test_declarative_runtime_installs_the_real_profile_preparation_service(
    stage_id: str,
    expected_status: SupportFleetStatus | None,
) -> None:
    runtime = DeclarativeCampaignMapRuntime(
        in_memory_config(f"fleet-preparation-wiring-{stage_id}", {}),
        object.__new__(Device),
        load_default_stage(StageRef("campaign_main", stage_id)),
    )
    preparation = _PreparationRuntime()

    assert runtime._fleet_preparation_service is runtime._profile_fleet_preparation_service  # ruff:ignore[private-member-access] - 删除生产 wiring 时必须失败。
    assert runtime._profile_fleet_preparation_service.prepare(preparation)  # ruff:ignore[private-member-access] - 用纯内存 primitive 验证真实 profile 链。
    assert runtime._runtime_profile.support_fleet_status(AbortToken()) is expected_status  # ruff:ignore[private-member-access] - 状态必须来自 runtime 持有的真实 manager。


def test_old_fleet_preparation_runtime_surfaces_are_removed() -> None:
    assert "FLEET_PREPARATION" not in RuntimeOperation.__members__
    assert "fleet_preparation" not in DeclarativeCampaignMapRuntime.__dict__
    assert "_base_fleet_preparation" not in DeclarativeCampaignMapRuntime.__dict__
    assert {field.name for field in fields(RuntimeStateSeed)} == {"use_single_fleet_override"}
    assert not hasattr(RuntimeExecutorInstance, "use_support_fleet")
    assert not hasattr(RuntimeExecutorInstance, "set_use_support_fleet")
    assert not hasattr(RuntimeExecutorInstance, "disable_support_fleet")
    assert hasattr(RuntimeExecutorInstance, "current_use_support_fleet")
    assert not hasattr(CampaignRuntimeProfileManager, "disable_support_fleet")


def test_real_hard_profiles_do_not_cross_the_pre_session_support_observation_boundary(
    packs_by_id: Mapping[str, EventPack],
    profile_registry: CampaignRuntimeProfileRegistry,
) -> None:
    hard_stages = packs_by_id["campaign_hard"].stages

    assert hard_stages
    for stage in hard_stages:
        profile = profile_registry.resolve(stage.runtime_profile_id)
        implementations = {
            binding.implementation_id.value for extension in profile.extensions for binding in extension.executors
        }
        assert _SUPPORT_IMPLEMENTATION not in implementations, stage.ref
