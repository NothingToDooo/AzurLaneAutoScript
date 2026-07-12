from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.logger import logger
from module.meowfficer.assets import (
    MEOWFFICER_FORT_CHECK,
    MEOWFFICER_FORT_CHORE,
    MEOWFFICER_FORT_ENTER,
    MEOWFFICER_FORT_GET_XP_1,
    MEOWFFICER_FORT_GET_XP_2,
    MEOWFFICER_FORT_RED_DOT,
)
from module.meowfficer.base import MeowfficerBase


class MeowfficerFort(MeowfficerBase):
    def meow_chores(self, *, skip_first_screenshot: bool = True) -> None:
        """在猫窝页循环完成杂务并领取经验。"""
        self.interval_clear(GET_ITEMS_1)
        check_timer = Timer(1, count=2)
        confirm_timer = Timer(1.5, count=4).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 意外退出猫窝时重新进入。
            if self.appear_then_click(MEOWFFICER_FORT_ENTER, offset=(20, 20), interval=3):
                check_timer.reset()
                confirm_timer.reset()
                continue

            if self.appear(MEOWFFICER_FORT_GET_XP_1) or self.appear(MEOWFFICER_FORT_GET_XP_2):
                check_timer.reset()
                confirm_timer.reset()
                continue

            if self.appear(GET_ITEMS_1, offset=5, interval=3):
                self.device.click(MEOWFFICER_FORT_CHECK)
                check_timer.reset()
                confirm_timer.reset()
                continue

            if check_timer.reached():
                is_chore = self.image_color_count(MEOWFFICER_FORT_CHORE, color=(247, 186, 90), threshold=235, count=50)
                check_timer.reset()
                if is_chore:
                    self.device.click(MEOWFFICER_FORT_CHORE)
                    confirm_timer.reset()
                    continue

            if self.appear(MEOWFFICER_FORT_CHECK, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def meow_fort(self) -> bool:
        """在指挥喵主页处理对所有指挥喵生效的猫窝杂务。"""
        if not self.appear(MEOWFFICER_FORT_RED_DOT):
            return False
        logger.hr("Meowfficer fort", level=1)

        self.meow_enter(MEOWFFICER_FORT_ENTER, check_button=MEOWFFICER_FORT_CHECK)

        self.meow_chores()

        self.meow_menu_close()

        return True
