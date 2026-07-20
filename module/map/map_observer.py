from typing import TYPE_CHECKING, Protocol, override

from module.logger import logger

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap
    from module.map_detection.grid_info import GridInfo


class MapObserverRuntime(Protocol):
    battle_count: int
    map: CampaignMap


class CampaignMapObserver(Protocol):
    """判断战斗结束后的地图镜头是否发生了需要重定位的移动。"""

    def camera_repositioned_after_combat(
        self,
        runtime: MapObserverRuntime,
        destination: GridInfo,
    ) -> bool: ...


class _StandardCampaignMapObserver(CampaignMapObserver):
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


STANDARD_CAMPAIGN_MAP_OBSERVER: CampaignMapObserver = _StandardCampaignMapObserver()
