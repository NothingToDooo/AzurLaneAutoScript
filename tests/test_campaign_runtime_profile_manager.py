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
from module.adapters.campaign_runtime_session import RuntimeProfileLease, RuntimeProfileLeaseState
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

    @override
    def apply_runtime_overlay(self, **kwargs: Unpack[ConfigOverrides]) -> None:
        self.overlays.append(dict(kwargs))


class _Runtime:
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = 0.0
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


class _CleanupFailingLifecycleExecutor(_LifecycleExecutor):
    def __init__(
        self,
        trace: list[object],
        *,
        end_error: BaseException,
        reset_error: BaseException,
    ) -> None:
        super().__init__(frozenset({RuntimeExecutorKind.MAP_MECHANIC}), trace)
        self._end_error = end_error
        self._reset_error = reset_error

    @override
    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        super().end_session(outcome)
        raise self._end_error

    @override
    def reset(self) -> None:
        super().reset()
        raise self._reset_error


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
    operation = RuntimeOperation.CLEAR_BOSS
    called: list[str] = []

    def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        name = context.implementation_id.value

        def method(runtime: object) -> object:
            del runtime
            called.append(name)
            return None

        return RuntimeExecutorInstance(
            {RuntimeExecutorKind.MAP_MECHANIC},
            methods={RuntimeExecutorKind.MAP_MECHANIC: {operation: method}},
        )

    schemas = {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()}
    manager = CampaignRuntimeProfileManager(
        _profile(
            _extension("base", _binding("base", RuntimeExecutorKind.MAP_MECHANIC)),
            _extension(
                "derived",
                _binding("derived", RuntimeExecutorKind.MAP_MECHANIC),
            ),
        ),
        CampaignRuntimeExecutorRegistry(
            (
                _descriptor("base", schemas, factory),
                _descriptor("derived", schemas, factory),
            )
        ),
    )

    manager.mechanic.invoke(operation, object(), lambda: called.append("fallback"))

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


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        (RuntimeTuningKey.FLEET_2, 1.0, "fleet_2 must be an integer"),
        (RuntimeTuningKey.FLEET_BOSS, 0, "fleet_boss must be 1 or 2"),
        (RuntimeTuningKey.FLEET_BOSS, 3, "fleet_boss must be 1 or 2"),
        (
            RuntimeTuningKey.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD,
            "bright",
            "map_air_raid_overlay_transparency_threshold must be a number",
        ),
        (
            RuntimeTuningKey.BOSS_APPEAR_REFOCUS_PRESET,
            (1,),
            "boss_appear_refocus_preset must contain two integers",
        ),
        (
            RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER,
            True,
            "map_clear_percentage_multiplier must be a number",
        ),
        (
            RuntimeTuningKey.COMBAT_DISABLE_STUCK_DETECTION_BATTLE,
            1.0,
            "combat_disable_stuck_detection_battle must be an integer",
        ),
    ],
)
def test_invalid_tuning_projection_fails_during_manager_construction(
    key: RuntimeTuningKey,
    value: object,
    match: str,
) -> None:
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("invalid_tuning"),
        tunings=(RuntimeTuning(key, value),),
    )

    with pytest.raises(CampaignRuntimeProfileError, match=match):
        CampaignRuntimeProfileManager(profile, CampaignRuntimeExecutorRegistry(()))


@pytest.mark.parametrize(
    ("kind", "match"),
    [
        (RuntimeExecutorKind.MAP_GRID_RECOGNITION, "more than one effective map grid executor"),
        (RuntimeExecutorKind.CAMERA_GRID_RECOGNITION, "more than one effective camera grid executor"),
    ],
)
def test_effective_grid_executor_conflict_fails_during_manager_construction(
    kind: RuntimeExecutorKind,
    match: str,
) -> None:
    def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        del context
        if kind is RuntimeExecutorKind.MAP_GRID_RECOGNITION:
            return RuntimeExecutorInstance({kind}, map_grid_class=_MapGrid)
        return RuntimeExecutorInstance({kind}, camera_grid_class=_CameraGrid)

    profile = _profile(
        _extension("first", _binding("first", kind)),
        _extension("second", _binding("second", kind)),
    )
    registry = CampaignRuntimeExecutorRegistry(
        (
            _descriptor("first", {kind: RuntimeExecutorOptionsSchema()}, factory),
            _descriptor("second", {kind: RuntimeExecutorOptionsSchema()}, factory),
        )
    )

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
    assert config.overlays[0]["Fleet_Fleet2"] == 1
    assert config.overlays[0]["Submarine_Fleet"] == 1
    assert manager.configured_boss_fleet == 1
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
    compiled = CampaignMap("test")

    manager.install_map_grid(compiled)

    assert compiled.grid_class is _MapGrid
    assert manager.map_grid_class is _MapGrid
    assert manager.camera_grid_class is _CameraGrid


def test_lifecycle_distinguishes_fresh_and_resume_and_new_manager_reseeds_state() -> None:
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
    manager.begin_session(
        RuntimeSessionContext(
            CampaignRunVariant.NORMAL,
            0,
            RuntimeSessionEntryKind.FRESH,
        )
    )
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
    assert not other.use_support_fleet(AbortToken())


def test_lease_rolls_back_a_partially_started_real_profile_in_reverse_order() -> None:
    trace: list[tuple[str, str]] = []
    begin_error = RuntimeError("second begin failed")

    class _BeginExecutor(RuntimeExecutorInstance):
        def __init__(self, label: str, *, fail: bool) -> None:
            super().__init__({RuntimeExecutorKind.MAP_MECHANIC})
            self._label = label
            self._fail = fail

        @override
        def bind(self, runtime: object, compiled_map: CampaignMap) -> None:
            super().bind(runtime, compiled_map)
            trace.append((self._label, "bind"))

        @override
        def begin_session(self, context: RuntimeSessionContext) -> None:
            super().begin_session(context)
            trace.append((self._label, "begin"))
            if self._fail:
                raise begin_error

        @override
        def reset(self) -> None:
            super().reset()
            trace.append((self._label, "reset"))

    def executor_factory(label: str, *, fail: bool) -> RuntimeExecutorFactory:
        def factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
            del context
            return _BeginExecutor(label, fail=fail)

        return factory

    schema = {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()}
    manager = CampaignRuntimeProfileManager(
        _profile(
            _extension("first", _binding("first", RuntimeExecutorKind.MAP_MECHANIC)),
            _extension("second", _binding("second", RuntimeExecutorKind.MAP_MECHANIC)),
        ),
        CampaignRuntimeExecutorRegistry(
            (
                _descriptor("first", schema, executor_factory("first", fail=False)),
                _descriptor("second", schema, executor_factory("second", fail=True)),
            )
        ),
    )
    manager.bind(_Runtime(), CampaignMap("partial-begin"))
    lease = RuntimeProfileLease(manager)

    with pytest.raises(RuntimeError) as raised:
        lease.start(
            RuntimeSessionContext(
                CampaignRunVariant.NORMAL,
                0,
                RuntimeSessionEntryKind.FRESH,
            )
        )

    assert raised.value is begin_error
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    assert trace == [
        ("first", "bind"),
        ("second", "bind"),
        ("first", "begin"),
        ("second", "begin"),
        ("second", "reset"),
        ("first", "reset"),
    ]


def test_lifecycle_attempts_every_executor_cleanup_and_poison_manager() -> None:
    first_trace: list[object] = []
    second_trace: list[object] = []
    first_end_error = RuntimeError("first end failed")
    second_end_error = OSError("second end failed")
    first_reset_error = RuntimeError("first reset failed")
    second_reset_error = OSError("second reset failed")

    def first_factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        del context
        return _CleanupFailingLifecycleExecutor(
            first_trace,
            end_error=first_end_error,
            reset_error=first_reset_error,
        )

    def second_factory(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        del context
        return _CleanupFailingLifecycleExecutor(
            second_trace,
            end_error=second_end_error,
            reset_error=second_reset_error,
        )

    schema = {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()}
    manager = CampaignRuntimeProfileManager(
        _profile(
            _extension("first", _binding("first", RuntimeExecutorKind.MAP_MECHANIC)),
            _extension("second", _binding("second", RuntimeExecutorKind.MAP_MECHANIC)),
        ),
        CampaignRuntimeExecutorRegistry(
            (
                _descriptor("first", schema, first_factory),
                _descriptor("second", schema, second_factory),
            )
        ),
    )
    manager.bind(_Runtime(), CampaignMap("cleanup-failure"))
    context = RuntimeSessionContext(
        CampaignRunVariant.NORMAL,
        0,
        RuntimeSessionEntryKind.FRESH,
    )
    manager.begin_session(context)

    with pytest.raises(ExceptionGroup) as end_raised:
        manager.end_session(RuntimeSessionOutcome.FAILED)

    assert end_raised.value.exceptions == (second_end_error, first_end_error)

    with pytest.raises(ExceptionGroup) as reset_raised:
        manager.reset()

    assert reset_raised.value.exceptions == (second_reset_error, first_reset_error)
    assert first_trace == [
        "bind",
        ("begin", RuntimeSessionEntryKind.FRESH, 0),
        ("end", RuntimeSessionOutcome.FAILED),
        "reset",
    ]
    assert second_trace == first_trace
    with pytest.raises(CampaignRuntimeProfileError, match="must be bound"):
        manager.begin_session(context)
