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


class RuntimeSessionOutcome(StrEnum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


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
        state_seed: RuntimeStateSeed = _EMPTY_STATE_SEED,
        map_grid_class: type[GridInfo] | None = None,
        camera_grid_class: type[Grid] | None = None,
    ) -> None:
        kinds = frozenset(supported_kinds)
        if not kinds or any(not isinstance(kind, RuntimeExecutorKind) for kind in kinds):
            message = "runtime executor instance requires typed supported kinds"
            raise TypeError(message)
        if map_grid_class is not None and not issubclass(map_grid_class, GridInfo):
            message = "map grid executor must provide a GridInfo subclass"
            raise TypeError(message)
        if camera_grid_class is not None and not issubclass(camera_grid_class, Grid):
            message = "camera grid executor must provide a Grid subclass"
            raise TypeError(message)
        self._supported_kinds = kinds
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
    """把不可变 profile 编译为单 attempt typed executor 集合和 tuning 投影。"""

    __slots__ = (
        "_compiled_map",
        "_facets",
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
