from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from module.adapters.campaign_runtime_tunings import (
    ConfiguredBossFleet,
    RuntimeTuningValidationError,
    compile_campaign_runtime_tuning_patch,
)
from module.base.failure import raise_cleanup_errors
from module.config.config import AzurLaneConfig
from module.content.errors import ContentValidationError
from module.content.runtime_profile import (
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
    RuntimeTuningValue,
)
from module.map.map_base import CampaignMap
from module.map.support_fleet import (
    SupportFleetAttemptState,
    SupportFleetStateSource,
    SupportFleetStatus,
)
from module.map_detection.grid import Grid
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.application import CancellationSource


class CampaignRuntimeProfileError(RuntimeError):
    """runtime profile 无法被固定生产适配器执行。"""


class RuntimeOperation(StrEnum):
    """旧地图引擎允许扩展的封闭调用面；值不是可反射的 Python 路径。"""

    EXPECTED_END = "expected_end"
    CLEAR_BOSS = "clear_boss"
    EQUIPMENT_TAKE_OFF_WHEN_FINISHED = "equipment_take_off_when_finished"
    HANDLE_CLEAR_MODE_CONFIG_COVER = "handle_clear_mode_config_cover"
    RUNTIME_CREATED = "runtime_created"


class RuntimeSessionOutcome(StrEnum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


type RuntimeFallback = Callable[..., object]
type RuntimeMethod = Callable[..., object]


class RuntimeProfileHost(Protocol):
    """manager 只依赖的固定 runtime 表面。"""

    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD: float
    MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD: float
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD: float


@dataclass(frozen=True, slots=True)
class RuntimeStateSeed:
    use_single_fleet_override: bool | None = None


@dataclass(slots=True)
class RuntimeSharedState:
    """同一 runtime profile 内跨 implementation 共享的显式 attempt 状态。"""

    support_fleet: SupportFleetAttemptState | None = None
    use_single_fleet_override: bool | None = None


_EMPTY_STATE_SEED = RuntimeStateSeed()


@dataclass(frozen=True, slots=True)
class RuntimeExecutorOptionsSchema:
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if any(not isinstance(name, str) or not name for name in self.required | self.optional):
            message = "runtime executor option names must be non-empty strings"
            raise TypeError(message)
        if self.required & self.optional:
            message = "runtime executor options cannot be both required and optional"
            raise ContentValidationError(message)

    def validate(
        self,
        implementation_id: RuntimeImplementationId,
        kind: RuntimeExecutorKind,
        options: Mapping[str, RuntimeTuningValue],
    ) -> None:
        names = set(options)
        missing = sorted(self.required - names)
        if missing:
            message = f"runtime executor {implementation_id.value}/{kind.value} is missing option: {missing[0]}"
            raise CampaignRuntimeProfileError(message)
        unknown = sorted(names - self.required - self.optional)
        if unknown:
            message = f"runtime executor {implementation_id.value}/{kind.value} has unknown option: {unknown[0]}"
            raise CampaignRuntimeProfileError(message)


@dataclass(frozen=True, slots=True)
class RuntimeExecutorBuildContext:
    extension_id: CampaignRuntimeExtensionId
    implementation_id: RuntimeImplementationId
    bindings: tuple[RuntimeExecutorBinding, ...]

    def options(self, kind: RuntimeExecutorKind) -> Mapping[str, RuntimeTuningValue]:
        matches = tuple(binding.options for binding in self.bindings if binding.kind is kind)
        if len(matches) != 1:
            message = f"runtime implementation {self.implementation_id.value} requires exactly one {kind.value} binding"
            raise CampaignRuntimeProfileError(message)
        return matches[0]


class RuntimeExecutorInstance:
    """单 session 的多 facet executor；同 implementation 的状态只能存在一份。"""

    __slots__ = (
        "_camera_grid_class",
        "_map_grid_class",
        "_methods",
        "_runtime",
        "_seed",
        "_shared_state",
        "_supported_kinds",
        "_use_single_fleet_override",
    )

    def __init__(
        self,
        supported_kinds: Iterable[RuntimeExecutorKind],
        *,
        methods: Mapping[RuntimeExecutorKind, Mapping[RuntimeOperation, RuntimeMethod]] | None = None,
        state_seed: RuntimeStateSeed = _EMPTY_STATE_SEED,
        map_grid_class: type[GridInfo] | None = None,
        camera_grid_class: type[Grid] | None = None,
    ) -> None:
        kinds = frozenset(supported_kinds)
        if not kinds or any(not isinstance(kind, RuntimeExecutorKind) for kind in kinds):
            message = "runtime executor instance requires typed supported kinds"
            raise TypeError(message)
        values = {} if methods is None else dict(methods)
        if set(values) - kinds:
            message = "runtime executor instance contains methods for an unsupported kind"
            raise ContentValidationError(message)
        frozen_methods: dict[RuntimeExecutorKind, Mapping[RuntimeOperation, RuntimeMethod]] = {}
        for kind, facet in values.items():
            facet_methods = dict(facet)
            if any(
                not isinstance(operation, RuntimeOperation) or not callable(method)
                for operation, method in facet_methods.items()
            ):
                message = "runtime executor methods must use typed operations and callables"
                raise TypeError(message)
            frozen_methods[kind] = MappingProxyType(facet_methods)
        if map_grid_class is not None and not issubclass(map_grid_class, GridInfo):
            message = "map grid executor must provide a GridInfo subclass"
            raise TypeError(message)
        if camera_grid_class is not None and not issubclass(camera_grid_class, Grid):
            message = "camera grid executor must provide a Grid subclass"
            raise TypeError(message)
        self._supported_kinds = kinds
        self._methods = MappingProxyType(frozen_methods)
        self._seed = state_seed
        self._map_grid_class = map_grid_class
        self._camera_grid_class = camera_grid_class
        self._runtime: object | None = None
        self._shared_state: RuntimeSharedState | None = None
        self._use_single_fleet_override = state_seed.use_single_fleet_override

    @property
    def supported_kinds(self) -> frozenset[RuntimeExecutorKind]:
        return self._supported_kinds

    @property
    def map_grid_class(self) -> type[GridInfo] | None:
        return self._map_grid_class

    @property
    def camera_grid_class(self) -> type[Grid] | None:
        return self._camera_grid_class

    def method(
        self,
        kind: RuntimeExecutorKind,
        operation: RuntimeOperation,
    ) -> RuntimeMethod | None:
        return self._methods.get(kind, {}).get(operation)

    @property
    def state_seed(self) -> RuntimeStateSeed:
        return self._seed

    def attach_shared_state(self, state: RuntimeSharedState) -> None:
        if not isinstance(state, RuntimeSharedState):
            message = "runtime executor shared state must be RuntimeSharedState"
            raise TypeError(message)
        if self._shared_state is not None:
            message = "runtime executor shared state is already attached"
            raise CampaignRuntimeProfileError(message)
        self._shared_state = state

    def bind(self, runtime: object, compiled_map: CampaignMap) -> None:
        del compiled_map
        if self._runtime is not None:
            message = "runtime executor instance is already bound"
            raise CampaignRuntimeProfileError(message)
        self._runtime = runtime

    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        if self._runtime is None:
            message = "runtime executor must be bound before end_session"
            raise CampaignRuntimeProfileError(message)
        del outcome

    def reset(self) -> None:
        self._runtime = None
        self._use_single_fleet_override = self._seed.use_single_fleet_override

    def use_single_fleet_override(self) -> bool | None:
        if self._use_single_fleet_override is not None and self._shared_state is not None:
            return self._shared_state.use_single_fleet_override
        return self._use_single_fleet_override

    def current_use_support_fleet(self) -> bool:
        state = self._shared_state
        if state is None:
            message = "runtime executor shared state is not attached"
            raise CampaignRuntimeProfileError(message)
        support_fleet = state.support_fleet
        return support_fleet is not None and support_fleet.available

    def current_support_fleet_status(self) -> SupportFleetStatus | None:
        state = self._shared_state
        if state is None:
            message = "runtime executor shared state is not attached"
            raise CampaignRuntimeProfileError(message)
        support_fleet = state.support_fleet
        return None if support_fleet is None else support_fleet.status

    def current_use_single_fleet_override(self) -> bool | None:
        state = self._shared_state
        if state is None:
            message = "runtime executor shared state is not attached"
            raise CampaignRuntimeProfileError(message)
        return state.use_single_fleet_override

    def set_use_single_fleet_override(self, *, enabled: bool) -> None:
        if type(enabled) is not bool:
            message = "use_single_fleet_override state must be a boolean"
            raise TypeError(message)
        if self._use_single_fleet_override is None:
            message = "runtime executor does not own use_single_fleet_override state"
            raise CampaignRuntimeProfileError(message)
        self._use_single_fleet_override = enabled
        if self._shared_state is not None:
            self._shared_state.use_single_fleet_override = enabled


type RuntimeExecutorFactory = Callable[[RuntimeExecutorBuildContext], RuntimeExecutorInstance]


@dataclass(frozen=True, slots=True)
class RuntimeExecutorFactoryDescriptor:
    implementation_id: RuntimeImplementationId
    option_schemas: Mapping[RuntimeExecutorKind, RuntimeExecutorOptionsSchema]
    factory: RuntimeExecutorFactory

    def __post_init__(self) -> None:
        if not isinstance(self.implementation_id, RuntimeImplementationId):
            message = "runtime implementation id must be a RuntimeImplementationId"
            raise TypeError(message)
        schemas = dict(self.option_schemas)
        if not schemas or any(
            not isinstance(kind, RuntimeExecutorKind) or not isinstance(schema, RuntimeExecutorOptionsSchema)
            for kind, schema in schemas.items()
        ):
            message = "runtime executor descriptor requires typed option schemas"
            raise TypeError(message)
        if not callable(self.factory):
            message = "runtime executor descriptor factory must be callable"
            raise TypeError(message)
        object.__setattr__(self, "option_schemas", MappingProxyType(schemas))

    def create(self, context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
        provided = frozenset(binding.kind for binding in context.bindings)
        supported = frozenset(self.option_schemas)
        unknown = sorted(kind.value for kind in provided - supported)
        if unknown:
            message = (
                f"runtime implementation {self.implementation_id.value} does not support executor kind: {unknown[0]}"
            )
            raise CampaignRuntimeProfileError(message)
        for binding in context.bindings:
            self.option_schemas[binding.kind].validate(
                self.implementation_id,
                binding.kind,
                binding.options,
            )
        instance = self.factory(context)
        if not isinstance(instance, RuntimeExecutorInstance):
            message = f"runtime implementation factory returned an invalid instance: {self.implementation_id.value}"
            raise TypeError(message)
        if not provided <= instance.supported_kinds:
            missing = sorted(kind.value for kind in provided - instance.supported_kinds)
            message = (
                f"runtime implementation {self.implementation_id.value} instance "
                f"does not expose executor kind: {missing[0]}"
            )
            raise CampaignRuntimeProfileError(message)
        return instance


class CampaignRuntimeExecutorRegistry:
    """显式 implementation id 到多 facet factory 的封闭注册表。"""

    __slots__ = ("_descriptors",)

    def __init__(self, descriptors: Iterable[RuntimeExecutorFactoryDescriptor]) -> None:
        values: dict[RuntimeImplementationId, RuntimeExecutorFactoryDescriptor] = {}
        for descriptor in descriptors:
            if not isinstance(descriptor, RuntimeExecutorFactoryDescriptor):
                message = "runtime executor registry contains an invalid descriptor"
                raise TypeError(message)
            if descriptor.implementation_id in values:
                message = f"duplicate runtime executor implementation: {descriptor.implementation_id.value}"
                raise ContentValidationError(message)
            values[descriptor.implementation_id] = descriptor
        self._descriptors = MappingProxyType(values)

    def resolve(
        self,
        implementation_id: RuntimeImplementationId,
    ) -> RuntimeExecutorFactoryDescriptor:
        if not isinstance(implementation_id, RuntimeImplementationId):
            message = "runtime executor resolution requires a RuntimeImplementationId"
            raise TypeError(message)
        try:
            return self._descriptors[implementation_id]
        except KeyError:
            message = f"unregistered runtime executor implementation: {implementation_id.value}"
            raise CampaignRuntimeProfileError(message) from None

    @property
    def descriptors(
        self,
    ) -> Mapping[RuntimeImplementationId, RuntimeExecutorFactoryDescriptor]:
        return self._descriptors


@dataclass(frozen=True, slots=True)
class _SessionFacet:
    binding: RuntimeExecutorBinding
    instance: RuntimeExecutorInstance


@dataclass(slots=True)
class _InvocationFrame:
    kind: RuntimeExecutorKind
    operation: RuntimeOperation
    runtime: object
    chain: tuple[_SessionFacet, ...]
    next_index: int
    fallback: RuntimeFallback


@dataclass(frozen=True, slots=True)
class _RuntimeInvocationRequest:
    kind: RuntimeExecutorKind
    operation: RuntimeOperation
    runtime: object
    fallback: RuntimeFallback
    args: tuple[object, ...]
    kwargs: Mapping[str, object]


class RuntimeFacetComposite:
    """一个细粒度 executor kind 的 base→derived around 链入口。"""

    __slots__ = ("_kind", "_manager")

    def __init__(
        self,
        manager: CampaignRuntimeProfileManager,
        kind: RuntimeExecutorKind,
    ) -> None:
        self._manager = manager
        self._kind = kind

    @property
    def kind(self) -> RuntimeExecutorKind:
        return self._kind

    def invoke(
        self,
        operation: RuntimeOperation,
        runtime: object,
        fallback: RuntimeFallback,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self._manager.invoke_facet(
            _RuntimeInvocationRequest(
                self._kind,
                operation,
                runtime,
                fallback,
                args,
                kwargs,
            )
        )


def _resolve_support_fleet_state(
    instances: Iterable[RuntimeExecutorInstance],
) -> SupportFleetAttemptState | None:
    sources = [instance for instance in instances if isinstance(instance, SupportFleetStateSource)]
    if len(sources) > 1:
        message = "runtime profile accepts at most one support fleet state source"
        raise CampaignRuntimeProfileError(message)
    if not sources:
        return None
    state = sources[0].support_fleet_state
    if not isinstance(state, SupportFleetAttemptState):
        message = "support fleet state source must provide SupportFleetAttemptState"
        raise CampaignRuntimeProfileError(message)
    return state


class CampaignRuntimeProfileManager:
    """把不可变 profile 编译为单 attempt 多 facet executor 链和 tuning 投影。"""

    __slots__ = (
        "_compiled_map",
        "_facets",
        "_frames",
        "_instances",
        "_profile",
        "_registry",
        "_runtime",
        "_session_active",
        "_shared_state",
        "_tuning_patch",
    )

    def __init__(
        self,
        profile: CampaignRuntimeProfile,
        registry: CampaignRuntimeExecutorRegistry,
    ) -> None:
        if not isinstance(profile, CampaignRuntimeProfile):
            message = "runtime profile manager requires a CampaignRuntimeProfile"
            raise TypeError(message)
        if not isinstance(registry, CampaignRuntimeExecutorRegistry):
            message = "runtime profile manager requires a CampaignRuntimeExecutorRegistry"
            raise TypeError(message)
        self._profile = profile
        self._registry = registry
        self._instances, self._facets = self._build_instances(profile, registry)
        self._shared_state = RuntimeSharedState(support_fleet=_resolve_support_fleet_state(self._instances))
        for instance in self._instances:
            instance.attach_shared_state(self._shared_state)
        self._seed_attempt_state()
        self._frames: list[_InvocationFrame] = []
        self._runtime: object | None = None
        self._compiled_map: CampaignMap | None = None
        self._session_active = False
        try:
            self._tuning_patch = compile_campaign_runtime_tuning_patch(profile.tunings)
        except (RuntimeTuningValidationError, TypeError, ValueError) as error:
            raise CampaignRuntimeProfileError(str(error)) from error
        self._validate_grid_contracts()

    @staticmethod
    def _build_instances(
        profile: CampaignRuntimeProfile,
        registry: CampaignRuntimeExecutorRegistry,
    ) -> tuple[tuple[RuntimeExecutorInstance, ...], tuple[_SessionFacet, ...]]:
        instances: list[RuntimeExecutorInstance] = []
        facets: list[_SessionFacet] = []
        for extension in profile.extensions:
            grouped: dict[RuntimeImplementationId, list[RuntimeExecutorBinding]] = {}
            for binding in extension.executors:
                grouped.setdefault(binding.implementation_id, []).append(binding)
            for implementation_id, bindings in grouped.items():
                if len({binding.kind for binding in bindings}) != len(bindings):
                    message = (
                        f"runtime extension {extension.extension_id.value} repeats an executor kind "
                        f"for implementation {implementation_id.value}"
                    )
                    raise CampaignRuntimeProfileError(message)
                context = RuntimeExecutorBuildContext(
                    extension.extension_id,
                    implementation_id,
                    tuple(bindings),
                )
                instance = registry.resolve(implementation_id).create(context)
                instances.append(instance)
                facets.extend(_SessionFacet(binding, instance) for binding in bindings)
        return tuple(instances), tuple(facets)

    def _validate_grid_contracts(self) -> None:
        _ = self.map_grid_class
        _ = self.camera_grid_class

    @property
    def profile(self) -> CampaignRuntimeProfile:
        return self._profile

    def facet(self, kind: RuntimeExecutorKind) -> RuntimeFacetComposite:
        if not isinstance(kind, RuntimeExecutorKind):
            message = "runtime facet requires a RuntimeExecutorKind"
            raise TypeError(message)
        return RuntimeFacetComposite(self, kind)

    @property
    def mechanic(self) -> RuntimeFacetComposite:
        return self.facet(RuntimeExecutorKind.MAP_MECHANIC)

    @property
    def hard(self) -> RuntimeFacetComposite:
        return self.facet(RuntimeExecutorKind.HARD_MODE)

    @property
    def engine(self) -> RuntimeFacetComposite:
        return self.facet(RuntimeExecutorKind.ENGINE_EXTENSION)

    def executor_instance(self, kind: RuntimeExecutorKind) -> RuntimeExecutorInstance | None:
        """返回由 profile 编译出的唯一 typed executor。"""

        values = self.executor_instances(kind)
        if len(values) > 1:
            message = f"runtime profile contains more than one {kind.value} executor"
            raise CampaignRuntimeProfileError(message)
        return None if not values else values[0]

    def executor_instances(self, kind: RuntimeExecutorKind) -> tuple[RuntimeExecutorInstance, ...]:
        """按 profile 声明顺序返回一个 kind 的全部已编译 executor。"""

        if not isinstance(kind, RuntimeExecutorKind):
            message = "runtime executor lookup requires a RuntimeExecutorKind"
            raise TypeError(message)
        return tuple(facet.instance for facet in self._facets if facet.binding.kind is kind)

    def executor_instances_in_profile_order(self) -> tuple[RuntimeExecutorInstance, ...]:
        """返回不可变的全部 executor；顺序与 profile 声明一致。"""

        return self._instances

    def apply_config(self, config: AzurLaneConfig) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "runtime profile config projection requires AzurLaneConfig"
            raise TypeError(message)
        overlay = self._tuning_patch.config.to_overrides()
        if overlay:
            config.apply_runtime_overlay(**overlay)

    @property
    def configured_boss_fleet(self) -> ConfiguredBossFleet | None:
        return self._tuning_patch.config.configured_boss_fleet

    def install_map_grid(self, compiled_map: CampaignMap) -> None:
        if not isinstance(compiled_map, CampaignMap):
            message = "runtime profile map grid installation requires CampaignMap"
            raise TypeError(message)
        grid_class = self.map_grid_class
        if grid_class is not None:
            compiled_map.grid_class = grid_class

    @property
    def map_grid_class(self) -> type[GridInfo] | None:
        values = tuple(
            facet.instance.map_grid_class
            for facet in self._facets
            if facet.binding.kind is RuntimeExecutorKind.MAP_GRID_RECOGNITION
            and facet.instance.map_grid_class is not None
        )
        if len(values) > 1:
            message = "runtime profile contains more than one effective map grid executor"
            raise CampaignRuntimeProfileError(message)
        return None if not values else values[0]

    @property
    def camera_grid_class(self) -> type[Grid] | None:
        values = tuple(
            facet.instance.camera_grid_class
            for facet in self._facets
            if facet.binding.kind is RuntimeExecutorKind.CAMERA_GRID_RECOGNITION
            and facet.instance.camera_grid_class is not None
        )
        if len(values) > 1:
            message = "runtime profile contains more than one effective camera grid executor"
            raise CampaignRuntimeProfileError(message)
        return None if not values else values[0]

    def bind(self, runtime: object, compiled_map: CampaignMap) -> None:
        if self._runtime is not None or self._compiled_map is not None:
            message = "runtime profile manager is already bound"
            raise CampaignRuntimeProfileError(message)
        if not isinstance(compiled_map, CampaignMap):
            message = "runtime profile binding requires CampaignMap"
            raise TypeError(message)
        self._runtime = runtime
        self._compiled_map = compiled_map
        for instance in self._instances:
            instance.bind(runtime, compiled_map)
        self.runtime_created(runtime)

    def begin_session(self) -> None:
        if self._runtime is None:
            message = "runtime profile manager must be bound before begin_session"
            raise CampaignRuntimeProfileError(message)
        if self._session_active:
            message = "runtime profile manager already has an active session"
            raise CampaignRuntimeProfileError(message)
        # 支援舰队允许 READY 阶段反复观察；session 一旦开始，后续消费者只能读取封存事实。
        support_fleet = self._shared_state.support_fleet
        if support_fleet is not None:
            support_fleet.seal()
        self._session_active = True

    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        if not self._session_active:
            message = "runtime profile manager has no active session"
            raise CampaignRuntimeProfileError(message)
        if not isinstance(outcome, RuntimeSessionOutcome):
            message = "runtime profile end_session requires RuntimeSessionOutcome"
            raise TypeError(message)
        # manager 先放弃 active ownership，避免任一 executor 失败后留下可复用的半关闭会话。
        self._session_active = False
        errors: list[BaseException] = []
        for instance in reversed(self._instances):
            try:
                instance.end_session(outcome)
            except BaseException as error:  # ruff:ignore[blind-except] - 各 executor 必须独立结束。
                errors.append(error)
        raise_cleanup_errors(errors, message="runtime profile session cleanup failed")

    def reset(self) -> None:
        if self._session_active:
            message = "runtime profile manager cannot reset an active session"
            raise CampaignRuntimeProfileError(message)
        # ownership 状态先失效；executor reset 即使失败也不能让 manager 再次参与执行。
        self._runtime = None
        self._compiled_map = None
        self._frames.clear()
        errors: list[BaseException] = []
        for instance in reversed(self._instances):
            try:
                instance.reset()
            except BaseException as error:  # ruff:ignore[blind-except] - 各 executor 必须独立重置。
                errors.append(error)
        self._seed_attempt_state()
        raise_cleanup_errors(errors, message="runtime profile reset failed")

    def apply_runtime_thresholds(self, runtime: RuntimeProfileHost) -> None:
        thresholds = self._tuning_patch.thresholds
        if thresholds.air_raid_overlay_transparency is not None:
            runtime.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = thresholds.air_raid_overlay_transparency
        if thresholds.ambush_overlay_transparency is not None:
            runtime.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD = thresholds.ambush_overlay_transparency
        if thresholds.enemy_searching_overlay_transparency is not None:
            runtime.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = thresholds.enemy_searching_overlay_transparency

    @property
    def boss_appear_refocus_preset(self) -> tuple[int, int] | None:
        return self._tuning_patch.behavior.boss_appear_refocus_preset

    @property
    def map_clear_percentage_multiplier(self) -> float:
        value = self._tuning_patch.behavior.map_clear_percentage_multiplier
        return 1.0 if value is None else value

    @property
    def combat_disable_stuck_detection_battle(self) -> int | None:
        return self._tuning_patch.behavior.combat_disable_stuck_detection_battle

    def use_support_fleet(self, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        support_fleet = self._shared_state.support_fleet
        return support_fleet is not None and support_fleet.available

    def support_fleet_status(
        self,
        cancellation: CancellationSource,
    ) -> SupportFleetStatus | None:
        cancellation.raise_if_requested()
        support_fleet = self._shared_state.support_fleet
        return None if support_fleet is None else support_fleet.status

    def use_single_fleet_override(self, cancellation: CancellationSource) -> bool | None:
        cancellation.raise_if_requested()
        return self._shared_state.use_single_fleet_override

    def _seed_attempt_state(self) -> None:
        use_single_fleet_override: bool | None = None
        for instance in self._instances:
            seed = instance.state_seed
            if seed.use_single_fleet_override is not None:
                use_single_fleet_override = seed.use_single_fleet_override
        self._shared_state.use_single_fleet_override = use_single_fleet_override

    def invoke_super(
        self,
        operation: RuntimeOperation,
        runtime: object,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        if not self._frames:
            message = "runtime super invocation requires an active executor frame"
            raise CampaignRuntimeProfileError(message)
        frame = self._frames[-1]
        if frame.operation is not operation or frame.runtime is not runtime:
            message = "runtime super invocation does not match the active executor frame"
            raise CampaignRuntimeProfileError(message)
        return self._invoke_at(
            _InvocationFrame(
                frame.kind,
                frame.operation,
                frame.runtime,
                frame.chain,
                frame.next_index,
                frame.fallback,
            ),
            args,
            kwargs,
        )

    def runtime_created(self, runtime: object) -> None:
        for kind in (
            RuntimeExecutorKind.MAP_MECHANIC,
            RuntimeExecutorKind.HARD_MODE,
            RuntimeExecutorKind.ENGINE_EXTENSION,
        ):
            result = self.invoke_facet(
                _RuntimeInvocationRequest(
                    kind,
                    RuntimeOperation.RUNTIME_CREATED,
                    runtime,
                    lambda: None,
                    (),
                    {},
                )
            )
            if result is not None:
                message = "runtime_created executor chain must return None"
                raise CampaignRuntimeProfileError(message)

    def invoke_facet(self, request: _RuntimeInvocationRequest) -> object:
        if not isinstance(request, _RuntimeInvocationRequest):
            message = "runtime invocation requires a typed request"
            raise TypeError(message)
        if not isinstance(request.operation, RuntimeOperation):
            message = "runtime invocation requires a RuntimeOperation"
            raise TypeError(message)
        if not callable(request.fallback):
            message = "runtime invocation fallback must be callable"
            raise TypeError(message)
        chain = tuple(
            facet
            for facet in self._facets
            if facet.binding.kind is request.kind and facet.instance.method(request.kind, request.operation) is not None
        )
        return self._invoke_at(
            _InvocationFrame(
                request.kind,
                request.operation,
                request.runtime,
                chain,
                len(chain) - 1,
                request.fallback,
            ),
            request.args,
            request.kwargs,
        )

    def _invoke_at(
        self,
        frame: _InvocationFrame,
        args: tuple[object, ...],
        kwargs: Mapping[str, object],
    ) -> object:
        if frame.next_index < 0:
            return frame.fallback(*args, **dict(kwargs))
        facet = frame.chain[frame.next_index]
        method = facet.instance.method(frame.kind, frame.operation)
        if method is None:
            message = "runtime executor chain contains an operation gap"
            raise AssertionError(message)
        active = _InvocationFrame(
            frame.kind,
            frame.operation,
            frame.runtime,
            frame.chain,
            frame.next_index - 1,
            frame.fallback,
        )
        self._frames.append(active)
        try:
            return method(frame.runtime, *args, **dict(kwargs))
        finally:
            popped = self._frames.pop()
            if popped is not active:
                message = "runtime executor frame stack was corrupted"
                raise AssertionError(message)
