from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from module.content.runtime_profile import RuntimeExecutorKind
from module.map.map_observer import (
    STANDARD_CAMPAIGN_MAP_OBSERVER,
    CampaignMapObserver,
    CampaignMapScanner,
    CombatMapObserver,
    EnemySearchingObserver,
    MapObserverRuntime,
    MapScannerRuntime,
)

from .campaign_runtime_profile import RuntimeExecutorInstance

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from module.base.type_alias import ImageArray
    from module.map.camera import FullScanOptions
    from module.map.map_grids import SelectedGrids
    from module.map.type_alias import GridMode
    from module.map_detection.grid_info import GridInfo

type CameraRepositioningNext = Callable[[MapObserverRuntime, GridInfo], bool]
type CameraRepositioningHandler = Callable[
    [MapObserverRuntime, GridInfo, CameraRepositioningNext],
    bool,
]


@dataclass(frozen=True, slots=True)
class FullScanRequest:
    options: FullScanOptions | None = None
    queue: SelectedGrids[GridInfo] | None = None
    must_scan: SelectedGrids[GridInfo] | None = None
    mode: GridMode = "normal"


type FullScanNext = Callable[[MapScannerRuntime, FullScanRequest], None]
type FullScanHandler = Callable[[MapScannerRuntime, FullScanRequest, FullScanNext], None]


class FullScanMovableNext(Protocol):
    def __call__(
        self,
        runtime: MapScannerRuntime,
        *,
        enemy_cleared: bool = True,
    ) -> None: ...


class FullScanMovableHandler(Protocol):
    def __call__(
        self,
        runtime: MapScannerRuntime,
        next_handler: FullScanMovableNext,
        *,
        enemy_cleared: bool = True,
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
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        self.full_scan_handler(
            runtime,
            FullScanRequest(
                options=options,
                queue=queue,
                must_scan=must_scan,
                mode=mode,
            ),
        )

    @override
    def full_scan_movable(
        self,
        runtime: MapScannerRuntime,
        *,
        enemy_cleared: bool = True,
    ) -> None:
        self.full_scan_movable_handler(runtime, enemy_cleared=enemy_cleared)


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
    def execute(runtime: MapScannerRuntime, request: FullScanRequest) -> None:
        handler(runtime, request, next_handler)

    return execute


def _overlay_full_scan_movable(
    handler: FullScanMovableHandler,
    next_handler: FullScanMovableNext,
) -> FullScanMovableNext:
    def execute(
        runtime: MapScannerRuntime,
        *,
        enemy_cleared: bool = True,
    ) -> None:
        handler(runtime, next_handler, enemy_cleared=enemy_cleared)

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


def _standard_full_scan(runtime: MapScannerRuntime, request: FullScanRequest) -> None:
    STANDARD_CAMPAIGN_MAP_OBSERVER.scanner.full_scan(
        runtime,
        options=request.options,
        queue=request.queue,
        must_scan=request.must_scan,
        mode=request.mode,
    )


def build_campaign_map_observer(instances: Iterable[object]) -> CampaignMapObserver:
    """按 profile 顺序组合地图观察规则；后声明的 contributor 先获得处理权。"""

    camera_repositioning = STANDARD_CAMPAIGN_MAP_OBSERVER.combat.camera_repositioned_after_combat
    full_scan = _standard_full_scan
    full_scan_movable = STANDARD_CAMPAIGN_MAP_OBSERVER.scanner.full_scan_movable
    enemy_searching = STANDARD_CAMPAIGN_MAP_OBSERVER.enemy_searching.appears
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
    return CampaignMapObserver(
        combat=_ComposedCombatMapObserver(camera_repositioning),
        scanner=_ComposedCampaignMapScanner(full_scan, full_scan_movable),
        enemy_searching=_ComposedEnemySearchingObserver(enemy_searching),
    )
