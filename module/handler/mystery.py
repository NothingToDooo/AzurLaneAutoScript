from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.handler.assets import GET_AMMO
from module.handler.enemy_searching import EnemySearchingHandler
from module.handler.mystery_item import (
    STANDARD_MYSTERY_ITEM_SERVICE,
    MysteryItemOutcome,
    MysteryItemRequest,
    MysteryItemService,
    MysteryKind,
    MysteryResult,
)
from module.handler.strategy import StrategyHandler
from module.logger import logger

if TYPE_CHECKING:
    from module.map_detection.grid import Grid


class MysteryHandler(StrategyHandler, EnemySearchingHandler):
    _get_ammo_log_timer = Timer(3)
    _mystery_item_service: MysteryItemService = STANDARD_MYSTERY_ITEM_SERVICE
    carrier_count = 0

    def handle_mystery(self, button: Grid | None = None) -> MysteryResult | None:
        """button 可传目标格作为领取点击位置，使点击轨迹更自然。"""
        item = self.handle_mystery_items(button=button)
        if item.handled:
            return MysteryResult(MysteryKind.GET_ITEM, item.counts_toward_mystery)
        if self.handle_mystery_ammo():
            return MysteryResult(MysteryKind.GET_AMMO, counts_toward_mystery=True)
        if self.handle_mystery_carrier():
            return MysteryResult(MysteryKind.GET_CARRIER, counts_toward_mystery=True)

        return None

    def handle_mystery_items(self, button: Grid | None = None) -> MysteryItemOutcome:
        """button 可传目标格作为领取点击位置，使点击轨迹更自然。"""
        return self._mystery_item_service.handle(self, MysteryItemRequest(button=button))

    def handle_mystery_ammo(self) -> bool:
        if self.info_bar_count() and self._get_ammo_log_timer.reached() and self.appear(GET_AMMO):
            logger.attr("Mystery", "Get ammo")
            self._get_ammo_log_timer.reset()
            return True

        return False

    def handle_mystery_carrier(self) -> bool:
        if self.config.MAP_MYSTERY_HAS_CARRIER and self.is_in_map() and self.enemy_searching_appear():
            logger.attr("Mystery", "Get carrier")
            self.carrier_count += 1
            self.handle_in_map_with_enemy_searching()
            return True

        return False
