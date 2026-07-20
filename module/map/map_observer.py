from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, override

from module.handler.assets import MAP_ENEMY_SEARCHING
from module.logger import logger

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray
    from module.map.camera import FullScanOptions
    from module.map.map_base import CampaignMap
    from module.map.map_grids import SelectedGrids
    from module.map.type_alias import FleetLocation, GridLocation, GridMode
    from module.map_detection.grid_info import GridInfo


class MapObserverRuntime(Protocol):
    battle_count: int
    map: CampaignMap


class CombatMapObserver(Protocol):
    """判断战斗结束后的地图镜头是否发生了需要重定位的移动。"""

    def camera_repositioned_after_combat(
        self,
        runtime: MapObserverRuntime,
        destination: GridInfo,
    ) -> bool: ...


class MapScannerRuntime(Protocol):
    map: CampaignMap

    def _standard_full_scan(
        self,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None: ...

    def _standard_full_scan_movable(self, *, enemy_cleared: bool = True) -> None: ...


class CampaignMapScanner(Protocol):
    def full_scan(
        self,
        runtime: MapScannerRuntime,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None: ...

    def full_scan_movable(
        self,
        runtime: MapScannerRuntime,
        *,
        enemy_cleared: bool = True,
    ) -> None: ...


class EnemySearchingObserver(Protocol):
    """识别当前截图中的寻敌动画；地图页判定由调用者统一负责。"""

    def appears(
        self,
        image: ImageArray,
        *,
        overlay_transparency_threshold: float,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class InSightRequest:
    """已经规范化的视野请求。"""

    location: GridLocation
    sight: tuple[int, int, int, int] | None = None


class MapViewportRuntime(Protocol):
    def focus_to(
        self,
        location: GridLocation,
        swipe_limit: GridLocation = (4, 3),
    ) -> None: ...

    def _standard_in_sight(self, request: InSightRequest) -> None: ...


class CampaignMapViewport(Protocol):
    """调整地图视野，但不负责把调用参数规范化。"""

    def in_sight(self, runtime: MapViewportRuntime, request: InSightRequest) -> None: ...


class FleetLocatorRuntime(Protocol):
    @property
    def _fleet_2_enabled(self) -> bool: ...

    @property
    def fleet_current(self) -> FleetLocation: ...

    def _set_fleet_location(
        self,
        index: Literal[1, 2],
        location: GridLocation,
    ) -> None: ...

    def _standard_find_current_fleet(self) -> FleetLocation: ...


class CampaignFleetLocator(Protocol):
    """定位当前舰队，不暴露旧 runtime string operation。"""

    def find_current_fleet(self, runtime: FleetLocatorRuntime) -> FleetLocation: ...


@dataclass(frozen=True, slots=True)
class CampaignMapObserver:
    combat: CombatMapObserver
    scanner: CampaignMapScanner
    enemy_searching: EnemySearchingObserver
    viewport: CampaignMapViewport
    fleet_locator: CampaignFleetLocator


class _StandardCombatMapObserver(CombatMapObserver):
    @override
    def camera_repositioned_after_combat(
        self,
        runtime: MapObserverRuntime,
        destination: GridInfo,
    ) -> bool:
        del destination
        for data in runtime.map.spawn_data:
            if data.get("battle") == runtime.battle_count and data.get("boss", 0):
                logger.info("Catch camera re-positioning after boss appear")
                return True
        return False


class _StandardCampaignMapScanner(CampaignMapScanner):
    @override
    def full_scan(
        self,
        runtime: MapScannerRuntime,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        runtime._standard_full_scan(  # ruff:ignore[private-member-access] - 标准 scanner 只负责调用 Fleet 私有算法原语。
            options=options,
            queue=queue,
            must_scan=must_scan,
            mode=mode,
        )

    @override
    def full_scan_movable(
        self,
        runtime: MapScannerRuntime,
        *,
        enemy_cleared: bool = True,
    ) -> None:
        runtime._standard_full_scan_movable(  # ruff:ignore[private-member-access] - 标准 scanner 只负责调用 Fleet 私有算法原语。
            enemy_cleared=enemy_cleared
        )


class _StandardEnemySearchingObserver(EnemySearchingObserver):
    @override
    def appears(
        self,
        image: ImageArray,
        *,
        overlay_transparency_threshold: float,
    ) -> bool:
        del overlay_transparency_threshold
        return MAP_ENEMY_SEARCHING.match_luma(image, offset=(5, 5))


class _StandardCampaignMapViewport(CampaignMapViewport):
    @override
    def in_sight(self, runtime: MapViewportRuntime, request: InSightRequest) -> None:
        runtime._standard_in_sight(  # ruff:ignore[private-member-access] - 标准 viewport 只负责调用 Camera 私有算法原语。
            request
        )


class _StandardCampaignFleetLocator(CampaignFleetLocator):
    @override
    def find_current_fleet(self, runtime: FleetLocatorRuntime) -> FleetLocation:
        return runtime._standard_find_current_fleet()  # ruff:ignore[private-member-access] - 标准 locator 只负责调用 Fleet 私有算法原语。


STANDARD_CAMPAIGN_MAP_OBSERVER = CampaignMapObserver(
    combat=_StandardCombatMapObserver(),
    scanner=_StandardCampaignMapScanner(),
    enemy_searching=_StandardEnemySearchingObserver(),
    viewport=_StandardCampaignMapViewport(),
    fleet_locator=_StandardCampaignFleetLocator(),
)
