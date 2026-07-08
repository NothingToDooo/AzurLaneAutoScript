from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.config.utils import get_server_next_update
from module.logger import logger
from module.meowfficer import assets as meow_assets
from module.ui.assets import MEOWFFICER_CHECK, MEOWFFICER_INFO
from module.ui.ui import UI


class MeowfficerBase(UI):
    def meow_additional(self):
        """处理页面切换间可能出现的额外弹窗。"""
        return self.appear_then_click(MEOWFFICER_INFO, offset=(30, 30), interval=3)

    def meow_enter(self, click_button, check_button, skip_first_screenshot=True):
        """
        Enters sub-page, handle MEOWFFICER_INFO and mistaken clicks

        Pages:
            in: page_meowfficer
            out: check_button
        """
        accident_page = [
            meow_assets.MEOWFFICER_TRAIN_START,
            meow_assets.MEOWFFICER_BUY,
            meow_assets.MEOWFFICER_FORT_CHECK,
        ]
        accident_page = [page for page in accident_page if page != check_button]
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束。
            if self.appear(check_button, offset=(20, 20)):
                break
            # 点击。
            if self.appear_then_click(click_button, offset=(20, 20), interval=3):
                continue
            # 误点击。
            if self.meow_additional():
                continue
            for button in accident_page:
                if self.appear(button, offset=(20, 20), interval=3):
                    self.device.click(MEOWFFICER_CHECK)
                    self.interval_clear(click_button)
                    break

    def meow_menu_close(self, skip_first_screenshot=True):
        """
        Exit from any meowfficer menu popups

        Pages:
            in: MEOWFFICER_FORT_CHECK, MEOWFFICER_BUY, MEOWFFICER_TRAIN_START, etc
            out: page_meowfficer
        """
        logger.hr("Meowfficer menu close")
        click_timer = Timer(3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._meow_menu_closed():
                break
            if self._meow_menu_safe_click(click_timer):
                continue
            if self._meow_menu_handle_known_page(click_timer):
                continue
            if self._meow_menu_handle_popup(click_timer):
                continue

    def _meow_menu_closed(self):
        return self.match_template_color(MEOWFFICER_CHECK, offset=(20, 20))

    def _meow_menu_safe_click(self, click_timer):
        if not click_timer.reached():
            return False

        # MEOWFFICER_CHECK 可以安全点击。
        self.device.click(MEOWFFICER_CHECK)
        click_timer.reset()
        return True

    def _meow_menu_handle_known_page(self, click_timer):
        for button in (
            meow_assets.MEOWFFICER_FORT_CHECK,
            meow_assets.MEOWFFICER_BUY,
            meow_assets.MEOWFFICER_TRAIN_FILL_QUEUE,
            meow_assets.MEOWFFICER_TRAIN_FINISH_ALL,
        ):
            if self.appear(button, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                return True
        return False

    def _meow_menu_handle_popup(self, click_timer):
        for button in (meow_assets.MEOWFFICER_CONFIRM, meow_assets.MEOWFFICER_CANCEL):
            if self.appear(button, offset=(40, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                return True
        if self.appear_then_click(GET_ITEMS_1, offset=5, interval=3):
            click_timer.reset()
            return True
        if not self.meow_additional():
            return False

        click_timer.reset()
        return True

    def handle_meow_popup_confirm(self):
        """确认猫窝弹窗并允许继续操作。"""
        return self.appear_then_click(meow_assets.MEOWFFICER_CONFIRM, offset=(40, 20), interval=5)

    def handle_meow_popup_cancel(self):
        """取消猫窝弹窗或拒绝当前操作。"""
        return self.appear_then_click(meow_assets.MEOWFFICER_CANCEL, offset=(40, 20), interval=5)

    def handle_meow_popup_dismiss(self):
        """
        Dismiss the popup; neither confirm
        or cancel the action

        Returns:
            bool:
        """
        if self.appear(meow_assets.MEOWFFICER_CONFIRM, offset=(40, 20), interval=5) or self.appear(
            meow_assets.MEOWFFICER_CANCEL, offset=(40, 20), interval=5
        ):
            self.device.click(MEOWFFICER_CHECK)
            return True
        return False

    def meow_is_sunday(self):
        """
        datetime argument is the next server update of,
        today's run. So check for Monday's weekday value
        (0) rather than Sunday's weekday value (6)

        Returns:
            bool:
        """
        return get_server_next_update(self.config.Scheduler_ServerUpdate).weekday() == 0
