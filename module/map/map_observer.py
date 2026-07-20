from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override

from module.logger import logger

if TYPE_CHECKING:
    from module.map.camera import FullScanOptions
    from module.map.map_base import CampaignMap
    from module.map.map_grids import SelectedGrids
    from module.map.type_alias import GridMode
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


@dataclass(frozen=True, slots=True)
class CampaignMapObserver:
    combat: CombatMapObserver
    scanner: CampaignMapScanner


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


STANDARD_CAMPAIGN_MAP_OBSERVER = CampaignMapObserver(
    combat=_StandardCombatMapObserver(),
    scanner=_StandardCampaignMapScanner(),
)
