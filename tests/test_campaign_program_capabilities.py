from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, cast

import pytest
from config_factory import in_memory_config

from module.adapters.campaign_fleet_preparation import build_campaign_fleet_preparation_service
from module.adapters.campaign_map_initialization import (
    CampaignMapInitializationRuntime,
    build_campaign_map_initialization_service,
)
from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.adapters.campaign_program_capabilities import (
    CampaignProgramCapabilities,
    CampaignProgramCapabilityContribution,
    CampaignProgramCapabilityReader,
    build_campaign_program_capability_reader,
)
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
    RuntimeSessionContext,
    RuntimeSessionEntryKind,
    RuntimeSessionOutcome,
)
from module.application import AbortToken
from module.content.campaign_session import CampaignRunVariant
from module.content.models import StageRef
from module.content.runtime_profile import RuntimeExecutorKind
from module.content.stage_loader import load_default_stage
from module.device.device import Device
from module.map.map_base import CampaignMap

if TYPE_CHECKING:
    from module.application import CancellationSource


class _ContributionSource:
    def __init__(self, *, value: bool | None) -> None:
        self._contribution = CampaignProgramCapabilityContribution(
            map_has_mob_move=value,
        )

    @property
    def program_capability_contribution(self) -> CampaignProgramCapabilityContribution:
        return self._contribution


class _OverrideSource:
    def __init__(self, value: object) -> None:
        self.value = value
        self.reads = 0

    def map_has_mob_move_override(
        self,
        cancellation: CancellationSource,
    ) -> bool | None:
        cancellation.raise_if_requested()
        self.reads += 1
        return cast("bool | None", self.value)


class _Runtime:
    FUNCTION_NAME_BASE = "CAPABILITY_TEST_"

    def __init__(
        self,
        manager: CampaignRuntimeProfileManager,
        *,
        clear_mode: bool,
        support_empty: bool,
    ) -> None:
        self.manager = manager
        self.map_is_clear_mode = clear_mode
        self.support_empty = support_empty
        self.config = _Config()
        self.combat_calls = 0

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self.manager.invoke_super(operation, self, *args, **kwargs)

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool:
        del button, offset
        return self.support_empty

    @staticmethod
    def _standard_fleet_preparation() -> bool:
        return True

    def combat(
        self,
        *,
        balance_hp: bool,
        emotion_reduce: bool,
        expected_end: str,
    ) -> None:
        del balance_hp, emotion_reduce, expected_end
        self.combat_calls += 1


class _Config:
    Fleet_FleetOrder = "fleet1_all_fleet2_standby"


def _production_manager(stage_id: str) -> CampaignRuntimeProfileManager:
    definition = load_default_stage(StageRef("campaign_main", stage_id))
    return CampaignRuntimeProfileManager(
        definition.runtime_profile,
        load_default_campaign_runtime_executor_registry(),
    )


def _reader(manager: CampaignRuntimeProfileManager) -> CampaignProgramCapabilityReader:
    return build_campaign_program_capability_reader(manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC))


def test_static_capabilities_default_false_are_frozen_and_later_explicit_contribution_wins() -> None:
    default = build_campaign_program_capability_reader(())
    reader = build_campaign_program_capability_reader(
        (
            _ContributionSource(value=True),
            _ContributionSource(value=None),
            _ContributionSource(value=False),
        )
    )
    inherited = build_campaign_program_capability_reader(
        (
            _ContributionSource(value=True),
            _ContributionSource(value=None),
        )
    )

    assert default.static_capabilities == CampaignProgramCapabilities(map_has_mob_move=False)
    assert inherited.static_capabilities.map_has_mob_move is True
    assert reader.static_capabilities.map_has_mob_move is False
    field = "map_has_mob_move"
    with pytest.raises(FrozenInstanceError):
        setattr(reader.static_capabilities, field, True)


@pytest.mark.parametrize(
    ("override", "expected"),
    [(None, True), (False, False), (True, True)],
)
def test_live_override_preserves_none_false_and_true(
    *,
    override: bool | None,
    expected: bool,
) -> None:
    source = _OverrideSource(override)
    reader = CampaignProgramCapabilityReader(
        CampaignProgramCapabilities(map_has_mob_move=True),
        source,
    )

    assert reader.map_has_mob_move(AbortToken()) is expected
    assert source.reads == 1


@pytest.mark.parametrize("value", [0, 1, "true", object()])
def test_capabilities_reject_non_boolean_values(value: object) -> None:
    with pytest.raises(TypeError, match="must be a boolean"):
        CampaignProgramCapabilities(map_has_mob_move=cast("bool", value))
    with pytest.raises(TypeError, match="boolean or None"):
        CampaignProgramCapabilityContribution(map_has_mob_move=cast("bool | None", value))

    reader = CampaignProgramCapabilityReader(
        CampaignProgramCapabilities(map_has_mob_move=True),
        _OverrideSource(value),
    )
    with pytest.raises(CampaignRuntimeProfileError, match="must return bool or None"):
        reader.map_has_mob_move(AbortToken())


def test_capability_builder_rejects_multiple_live_override_sources() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="at most one live override"):
        build_campaign_program_capability_reader((_OverrideSource(None), _OverrideSource(value=False)))


@pytest.mark.parametrize("stage_id", ["15-1", "15-2", "15-3", "15-4", "15-4-121"])
def test_real_chapter_15_profiles_declare_static_mob_move(stage_id: str) -> None:
    reader = _reader(_production_manager(stage_id))

    assert reader.static_capabilities.map_has_mob_move is True
    assert reader.override_source is None
    assert reader.map_has_mob_move(AbortToken()) is True


@pytest.mark.parametrize("stage_id", ["16-1", "16-2"])
def test_real_early_chapter_16_profiles_do_not_inherit_mob_move(stage_id: str) -> None:
    reader = _reader(_production_manager(stage_id))

    assert reader.static_capabilities.map_has_mob_move is False
    assert reader.override_source is None
    assert reader.map_has_mob_move(AbortToken()) is False


@pytest.mark.parametrize("stage_id", ["16-3", "16-4"])
def test_real_late_chapter_16_profiles_start_with_explicit_false_override(stage_id: str) -> None:
    reader = _reader(_production_manager(stage_id))

    assert reader.static_capabilities.map_has_mob_move is True
    assert reader.override_source is not None
    assert reader.map_has_mob_move(AbortToken()) is False


@pytest.mark.parametrize(
    ("stage_id", "expected"),
    [("14-4", False), ("15-1", True), ("16-3", False)],
)
def test_declarative_runtime_installs_real_program_capabilities(
    stage_id: str,
    *,
    expected: bool,
) -> None:
    runtime = DeclarativeCampaignMapRuntime(
        in_memory_config(f"program-capability-wiring-{stage_id}", {}),
        object.__new__(Device),
        load_default_stage(StageRef("campaign_main", stage_id)),
    )

    assert runtime._program_capabilities.map_has_mob_move(AbortToken()) is expected  # ruff:ignore[private-member-access] - deleting production wiring must fail.
    assert "strategy_set_execute" not in DeclarativeCampaignMapRuntime.__dict__


@pytest.mark.parametrize(
    ("clear_mode", "support_empty", "expected"),
    [(True, False, True), (True, True, False), (False, False, False)],
)
@pytest.mark.parametrize("stage_id", ["16-3", "16-4"])
def test_real_chapter_16_map_init_updates_live_override_and_reset_clears_it(
    stage_id: str,
    *,
    clear_mode: bool,
    support_empty: bool,
    expected: bool,
) -> None:
    manager = _production_manager(stage_id)
    reader = _reader(manager)
    runtime = _Runtime(
        manager,
        clear_mode=clear_mode,
        support_empty=support_empty,
    )
    manager.bind(runtime, CampaignMap("capability-test"))
    service = build_campaign_fleet_preparation_service(manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC))
    assert service.prepare(runtime)
    manager.begin_session(
        RuntimeSessionContext(
            CampaignRunVariant.LOOP,
            0,
            RuntimeSessionEntryKind.FRESH,
        )
    )

    initialization = build_campaign_map_initialization_service(manager.executor_instances_in_profile_order())
    initialization.post_control(cast("CampaignMapInitializationRuntime", runtime))

    assert reader.map_has_mob_move(AbortToken()) is expected
    manager.end_session(RuntimeSessionOutcome.COMPLETED)
    manager.reset()
    assert reader.map_has_mob_move(AbortToken()) is False
