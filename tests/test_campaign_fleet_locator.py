from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    LocateSurfaceFleetNext,
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
from module.map.fleet_locator import (
    FleetLocationContext,
    SurfaceFleetLocationRequest,
    SurfaceFleetLocations,
    SurfaceFleetObservation,
)
from module.map.map_grids import SelectedGrids
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.map.map_base import CampaignMap
    from module.map.map_observer import CampaignMapObserver
    from module.map.type_alias import GridLocation

_IMPLEMENTATION = RuntimeImplementationId("observation/fixed_fleet_locations")
_PREVIOUS = SurfaceFleetLocations(fleet_1=(9, 9), fleet_2=(8, 8))


class _Grid(GridInfo):
    def __init__(self, location: GridLocation) -> None:
        self.location = location
        self.is_fleet = True
        self.is_spawn_point = True


class _Map:
    shape = (1, 1)

    def __init__(self, detected: GridLocation) -> None:
        self._grids: SelectedGrids[GridInfo] = SelectedGrids([_Grid(detected)])

    def select(self, **criteria: object) -> SelectedGrids[GridInfo]:
        return self._grids.select(**criteria)

    @staticmethod
    def grid_covered(
        grid: GridInfo,
        *,
        location: list[GridLocation],
    ) -> SelectedGrids[GridInfo]:
        del grid, location
        return SelectedGrids([])


class _LocatorContext:
    camera: GridLocation = (0, 0)

    def __init__(self, detected: GridLocation = (4, 6)) -> None:
        self.map = cast("CampaignMap", _Map(detected))
        self.observation_calls: list[str] = []

    def _observe_surface_fleet(self, grid: GridInfo) -> SurfaceFleetObservation:
        del grid
        self.observation_calls.append("surface")
        message = "single detected fleet must not require directed observation"
        raise AssertionError(message)

    def _observe_current_fleet(self, grid: GridInfo) -> bool:
        del grid
        self.observation_calls.append("current")
        message = "single detected fleet must not require current-fleet observation"
        raise AssertionError(message)

    def _observe_submarine(self, grid: GridInfo) -> bool:
        del grid
        self.observation_calls.append("submarine")
        message = "surface fleet location must not observe submarines"
        raise AssertionError(message)


class _UnusedLocatorContext:
    def __init__(self) -> None:
        self.observation_calls: list[str] = []

    @property
    def map(self) -> CampaignMap:
        message = "fixed fleet profile must not inspect the map"
        raise AssertionError(message)

    @property
    def camera(self) -> GridLocation:
        message = "fixed fleet profile must not inspect the camera"
        raise AssertionError(message)

    def _observe_surface_fleet(self, grid: GridInfo) -> SurfaceFleetObservation:
        del grid
        self.observation_calls.append("surface")
        message = "fixed fleet profile must not observe fleets"
        raise AssertionError(message)

    def _observe_current_fleet(self, grid: GridInfo) -> bool:
        del grid
        self.observation_calls.append("current")
        message = "fixed fleet profile must not observe the current fleet"
        raise AssertionError(message)

    def _observe_submarine(self, grid: GridInfo) -> bool:
        del grid
        self.observation_calls.append("submarine")
        message = "fixed fleet profile must not observe submarines"
        raise AssertionError(message)


def _request(*, fleet_2_enabled: bool = False) -> SurfaceFleetLocationRequest:
    return SurfaceFleetLocationRequest(
        previous=_PREVIOUS,
        fleet_2_enabled=fleet_2_enabled,
        poor_map_data=False,
    )


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


def test_fleet_locator_composition_preserves_exact_context_request_and_return() -> None:
    context = _LocatorContext()
    request = _request()
    expected = SurfaceFleetLocations(fleet_1=(7, 8), fleet_2=())
    seen: list[tuple[FleetLocationContext, SurfaceFleetLocationRequest]] = []

    def locate_surface_fleet(
        received_context: FleetLocationContext,
        received_request: SurfaceFleetLocationRequest,
        next_handler: LocateSurfaceFleetNext,
    ) -> SurfaceFleetLocations:
        del next_handler
        seen.append((received_context, received_request))
        return expected

    observer = build_campaign_map_observer(
        (CampaignMapObserverExecutor(CampaignMapObserverContributor(locate_surface_fleet=locate_surface_fleet)),)
    )

    result = observer.fleet_locator.locate_surface(context, request)

    assert seen == [(context, request)]
    assert seen[0][0] is context
    assert seen[0][1] is request
    assert result is expected


def test_standard_fleet_locator_is_the_composition_fallback() -> None:
    context = _LocatorContext()
    request = _request()

    result = build_campaign_map_observer(()).fleet_locator.locate_surface(context, request)

    assert result == SurfaceFleetLocations(fleet_1=(4, 6), fleet_2=(8, 8))


def test_fleet_locator_composition_is_later_first() -> None:
    order: list[str] = []
    seen: list[tuple[FleetLocationContext, SurfaceFleetLocationRequest]] = []

    def earlier(
        context: FleetLocationContext,
        request: SurfaceFleetLocationRequest,
        next_handler: LocateSurfaceFleetNext,
    ) -> SurfaceFleetLocations:
        order.append("earlier")
        seen.append((context, request))
        return next_handler(context, request)

    def later(
        context: FleetLocationContext,
        request: SurfaceFleetLocationRequest,
        next_handler: LocateSurfaceFleetNext,
    ) -> SurfaceFleetLocations:
        order.append("later")
        seen.append((context, request))
        return next_handler(context, request)

    context = _LocatorContext(detected=(5, 7))
    request = _request()
    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(CampaignMapObserverContributor(locate_surface_fleet=earlier)),
            CampaignMapObserverExecutor(CampaignMapObserverContributor(locate_surface_fleet=later)),
        )
    )

    result = observer.fleet_locator.locate_surface(context, request)

    assert order == ["later", "earlier"]
    assert seen == [(context, request), (context, request)]
    assert all(received_context is context for received_context, _ in seen)
    assert all(received_request is request for _, received_request in seen)
    assert result == SurfaceFleetLocations(fleet_1=(5, 7), fleet_2=(8, 8))


@pytest.mark.parametrize(
    ("fleet_2_enabled", "expected"),
    [
        (False, SurfaceFleetLocations(fleet_1=(3, 4), fleet_2=(8, 8))),
        (True, SurfaceFleetLocations(fleet_1=(3, 4), fleet_2=(5, 4))),
    ],
)
def test_fixed_fleet_locations_replace_standard_and_honor_fleet_2(
    *,
    fleet_2_enabled: bool,
    expected: SurfaceFleetLocations,
) -> None:
    observer = _observer_for(_fixed_profile({"fleet_1": "D5", "fleet_2": "F5"}))

    result = observer.fleet_locator.locate_surface(
        _UnusedLocatorContext(),
        _request(fleet_2_enabled=fleet_2_enabled),
    )

    assert result == expected


@pytest.mark.parametrize("stage_id", ["a1", "c1"])
def test_real_20240521_profiles_wire_fixed_fleet_locator(stage_id: str) -> None:
    profile = _real_profile("event_20240521_cn", stage_id)
    bindings = tuple(
        binding
        for extension in profile.extensions
        for binding in extension.executors
        if binding.implementation_id == _IMPLEMENTATION
    )

    result = _observer_for(profile).fleet_locator.locate_surface(
        _UnusedLocatorContext(),
        _request(fleet_2_enabled=True),
    )

    assert len(bindings) == 1
    assert dict(bindings[0].options) == {"fleet_1": "D5", "fleet_2": "F5"}
    assert result == SurfaceFleetLocations(fleet_1=(3, 4), fleet_2=(5, 4))


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
