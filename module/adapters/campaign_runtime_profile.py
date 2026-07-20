from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast

from module.base.failure import raise_cleanup_errors
from module.config.config import AzurLaneConfig
from module.content.campaign_session import CampaignRunVariant
from module.content.errors import ContentValidationError
from module.content.runtime_profile import (
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
    RuntimeTuningKey,
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
    from module.config.config_generated import ConfigOverrides


class CampaignRuntimeProfileError(RuntimeError):
    """runtime profile 无法被固定生产适配器执行。"""


class RuntimeOperation(StrEnum):
    """旧地图引擎允许扩展的封闭调用面；值不是可反射的 Python 路径。"""

    EXPECTED_END = "expected_end"
    CLEAR_BOSS = "clear_boss"
    EQUIPMENT_TAKE_OFF_WHEN_FINISHED = "equipment_take_off_when_finished"
    HANDLE_CLEAR_MODE_CONFIG_COVER = "handle_clear_mode_config_cover"
    MAP_DATA_INIT = "map_data_init"
    MAP_INIT = "map_init"
    RUNTIME_CREATED = "runtime_created"


class RuntimeSessionEntryKind(StrEnum):
    FRESH = "fresh"
    RESUME = "resume"


class RuntimeSessionOutcome(StrEnum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeSessionContext:
    variant: CampaignRunVariant
    battle_index: int
    entry_kind: RuntimeSessionEntryKind

    def __post_init__(self) -> None:
        if not isinstance(self.variant, CampaignRunVariant):
            message = "runtime session variant must be a CampaignRunVariant"
            raise TypeError(message)
        if type(self.battle_index) is not int or self.battle_index < 0:
            message = "runtime session battle_index must be a non-negative integer"
            raise ValueError(message)
        if not isinstance(self.entry_kind, RuntimeSessionEntryKind):
            message = "runtime session entry_kind must be a RuntimeSessionEntryKind"
            raise TypeError(message)


type RuntimeFallback = Callable[..., object]
type RuntimeMethod = Callable[..., object]


class RuntimeProfileHost(Protocol):
    """manager 只依赖的固定 runtime 表面。"""

    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD: float
    MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD: float
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

    def begin_session(self, context: RuntimeSessionContext) -> None:
        if self._runtime is None:
            message = "runtime executor must be bound before begin_session"
            raise CampaignRuntimeProfileError(message)
        del context

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


_CONFIG_TUNING_FIELDS: Mapping[RuntimeTuningKey, str] = MappingProxyType(
    {
        RuntimeTuningKey.CAMPAIGN_MODE: "Campaign_Mode",
        RuntimeTuningKey.COINCIDENT_POINT_ENCOURAGE_DISTANCE: "COINCIDENT_POINT_ENCOURAGE_DISTANCE",
        RuntimeTuningKey.DETECTION_BACKEND: "DETECTION_BACKEND",
        RuntimeTuningKey.DISTANCE_POINT_X_RANGE: "DISTANCE_POINT_X_RANGE",
        RuntimeTuningKey.HOMO_EDGE_COLOR_RANGE: "HOMO_EDGE_COLOR_RANGE",
        RuntimeTuningKey.HOMO_EDGE_HOUGHLINES_THRESHOLD: "HOMO_EDGE_HOUGHLINES_THRESHOLD",
        RuntimeTuningKey.HOMO_CANNY_THRESHOLD: "HOMO_CANNY_THRESHOLD",
        RuntimeTuningKey.HOMO_CENTER_OFFSET: "HOMO_CENTER_OFFSET",
        RuntimeTuningKey.HOMO_TILE: "HOMO_TILE",
        RuntimeTuningKey.INTERNAL_LINES_FIND_PEAKS_PARAMETERS: "INTERNAL_LINES_FIND_PEAKS_PARAMETERS",
        RuntimeTuningKey.INTERNAL_LINES_HOUGHLINES_THRESHOLD: "INTERNAL_LINES_HOUGHLINES_THRESHOLD",
        RuntimeTuningKey.EDGE_LINES_FIND_PEAKS_PARAMETERS: "EDGE_LINES_FIND_PEAKS_PARAMETERS",
        RuntimeTuningKey.EDGE_LINES_HOUGHLINES_THRESHOLD: "EDGE_LINES_HOUGHLINES_THRESHOLD",
        RuntimeTuningKey.GRID_IMAGE_A_MULTIPLY: "GRID_IMAGE_A_MULTIPLY",
        RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_SHORT: "MAP_CLEAR_PERCENTAGE_SHORT",
        RuntimeTuningKey.MAP_ENEMY_GENRE_DETECTION_SCALING: "MAP_ENEMY_GENRE_DETECTION_SCALING",
        RuntimeTuningKey.MAP_ENEMY_GENRE_SIMILARITY: "MAP_ENEMY_GENRE_SIMILARITY",
        RuntimeTuningKey.MAP_WALK_TURNING_OPTIMIZE: "MAP_WALK_TURNING_OPTIMIZE",
        RuntimeTuningKey.MAP_WALK_USE_CURRENT_FLEET: "MAP_WALK_USE_CURRENT_FLEET",
        RuntimeTuningKey.MAP_SIREN_MOVE_WAIT: "MAP_SIREN_MOVE_WAIT",
        RuntimeTuningKey.MAP_SWIPE_PREDICT_WITH_SEA_GRIDS: "MAP_SWIPE_PREDICT_WITH_SEA_GRIDS",
        RuntimeTuningKey.MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET: "MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET",
        RuntimeTuningKey.MAP_SWIPE_PREDICT: "MAP_SWIPE_PREDICT",
        RuntimeTuningKey.MAP_ENEMY_TEMPLATE: "MAP_ENEMY_TEMPLATE",
        RuntimeTuningKey.MAP_GRID_CENTER_TOLERANCE: "MAP_GRID_CENTER_TOLERANCE",
        RuntimeTuningKey.MAP_HAS_CLEAR_PERCENTAGE: "MAP_HAS_CLEAR_PERCENTAGE",
        RuntimeTuningKey.MAP_HAS_DECOY_ENEMY: "MAP_HAS_DECOY_ENEMY",
        RuntimeTuningKey.MAP_HAS_DYNAMIC_RED_BORDER: "MAP_HAS_DYNAMIC_RED_BORDER",
        RuntimeTuningKey.MAP_HAS_MISSILE_ATTACK: "MAP_HAS_MISSILE_ATTACK",
        RuntimeTuningKey.MAP_HAS_PT_BONUS: "MAP_HAS_PT_BONUS",
        RuntimeTuningKey.MAP_HAS_WALK_SPEEDUP: "MAP_HAS_WALK_SPEEDUP",
        RuntimeTuningKey.MAP_MYSTERY_HAS_CARRIER: "MAP_MYSTERY_HAS_CARRIER",
        RuntimeTuningKey.MAP_MYSTERY_MAP_CLICK: "MAP_MYSTERY_MAP_CLICK",
        RuntimeTuningKey.MAP_SIREN_COUNT: "MAP_SIREN_COUNT",
        RuntimeTuningKey.MAP_SIREN_HAS_BOSS_ICON: "MAP_SIREN_HAS_BOSS_ICON",
        RuntimeTuningKey.MAP_SIREN_HAS_BOSS_ICON_SMALL: "MAP_SIREN_HAS_BOSS_ICON_SMALL",
        RuntimeTuningKey.MID_DIFF_RANGE_H: "MID_DIFF_RANGE_H",
        RuntimeTuningKey.MID_DIFF_RANGE_V: "MID_DIFF_RANGE_V",
        RuntimeTuningKey.POOR_MAP_DATA: "POOR_MAP_DATA",
        RuntimeTuningKey.TRUST_EDGE_LINES: "TRUST_EDGE_LINES",
        RuntimeTuningKey.TRUST_EDGE_LINES_THRESHOLD: "TRUST_EDGE_LINES_THRESHOLD",
        RuntimeTuningKey.VANISH_POINT_RANGE: "VANISH_POINT_RANGE",
    }
)

_RUNTIME_ATTRIBUTE_TUNINGS = frozenset(
    {
        RuntimeTuningKey.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD,
        RuntimeTuningKey.MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD,
        RuntimeTuningKey.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD,
        RuntimeTuningKey.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD,
    }
)
_DIRECT_CONFIG_TUNINGS = frozenset(
    {
        RuntimeTuningKey.FLEET_2,
        RuntimeTuningKey.FLEET_BOSS,
        RuntimeTuningKey.SUBMARINE,
    }
)
_BEHAVIOR_TUNINGS = frozenset(
    {
        RuntimeTuningKey.BOSS_APPEAR_REFOCUS_PRESET,
        RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER,
        RuntimeTuningKey.COMBAT_DISABLE_STUCK_DETECTION_BATTLE,
    }
)
_PROJECTED_TUNING_KEYS = (
    frozenset(_CONFIG_TUNING_FIELDS) | _RUNTIME_ATTRIBUTE_TUNINGS | _DIRECT_CONFIG_TUNINGS | _BEHAVIOR_TUNINGS
)
if frozenset(RuntimeTuningKey) != _PROJECTED_TUNING_KEYS:
    missing = sorted(key.value for key in frozenset(RuntimeTuningKey) - _PROJECTED_TUNING_KEYS)
    extra = sorted(key.value for key in _PROJECTED_TUNING_KEYS - frozenset(RuntimeTuningKey))
    message = f"runtime tuning projection is incomplete: missing={missing}, extra={extra}"
    raise AssertionError(message)


def _thaw_tuning(value: RuntimeTuningValue) -> object:
    if isinstance(value, tuple):
        return tuple(_thaw_tuning(item) for item in value)
    if isinstance(value, Mapping):
        typed = cast("Mapping[str, RuntimeTuningValue]", value)
        return {key: _thaw_tuning(item) for key, item in typed.items()}
    return value


def _integer_tuning(value: RuntimeTuningValue, key: RuntimeTuningKey) -> int:
    if type(value) is not int:
        message = f"runtime tuning {key.value} must be an integer"
        raise CampaignRuntimeProfileError(message)
    return value


def _number_tuning(value: RuntimeTuningValue, key: RuntimeTuningKey) -> float:
    if type(value) not in (int, float):
        message = f"runtime tuning {key.value} must be a number"
        raise CampaignRuntimeProfileError(message)
    return float(cast("int | float", value))


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
        "_active_context",
        "_behavior_tunings",
        "_compiled_map",
        "_direct_config_tunings",
        "_facets",
        "_frames",
        "_instances",
        "_profile",
        "_registry",
        "_runtime",
        "_runtime_attribute_tunings",
        "_shared_state",
        "_standard_config_tunings",
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
        self._active_context: RuntimeSessionContext | None = None
        standard: dict[str, object] = {}
        direct: dict[RuntimeTuningKey, RuntimeTuningValue] = {}
        runtime_attributes: dict[RuntimeTuningKey, RuntimeTuningValue] = {}
        behavior: dict[RuntimeTuningKey, RuntimeTuningValue] = {}
        for tuning in profile.tunings:
            field = _CONFIG_TUNING_FIELDS.get(tuning.key)
            if field is not None:
                standard[field] = _thaw_tuning(tuning.value)
            elif tuning.key in _DIRECT_CONFIG_TUNINGS:
                direct[tuning.key] = tuning.value
            elif tuning.key in _RUNTIME_ATTRIBUTE_TUNINGS:
                runtime_attributes[tuning.key] = tuning.value
            elif tuning.key in _BEHAVIOR_TUNINGS:
                behavior[tuning.key] = tuning.value
            else:
                message = f"runtime tuning has no production projection: {tuning.key.value}"
                raise CampaignRuntimeProfileError(message)
        self._standard_config_tunings = MappingProxyType(standard)
        self._direct_config_tunings = MappingProxyType(direct)
        self._runtime_attribute_tunings = MappingProxyType(runtime_attributes)
        self._behavior_tunings = MappingProxyType(behavior)
        self._validate_projection_contracts()

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

    def _validate_projection_contracts(self) -> None:
        for key, value in self._direct_config_tunings.items():
            _integer_tuning(value, key)
        _ = self.configured_boss_fleet
        for key, value in self._runtime_attribute_tunings.items():
            _number_tuning(value, key)
        _ = self.boss_appear_refocus_preset
        _ = self.map_clear_percentage_multiplier
        _ = self.combat_disable_stuck_detection_battle
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

    def apply_config(self, config: AzurLaneConfig) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "runtime profile config projection requires AzurLaneConfig"
            raise TypeError(message)
        overlay = dict(self._standard_config_tunings)
        fleet_2 = self._direct_config_tunings.get(RuntimeTuningKey.FLEET_2)
        if fleet_2 is not None:
            overlay["Fleet_Fleet2"] = _integer_tuning(fleet_2, RuntimeTuningKey.FLEET_2)
        submarine = self._direct_config_tunings.get(RuntimeTuningKey.SUBMARINE)
        if submarine is not None:
            overlay["Submarine_Fleet"] = _integer_tuning(submarine, RuntimeTuningKey.SUBMARINE)
        if overlay:
            config.apply_runtime_overlay(**cast("ConfigOverrides", overlay))

    @property
    def configured_boss_fleet(self) -> int | None:
        value = self._direct_config_tunings.get(RuntimeTuningKey.FLEET_BOSS)
        if value is None:
            return None
        fleet = _integer_tuning(value, RuntimeTuningKey.FLEET_BOSS)
        if fleet not in (1, 2):
            message = "fleet_boss must be 1 or 2"
            raise CampaignRuntimeProfileError(message)
        return fleet

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

    def begin_session(self, context: RuntimeSessionContext) -> None:
        if self._runtime is None:
            message = "runtime profile manager must be bound before begin_session"
            raise CampaignRuntimeProfileError(message)
        if self._active_context is not None:
            message = "runtime profile manager already has an active session"
            raise CampaignRuntimeProfileError(message)
        if not isinstance(context, RuntimeSessionContext):
            message = "runtime profile begin_session requires RuntimeSessionContext"
            raise TypeError(message)
        # 支援舰队允许 READY 阶段反复观察；session 一旦开始，后续消费者只能读取封存事实。
        support_fleet = self._shared_state.support_fleet
        if support_fleet is not None:
            support_fleet.seal()
        for instance in self._instances:
            instance.begin_session(context)
        self._active_context = context

    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        if self._active_context is None:
            message = "runtime profile manager has no active session"
            raise CampaignRuntimeProfileError(message)
        if not isinstance(outcome, RuntimeSessionOutcome):
            message = "runtime profile end_session requires RuntimeSessionOutcome"
            raise TypeError(message)
        # manager 先放弃 active ownership，避免任一 executor 失败后留下可复用的半关闭会话。
        self._active_context = None
        errors: list[BaseException] = []
        for instance in reversed(self._instances):
            try:
                instance.end_session(outcome)
            except BaseException as error:  # ruff:ignore[blind-except] - 各 executor 必须独立结束。
                errors.append(error)
        raise_cleanup_errors(errors, message="runtime profile session cleanup failed")

    def reset(self) -> None:
        if self._active_context is not None:
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

    def apply_runtime_tunings(self, runtime: RuntimeProfileHost) -> None:
        for key, value in self._runtime_attribute_tunings.items():
            number = _number_tuning(value, key)
            if key is RuntimeTuningKey.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD:
                runtime.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = number
            elif key is RuntimeTuningKey.MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD:
                runtime.MAP_AIR_STRIKE_OVERLAY_TRANSPARENCY_THRESHOLD = number
            elif key is RuntimeTuningKey.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD:
                runtime.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD = number
            elif key is RuntimeTuningKey.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD:
                runtime.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = number
            else:
                message = f"unreachable runtime attribute tuning: {key.value}"
                raise AssertionError(message)

    @property
    def boss_appear_refocus_preset(self) -> tuple[int, int] | None:
        value = self._behavior_tunings.get(RuntimeTuningKey.BOSS_APPEAR_REFOCUS_PRESET)
        if value is None:
            return None
        if not isinstance(value, tuple) or len(value) != 2 or any(type(item) is not int for item in value):
            message = "boss_appear_refocus_preset must contain two integers"
            raise CampaignRuntimeProfileError(message)
        return cast("tuple[int, int]", value)

    @property
    def map_clear_percentage_multiplier(self) -> float:
        value = self._behavior_tunings.get(RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER)
        if value is None:
            return 1.0
        return _number_tuning(value, RuntimeTuningKey.MAP_CLEAR_PERCENTAGE_MULTIPLIER)

    @property
    def combat_disable_stuck_detection_battle(self) -> int | None:
        value = self._behavior_tunings.get(RuntimeTuningKey.COMBAT_DISABLE_STUCK_DETECTION_BATTLE)
        if value is None:
            return None
        return _integer_tuning(
            value,
            RuntimeTuningKey.COMBAT_DISABLE_STUCK_DETECTION_BATTLE,
        )

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
