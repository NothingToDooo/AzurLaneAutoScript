from module.combat.assets import BATTLE_PREPARATION
from module.event_hospital import assets as hospital_assets
from module.logger import logger
from module.minigame.assets import BACK
from module.raid.assets import RAID_FLEET_PREPARATION
from module.ui.page import page_hospital
from module.ui.ui import UI


class HospitalUI(UI):
    def is_in_clue(self, interval=0):
        return self.appear(hospital_assets.HOSIPITAL_CLUE_CHECK, offset=(20, 20), interval=interval)

    def handle_get_clue(self):
        """
        Returns:
            bool: If clicked
        """
        if self.appear_then_click(hospital_assets.GET_CLUE, offset=(20, 20), interval=1):
            return True
        if self.appear(hospital_assets.GET_CLUE_TEXT, offset=(20, 20), interval=1):
            logger.info(f"{hospital_assets.GET_CLUE_TEXT} -> {hospital_assets.GET_CLUE}")
            self.device.click(hospital_assets.GET_CLUE)
            return True
        return False

    def handle_clue_exit(self):
        """
        Returns:
            bool: 是否发生点击。
        """
        if self.appear_then_click(hospital_assets.HOSPITAL_BATTLE_EXIT, offset=(20, 20), interval=2):
            return True
        if self.ui_page_appear(page_hospital, interval=2):
            logger.info(f"{page_hospital} -> {hospital_assets.HOSIPITAL_GOTO_CLUE}")
            self.device.click(hospital_assets.HOSIPITAL_GOTO_CLUE)
            return True
        if self.appear(BATTLE_PREPARATION, offset=(30, 20), interval=2):
            logger.info(f"{BATTLE_PREPARATION} -> {BACK}")
            self.device.click(BACK)
            return True
        if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30), interval=2):
            logger.info(f"{RAID_FLEET_PREPARATION} -> {BACK}")
            self.device.click(BACK)
            return True
        return bool(self.handle_get_clue())
