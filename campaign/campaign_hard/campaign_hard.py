from typing import Literal

from module.base.timer import Timer
from module.campaign.campaign_base import CampaignBase
from module.exception import CampaignEnd
from module.hard.equipment import HardEquipment
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION
from module.ui.assets import CAMPAIGN_CHECK

HARD_BOSS_CLEAR_MESSAGE = "BOSS Clear."


class Config:
    MAP_HAS_AMBUSH = False
    ENABLE_EMOTION_REDUCE = False
    ENABLE_HP_BALANCE = False


class Campaign(CampaignBase, HardEquipment):
    _EXPECTED_END: Literal["in_stage"] = "in_stage"

    def _expected_end(self, expected: str) -> Literal["in_stage"]:
        del expected
        return self._EXPECTED_END

    def clear_boss(self) -> bool:
        grids = self.map.select(is_boss=True)
        grids = grids.add(self.map.select(may_boss=True, is_enemy=True))
        logger.info(f"May boss: {self.map.select(may_boss=True)}")
        logger.info(f"May boss and is enemy: {self.map.select(may_boss=True, is_enemy=True)}")
        logger.info(f"Is boss: {self.map.select(is_boss=True)}")
        if grids:
            logger.hr("Clear BOSS")
            grids = grids.sort("weight", "cost")
            logger.info(f"Grids: {grids}")
            self._goto(grids[0], expected="boss")
            raise CampaignEnd(HARD_BOSS_CLEAR_MESSAGE)

        logger.warning("BOSS not detected, trying all boss spawn point.")
        self.clear_potential_boss()

        return False

    def equipment_take_off_when_finished(self) -> bool:
        if self.config.FLEET_HARD_EQUIPMENT is None:
            return False
        if not self.equipment_has_take_on:
            return False

        logger.info("equipment_take_off_when_finished")
        campaign_timer = Timer(2)
        map_timer = Timer(1)
        fleet_timer = Timer(1)

        while 1:
            self.device.screenshot()

            if campaign_timer.reached() and self.is_in_stage():
                self.device.click(self.ENTRANCE)
                campaign_timer.reset()
                continue

            if map_timer.reached() and self.appear(MAP_PREPARATION, offset=(20, 20)):
                self.device.click(MAP_PREPARATION)
                map_timer.reset()
                campaign_timer.reset()
                continue

            if fleet_timer.reached() and self.appear(FLEET_PREPARATION, offset=(20, 50)):
                self.equipment_take_off()
                self.ui_back(check_button=CAMPAIGN_CHECK, appear_button=FLEET_PREPARATION)
                break

            if self.handle_retirement():
                continue

        return True
