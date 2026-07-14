from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast, override

from module.base.utils import get_color, location2node, node2location, red_overlay_transparency
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.handler.assets import MAP_ENEMY_SEARCHING
from module.handler.fast_forward import AUTO_SEARCH
from module.logger import logger
from module.map.utils import location_ensure

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
)

if TYPE_CHECKING:
    from module.base.type_alias import Point
    from module.campaign.campaign_engine import CampaignEngine
    from module.config.config import AzurLaneConfig
    from module.device.device import Device
    from module.map.map_grids import SelectedGrids
    from module.map.utils import HasLocation
    from module.map_detection.grid_info import GridInfo


class _ObservationRuntimeHost(Protocol):
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD: float
    config: AzurLaneConfig
    device: Device
    map: object
    fleet_1: object
    fleet_2: object
    fleet_current: object
    map_is_100_percent_clear: bool
    map_is_3_stars: bool
    map_is_threat_safe: bool
    map_has_clear_mode: bool

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object: ...

    def is_in_map(self) -> bool: ...

    def focus_to(self, location: object) -> object: ...

    def map_show_info(self) -> None: ...


def _host(runtime: object) -> _ObservationRuntimeHost:
    return cast("_ObservationRuntimeHost", runtime)


def _operations(options: Mapping[str, RuntimeTuningValue]) -> frozenset[str]:
    value = options["operations"]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = "runtime observation operations must contain strings"
        raise CampaignRuntimeProfileError(message)
    return frozenset(cast("tuple[str, ...]", value))


def _require_operations(
    options: Mapping[str, RuntimeTuningValue],
    expected: frozenset[str],
) -> None:
    actual = _operations(options)
    if actual != expected:
        message = f"runtime observation operations mismatch: expected={sorted(expected)}, actual={sorted(actual)}"
        raise CampaignRuntimeProfileError(message)


def _string(options: Mapping[str, RuntimeTuningValue], name: str) -> str:
    value = options[name]
    if not isinstance(value, str) or not value:
        message = f"runtime observation option {name} must be a non-empty string"
        raise CampaignRuntimeProfileError(message)
    return value


class PreserveEnemyGenreExecutor(RuntimeExecutorInstance):
    """全图扫描移动敌人时暂存并恢复会短暂消失的敌人类型。"""

    __slots__ = ("_genre", "_preserved")

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
        _require_operations(options, frozenset({"full_scan", "full_scan_movable"}))
        state = options["state"]
        if state != ("dace",):
            message = "preserved enemy genre state must be ['dace']"
            raise CampaignRuntimeProfileError(message)
        self._genre = _string(options, "genre")
        self._preserved: SelectedGrids[GridInfo] | None = None
        super().__init__(
            {RuntimeExecutorKind.MAP_OBSERVATION},
            methods={
                RuntimeExecutorKind.MAP_OBSERVATION: {
                    RuntimeOperation.FULL_SCAN: self._full_scan,
                    RuntimeOperation.FULL_SCAN_MOVABLE: self._full_scan_movable,
                }
            },
        )

    @override
    def reset(self) -> None:
        super().reset()
        self._preserved = None

    def _full_scan_movable(self, runtime: object, *args: object, **kwargs: object) -> object:
        host = _host(runtime)
        typed_map = cast("CampaignEngine", runtime).map
        self._preserved = typed_map.select(enemy_genre=self._genre)
        logger.attr("Preserved_enemy_genre", self._preserved)
        return host.runtime_super(RuntimeOperation.FULL_SCAN_MOVABLE, *args, **kwargs)

    def _full_scan(self, runtime: object, *args: object, **kwargs: object) -> object:
        host = _host(runtime)
        result = host.runtime_super(RuntimeOperation.FULL_SCAN, *args, **kwargs)
        if self._preserved is not None:
            logger.attr("Preserved_enemy_genre", self._preserved)
            for grid in self._preserved:
                grid.is_siren = True
                grid.enemy_genre = self._genre
            self._preserved = None
        return result


def _build_preserve_enemy_genre(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return PreserveEnemyGenreExecutor(context)


def _build_red_overlay_enemy_search(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
    _require_operations(options, frozenset({"enemy_searching_appear"}))

    def enemy_searching_appear(runtime: object) -> object:
        host = _host(runtime)
        if not host.is_in_map():
            return False
        transparency = red_overlay_transparency(
            MAP_ENEMY_SEARCHING.color,
            get_color(host.device.image, MAP_ENEMY_SEARCHING.area),
        )
        return bool(transparency > host.MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD)

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.MAP_OBSERVATION},
        methods={
            RuntimeExecutorKind.MAP_OBSERVATION: {
                RuntimeOperation.ENEMY_SEARCHING_APPEAR: enemy_searching_appear,
            }
        },
    )


def _build_fixed_fleet_locations(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
    _require_operations(options, frozenset({"find_current_fleet"}))
    fleet_1 = node2location(_string(options, "fleet_1"))
    fleet_2 = node2location(_string(options, "fleet_2"))

    def find_current_fleet(runtime: object) -> object:
        host = _host(runtime)
        logger.hr("Find current fleet")
        logger.info(f"No fleet scan, assume fleet_1 at {location2node(fleet_1)}")
        host.fleet_1 = fleet_1
        if host.config.fleet_2:
            logger.info(f"No fleet scan, assume fleet_2 at {location2node(fleet_2)}")
            host.fleet_2 = fleet_2
        return host.fleet_current

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.MAP_OBSERVATION},
        methods={
            RuntimeExecutorKind.MAP_OBSERVATION: {
                RuntimeOperation.FIND_CURRENT_FLEET: find_current_fleet,
            }
        },
    )


@dataclass(frozen=True, slots=True)
class _FocusRule:
    cell: str | None
    x_gte: int | None
    x_lte: int | None
    y_lte: int | None
    focus_x: int | None
    focus_cell: str | None

    def matches(self, *, node: str, x: int, y: int) -> bool:
        return (
            (self.cell is None or node == self.cell)
            and (self.x_gte is None or x >= self.x_gte)
            and (self.x_lte is None or x <= self.x_lte)
            and (self.y_lte is None or y <= self.y_lte)
        )

    def target(self, *, y: int) -> tuple[int, int]:
        if self.focus_cell is not None:
            return node2location(self.focus_cell)
        if self.focus_x is None:
            message = "focus rule has no target"
            raise AssertionError(message)
        return self.focus_x, y


def _optional_int(values: Mapping[str, RuntimeTuningValue], name: str) -> int | None:
    value = values.get(name)
    if value is None:
        return None
    if type(value) is not int:
        message = f"focus rule {name} must be an integer"
        raise CampaignRuntimeProfileError(message)
    return value


def _optional_string(values: Mapping[str, RuntimeTuningValue], name: str) -> str | None:
    value = values.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        message = f"focus rule {name} must be a non-empty string"
        raise CampaignRuntimeProfileError(message)
    return value


def _focus_rule(raw: RuntimeTuningValue) -> _FocusRule:
    if not isinstance(raw, Mapping):
        message = "focus rule must be an object"
        raise CampaignRuntimeProfileError(message)
    values = cast("Mapping[str, RuntimeTuningValue]", raw)
    condition = values.get("when")
    if not isinstance(condition, Mapping):
        message = "focus rule requires a when object"
        raise CampaignRuntimeProfileError(message)
    typed_condition = cast("Mapping[str, RuntimeTuningValue]", condition)
    rule = _FocusRule(
        _optional_string(typed_condition, "cell"),
        _optional_int(typed_condition, "x_gte"),
        _optional_int(typed_condition, "x_lte"),
        _optional_int(typed_condition, "y_lte"),
        _optional_int(values, "focus_x"),
        _optional_string(values, "focus_cell"),
    )
    if (rule.focus_x is None) == (rule.focus_cell is None):
        message = "focus rule requires exactly one focus target"
        raise CampaignRuntimeProfileError(message)
    return rule


def _build_focus_rules(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
    _require_operations(options, frozenset({"in_sight"}))
    raw_rules = options["rules"]
    if not isinstance(raw_rules, tuple) or not raw_rules:
        message = "focus rules must be a non-empty array"
        raise CampaignRuntimeProfileError(message)
    rules = tuple(_focus_rule(raw) for raw in raw_rules)

    def in_sight(
        runtime: object,
        location: HasLocation | str | Point,
        sight: object = None,
    ) -> object:
        host = _host(runtime)
        normalized = location_ensure(location)
        x, y = normalized
        node = location2node(normalized)
        logger.info(f"In sight: {node}")
        for rule in rules:
            if rule.matches(node=node, x=x, y=y):
                target = rule.target(y=y)
                logger.info(f"Focus to: {location2node(target)}")
                return host.focus_to(target)
        return host.runtime_super(RuntimeOperation.IN_SIGHT, normalized, sight=sight)

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.MAP_OBSERVATION},
        methods={
            RuntimeExecutorKind.MAP_OBSERVATION: {
                RuntimeOperation.IN_SIGHT: in_sight,
            }
        },
    )


def _auto_search_options(
    options: Mapping[str, RuntimeTuningValue],
) -> tuple[tuple[str, ...], bool]:
    operations = _operations(options)
    prefixes_value = options["campaign_name_prefixes"]
    if (
        not isinstance(prefixes_value, tuple)
        or not prefixes_value
        or any(not isinstance(prefix, str) or not prefix for prefix in prefixes_value)
    ):
        message = "auto-search clear-status prefixes must contain strings"
        raise CampaignRuntimeProfileError(message)
    prefixes = cast("tuple[str, ...]", prefixes_value)
    override_percentage = options["override_map_clear_percentage"]
    if type(override_percentage) is not bool:
        message = "auto-search clear-status percentage option must be a boolean"
        raise CampaignRuntimeProfileError(message)
    expected = {"map_get_info"}
    if override_percentage:
        expected.add("get_map_clear_percentage")
    if operations != expected:
        message = (
            f"auto-search clear-status operations mismatch: expected={sorted(expected)}, actual={sorted(operations)}"
        )
        raise CampaignRuntimeProfileError(message)
    return prefixes, override_percentage


def _build_auto_search_clear_status(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
    prefixes, override_percentage = _auto_search_options(options)

    def applies(host: _ObservationRuntimeHost) -> bool:
        name = str(host.config.Campaign_Name).lower()
        return "*" in prefixes or name.startswith(prefixes)

    def appears(runtime: object) -> bool:
        return bool(AUTO_SEARCH.appear(main=cast("CampaignEngine", runtime)))

    def map_get_info(runtime: object) -> object:
        host = _host(runtime)
        result = host.runtime_super(RuntimeOperation.MAP_GET_INFO)
        if applies(host):
            visible = appears(runtime)
            host.map_is_100_percent_clear = visible
            host.map_is_3_stars = visible
            host.map_is_threat_safe = visible
            host.map_has_clear_mode = visible
            host.map_show_info()
        return result

    methods = {RuntimeOperation.MAP_GET_INFO: map_get_info}
    if override_percentage:

        def get_map_clear_percentage(runtime: object) -> object:
            if appears(runtime):
                return 1.0
            return _host(runtime).runtime_super(RuntimeOperation.GET_MAP_CLEAR_PERCENTAGE)

        methods[RuntimeOperation.GET_MAP_CLEAR_PERCENTAGE] = get_map_clear_percentage

    return RuntimeExecutorInstance(
        {RuntimeExecutorKind.MAP_OBSERVATION},
        methods={RuntimeExecutorKind.MAP_OBSERVATION: methods},
    )


def observation_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    observation = RuntimeExecutorKind.MAP_OBSERVATION
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/preserve_enemy_genre"),
            {
                observation: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "state", "genre"}),
                )
            },
            _build_preserve_enemy_genre,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/red_overlay_enemy_search"),
            {observation: RuntimeExecutorOptionsSchema(required=frozenset({"operations"}))},
            _build_red_overlay_enemy_search,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/fixed_fleet_locations"),
            {
                observation: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "fleet_1", "fleet_2"}),
                )
            },
            _build_fixed_fleet_locations,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/focus_rules"),
            {
                observation: RuntimeExecutorOptionsSchema(
                    required=frozenset({"operations", "rules"}),
                )
            },
            _build_focus_rules,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/auto_search_clear_status"),
            {
                observation: RuntimeExecutorOptionsSchema(
                    required=frozenset(
                        {
                            "operations",
                            "campaign_name_prefixes",
                            "override_map_clear_percentage",
                        }
                    ),
                )
            },
            _build_auto_search_clear_status,
        ),
    )
