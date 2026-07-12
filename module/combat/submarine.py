from module.base.base import ModuleBase
from module.base.timer import Timer
from module.combat.assets import (
    SUBMARINE_AVAILABLE_CHECK_1,
    SUBMARINE_AVAILABLE_CHECK_2,
    SUBMARINE_CALLED,
    SUBMARINE_READY,
)
from module.logger import logger

_SUBMARINE_SKIP_MODES = {"do_not_use", "hunt_only", "hunt_and_boss"}


class SubmarineCall(ModuleBase):
    submarine_call_flag = False
    submarine_call_timer = Timer(5)
    submarine_call_click_timer = Timer(1)

    def submarine_call_reset(self) -> None:
        """进入战斗执行阶段后重置潜艇呼叫状态。"""
        self.submarine_call_timer.reset()
        self.submarine_call_flag = False

    def _submarine_call_should_wait(self, submarine: str) -> bool:
        if self.submarine_call_flag:
            return True
        if submarine in _SUBMARINE_SKIP_MODES:
            self.submarine_call_flag = True
            return True
        if self.submarine_call_timer.reached():
            logger.info("Submarine call timer reached")
            self.submarine_call_flag = True
            return True
        if not self.appear(SUBMARINE_AVAILABLE_CHECK_1) or not self.appear(SUBMARINE_AVAILABLE_CHECK_2):
            return True
        if self.appear(SUBMARINE_CALLED):
            logger.info("Submarine called")
            self.submarine_call_flag = True
            return True
        return False

    def handle_submarine_call(self, submarine: str = "do_not_use") -> bool:
        if self._submarine_call_should_wait(submarine) or not self.submarine_call_click_timer.reached():
            return False

        if not self.appear_then_click(SUBMARINE_READY):
            logger.info("Incorrect submarine icon")
            self.device.click(SUBMARINE_READY)
        logger.info("Call submarine")
        self.submarine_call_click_timer.reset()
        return True
