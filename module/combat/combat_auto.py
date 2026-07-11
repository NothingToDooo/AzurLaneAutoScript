from module.base.base import ModuleBase
from module.base.timer import Timer
from module.combat.assets import COMBAT_AUTO, COMBAT_AUTO_133, COMBAT_AUTO_150, COMBAT_AUTO_SWITCH
from module.logger import logger


class CombatAuto(ModuleBase):
    auto_skip_timer = Timer(1)
    auto_click_interval_timer = Timer(1)
    auto_mode_checked = False
    auto_mode_switched = False
    auto_mode_click_timer = Timer(5)

    def combat_joystick_appear(self) -> bool:
        if self.appear(COMBAT_AUTO, offset=(20, 20)):
            return True
        if self.appear(COMBAT_AUTO_133, offset=(20, 20)):
            return True
        return self.appear(COMBAT_AUTO_150, offset=(20, 20))

    def combat_auto_reset(self):
        self.auto_mode_click_timer.reset()
        self.auto_skip_timer.reset()
        self.auto_mode_checked = False
        self.auto_mode_switched = False

    def _combat_auto_should_wait(self):
        if self.auto_mode_checked:
            return True
        if self.auto_mode_click_timer.reached():
            logger.info("Combat auto check timer reached")
            self.auto_mode_checked = True
            return True
        return not self.auto_skip_timer.reached() or not self.auto_click_interval_timer.reached()

    def _combat_auto_click_switch(self):
        self.device.click(COMBAT_AUTO_SWITCH)
        self.auto_click_interval_timer.reset()
        self.auto_mode_switched = True

    def handle_combat_auto(self, auto):
        if self._combat_auto_should_wait():
            return False

        auto_enabled = auto == "combat_auto"
        if self.combat_joystick_appear() == auto_enabled:
            self._combat_auto_click_switch()
            return True

        return False
