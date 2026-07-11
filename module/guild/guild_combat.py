from module.combat.combat import Combat
from module.guild.assets import BATTLE_STATUS_CF, EXP_INFO_CF


class GuildCombat(Combat):
    def handle_battle_status(self):
        if self.is_combat_executing():
            return False
        if super().handle_battle_status():
            return True
        if self.appear(BATTLE_STATUS_CF, interval=self.battle_status_click_interval):
            self.device.sleep((0.25, 0.5))
            self.device.click(BATTLE_STATUS_CF)
            return True

        return False

    def handle_get_items(self):
        if super().handle_get_items():
            self.interval_reset(BATTLE_STATUS_CF)
            return True
        return False

    def handle_exp_info(self):
        if self.is_combat_executing():
            return False
        if super().handle_exp_info():
            return True
        if self.appear_then_click(EXP_INFO_CF):
            self.device.sleep((0.25, 0.5))
            return True

        return False
