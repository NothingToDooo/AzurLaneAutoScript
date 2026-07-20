from dataclasses import FrozenInstanceError
from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import numpy as np
import pytest
from config_factory import in_memory_config

from module.adapters.campaign_map_swipe import build_campaign_map_swipe_service
from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_mechanics import mechanic_runtime_executor_descriptors
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
)
from module.content.manifest import load_default_event_manifests
from module.content.models import StageRef
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
from module.content.stage_loader import load_default_stage
from module.device.device import Device
from module.map.camera import Camera
from module.map.map_swipe import (
    STANDARD_MAP_SWIPE_POLICY,
    MapSwipeBox,
    MapSwipePolicy,
    MapSwipeRequest,
    MapSwipeService,
)
from module.os.camera import OSCamera

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.base.type_alias import Area, Point
    from module.content.models import EventPack, StageSpec
    from module.map_detection.view import View

_STANDARD_BOX = (123, 159, 1175, 628)
_SUPPORT_BOX = (239, 159, 1175, 628)
_OS_BOX = (239, 128, 993, 628)
_SUPPORT_IMPLEMENTATION = "map_mechanic/support_fleet"


class _RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[Point, Area]] = []

    def _standard_map_swipe(self, vector: Point, *, box: Area) -> bool:
        self.calls.append((vector, box))
        return True


class _RecordingCamera(Camera):
    def __init__(self, service: MapSwipeService) -> None:
        self._map_swipe_service = service
        self.view = cast("View", SimpleNamespace(center_offset=np.array((0.5, 0.5))))
        self.calls: list[tuple[Point, Area]] = []

    @override
    def _standard_map_swipe(self, vector: Point, *, box: Area) -> bool:
        self.calls.append((vector, box))
        return True


class _RecordingOSCamera(OSCamera):
    def __init__(self) -> None:
        self.calls: list[tuple[Point, Area]] = []

    @override
    def _standard_map_swipe(self, vector: Point, *, box: Area) -> bool:
        self.calls.append((vector, box))
        return True

    def swipe_for_test(self, vector: Point) -> bool:
        return self._map_swipe(vector)


def _support_binding(operations: list[str] | None = None) -> RuntimeExecutorBinding:
    return RuntimeExecutorBinding(
        RuntimeExecutorKind.MAP_MECHANIC,
        RuntimeImplementationId(_SUPPORT_IMPLEMENTATION),
        {
            "operations": ["fleet_preparation"] if operations is None else operations,
            "state": ["use_support_fleet"],
        },
    )


def _manager(*bindings: RuntimeExecutorBinding) -> CampaignRuntimeProfileManager:
    extensions = tuple(
        CampaignRuntimeExtension(
            CampaignRuntimeExtensionId(f"map-swipe-test-{index}"),
            (binding,),
        )
        for index, binding in enumerate(bindings)
    )
    return CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(CampaignRuntimeProfileId("map-swipe-test"), extensions),
        CampaignRuntimeExecutorRegistry(mechanic_runtime_executor_descriptors()),
    )


def _service(manager: CampaignRuntimeProfileManager) -> MapSwipeService:
    return build_campaign_map_swipe_service(manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC))


def test_camera_map_swipe_uses_the_support_policy_when_box_is_omitted() -> None:
    camera = _RecordingCamera(_service(_manager(_support_binding())))

    assert camera.map_swipe((2, -1))

    assert len(camera.calls) == 1
    vector, box = camera.calls[0]
    assert tuple(vector) == (2, -1)
    assert box == _SUPPORT_BOX


def test_explicit_box_always_wins_and_preserves_the_exact_vector() -> None:
    runtime = _RecordingRuntime()
    vector = np.array((1.25, -2.5))
    explicit_box = np.array((10, 20, 30, 40))
    service = MapSwipeService(policy=MapSwipePolicy(default_box=_SUPPORT_BOX))

    assert service.swipe(runtime, MapSwipeRequest(vector=vector, explicit_box=explicit_box))

    observed_vector, observed_box = runtime.calls[0]
    assert observed_vector is vector
    assert observed_box is explicit_box


def test_standard_service_uses_the_standard_box() -> None:
    runtime = _RecordingRuntime()
    service = build_campaign_map_swipe_service(())

    assert service.swipe(runtime, MapSwipeRequest(vector=(3, 4)))

    assert service.policy is STANDARD_MAP_SWIPE_POLICY
    assert runtime.calls == [((3, 4), _STANDARD_BOX)]


def test_os_camera_keeps_its_explicit_custom_default() -> None:
    camera = _RecordingOSCamera()

    assert camera.swipe_for_test((1, 0))

    assert camera.calls == [((1, 0), _OS_BOX)]


def test_multiple_campaign_map_swipe_policies_are_rejected() -> None:
    sources = (
        SimpleNamespace(map_swipe_policy=MapSwipePolicy(default_box=_SUPPORT_BOX)),
        SimpleNamespace(map_swipe_policy=MapSwipePolicy(default_box=(100, 100, 200, 200))),
    )

    with pytest.raises(CampaignRuntimeProfileError, match="at most one policy source"):
        build_campaign_map_swipe_service(sources)


def test_request_and_policy_are_frozen_and_policy_requires_a_canonical_box() -> None:
    vector = np.array((1.0, 2.0))
    request = MapSwipeRequest(vector=vector)
    policy = MapSwipePolicy(default_box=_STANDARD_BOX)

    assert request.vector is vector
    assert policy.default_box is _STANDARD_BOX
    with pytest.raises(FrozenInstanceError):
        setattr(  # ruff:ignore[set-attr-with-constant] - 刻意验证 frozen request 拒绝修改。
            request,
            "explicit_box",
            _SUPPORT_BOX,
        )
    with pytest.raises(FrozenInstanceError):
        setattr(  # ruff:ignore[set-attr-with-constant] - 刻意验证 frozen policy 拒绝修改。
            policy,
            "default_box",
            _SUPPORT_BOX,
        )
    with pytest.raises(TypeError, match="canonical integer tuple"):
        MapSwipePolicy(default_box=cast("MapSwipeBox", [1, 2, 3, 4]))
    with pytest.raises(ValueError, match="four coordinates"):
        MapSwipePolicy(default_box=cast("MapSwipeBox", (1, 2, 3)))


def test_support_executor_rejects_the_obsolete_map_swipe_operation() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="operations mismatch"):
        _manager(_support_binding(["_map_swipe", "fleet_preparation"]))


@pytest.fixture(scope="module")
def packs_by_id() -> Mapping[str, EventPack]:
    return MappingProxyType({str(pack.pack_id): pack for pack in load_default_event_manifests()})


def _stage(packs_by_id: Mapping[str, EventPack], stage_id: str) -> StageSpec:
    return next(stage for stage in packs_by_id["campaign_main"].stages if stage.ref.stage_id == stage_id)


def _production_service(
    packs_by_id: Mapping[str, EventPack],
    stage_id: str,
) -> tuple[MapSwipeService, frozenset[tuple[RuntimeExecutorKind, str]]]:
    profiles = load_default_campaign_runtime_profile_registry()
    profile = profiles.resolve(_stage(packs_by_id, stage_id).runtime_profile_id)
    manager = CampaignRuntimeProfileManager(
        profile,
        load_default_campaign_runtime_executor_registry(),
    )
    bindings = frozenset(
        (binding.kind, binding.implementation_id.value)
        for extension in profile.extensions
        for binding in extension.executors
    )
    return _service(manager), bindings


@pytest.mark.parametrize(
    "stage_id",
    ["15-1", "15-2", "15-3", "15-4", "15-4-121", "16-1", "16-2", "16-3", "16-4"],
)
def test_real_support_fleet_stages_use_the_support_policy(
    packs_by_id: Mapping[str, EventPack],
    stage_id: str,
) -> None:
    service, bindings = _production_service(packs_by_id, stage_id)

    assert (RuntimeExecutorKind.MAP_MECHANIC, _SUPPORT_IMPLEMENTATION) in bindings
    assert service.policy == MapSwipePolicy(default_box=_SUPPORT_BOX)


def test_real_non_support_stage_uses_the_standard_policy(
    packs_by_id: Mapping[str, EventPack],
) -> None:
    service, bindings = _production_service(packs_by_id, "14-4")
    runtime = _RecordingRuntime()

    assert (RuntimeExecutorKind.MAP_MECHANIC, _SUPPORT_IMPLEMENTATION) not in bindings
    assert service.policy is STANDARD_MAP_SWIPE_POLICY
    assert service.swipe(runtime, MapSwipeRequest(vector=(1, 1)))
    assert runtime.calls == [((1, 1), _STANDARD_BOX)]


@pytest.mark.parametrize(
    ("stage_id", "expected_box"),
    [("15-1", _SUPPORT_BOX), ("14-4", _STANDARD_BOX)],
)
def test_declarative_runtime_installs_the_real_profile_map_swipe_service(
    stage_id: str,
    expected_box: MapSwipeBox,
) -> None:
    runtime = DeclarativeCampaignMapRuntime(
        in_memory_config(f"map-swipe-wiring-{stage_id}", {}),
        object.__new__(Device),
        load_default_stage(StageRef("campaign_main", stage_id)),
    )

    assert runtime._map_swipe_service.policy.default_box == expected_box  # ruff:ignore[private-member-access] - 删除生产 wiring 时必须失败。
