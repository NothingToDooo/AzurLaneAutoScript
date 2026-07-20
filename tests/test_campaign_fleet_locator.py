from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

import pytest

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    FindCurrentFleetNext,
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
    RuntimeTuningValue,
)
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.map.fleet import Fleet

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Literal

    from module.map.map_observer import CampaignMapObserver, FleetLocatorRuntime
    from module.map.type_alias import FleetLocation, GridLocation

_IMPLEMENTATION = RuntimeImplementationId("observation/fixed_fleet_locations")


class _DispatchFleet(Fleet):
    def __init__(self, observer: CampaignMapObserver) -> None:
        self._map_observer = observer


@dataclass(frozen=True, slots=True)
class _FleetConfig:
    fleet_2: bool


class _FixedProfileFleet(Fleet):
    config: _FleetConfig

    def __init__(
        self,
        observer: CampaignMapObserver,
        *,
        fleet_2_enabled: bool,
        current_index: Literal[1, 2],
    ) -> None:
        self._map_observer = observer
        self.config = _FleetConfig(fleet_2_enabled)
        self.fleet_current_index = current_index
        self.fleet_1_location = (9, 9)
        self.fleet_2_location = (8, 8)

    @override
    def _standard_find_current_fleet(self) -> FleetLocation:
        message = "fixed profile must not call the standard Fleet locator"
        raise AssertionError(message)


class _LocatorRuntime:
    def __init__(
        self,
        *,
        fleet_2_enabled: bool = False,
        current_index: Literal[1, 2] = 1,
        standard_result: FleetLocation | None = None,
        standard_bomb: bool = False,
    ) -> None:
        self._fleet_2_enabled_value = fleet_2_enabled
        self.current_index = current_index
        self.locations: dict[int, FleetLocation] = {1: (9, 9), 2: (8, 8)}
        self.assignments: list[tuple[int, GridLocation]] = []
        self.standard_result = standard_result
        self.standard_bomb = standard_bomb
        self.standard_calls = 0

    @property
    def _fleet_2_enabled(self) -> bool:
        return self._fleet_2_enabled_value

    @property
    def fleet_current(self) -> FleetLocation:
        return self.locations[self.current_index]

    def _set_fleet_location(
        self,
        index: Literal[1, 2],
        location: GridLocation,
    ) -> None:
        self.assignments.append((index, location))
        self.locations[index] = location

    def _standard_find_current_fleet(self) -> FleetLocation:
        self.standard_calls += 1
        if self.standard_bomb:
            message = "replacement must not call the standard locator"
            raise AssertionError(message)
        if self.standard_result is not None:
            return self.standard_result
        return self.fleet_current


def _real_profile(pack_id: str, stage_id: str) -> CampaignRuntimeProfile:
    pack = next(pack for pack in load_default_event_manifests() if str(pack.pack_id) == pack_id)
    stage = next(stage for stage in pack.stages if stage.ref.stage_id == stage_id)
    return load_default_campaign_runtime_profile_registry().resolve(stage.runtime_profile_id)


def _fixed_profile(options: Mapping[str, object]) -> CampaignRuntimeProfile:
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("fleet-locator-test"),
        (
            RuntimeExecutorBinding(
                RuntimeExecutorKind.MAP_OBSERVATION,
                _IMPLEMENTATION,
                cast("Mapping[str, RuntimeTuningValue]", options),
            ),
        ),
    )
    return CampaignRuntimeProfile(
        CampaignRuntimeProfileId("fleet-locator-test"),
        (extension,),
    )


def _observer_for(profile: CampaignRuntimeProfile) -> CampaignMapObserver:
    manager = CampaignRuntimeProfileManager(profile, load_default_campaign_runtime_executor_registry())
    instances = manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION)
    assert any(isinstance(instance, CampaignMapObserverExecutor) for instance in instances)
    return build_campaign_map_observer(instances)


def test_fleet_public_locator_preserves_exact_runtime_and_return() -> None:
    seen: list[FleetLocatorRuntime] = []
    expected = (int("7"), int("8"))

    def find_current_fleet(
        runtime: FleetLocatorRuntime,
        next_handler: FindCurrentFleetNext,
    ) -> FleetLocation:
        del next_handler
        seen.append(runtime)
        return expected

    observer = build_campaign_map_observer(
        (CampaignMapObserverExecutor(CampaignMapObserverContributor(find_current_fleet=find_current_fleet)),)
    )
    fleet = _DispatchFleet(observer)

    result = fleet.find_current_fleet()

    assert seen == [fleet]
    assert seen[0] is fleet
    assert result is expected


def test_standard_fleet_locator_is_the_composition_fallback() -> None:
    expected = (int("4"), int("6"))
    runtime = _LocatorRuntime(standard_result=expected)

    result = build_campaign_map_observer(()).fleet_locator.find_current_fleet(runtime)

    assert result is expected
    assert runtime.standard_calls == 1


def test_fleet_locator_composition_is_later_first() -> None:
    order: list[str] = []
    seen: list[FleetLocatorRuntime] = []

    def earlier(
        runtime: FleetLocatorRuntime,
        next_handler: FindCurrentFleetNext,
    ) -> FleetLocation:
        order.append("earlier")
        seen.append(runtime)
        return next_handler(runtime)

    def later(
        runtime: FleetLocatorRuntime,
        next_handler: FindCurrentFleetNext,
    ) -> FleetLocation:
        order.append("later")
        seen.append(runtime)
        return next_handler(runtime)

    expected = (int("5"), int("7"))
    runtime = _LocatorRuntime(standard_result=expected)
    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(CampaignMapObserverContributor(find_current_fleet=earlier)),
            CampaignMapObserverExecutor(CampaignMapObserverContributor(find_current_fleet=later)),
        )
    )

    result = observer.fleet_locator.find_current_fleet(runtime)

    assert order == ["later", "earlier"]
    assert seen == [runtime, runtime]
    assert all(item is runtime for item in seen)
    assert runtime.standard_calls == 1
    assert result is expected


@pytest.mark.parametrize(
    ("fleet_2_enabled", "current_index", "expected_assignments", "expected_result"),
    [
        (False, 1, [(1, (3, 4))], (3, 4)),
        (True, 2, [(1, (3, 4)), (2, (5, 4))], (5, 4)),
    ],
)
def test_fixed_fleet_locations_replace_standard_and_honor_fleet_2(
    *,
    fleet_2_enabled: bool,
    current_index: Literal[1, 2],
    expected_assignments: list[tuple[int, GridLocation]],
    expected_result: FleetLocation,
) -> None:
    observer = _observer_for(_fixed_profile({"fleet_1": "D5", "fleet_2": "F5"}))
    runtime = _LocatorRuntime(
        fleet_2_enabled=fleet_2_enabled,
        current_index=current_index,
        standard_bomb=True,
    )

    result = observer.fleet_locator.find_current_fleet(runtime)

    assert runtime.assignments == expected_assignments
    assert result == expected_result
    assert result == runtime.fleet_current
    assert runtime.standard_calls == 0
    if not fleet_2_enabled:
        assert runtime.locations[2] == (8, 8)


@pytest.mark.parametrize("stage_id", ["a1", "c1"])
def test_real_20240521_profiles_wire_fixed_fleet_locator(stage_id: str) -> None:
    profile = _real_profile("event_20240521_cn", stage_id)
    bindings = tuple(
        binding
        for extension in profile.extensions
        for binding in extension.executors
        if binding.implementation_id == _IMPLEMENTATION
    )
    runtime = _LocatorRuntime(fleet_2_enabled=True, current_index=2, standard_bomb=True)

    result = _observer_for(profile).fleet_locator.find_current_fleet(runtime)

    assert len(bindings) == 1
    assert dict(bindings[0].options) == {"fleet_1": "D5", "fleet_2": "F5"}
    assert runtime.assignments == [(1, (3, 4)), (2, (5, 4))]
    assert result == (5, 4)
    assert runtime.standard_calls == 0


@pytest.mark.parametrize(
    ("fleet_2_enabled", "current_index", "expected_fleet_2", "expected_result"),
    [
        (False, 1, (8, 8), (3, 4)),
        (True, 2, (5, 4), (5, 4)),
    ],
)
def test_real_fixed_profile_uses_the_fleet_private_location_port(
    *,
    fleet_2_enabled: bool,
    current_index: Literal[1, 2],
    expected_fleet_2: FleetLocation,
    expected_result: FleetLocation,
) -> None:
    fleet = _FixedProfileFleet(
        _observer_for(_real_profile("event_20240521_cn", "a1")),
        fleet_2_enabled=fleet_2_enabled,
        current_index=current_index,
    )

    result = fleet.find_current_fleet()

    assert fleet.fleet_1_location == (3, 4)
    assert fleet.fleet_2_location == expected_fleet_2
    assert result == expected_result
    assert result == fleet.fleet_current


def test_fixed_fleet_profile_rejects_obsolete_string_operation() -> None:
    profile = _fixed_profile(
        {
            "fleet_1": "D5",
            "fleet_2": "F5",
            "operations": ["find_current_fleet"],
        }
    )

    with pytest.raises(CampaignRuntimeProfileError, match=r"unknown option: operations"):
        CampaignRuntimeProfileManager(profile, load_default_campaign_runtime_executor_registry())
