from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast, override

from module.base.utils import get_color, location2node, node2location, red_overlay_transparency
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.handler.assets import MAP_ENEMY_SEARCHING
from module.handler.fast_forward import AUTO_SEARCH
from module.logger import logger

from .campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    EnemySearchingNext,
    FindCurrentFleetNext,
    FullScanMovableNext,
    FullScanNext,
    FullScanRequest,
    InSightNext,
    MapClearPercentageNext,
    MapGetInfoNext,
)
from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray
    from module.campaign.campaign_engine import CampaignEngine
    from module.config.config import AzurLaneConfig
    from module.map.map_grids import SelectedGrids
    from module.map.map_observer import (
        FleetLocatorRuntime,
        InSightRequest,
        MapPreparationRuntime,
        MapScannerRuntime,
        MapViewportRuntime,
    )
    from module.map.type_alias import FleetLocation
    from module.map_detection.grid_info import GridInfo


class _AutoSearchClearStatusRuntime(Protocol):
    config: AzurLaneConfig
    map_is_100_percent_clear: bool
    map_is_3_stars: bool
    map_is_threat_safe: bool
    map_has_clear_mode: bool

    def map_show_info(self) -> None: ...


def _string(options: Mapping[str, RuntimeTuningValue], name: str) -> str:
    value = options[name]
    if not isinstance(value, str) or not value:
        message = f"runtime observation option {name} must be a non-empty string"
        raise CampaignRuntimeProfileError(message)
    return value


class PreserveEnemyGenreExecutor(CampaignMapObserverExecutor):
    """全图扫描移动敌人时暂存并恢复会短暂消失的敌人类型。"""

    __slots__ = ("_genre", "_preserved")

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
        self._genre = _string(options, "genre")
        self._preserved: SelectedGrids[GridInfo] | None = None
        super().__init__(
            CampaignMapObserverContributor(
                full_scan=self._full_scan,
                full_scan_movable=self._full_scan_movable,
            )
        )

    @override
    def reset(self) -> None:
        self._restore_preserved()
        super().reset()

    def _restore_preserved(self) -> None:
        preserved = self._preserved
        if preserved is None:
            return
        self._preserved = None
        logger.attr("Preserved_enemy_genre", preserved)
        for grid in preserved:
            grid.is_siren = True
            grid.enemy_genre = self._genre

    def _full_scan_movable(
        self,
        runtime: MapScannerRuntime,
        next_handler: FullScanMovableNext,
        *,
        enemy_cleared: bool = True,
    ) -> None:
        self._preserved = runtime.map.select(enemy_genre=self._genre)
        logger.attr("Preserved_enemy_genre", self._preserved)
        try:
            next_handler(runtime, enemy_cleared=enemy_cleared)
        finally:
            self._restore_preserved()

    def _full_scan(
        self,
        runtime: MapScannerRuntime,
        request: FullScanRequest,
        next_handler: FullScanNext,
    ) -> None:
        next_handler(runtime, request)
        self._restore_preserved()


def _build_preserve_enemy_genre(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return PreserveEnemyGenreExecutor(context)


def _build_red_overlay_enemy_search(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    del context

    def enemy_searching_appear(
        image: ImageArray,
        next_handler: EnemySearchingNext,
        *,
        overlay_transparency_threshold: float,
    ) -> bool:
        del next_handler
        transparency = red_overlay_transparency(
            MAP_ENEMY_SEARCHING.color,
            get_color(image, MAP_ENEMY_SEARCHING.area),
        )
        return bool(transparency > overlay_transparency_threshold)

    return CampaignMapObserverExecutor(CampaignMapObserverContributor(enemy_searching=enemy_searching_appear))


def _build_fixed_fleet_locations(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
    fleet_1 = node2location(_string(options, "fleet_1"))
    fleet_2 = node2location(_string(options, "fleet_2"))

    def find_current_fleet(
        runtime: FleetLocatorRuntime,
        next_handler: FindCurrentFleetNext,
    ) -> FleetLocation:
        del next_handler
        logger.hr("Find current fleet")
        logger.info(f"No fleet scan, assume fleet_1 at {location2node(fleet_1)}")
        runtime._set_fleet_location(  # ruff:ignore[private-member-access] - fixed locator 只能通过显式 port 原语更新舰队位置。
            1,
            fleet_1,
        )
        if runtime._fleet_2_enabled:  # ruff:ignore[private-member-access] - fixed locator 只读取显式 port 开关。
            logger.info(f"No fleet scan, assume fleet_2 at {location2node(fleet_2)}")
            runtime._set_fleet_location(  # ruff:ignore[private-member-access] - fixed locator 只能通过显式 port 原语更新舰队位置。
                2,
                fleet_2,
            )
        return runtime.fleet_current

    return CampaignMapObserverExecutor(CampaignMapObserverContributor(find_current_fleet=find_current_fleet))


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
    raw_rules = options["rules"]
    if not isinstance(raw_rules, tuple) or not raw_rules:
        message = "focus rules must be a non-empty array"
        raise CampaignRuntimeProfileError(message)
    rules = tuple(_focus_rule(raw) for raw in raw_rules)

    def in_sight(
        runtime: MapViewportRuntime,
        request: InSightRequest,
        next_handler: InSightNext,
    ) -> None:
        x, y = request.location
        node = location2node(request.location)
        for rule in rules:
            if rule.matches(node=node, x=x, y=y):
                target = rule.target(y=y)
                logger.info(f"In sight: {node}")
                logger.info(f"Focus to: {location2node(target)}")
                runtime.focus_to(target)
                return
        next_handler(runtime, request)

    return CampaignMapObserverExecutor(CampaignMapObserverContributor(in_sight=in_sight))


def _auto_search_options(
    options: Mapping[str, RuntimeTuningValue],
) -> tuple[tuple[str, ...], bool]:
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
    return prefixes, override_percentage


def _build_auto_search_clear_status(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.MAP_OBSERVATION)
    prefixes, override_percentage = _auto_search_options(options)

    def applies(host: _AutoSearchClearStatusRuntime) -> bool:
        name = str(host.config.Campaign_Name).lower()
        return "*" in prefixes or name.startswith(prefixes)

    def appears(runtime: MapPreparationRuntime) -> bool:
        return bool(AUTO_SEARCH.appear(main=cast("CampaignEngine", runtime)))

    def map_get_info(
        runtime: MapPreparationRuntime,
        next_handler: MapGetInfoNext,
    ) -> None:
        next_handler(runtime)
        host = cast("_AutoSearchClearStatusRuntime", runtime)
        if not applies(host):
            return
        visible = appears(runtime)
        host.map_is_100_percent_clear = visible
        host.map_is_3_stars = visible
        host.map_is_threat_safe = visible
        host.map_has_clear_mode = visible
        host.map_show_info()

    def get_map_clear_percentage(
        runtime: MapPreparationRuntime,
        next_handler: MapClearPercentageNext,
    ) -> float:
        if appears(runtime):
            return 1.0
        return next_handler(runtime)

    return CampaignMapObserverExecutor(
        CampaignMapObserverContributor(
            map_get_info=map_get_info,
            map_clear_percentage=(get_map_clear_percentage if override_percentage else None),
        )
    )


def observation_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    observation = RuntimeExecutorKind.MAP_OBSERVATION
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/preserve_enemy_genre"),
            {
                observation: RuntimeExecutorOptionsSchema(
                    required=frozenset({"genre"}),
                )
            },
            _build_preserve_enemy_genre,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/red_overlay_enemy_search"),
            {observation: RuntimeExecutorOptionsSchema()},
            _build_red_overlay_enemy_search,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/fixed_fleet_locations"),
            {
                observation: RuntimeExecutorOptionsSchema(
                    required=frozenset({"fleet_1", "fleet_2"}),
                )
            },
            _build_fixed_fleet_locations,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("observation/focus_rules"),
            {
                observation: RuntimeExecutorOptionsSchema(
                    required=frozenset({"rules"}),
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
                            "campaign_name_prefixes",
                            "override_map_clear_percentage",
                        }
                    ),
                )
            },
            _build_auto_search_clear_status,
        ),
    )
