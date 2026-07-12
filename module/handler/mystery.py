from typing import TYPE_CHECKING, Literal

from module.base.timer import Timer
from module.base.utils import area_cross_area
from module.combat.assets import GET_ITEMS_1
from module.handler.assets import GET_AMMO, MYSTERY_ITEM
from module.handler.enemy_searching import EnemySearchingHandler
from module.handler.strategy import StrategyHandler
from module.logger import logger

if TYPE_CHECKING:
    from module.device.control import ButtonTarget
    from module.map_detection.grid import Grid


class MysteryHandler(StrategyHandler, EnemySearchingHandler):
    _get_ammo_log_timer = Timer(3)
    carrier_count = 0

    def handle_mystery(self, button: Grid | None = None) -> Literal["get_item", "get_ammo", "get_carrier", False]:
        """button 可传目标格作为领取点击位置，使点击轨迹更自然。"""
        if self.handle_mystery_items(button=button):
            return "get_item"
        if self.handle_mystery_ammo():
            return "get_ammo"
        if self.handle_mystery_carrier():
            return "get_carrier"

        return False

    def handle_mystery_items(self, button: Grid | None = None) -> bool:
        """button 可传目标格作为领取点击位置，使点击轨迹更自然。"""
        if not self.config.MAP_MYSTERY_MAP_CLICK:
            click_target: ButtonTarget = MYSTERY_ITEM
        elif button is None or area_cross_area(button.button, MYSTERY_ITEM.area, threshold=5):
            click_target = MYSTERY_ITEM
        else:
            click_target = button

        if self.appear(GET_ITEMS_1, offset=5):
            logger.attr("Mystery", "Get item")
            self.device.click(click_target)
            self.device.sleep(0.5)
            self.device.screenshot()
            self.strategy_close()
            return True

        return False

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
