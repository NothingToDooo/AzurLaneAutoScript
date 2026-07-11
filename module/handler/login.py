from module.base.timer import Timer
from module.device.control_options import SwipeVectorOptions
from module.handler import assets as handler_assets
from module.logger import logger
from module.map.assets import WITHDRAW
from module.ui.assets import (
    BACK_ARROW,
    CAMPAIGN_CHECK,
    CAMPAIGN_MENU_CHECK,
    EVENT_CHECK,
    EVENT_LIST_CHECK,
    GOTO_MAIN,
    SP_CHECK,
)
from module.ui.page import page_campaign_menu
from module.ui.ui import UI


class LoginHandler(UI):
    def _handle_app_login(self):
        """从任意页面回到 page_main；可能抛出 GameStuckError、GameTooManyClickError 或 GameNotRunningError。"""
        logger.hr("App login")

        confirm_timer = Timer(1.5, count=4).start()
        orientation_timer = Timer(5)
        login_success = False
        self.device.stuck_record_clear()
        self.device.click_record_clear()

        while 1:
            if not login_success and orientation_timer.reached():
                # 启动应用后屏幕可能会旋转。
                self.device.get_orientation()
                orientation_timer.reset()

            self.device.screenshot()

            if self._login_main_confirmed(confirm_timer):
                break

            login_success = self._handle_login_button(login_success)
            action = self._handle_login_screen_actions(login_success)
            if action == "success":
                return True
            if action == "continue":
                continue

        return True

    def _login_main_confirmed(self, confirm_timer):
        if self.is_in_main():
            if confirm_timer.reached():
                logger.info("Login to main confirm")
                return True
        else:
            confirm_timer.reset()
        return False

    def _handle_login_button(self, login_success):
        if not self.match_template_color(handler_assets.LOGIN_CHECK, offset=(30, 30), interval=5):
            return login_success

        self.device.click(handler_assets.LOGIN_CHECK)
        if not login_success:
            logger.info("Login success")
        return True

    def _handle_android_no_respond(self):
        if not self.appear(handler_assets.ANDROID_NO_RESPOND, offset=(30, 30), interval=5):
            return False

        logger.warning("Emulator no respond")
        self.device.click_record_add(handler_assets.ANDROID_NO_RESPOND)
        self.device.click_record_check()
        self.device.click(handler_assets.ANDROID_NO_RESPOND, control_check=False)
        return True

    def _handle_login_screen_actions(self, login_success):
        handlers = (
            self._handle_android_no_respond,
            self._handle_login_announcements,
            lambda: self._handle_pre_login_user_agreement(login_success),
            self._handle_return_player_popups,
            self._handle_login_popups,
        )
        for handler in handlers:
            if handler():
                return "continue"
        if self.ui_page_main_popups(get_ship=login_success):
            return "success"
        # 始终回到 page_main。
        if self._handle_goto_main():
            return "continue"
        return None

    def _handle_login_announcements(self):
        if self.appear_then_click(handler_assets.LOGIN_ANNOUNCE, offset=(30, 30), interval=5):
            return True
        if self.appear_then_click(handler_assets.LOGIN_ANNOUNCE_2, offset=(30, 30), interval=5):
            return True
        if self.appear(EVENT_LIST_CHECK, offset=(30, 30), interval=5):
            self.device.click(BACK_ARROW)
            return True
        if self.appear_then_click(handler_assets.MAINTENANCE_ANNOUNCE, offset=(30, 30), interval=5):
            return True
        return bool(self.appear_then_click(handler_assets.LOGIN_GAME_UPDATE, offset=(30, 30), interval=5))

    def _handle_pre_login_user_agreement(self, login_success):
        return bool(not login_success and self.handle_cn_user_agreement())

    def _handle_return_player_popups(self):
        return (
            self.appear_then_click(handler_assets.LOGIN_RETURN_SIGN, offset=(30, 30), interval=5)
            or self.appear_then_click(handler_assets.LOGIN_RETURN_INFO, offset=(30, 30), interval=5)
            or self.appear_then_click(handler_assets.AVATAR_EXPIRED, offset=(30, 30), interval=5)
        )

    def _handle_login_popups(self):
        return self.handle_popup_confirm("LOGIN") or self.handle_urgent_commission()

    def _handle_goto_main(self):
        return self.appear_then_click(GOTO_MAIN, offset=(30, 30), interval=5)

    _user_agreement_timer = Timer(1, count=2)

    def handle_cn_user_agreement(self):
        if not self._user_agreement_timer.reached():
            return False

        right = self.image_color_button(
            area=(640, 360, 1280, 720),
            color=(78, 189, 234),
            color_threshold=245,
            encourage=25,
            name="AGREEMENT_CONFIRM",
        )
        if right is None:
            return False
        # 2026.04.17 不再需要滚动，点击确认前只做一次空滑动。
        # 右半屏有蓝色按钮、左半屏没有时，是确认按钮。
        # 两边都有时，是中间的登录确认蓝色按钮。
        left = self.image_color_button(
            area=(0, 360, 640, 720), color=(78, 189, 234), color_threshold=245, encourage=25, name="AGREEMENT_CONFIRM"
        )
        if left is None:
            box = (350, 230, 920, 430)
            self.device.swipe_vector((0, -150), SwipeVectorOptions(box=box, name="AGREEMENT_SCROLL"))
            self.device.swipe_vector((0, -150), SwipeVectorOptions(box=box, name="AGREEMENT_SCROLL"))
            self.device.click(right)
            self._user_agreement_timer.reset()
            return True
        self.device.click(right)
        self._user_agreement_timer.reset()
        return True

    def handle_app_login(self):
        """可能抛出 GameStuckError、GameTooManyClickError 或 GameNotRunningError。"""
        logger.info("handle_app_login")
        self.device.screenshot_interval_set(1.0)
        try:
            self._handle_app_login()
        finally:
            self.device.screenshot_interval_set()

    def app_stop(self):
        logger.hr("App stop")
        self.device.app_stop()

    def app_start(self):
        logger.hr("App start")
        self.device.app_start()
        self.handle_app_login()

    def app_restart(self):
        logger.hr("App restart")
        self.device.app_stop()
        self.device.app_start()
        self.handle_app_login()
        self.config.task_delay(server_update=True)

    def ensure_no_unfinished_campaign(self):
        """退出未完成战役；页面进出均为 page_main。"""

        def ensure_campaign_retreat():
            if self.appear_then_click(WITHDRAW, offset=(30, 30), interval=5):
                return True
            return bool(self.handle_popup_confirm("WITHDRAW"))

        def in_campaign():
            return (
                self.appear(CAMPAIGN_CHECK, offset=(30, 30))
                or self.appear(CAMPAIGN_MENU_CHECK, offset=(30, 30))
                or self.appear(EVENT_CHECK, offset=(30, 30))
                or self.appear(SP_CHECK, offset=(30, 30))
            )

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if in_campaign():
                break

            if self.ui_main_appear_then_click(page_campaign_menu, interval=3):
                continue
            if ensure_campaign_retreat():
                continue

        self.ui_goto_main()
