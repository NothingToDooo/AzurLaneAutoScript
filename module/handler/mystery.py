from module.base.timer import Timer
from module.base.utils import area_cross_area
from module.combat.assets import GET_ITEMS_1
from module.handler.assets import GET_AMMO, MYSTERY_ITEM
from module.handler.enemy_searching import EnemySearchingHandler
from module.handler.strategy import StrategyHandler
from module.logger import logger


class MysteryHandler(StrategyHandler, EnemySearchingHandler):
    _get_ammo_log_timer = Timer(3)
    carrier_count = 0

    def handle_mystery(self, button=None):
        """
        Args:
            button (optional): Button to click when get_items.
                Can be destination grid which makes the bot more like human.
        """
        if self.handle_mystery_items(button=button):
            return "get_item"
        if self.handle_mystery_ammo():
            return "get_ammo"
        if self.handle_mystery_carrier():
            return "get_carrier"

        return False

    def handle_mystery_items(self, button=None):
        """
        Args:
            button: Button to click when get_items.
                Can be destination grid which makes the bot more like human.

        Returns:
            bool: If handled.
        """
        if not self.config.MAP_MYSTERY_MAP_CLICK:
            button = MYSTERY_ITEM
        if button is None or area_cross_area(button.button, MYSTERY_ITEM.area, threshold=5):
            button = MYSTERY_ITEM

        if self.appear(GET_ITEMS_1, offset=5):
            logger.attr("Mystery", "Get item")
            self.device.click(button)
            self.device.sleep(0.5)
            self.device.screenshot()
            self.strategy_close()
            return True

        return False

    def handle_mystery_ammo(self):
        """
        Returns:
            bool: 是否已处理。
        """
        if self.info_bar_count() and self._get_ammo_log_timer.reached() and self.appear(GET_AMMO):
            logger.attr("Mystery", "Get ammo")
            self._get_ammo_log_timer.reset()
            return True

        return False

    def handle_mystery_carrier(self):
        """
        Returns:
            bool: 是否已处理。
        """
        if self.config.MAP_MYSTERY_HAS_CARRIER and self.is_in_map() and self.enemy_searching_appear():
            logger.attr("Mystery", "Get carrier")
            self.carrier_count += 1
            self.handle_in_map_with_enemy_searching()
            return True

        return False
