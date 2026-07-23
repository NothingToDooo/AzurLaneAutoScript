from typing import TYPE_CHECKING, override

from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeSessionOutcome,
    RuntimeStateSeed,
)
from module.application import AbortToken
from module.config.config import AzurLaneConfig
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
from module.map.map_base import CampaignMap
from module.map.map_layout import CampaignMapLayout
from module.map_detection.grid import Grid
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Unpack

    from module.adapters.campaign_runtime_profile import RuntimeExecutorFactory
    from module.config.config_generated import ConfigOverrides


class _Config(AzurLaneConfig):
    def __init__(self) -> None:
        self.overlays: list[dict[str, object]] = []

    @override
    def apply_runtime_overlay(self, **kwargs: Unpack[ConfigOverrides]) -> None:
        self.overlays.append(dict(kwargs))


class _Runtime:
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = 0.0
    MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD = 0.0
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = 0.0


class _MapGrid(GridInfo):
    pass


class _CameraGrid(Grid):
    pass


class _LifecycleExecutor(RuntimeExecutorInstance):
    def __init__(
        self,
        kinds: frozenset[RuntimeExecutorKind],
        trace: list[object],
        *,
        state_seed: RuntimeStateSeed | None = None,
    ) -> None:
        super().__init__(
            kinds,
            state_seed=RuntimeStateSeed() if state_seed is None else state_seed,
        )
        self.trace = trace

    @override
    def bind(self, runtime: object, compiled_map: CampaignMap) -> None:
        super().bind(runtime, compiled_map)
        self.trace.append("bind")

    @override
    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        super().end_session(outcome)
        self.trace.append(("end", outcome))

    @override
    def reset(self) -> None:
        super().reset()
        self.trace.append("reset")


def _binding(
    implementation: str,
    kind: RuntimeExecutorKind,
    options: Mapping[str, object] | None = None,
) -> RuntimeExecutorBinding:
    return RuntimeExecutorBinding(
        kind,
        RuntimeImplementationId(implementation),
        {} if options is None else options,
    )


def _profile(*extensions: CampaignRuntimeExtension) -> CampaignRuntimeProfile:
    return CampaignRuntimeProfile(
        CampaignRuntimeProfileId("test"),
        extensions,
    )


def _extension(
    name: str,
    *bindings: RuntimeExecutorBinding,
) -> CampaignRuntimeExtension:
    return CampaignRuntimeExtension(
        CampaignRuntimeExtensionId(name),
        bindings,
    )


def _descriptor(
    implementation: str,
    schemas: Mapping[RuntimeExecutorKind, RuntimeExecutorOptionsSchema],
    factory: RuntimeExecutorFactory,
) -> RuntimeExecutorFactoryDescriptor:
    return RuntimeExecutorFactoryDescriptor(
        RuntimeImplementationId(implementation),
        schemas,
        factory,
    )


def test_one_implementation_builds_once_and_shares_multiple_facets() -> None:
    builds: list[RuntimeExecutorBuildContext] = []

    def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        builds.append(context)
        return RuntimeExecutorInstance(
            {RuntimeExecutorKind.MAP_MECHANIC, RuntimeExecutorKind.ENGINE_EXTENSION},
        )

    registry = CampaignRuntimeExecutorRegistry(
        (
            _descriptor(
                "shared",
                {
                    RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema(),
                    RuntimeExecutorKind.ENGINE_EXTENSION: RuntimeExecutorOptionsSchema(),
                },
                factory,
            ),
        )
    )
    profile = _profile(
        _extension(
            "shared",
            _binding("shared", RuntimeExecutorKind.MAP_MECHANIC),
            _binding("shared", RuntimeExecutorKind.ENGINE_EXTENSION),
        )
    )

    CampaignRuntimeProfileManager(profile, registry)

    assert len(builds) == 1
    assert {binding.kind for binding in builds[0].bindings} == {
        RuntimeExecutorKind.MAP_MECHANIC,
        RuntimeExecutorKind.ENGINE_EXTENSION,
    }


def test_tuning_patch_is_sparse_and_does_not_leak_between_runtimes() -> None:
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("tunings"),
        tunings=(
            RuntimeTuning(RuntimeTuningKey.MAP_SWIPE_PREDICT, value=False),
            RuntimeTuning(RuntimeTuningKey.FLEET_2, 0),
            RuntimeTuning(RuntimeTuningKey.SUBMARINE, 0),
            RuntimeTuning(RuntimeTuningKey.FLEET_BOSS, 1),
            RuntimeTuning(RuntimeTuningKey.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD, 1),
            RuntimeTuning(RuntimeTuningKey.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD, 1),
            RuntimeTuning(RuntimeTuningKey.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD, 1),
            RuntimeTuning(RuntimeTuningKey.BOSS_APPEAR_REFOCUS_PRESET, [-3, 0]),
            RuntimeTuning(RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER, 0.5),
            RuntimeTuning(RuntimeTuningKey.COMBAT_DISABLE_STUCK_DETECTION_BATTLE, 1),
        ),
    )
    manager = CampaignRuntimeProfileManager(
        profile,
        CampaignRuntimeExecutorRegistry(()),
    )
    other = CampaignRuntimeProfileManager(
        CampaignRuntimeProfile.core(),
        CampaignRuntimeExecutorRegistry(()),
    )
    config = _Config()
    runtime = _Runtime()
    untouched = _Runtime()

    manager.apply_config(config)
    manager.apply_runtime_thresholds(runtime)

    assert len(config.overlays) == 1
    assert config.overlays[0]["MAP_SWIPE_PREDICT"] is False
    assert config.overlays[0]["Fleet_Fleet2"] == 0
    assert config.overlays[0]["Submarine_Fleet"] == 0
    assert manager.configured_boss_fleet is not None
    assert manager.configured_boss_fleet.index == 1
    assert runtime.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD == 1.0
    assert runtime.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD == 1.0
    assert runtime.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD == 1.0
    assert untouched.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD == 0.0
    assert manager.boss_appear_refocus_preset == (-3, 0)
    assert manager.map_clear_percentage_multiplier == 0.5
    assert manager.combat_disable_stuck_detection_battle == 1
    assert other.boss_appear_refocus_preset is None
    assert other.map_clear_percentage_multiplier == 1.0
    assert other.configured_boss_fleet is None


def test_map_and_camera_grid_ports_are_selected_independently() -> None:
    def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        return RuntimeExecutorInstance(
            {binding.kind for binding in context.bindings},
            map_grid_class=_MapGrid,
            camera_grid_class=_CameraGrid,
        )

    manager = CampaignRuntimeProfileManager(
        _profile(
            _extension(
                "grids",
                _binding("grids", RuntimeExecutorKind.MAP_GRID_RECOGNITION),
                _binding("grids", RuntimeExecutorKind.CAMERA_GRID_RECOGNITION),
            )
        ),
        CampaignRuntimeExecutorRegistry(
            (
                _descriptor(
                    "grids",
                    {
                        RuntimeExecutorKind.MAP_GRID_RECOGNITION: RuntimeExecutorOptionsSchema(),
                        RuntimeExecutorKind.CAMERA_GRID_RECOGNITION: RuntimeExecutorOptionsSchema(),
                    },
                    factory,
                ),
            )
        ),
    )
    grid_class = manager.map_grid_class
    assert grid_class is _MapGrid
    layout = CampaignMapLayout(grid_class=grid_class)
    layout.initialize("A1")

    assert isinstance(layout[(0, 0)], _MapGrid)
    assert manager.camera_grid_class is _CameraGrid


def test_lifecycle_closes_and_a_new_manager_reseeds_state() -> None:
    traces: list[list[object]] = []

    def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        trace: list[object] = []
        traces.append(trace)
        return _LifecycleExecutor(
            frozenset(binding.kind for binding in context.bindings),
            trace,
        )

    registry = CampaignRuntimeExecutorRegistry(
        (
            _descriptor(
                "lifecycle",
                {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()},
                factory,
            ),
        )
    )
    profile = _profile(
        _extension(
            "lifecycle",
            _binding("lifecycle", RuntimeExecutorKind.MAP_MECHANIC),
        )
    )
    manager = CampaignRuntimeProfileManager(profile, registry)
    compiled = CampaignMap("test")
    runtime = _Runtime()
    manager.bind(runtime, compiled)
    manager.begin_session()
    manager.end_session(RuntimeSessionOutcome.COMPLETED)
    manager.reset()

    other = CampaignRuntimeProfileManager(profile, registry)
    other.bind(_Runtime(), CampaignMap("other"))
    other.begin_session()

    assert traces[0] == [
        "bind",
        ("end", RuntimeSessionOutcome.COMPLETED),
        "reset",
    ]
    assert traces[1] == ["bind"]
    assert not other.use_support_fleet(AbortToken())
