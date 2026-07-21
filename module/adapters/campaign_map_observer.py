from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from module.content.runtime_profile import RuntimeExecutorKind
from module.map.fleet_locator import (
    STANDARD_CAMPAIGN_FLEET_LOCATOR,
    CampaignFleetLocator,
    FleetLocationContext,
    SurfaceFleetLocationRequest,
    SurfaceFleetLocations,
)
from module.map.map_observer import (
    STANDARD_CAMPAIGN_MAP_OBSERVER,
    CampaignMapObserver,
    CampaignMapPreparation,
    CampaignMapScanner,
    CampaignMapViewport,
    CombatMapObserver,
    EnemySearchingObserver,
    InSightRequest,
    MapObserverRuntime,
    MapPreparationRuntime,
    MapViewportRuntime,
)
from module.map.map_scanner import MapScannerRuntime, MapScanRequest, MovableScanRequest

from .campaign_runtime_profile import CampaignRuntimeProfileError, RuntimeExecutorInstance

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from module.base.type_alias import ImageArray
    from module.map.type_alias import GridLocation
    from module.map_detection.grid_info import GridInfo

type CameraRepositioningNext = Callable[[MapObserverRuntime, GridInfo], bool]
type CameraRepositioningHandler = Callable[
    [MapObserverRuntime, GridInfo, CameraRepositioningNext],
    bool,
]


type FullScanNext = Callable[[MapScannerRuntime, MapScanRequest], None]
type FullScanHandler = Callable[[MapScannerRuntime, MapScanRequest, FullScanNext], None]

type InSightNext = Callable[[MapViewportRuntime, InSightRequest], None]
type InSightHandler = Callable[[MapViewportRuntime, InSightRequest, InSightNext], None]

type LocateSurfaceFleetNext = Callable[
    [FleetLocationContext, SurfaceFleetLocationRequest],
    SurfaceFleetLocations,
]
type LocateSurfaceFleetHandler = Callable[
    [FleetLocationContext, SurfaceFleetLocationRequest, LocateSurfaceFleetNext],
    SurfaceFleetLocations,
]

type MapGetInfoNext = Callable[[MapPreparationRuntime], None]
type MapGetInfoHandler = Callable[[MapPreparationRuntime, MapGetInfoNext], None]
type MapClearPercentageNext = Callable[[MapPreparationRuntime], float]
type MapClearPercentageHandler = Callable[
    [MapPreparationRuntime, MapClearPercentageNext],
    float,
]


class FullScanMovableNext(Protocol):
    def __call__(
        self,
        runtime: MapScannerRuntime,
        request: MovableScanRequest,
    ) -> None: ...


class FullScanMovableHandler(Protocol):
    def __call__(
        self,
        runtime: MapScannerRuntime,
        request: MovableScanRequest,
        next_handler: FullScanMovableNext,
    ) -> None: ...


class EnemySearchingNext(Protocol):
    def __call__(
        self,
        image: ImageArray,
        /,
        *,
        overlay_transparency_threshold: float,
    ) -> bool: ...


class EnemySearchingHandler(Protocol):
    def __call__(
        self,
        image: ImageArray,
        next_handler: EnemySearchingNext,
        /,
        *,
        overlay_transparency_threshold: float,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class CampaignMapObserverContributor:
    camera_repositioning: CameraRepositioningHandler | None = None
    full_scan: FullScanHandler | None = None
    full_scan_movable: FullScanMovableHandler | None = None
    enemy_searching: EnemySearchingHandler | None = None
    in_sight: InSightHandler | None = None
    locate_surface_fleet: LocateSurfaceFleetHandler | None = None
    map_get_info: MapGetInfoHandler | None = None
    map_clear_percentage: MapClearPercentageHandler | None = None


@runtime_checkable
class CampaignMapObserverContributorSource(Protocol):
    @property
    def map_observer_contributor(self) -> CampaignMapObserverContributor: ...


class CampaignMapObserverExecutor(RuntimeExecutorInstance):
    """提供 typed 地图观察能力，不暴露 string-dispatched observation method。"""

    __slots__ = ("_map_observer_contributor",)

    def __init__(self, contributor: CampaignMapObserverContributor) -> None:
        if not isinstance(contributor, CampaignMapObserverContributor):
            message = "campaign map observer executor requires a typed contributor"
            raise TypeError(message)
        super().__init__({RuntimeExecutorKind.MAP_OBSERVATION})
        self._map_observer_contributor = contributor

    @property
    def map_observer_contributor(self) -> CampaignMapObserverContributor:
        return self._map_observer_contributor


@dataclass(frozen=True, slots=True)
class _ComposedCombatMapObserver(CombatMapObserver):
    camera_repositioning_handler: CameraRepositioningNext

    @override
    def camera_repositioned_after_combat(
        self,
        runtime: MapObserverRuntime,
        destination: GridInfo,
    ) -> bool:
        return self.camera_repositioning_handler(runtime, destination)


@dataclass(frozen=True, slots=True)
class _ComposedCampaignMapScanner(CampaignMapScanner):
    full_scan_handler: FullScanNext
    full_scan_movable_handler: FullScanMovableNext

    @override
    def full_scan(
        self,
        runtime: MapScannerRuntime,
        request: MapScanRequest,
    ) -> None:
        self.full_scan_handler(runtime, request)

    @override
    def full_scan_movable(
        self,
        runtime: MapScannerRuntime,
        request: MovableScanRequest,
    ) -> None:
        self.full_scan_movable_handler(runtime, request)


@dataclass(frozen=True, slots=True)
class _ComposedEnemySearchingObserver(EnemySearchingObserver):
    handler: EnemySearchingNext

    @override
    def appears(
        self,
        image: ImageArray,
        *,
        overlay_transparency_threshold: float,
    ) -> bool:
        return self.handler(
            image,
            overlay_transparency_threshold=overlay_transparency_threshold,
        )


@dataclass(frozen=True, slots=True)
class _ComposedCampaignMapViewport(CampaignMapViewport):
    handler: InSightNext

    @override
    def in_sight(self, runtime: MapViewportRuntime, request: InSightRequest) -> None:
        self.handler(runtime, request)


@dataclass(frozen=True, slots=True)
class _ComposedCampaignFleetLocator(CampaignFleetLocator):
    handler: LocateSurfaceFleetNext

    @override
    def locate_surface(
        self,
        context: FleetLocationContext,
        request: SurfaceFleetLocationRequest,
    ) -> SurfaceFleetLocations:
        return self.handler(context, request)

    @override
    def locate_submarine(
        self,
        context: FleetLocationContext,
        *,
        enabled: bool,
    ) -> GridLocation | None:
        return STANDARD_CAMPAIGN_FLEET_LOCATOR.locate_submarine(context, enabled=enabled)


@dataclass(frozen=True, slots=True)
class _ComposedCampaignMapPreparation(CampaignMapPreparation):
    map_get_info_handler: MapGetInfoNext
    map_clear_percentage_handler: MapClearPercentageNext
    map_clear_percentage_multiplier: float

    @override
    def map_get_info(self, runtime: MapPreparationRuntime) -> None:
        self.map_get_info_handler(runtime)

    @override
    def get_map_clear_percentage(self, runtime: MapPreparationRuntime) -> float:
        result = self.map_clear_percentage_handler(runtime)
        if not isinstance(result, int | float):
            message = "map clear percentage executor must return a number"
            raise CampaignRuntimeProfileError(message)
        return float(result) * self.map_clear_percentage_multiplier


def _overlay_camera_repositioning(
    handler: CameraRepositioningHandler,
    next_handler: CameraRepositioningNext,
) -> CameraRepositioningNext:
    def execute(runtime: MapObserverRuntime, destination: GridInfo) -> bool:
        return handler(runtime, destination, next_handler)

    return execute


def _overlay_full_scan(
    handler: FullScanHandler,
    next_handler: FullScanNext,
) -> FullScanNext:
    def execute(runtime: MapScannerRuntime, request: MapScanRequest) -> None:
        handler(runtime, request, next_handler)

    return execute


def _overlay_full_scan_movable(
    handler: FullScanMovableHandler,
    next_handler: FullScanMovableNext,
) -> FullScanMovableNext:
    def execute(
        runtime: MapScannerRuntime,
        request: MovableScanRequest,
    ) -> None:
        handler(runtime, request, next_handler)

    return execute


def _overlay_enemy_searching(
    handler: EnemySearchingHandler,
    next_handler: EnemySearchingNext,
) -> EnemySearchingNext:
    def execute(
        image: ImageArray,
        *,
        overlay_transparency_threshold: float,
    ) -> bool:
        return handler(
            image,
            next_handler,
            overlay_transparency_threshold=overlay_transparency_threshold,
        )

    return execute


def _overlay_in_sight(
    handler: InSightHandler,
    next_handler: InSightNext,
) -> InSightNext:
    def execute(runtime: MapViewportRuntime, request: InSightRequest) -> None:
        handler(runtime, request, next_handler)

    return execute


def _overlay_locate_surface_fleet(
    handler: LocateSurfaceFleetHandler,
    next_handler: LocateSurfaceFleetNext,
) -> LocateSurfaceFleetNext:
    def execute(
        context: FleetLocationContext,
        request: SurfaceFleetLocationRequest,
    ) -> SurfaceFleetLocations:
        return handler(context, request, next_handler)

    return execute


def _overlay_map_get_info(
    handler: MapGetInfoHandler,
    next_handler: MapGetInfoNext,
) -> MapGetInfoNext:
    def execute(runtime: MapPreparationRuntime) -> None:
        handler(runtime, next_handler)

    return execute


def _overlay_map_clear_percentage(
    handler: MapClearPercentageHandler,
    next_handler: MapClearPercentageNext,
) -> MapClearPercentageNext:
    def execute(runtime: MapPreparationRuntime) -> float:
        return handler(runtime, next_handler)

    return execute


def _overlay_preparation(
    contributor: CampaignMapObserverContributor,
    map_get_info: MapGetInfoNext,
    map_clear_percentage: MapClearPercentageNext,
) -> tuple[MapGetInfoNext, MapClearPercentageNext]:
    if contributor.map_get_info is not None:
        map_get_info = _overlay_map_get_info(contributor.map_get_info, map_get_info)
    if contributor.map_clear_percentage is not None:
        map_clear_percentage = _overlay_map_clear_percentage(
            contributor.map_clear_percentage,
            map_clear_percentage,
        )
    return map_get_info, map_clear_percentage


def _standard_full_scan(runtime: MapScannerRuntime, request: MapScanRequest) -> None:
    STANDARD_CAMPAIGN_MAP_OBSERVER.scanner.full_scan(runtime, request)


def build_campaign_map_observer(
    instances: Iterable[object],
    *,
    map_clear_percentage_multiplier: float = 1.0,
) -> CampaignMapObserver:
    """按 profile 顺序组合地图观察规则；后声明的 contributor 先获得处理权。"""

    camera_repositioning = STANDARD_CAMPAIGN_MAP_OBSERVER.combat.camera_repositioned_after_combat
    full_scan = _standard_full_scan
    full_scan_movable = STANDARD_CAMPAIGN_MAP_OBSERVER.scanner.full_scan_movable
    enemy_searching = STANDARD_CAMPAIGN_MAP_OBSERVER.enemy_searching.appears
    in_sight = STANDARD_CAMPAIGN_MAP_OBSERVER.viewport.in_sight
    locate_surface_fleet = STANDARD_CAMPAIGN_MAP_OBSERVER.fleet_locator.locate_surface
    map_get_info = STANDARD_CAMPAIGN_MAP_OBSERVER.preparation.map_get_info
    map_clear_percentage = STANDARD_CAMPAIGN_MAP_OBSERVER.preparation.get_map_clear_percentage
    for instance in instances:
        if not isinstance(instance, CampaignMapObserverContributorSource):
            continue
        contributor = instance.map_observer_contributor
        if contributor.camera_repositioning is not None:
            camera_repositioning = _overlay_camera_repositioning(
                contributor.camera_repositioning,
                camera_repositioning,
            )
        if contributor.full_scan is not None:
            full_scan = _overlay_full_scan(contributor.full_scan, full_scan)
        if contributor.full_scan_movable is not None:
            full_scan_movable = _overlay_full_scan_movable(
                contributor.full_scan_movable,
                full_scan_movable,
            )
        if contributor.enemy_searching is not None:
            enemy_searching = _overlay_enemy_searching(
                contributor.enemy_searching,
                enemy_searching,
            )
        if contributor.in_sight is not None:
            in_sight = _overlay_in_sight(contributor.in_sight, in_sight)
        if contributor.locate_surface_fleet is not None:
            locate_surface_fleet = _overlay_locate_surface_fleet(
                contributor.locate_surface_fleet,
                locate_surface_fleet,
            )
        map_get_info, map_clear_percentage = _overlay_preparation(
            contributor,
            map_get_info,
            map_clear_percentage,
        )
    return CampaignMapObserver(
        combat=_ComposedCombatMapObserver(camera_repositioning),
        scanner=_ComposedCampaignMapScanner(full_scan, full_scan_movable),
        enemy_searching=_ComposedEnemySearchingObserver(enemy_searching),
        viewport=_ComposedCampaignMapViewport(in_sight),
        fleet_locator=_ComposedCampaignFleetLocator(locate_surface_fleet),
        preparation=_ComposedCampaignMapPreparation(
            map_get_info,
            map_clear_percentage,
            map_clear_percentage_multiplier,
        ),
    )
