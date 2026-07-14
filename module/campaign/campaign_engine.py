from typing import TYPE_CHECKING

from module.base.decorator import cached_property
from module.campaign.campaign_ui import CampaignUI
from module.combat.auto_search_combat import AutoSearchCombat
from module.logger import logger
from module.map.map import Map

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap


class CampaignEngine(CampaignUI, Map, AutoSearchCombat):
    """提供关卡 UI、地图与战斗原语，不负责业务 turn 编排。"""

    FUNCTION_NAME_BASE = "battle_"
    MAP: CampaignMap

    @cached_property
    def _map_battle(self) -> int:
        for data in self.MAP.spawn_data:
            if "boss" in data:
                if "battle" in data:
                    return data["battle"] + 1
                logger.warning("No battle count in spawn_data")

        logger.warning("No boss data found in spawn_data")
        return 0

    @property
    def map_battle_count(self) -> int:
        """返回从进图到 Boss 战结束的预计战斗次数。"""
        return self._map_battle

    def auto_search_execute_a_battle(self) -> None:
        logger.hr(f"{self.FUNCTION_NAME_BASE}{self.battle_count}", level=2)
        self.auto_search_moving()
        self.auto_search_combat(fleet_index=self.fleet_show_index)
        self.battle_count += 1
