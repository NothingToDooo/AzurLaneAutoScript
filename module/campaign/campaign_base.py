from contextlib import suppress
from typing import TYPE_CHECKING

from module.base.decorator import cached_property
from module.campaign.campaign_ui import CampaignUI
from module.combat.auto_search_combat import AutoSearchCombat
from module.exception import CampaignEnd, MapEnemyMoved, ScriptError
from module.logger import logger
from module.map.map import Map

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap

NO_COMBAT_EXECUTED_MESSAGE = "No combat executed."
BATTLE_FUNCTION_EXHAUSTED_MESSAGE = "Battle function exhausted."


class CampaignBase(CampaignUI, Map, AutoSearchCombat):
    FUNCTION_NAME_BASE = "battle_"
    MAP: CampaignMap

    def battle_default(self):
        if self.clear_enemy():
            return True

        logger.warning("No battle executed.")
        return False

    def battle_boss(self):
        if self.brute_clear_boss():
            return True

        logger.warning("No battle executed.")
        return False

    def battle_function(self):
        if self.config.MAP_CLEAR_ALL_THIS_TIME:
            return self._battle_clear_all()
        if self.config.POOR_MAP_DATA:
            return self._battle_with_poor_map_data()
        return self._battle_by_count()

    def _battle_with_poor_map_data(self):
        logger.info("Using function: battle_with_poor_map_data")
        if self.fleet_2_break_siren_caught():
            return True
        self.clear_all_mystery()

        if self.battle_count >= 3:
            self.pick_up_ammo()

        if self.map.select(is_boss=True):
            if self.brute_clear_boss():
                return True
        else:
            if self.clear_siren():
                return True
            return self.clear_enemy()

        return False

    def _battle_clear_all(self):
        logger.info("Using function: clear_all")
        if self.fleet_2_break_siren_caught():
            return True
        self.clear_all_mystery()

        if self.battle_count >= 3:
            self.pick_up_ammo()

        remain = (
            self.map.select(is_enemy=True)
            .add(self.map.select(is_siren=True))
            .add(self.map.select(is_fortress=True))
            .delete(self.map.select(is_boss=True))
        )
        logger.info(f"Enemy remain: {remain}")
        if remain.count > 0:
            return self._clear_remaining_enemy_for_clear_all()
        return self.battle_boss()

    def _clear_remaining_enemy_for_clear_all(self):
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            if self.clear_any_enemy(sort=("cost_2",)):
                return True
            return self.battle_default()
        if self.clear_bouncing_enemy():
            return True
        if self.clear_siren():
            return True
        self.clear_mechanism()
        return self.battle_default()

    def _battle_by_count(self):
        func_name = self.FUNCTION_NAME_BASE + "default"
        for extra_battle in range(10):
            candidate = self.FUNCTION_NAME_BASE + str(self.battle_count - extra_battle)
            if hasattr(self, candidate):
                func_name = candidate
                break

        logger.info(f"Using function: {func_name}")
        return getattr(self, func_name)()

    def execute_a_battle(self):
        logger.hr(f"{self.FUNCTION_NAME_BASE}{self.battle_count}", level=2)
        prev = self.battle_count
        result = False
        for _ in range(10):
            try:
                result = self.battle_function()
                break
            except MapEnemyMoved:
                if self.battle_count > prev:
                    result = True
                    break
                continue

        if not result:
            logger.warning("ScriptError, No combat executed.")
            if self.config.Error_HandleError:
                logger.warning("ScriptError, No combat executed, Withdrawing")
                self.withdraw()
            else:
                raise ScriptError(NO_COMBAT_EXECUTED_MESSAGE)

        return result

    def run(self):
        logger.hr(self.ENTRANCE, level=2)

        self.emotion.check_reduce(self._map_battle)
        self.ENTRANCE.area = self.ENTRANCE.button
        self.enter_map(self.ENTRANCE, mode=self.config.Campaign_Mode)

        if not self.map_is_auto_search:
            self.handle_map_fleet_lock()
            self.map_init(self.MAP)
        else:
            self.map = self.MAP
            self.battle_count = 0
            self.lv_reset()
            self.lv_get()

        for _ in range(20):
            try:
                if not self.map_is_auto_search:
                    self.execute_a_battle()
                else:
                    self.auto_search_execute_a_battle()
            except CampaignEnd:
                logger.hr("Campaign end")
                return True

        logger.warning("Battle function exhausted.")
        if self.config.Error_HandleError:
            logger.warning("ScriptError, Battle function exhausted, Withdrawing")
            with suppress(CampaignEnd):
                self.withdraw()
            return False
        raise ScriptError(BATTLE_FUNCTION_EXHAUSTED_MESSAGE)

    @cached_property
    def _map_battle(self):
        for data in self.MAP.spawn_data:
            if "boss" in data:
                if "battle" in data:
                    return data["battle"] + 1
                logger.warning("No battle count in spawn_data")

        logger.warning("No boss data found in spawn_data")
        return 0

    def auto_search_execute_a_battle(self):
        logger.hr(f"{self.FUNCTION_NAME_BASE}{self.battle_count}", level=2)
        self.auto_search_moving()
        self.auto_search_combat(fleet_index=self.fleet_show_index)
        self.battle_count += 1
