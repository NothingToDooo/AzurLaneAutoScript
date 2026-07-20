from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, cast, override

import pytest

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    InSightNext,
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
from module.map.camera import Camera
from module.map.map_observer import (
    STANDARD_CAMPAIGN_MAP_OBSERVER,
    CampaignMapObserver,
    InSightRequest,
    MapViewportRuntime,
)
from module.map.utils import node2location

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Protocol

    from module.base.type_alias import Point
    from module.map.map_base import CampaignMap
    from module.map.type_alias import GridLocation
    from module.map_detection.grid_info import GridInfo

    class _MutableRequest(Protocol):
        location: GridLocation


_IMPLEMENTATION = RuntimeImplementationId("observation/focus_rules")


class _RecordingViewport:
    def __init__(self) -> None:
        self.calls: list[tuple[MapViewportRuntime, InSightRequest]] = []

    def in_sight(self, runtime: MapViewportRuntime, request: InSightRequest) -> None:
        self.calls.append((runtime, request))


class _DispatchCamera(Camera):
    def __init__(self, viewport: _RecordingViewport) -> None:
        self._map_observer = CampaignMapObserver(
            combat=STANDARD_CAMPAIGN_MAP_OBSERVER.combat,
            scanner=STANDARD_CAMPAIGN_MAP_OBSERVER.scanner,
            enemy_searching=STANDARD_CAMPAIGN_MAP_OBSERVER.enemy_searching,
            viewport=viewport,
        )


class _ViewportMap:
    camera_sight = (-3, -1, 3, 2)


class _StandardCamera(Camera):
    def __init__(self) -> None:
        self._map_observer = STANDARD_CAMPAIGN_MAP_OBSERVER
        self.map = cast("CampaignMap", _ViewportMap())
        self.camera = (5, 5)
        self.focused: list[GridLocation] = []

    @override
    def focus_to(
        self,
        location: GridInfo | str | Point,
        swipe_limit: GridLocation = (4, 3),
    ) -> None:
        del swipe_limit
        assert not isinstance(location, str)
        assert not hasattr(location, "location")
        self.focused.append(cast("GridLocation", location))


class _RuleRuntime:
    def __init__(self, order: list[str] | None = None) -> None:
        self.focused: list[GridLocation] = []
        self.standard_requests: list[InSightRequest] = []
        self.order = order

    def focus_to(
        self,
        location: GridLocation,
        swipe_limit: GridLocation = (4, 3),
    ) -> None:
        del swipe_limit
        self.focused.append(location)

    def _standard_in_sight(self, request: InSightRequest) -> None:
        if self.order is not None:
            self.order.append("standard")
        self.standard_requests.append(request)


def _real_profile(pack_id: str, stage_id: str) -> CampaignRuntimeProfile:
    pack = next(pack for pack in load_default_event_manifests() if str(pack.pack_id) == pack_id)
    stage = next(stage for stage in pack.stages if stage.ref.stage_id == stage_id)
    return load_default_campaign_runtime_profile_registry().resolve(stage.runtime_profile_id)


def _focus_profile(options: Mapping[str, object]) -> CampaignRuntimeProfile:
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("viewport-focus-test"),
        (
            RuntimeExecutorBinding(
                RuntimeExecutorKind.MAP_OBSERVATION,
                _IMPLEMENTATION,
                cast("Mapping[str, RuntimeTuningValue]", options),
            ),
        ),
    )
    return CampaignRuntimeProfile(
        CampaignRuntimeProfileId("viewport-focus-test"),
        (extension,),
    )


def _observer_for(profile: CampaignRuntimeProfile) -> CampaignMapObserver:
    manager = CampaignRuntimeProfileManager(profile, load_default_campaign_runtime_executor_registry())
    instances = manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION)
    assert any(isinstance(instance, CampaignMapObserverExecutor) for instance in instances)
    return build_campaign_map_observer(instances)


def test_camera_normalizes_in_sight_once_into_a_frozen_request() -> None:
    viewport = _RecordingViewport()
    camera = _DispatchCamera(viewport)
    sight = (-4, -2, 4, 3)

    camera.in_sight("B3", sight=sight)

    assert len(viewport.calls) == 1
    runtime, request = viewport.calls[0]
    assert runtime is camera
    assert request.location == (1, 2)
    assert request.sight is sight
    with pytest.raises(FrozenInstanceError):
        cast("_MutableRequest", request).location = (0, 0)


@pytest.mark.parametrize(
    ("location", "sight", "expected_focus"),
    [
        ((10, 10), None, (7, 8)),
        ((10, 10), (-1, -1, 1, 1), (9, 9)),
        ((1, 2), (-2, -2, 2, 2), (3, 4)),
    ],
)
def test_standard_viewport_preserves_default_and_explicit_sight_algorithm(
    location: GridLocation,
    sight: tuple[int, int, int, int] | None,
    expected_focus: GridLocation,
) -> None:
    camera = _StandardCamera()

    camera.in_sight(location, sight=sight)

    assert camera.focused == [expected_focus]


def test_viewport_composition_is_later_first_and_preserves_request_identity() -> None:
    order: list[str] = []
    seen: list[InSightRequest] = []

    def earlier(
        runtime: MapViewportRuntime,
        request: InSightRequest,
        next_handler: InSightNext,
    ) -> None:
        order.append("earlier")
        seen.append(request)
        next_handler(runtime, request)

    def later(
        runtime: MapViewportRuntime,
        request: InSightRequest,
        next_handler: InSightNext,
    ) -> None:
        order.append("later")
        seen.append(request)
        next_handler(runtime, request)

    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(CampaignMapObserverContributor(in_sight=earlier)),
            CampaignMapObserverExecutor(CampaignMapObserverContributor(in_sight=later)),
        )
    )
    runtime = _RuleRuntime(order)
    request = InSightRequest((4, 5), sight=(-9, -8, 7, 6))

    observer.viewport.in_sight(runtime, request)

    assert order == ["later", "earlier", "standard"]
    assert seen == [request, request]
    assert all(item is request for item in seen)
    assert runtime.standard_requests == [request]
    assert runtime.standard_requests[0] is request


def test_focus_rules_use_the_first_match_without_calling_next() -> None:
    observer = _observer_for(
        _focus_profile(
            {
                "rules": [
                    {"when": {"x_gte": 1}, "focus_x": 2},
                    {"when": {"x_gte": 1}, "focus_x": 3},
                ]
            }
        )
    )
    runtime = _RuleRuntime()

    observer.viewport.in_sight(runtime, InSightRequest((8, 6)))

    assert runtime.focused == [(2, 6)]
    assert runtime.standard_requests == []


@pytest.mark.parametrize(
    ("pack_id", "stage_id", "location", "expected_focus"),
    [
        ("event_20240521_cn", "b3", "I4", "H4"),
        ("event_20240521_cn", "d3", "C5", "D5"),
        ("event_20260520_cn", "b3", "E3", "E3"),
        ("event_20260520_cn", "d3", "E3", "E3"),
    ],
)
def test_real_b3_d3_profiles_wire_their_focus_rules(
    pack_id: str,
    stage_id: str,
    location: str,
    expected_focus: str,
) -> None:
    profile = _real_profile(pack_id, stage_id)
    focus_bindings = tuple(
        binding
        for extension in profile.extensions
        for binding in extension.executors
        if binding.implementation_id == _IMPLEMENTATION
    )
    runtime = _RuleRuntime()

    _observer_for(profile).viewport.in_sight(
        runtime,
        InSightRequest(node2location(location)),
    )

    assert len(focus_bindings) == 1
    assert "operations" not in focus_bindings[0].options
    assert runtime.focused == [node2location(expected_focus)]
    assert runtime.standard_requests == []


def test_unmatched_focus_rules_preserve_normalized_location_and_sight_for_fallback() -> None:
    observer = _observer_for(_real_profile("event_20240521_cn", "b3"))
    runtime = _RuleRuntime()
    sight = (-9, -8, 7, 6)
    request = InSightRequest(node2location("F6"), sight=sight)

    observer.viewport.in_sight(runtime, request)

    assert runtime.focused == []
    assert runtime.standard_requests == [request]
    assert runtime.standard_requests[0] is request
    assert runtime.standard_requests[0].location == (5, 5)
    assert runtime.standard_requests[0].sight is sight


def test_focus_rules_profile_rejects_obsolete_string_operation() -> None:
    profile = _focus_profile(
        {
            "operations": ["in_sight"],
            "rules": [{"when": {"cell": "E3"}, "focus_cell": "E3"}],
        }
    )

    with pytest.raises(CampaignRuntimeProfileError, match=r"unknown option: operations"):
        CampaignRuntimeProfileManager(profile, load_default_campaign_runtime_executor_registry())
