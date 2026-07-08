from module.base.timer import Timer
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
        """
        Pages:
            in: Any page
            out: page_main

        Raises:
            GameStuckError:
            GameTooManyClickError:
            GameNotRunningError:
        """
        logger.hr("App login")

        confirm_timer = Timer(1.5, count=4).start()
        orientation_timer = Timer(5)
        login_success = False
        self.device.stuck_record_clear()
        self.device.click_record_clear()

        while 1:
            # 监控设备旋转。
            if not login_success and orientation_timer.reached():
                # 启动应用后屏幕可能会旋转。
                self.device.get_orientation()
                orientation_timer.reset()

            self.device.screenshot()

            # 结束。
            if self.is_in_main():
                if confirm_timer.reached():
                    logger.info("Login to main confirm")
                    break
            else:
                confirm_timer.reset()

            # 登录。
            if self.match_template_color(handler_assets.LOGIN_CHECK, offset=(30, 30), interval=5):
                self.device.click(handler_assets.LOGIN_CHECK)
                if not login_success:
                    logger.info("Login success")
                    login_success = True
            if self.appear(handler_assets.ANDROID_NO_RESPOND, offset=(30, 30), interval=5):
                logger.warning("Emulator no respond")
                self.device.click_record_add(handler_assets.ANDROID_NO_RESPOND)
                self.device.click_record_check()
                self.device.click(handler_assets.ANDROID_NO_RESPOND, control_check=False)
                continue
            if self.appear_then_click(handler_assets.LOGIN_ANNOUNCE, offset=(30, 30), interval=5):
                continue
            if self.appear_then_click(handler_assets.LOGIN_ANNOUNCE_2, offset=(30, 30), interval=5):
                continue
            if self.appear(EVENT_LIST_CHECK, offset=(30, 30), interval=5):
                self.device.click(BACK_ARROW)
                continue
            # 更新和维护公告。
            if self.appear_then_click(handler_assets.MAINTENANCE_ANNOUNCE, offset=(30, 30), interval=5):
                continue
            if self.appear_then_click(handler_assets.LOGIN_GAME_UPDATE, offset=(30, 30), interval=5):
                continue
            if not login_success and self.handle_cn_user_agreement():
                continue
            # 回归玩家。
            if self.appear_then_click(handler_assets.LOGIN_RETURN_SIGN, offset=(30, 30), interval=5):
                continue
            if self.appear_then_click(handler_assets.LOGIN_RETURN_INFO, offset=(30, 30), interval=5):
                continue
            if self.appear_then_click(handler_assets.AVATAR_EXPIRED, offset=(30, 30), interval=5):
                continue
            # 弹窗。
            if self.handle_popup_confirm("LOGIN"):
                continue
            if self.handle_urgent_commission():
                continue
            # page_main 上出现的弹窗。
            if self.ui_page_main_popups(get_ship=login_success):
                return True
            # 始终回到 page_main。
            if self.appear_then_click(GOTO_MAIN, offset=(30, 30), interval=5):
                continue

        return True

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
            # 用户协议在中间区域。
            box = (350, 230, 920, 430)
            self.device.swipe_vector((0, -150), box, name="AGREEMENT_SCROLL")
            self.device.swipe_vector((0, -150), box, name="AGREEMENT_SCROLL")
            self.device.click(right)
            self._user_agreement_timer.reset()
            return True
        # 用户登录。
        self.device.click(right)
        self._user_agreement_timer.reset()
        return True

    def handle_app_login(self):
        """
        Returns:
            bool: If login success

        Raises:
            GameStuckError:
            GameTooManyClickError:
            GameNotRunningError:
        """
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
        # self.ensure_no_unfinished_campaign()

    def app_restart(self):
        logger.hr("App restart")
        self.device.app_stop()
        self.device.app_start()
        self.handle_app_login()
        # self.ensure_no_unfinished_campaign()
        self.config.task_delay(server_update=True)

    def ensure_no_unfinished_campaign(self):
        """
        确保没有未完成的战役停留在地图中。

        页面：
            进入：page_main
            退出：page_main
        """

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

            # 结束。
            if in_campaign():
                break

            # 点击。
            if self.ui_main_appear_then_click(page_campaign_menu, interval=3):
                continue
            if ensure_campaign_retreat():
                continue

        self.ui_goto_main()
