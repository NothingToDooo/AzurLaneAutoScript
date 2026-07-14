from __future__ import annotations

from typing import TYPE_CHECKING, override

import pytest

from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
    RuntimeSessionContext,
    RuntimeSessionEntryKind,
    RuntimeSessionOutcome,
    RuntimeStateSeed,
)
from module.application import AbortToken
from module.config.config import AzurLaneConfig
from module.content.campaign_session import CampaignRunVariant
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
from module.map_detection.grid import Grid
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Unpack

    from module.adapters.campaign_runtime_profile import (
        RuntimeExecutorFactory,
        RuntimeMethod,
    )
    from module.config.config_generated import ConfigOverrides


class _Config(AzurLaneConfig):
    def __init__(self) -> None:
        self.overlays: list[dict[str, object]] = []
        self._fleet_2_value = -1
        self._fleet_boss_value = -1
        self._submarine_value = -1

    @override
    def apply_runtime_overlay(self, **kwargs: Unpack[ConfigOverrides]) -> None:
        self.overlays.append(dict(kwargs))

    @property
    @override
    def fleet_2(self) -> int:
        return self._fleet_2_value

    @fleet_2.setter
    def fleet_2(self, value: int) -> None:
        self._fleet_2_value = value

    @property
    @override
    def fleet_boss(self) -> int:
        return self._fleet_boss_value

    @fleet_boss.setter
    def fleet_boss(self, value: int) -> None:
        self._fleet_boss_value = value

    @property
    @override
    def submarine(self) -> int:
        return self._submarine_value

    @submarine.setter
    def submarine(self, value: int) -> None:
        self._submarine_value = value


class _Runtime:
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = 0.0
    MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD = 0.0
    MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD = 0.0
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = 0.0

    def __init__(self) -> None:
        self.manager: CampaignRuntimeProfileManager | None = None
        self.trace: list[str] = []

    def runtime_super(
        self,
        operation: RuntimeOperation,
        value: int,
    ) -> int:
        if self.manager is None:
            message = "runtime manager is not installed"
            raise AssertionError(message)
        result = self.manager.invoke_super(operation, self, value)
        if type(result) is not int:
            message = "test runtime expected an integer result"
            raise AssertionError(message)
        return result


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
    def begin_session(self, context: RuntimeSessionContext) -> None:
        super().begin_session(context)
        self.trace.append(("begin", context.entry_kind, context.battle_index))

    @override
    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        super().end_session(outcome)
        self.trace.append(("end", outcome))

    @override
    def reset(self) -> None:
        super().reset()
        self.trace.append("reset")


class _DependentStateExecutor(RuntimeExecutorInstance):
    def __init__(self) -> None:
        super().__init__(
            {RuntimeExecutorKind.MAP_MECHANIC},
            state_seed=RuntimeStateSeed(map_has_mob_move=False),
        )

    @override
    def begin_session(self, context: RuntimeSessionContext) -> None:
        super().begin_session(context)
        self.set_map_has_mob_move(enabled=self.current_use_support_fleet())


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


def _empty_navigation(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    del context
    return RuntimeExecutorInstance({RuntimeExecutorKind.NAVIGATION})


def test_one_implementation_builds_once_and_shares_multiple_facets() -> None:
    builds: list[RuntimeExecutorBuildContext] = []

    def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        builds.append(context)
        return RuntimeExecutorInstance(
            {RuntimeExecutorKind.MAP_MECHANIC, RuntimeExecutorKind.ENGINE_EXTENSION},
            state_seed=RuntimeStateSeed(map_has_mob_move=True),
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

    manager = CampaignRuntimeProfileManager(profile, registry)

    assert manager.executor_instance_count == 1
    assert len(builds) == 1
    assert {binding.kind for binding in builds[0].bindings} == {
        RuntimeExecutorKind.MAP_MECHANIC,
        RuntimeExecutorKind.ENGINE_EXTENSION,
    }
    assert manager.map_has_mob_move(AbortToken())
    manager.disable_mob_move()
    assert not manager.map_has_mob_move(AbortToken())


def test_distinct_implementations_share_typed_session_state() -> None:
    def support_factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        del context
        return RuntimeExecutorInstance(
            {RuntimeExecutorKind.MAP_MECHANIC},
            state_seed=RuntimeStateSeed(use_support_fleet=True),
        )

    def dependent_factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        del context
        return _DependentStateExecutor()

    schema = {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()}
    manager = CampaignRuntimeProfileManager(
        _profile(
            _extension("support", _binding("support", RuntimeExecutorKind.MAP_MECHANIC)),
            _extension("dependent", _binding("dependent", RuntimeExecutorKind.MAP_MECHANIC)),
        ),
        CampaignRuntimeExecutorRegistry(
            (
                _descriptor("support", schema, support_factory),
                _descriptor("dependent", schema, dependent_factory),
            )
        ),
    )
    manager.bind(_Runtime(), CampaignMap("shared-state"))
    context = RuntimeSessionContext(
        CampaignRunVariant.LOOP,
        0,
        RuntimeSessionEntryKind.FRESH,
    )

    manager.begin_session(context)

    assert manager.use_support_fleet(AbortToken())
    assert manager.map_has_mob_move(AbortToken())
    assert manager.use_single_fleet_override(AbortToken()) is None
    manager.disable_support_fleet()
    assert not manager.use_support_fleet(AbortToken())
    manager.end_session(RuntimeSessionOutcome.COMPLETED)
    manager.begin_session(context)
    assert manager.use_support_fleet(AbortToken())
    assert manager.map_has_mob_move(AbortToken())


def test_same_kind_composes_base_to_derived_as_an_around_chain() -> None:
    operation = RuntimeOperation.EXPECTED_END

    def base(runtime: object, value: object) -> object:
        typed = runtime if isinstance(runtime, _Runtime) else None
        if typed is None or type(value) is not int:
            message = "invalid base test call"
            raise AssertionError(message)
        typed.trace.append("base:before")
        result = typed.runtime_super(operation, value + 1)
        typed.trace.append("base:after")
        return result + 10

    def derived(runtime: object, value: object) -> object:
        typed = runtime if isinstance(runtime, _Runtime) else None
        if typed is None or type(value) is not int:
            message = "invalid derived test call"
            raise AssertionError(message)
        typed.trace.append("derived:before")
        result = typed.runtime_super(operation, value + 1)
        typed.trace.append("derived:after")
        return result + 100

    def descriptor(name: str, method: RuntimeMethod) -> RuntimeExecutorFactoryDescriptor:
        def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
            del context
            return RuntimeExecutorInstance(
                {RuntimeExecutorKind.ENGINE_EXTENSION},
                methods={
                    RuntimeExecutorKind.ENGINE_EXTENSION: {
                        operation: method,
                    }
                },
            )

        return _descriptor(
            name,
            {RuntimeExecutorKind.ENGINE_EXTENSION: RuntimeExecutorOptionsSchema()},
            factory,
        )

    manager = CampaignRuntimeProfileManager(
        _profile(
            _extension("base", _binding("base", RuntimeExecutorKind.ENGINE_EXTENSION)),
            _extension(
                "derived",
                _binding("derived", RuntimeExecutorKind.ENGINE_EXTENSION),
            ),
        ),
        CampaignRuntimeExecutorRegistry((descriptor("base", base), descriptor("derived", derived))),
    )
    runtime = _Runtime()
    runtime.manager = manager

    result = manager.engine.invoke(
        operation,
        runtime,
        lambda value: value * 2,
        1,
    )

    assert result == 116
    assert runtime.trace == [
        "derived:before",
        "base:before",
        "base:after",
        "derived:after",
    ]


def test_derived_executor_can_short_circuit_without_calling_next() -> None:
    operation = RuntimeOperation.FULL_SCAN
    called: list[str] = []

    def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        name = context.implementation_id.value

        def method(runtime: object) -> object:
            del runtime
            called.append(name)
            return None

        return RuntimeExecutorInstance(
            {RuntimeExecutorKind.MAP_OBSERVATION},
            methods={RuntimeExecutorKind.MAP_OBSERVATION: {operation: method}},
        )

    schemas = {RuntimeExecutorKind.MAP_OBSERVATION: RuntimeExecutorOptionsSchema()}
    manager = CampaignRuntimeProfileManager(
        _profile(
            _extension("base", _binding("base", RuntimeExecutorKind.MAP_OBSERVATION)),
            _extension(
                "derived",
                _binding("derived", RuntimeExecutorKind.MAP_OBSERVATION),
            ),
        ),
        CampaignRuntimeExecutorRegistry(
            (
                _descriptor("base", schemas, factory),
                _descriptor("derived", schemas, factory),
            )
        ),
    )

    manager.observation.invoke(operation, object(), lambda: called.append("fallback"))

    assert called == ["derived"]


@pytest.mark.parametrize(
    ("profile", "registry", "match"),
    [
        (
            _profile(_extension("missing", _binding("missing", RuntimeExecutorKind.NAVIGATION))),
            CampaignRuntimeExecutorRegistry(()),
            "unregistered",
        ),
        (
            _profile(_extension("wrong", _binding("wrong", RuntimeExecutorKind.EVENT_UI))),
            CampaignRuntimeExecutorRegistry(
                (
                    _descriptor(
                        "wrong",
                        {RuntimeExecutorKind.NAVIGATION: RuntimeExecutorOptionsSchema()},
                        _empty_navigation,
                    ),
                )
            ),
            "does not support",
        ),
        (
            _profile(
                _extension(
                    "options",
                    _binding(
                        "options",
                        RuntimeExecutorKind.NAVIGATION,
                        {"unexpected": True},
                    ),
                )
            ),
            CampaignRuntimeExecutorRegistry(
                (
                    _descriptor(
                        "options",
                        {RuntimeExecutorKind.NAVIGATION: RuntimeExecutorOptionsSchema()},
                        _empty_navigation,
                    ),
                )
            ),
            "unknown option",
        ),
    ],
)
def test_registry_contracts_fail_before_runtime_binding(
    profile: CampaignRuntimeProfile,
    registry: CampaignRuntimeExecutorRegistry,
    match: str,
) -> None:
    with pytest.raises(CampaignRuntimeProfileError, match=match):
        CampaignRuntimeProfileManager(profile, registry)


def test_tuning_projection_is_exhaustive_and_does_not_leak_between_runtimes() -> None:
    values: dict[RuntimeTuningKey, object] = dict.fromkeys(RuntimeTuningKey, 1)
    values[RuntimeTuningKey.CAMPAIGN_MODE] = "normal"
    values[RuntimeTuningKey.BOSS_APPEAR_REFOCUS_PRESET] = [-3, 0]
    values[RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER] = 0.5
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("tunings"),
        tunings=tuple(RuntimeTuning(key, value) for key, value in values.items()),
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
    manager.apply_runtime_tunings(runtime)

    assert len(config.overlays) == 1
    assert len(config.overlays[0]) == len(manager.config_overlay) + 2
    assert config.overlays[0]["Fleet_Fleet2"] == 1
    assert config.fleet_boss == 1
    assert config.overlays[0]["Submarine_Fleet"] == 1
    assert runtime.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD == 1.0
    assert runtime.MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD == 1.0
    assert runtime.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD == 1.0
    assert runtime.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD == 1.0
    assert untouched.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD == 0.0
    assert manager.boss_appear_refocus_preset == (-3, 0)
    assert manager.map_clear_percentage_multiplier == 0.5
    assert manager.combat_disable_stuck_detection_battle == 1
    assert other.config_overlay == {}
    assert other.boss_appear_refocus_preset is None
    assert other.map_clear_percentage_multiplier == 1.0


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
    compiled = CampaignMap("test")

    manager.install_map_grid(compiled)

    assert compiled.grid_class is _MapGrid
    assert manager.map_grid_class is _MapGrid
    assert manager.camera_grid_class is _CameraGrid


def test_lifecycle_distinguishes_fresh_and_resume_and_resets_session_state() -> None:
    traces: list[list[object]] = []

    def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        trace: list[object] = []
        traces.append(trace)
        return _LifecycleExecutor(
            frozenset(binding.kind for binding in context.bindings),
            trace,
            state_seed=RuntimeStateSeed(use_support_fleet=True),
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
    manager.begin_session(
        RuntimeSessionContext(
            CampaignRunVariant.NORMAL,
            0,
            RuntimeSessionEntryKind.FRESH,
        )
    )
    manager.disable_support_fleet()
    assert not manager.use_support_fleet(AbortToken())
    manager.end_session(RuntimeSessionOutcome.COMPLETED)
    manager.reset()

    other = CampaignRuntimeProfileManager(profile, registry)
    other.bind(_Runtime(), CampaignMap("other"))
    other.begin_session(
        RuntimeSessionContext(
            CampaignRunVariant.LOOP,
            3,
            RuntimeSessionEntryKind.RESUME,
        )
    )

    assert traces[0] == [
        "bind",
        ("begin", RuntimeSessionEntryKind.FRESH, 0),
        ("end", RuntimeSessionOutcome.COMPLETED),
        "reset",
    ]
    assert traces[1] == [
        "bind",
        ("begin", RuntimeSessionEntryKind.RESUME, 3),
    ]
    assert other.use_support_fleet(AbortToken())
