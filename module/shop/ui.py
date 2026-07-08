from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.handler.assets import POPUP_CONFIRM
from module.logger import logger
from module.shop.assets import (
    NAV_GENERAL,
    NAV_MONTHLY,
    SHOP_BUY_CONFIRM_MISTAKE,
    SHOP_CLICK_SAFE_AREA,
    SHOP_REFRESH,
    SHOP_REFRESH_CHECK,
    TAB_CORE_LIMITED,
    TAB_CORE_MONTHLY,
    TAB_GENERAL,
    TAB_GUILD,
    TAB_MEDAL,
    TAB_MERIT,
    TAB_META,
    TAB_PRIZE,
    TAB_PROTOTYPE,
)
from module.ui.assets import ACADEMY_GOTO_MUNITIONS, SHOP_BACK_ARROW
from module.ui.navbar import Navbar
from module.ui.page import page_academy, page_munitions
from module.ui.switch import Switch
from module.ui.ui import UI


class ShopUI(UI):
    _SHOP_REFRESH_ACTIVE_COLORS = ((49, 142, 207), (54, 117, 161))
    _SHOP_REFRESH_UNAVAILABLE_COLOR = (52, 74, 94)

    @cached_property
    def _shop_bottom_navbar(self):
        """
        Below information relative to after
        shop_swipe
        shop_bottom_navbar 5 options
            medal
            guild.
            prototype.
            core.
            merit.
        """
        shop_bottom_navbar = ButtonGrid(
            origin=(399, 619), delta=(182, 0), button_shape=(56, 42), grid_shape=(5, 1), name="SHOP_BOTTOM_NAVBAR"
        )

        return Navbar(grids=shop_bottom_navbar, active_color=(33, 195, 239), inactive_color=(181, 178, 181))

    def shop_bottom_navbar_ensure(self, left=None, right=None):
        """确保商店底部导航栏已经切换到目标范围。"""
        return self._shop_bottom_navbar.set(self, left=left, right=right)

    @cached_property
    def shop_nav_250814(self):
        switch = Switch("shop_nav_250814", is_selector=True, offset=(20, 20))
        switch.add_state(NAV_GENERAL, check_button=NAV_GENERAL)
        switch.add_state(NAV_MONTHLY, check_button=NAV_MONTHLY)
        return switch

    @cached_property
    def shop_tab_250814(self):
        switch = Switch("shop_tab_250814", is_selector=True, offset=(20, 20))
        switch.add_state(TAB_GENERAL, check_button=TAB_GENERAL)
        switch.add_state(TAB_MERIT, check_button=TAB_MERIT)
        switch.add_state(TAB_GUILD, check_button=TAB_GUILD)
        switch.add_state(TAB_META, check_button=TAB_META)
        switch.add_state(TAB_PRIZE, check_button=TAB_PRIZE)
        switch.add_state(TAB_CORE_LIMITED, check_button=TAB_CORE_LIMITED)
        switch.add_state(TAB_CORE_MONTHLY, check_button=TAB_CORE_MONTHLY)
        switch.add_state(TAB_MEDAL, check_button=TAB_MEDAL)
        switch.add_state(TAB_PROTOTYPE, check_button=TAB_PROTOTYPE)
        return switch

    def _shop_refresh_state(self):
        if not self.appear(SHOP_REFRESH_CHECK, offset=(30, 30), interval=3):
            return None
        if any(
            self.image_color_count(SHOP_REFRESH.button, color=color, threshold=221, count=50)
            for color in self._SHOP_REFRESH_ACTIVE_COLORS
        ):
            return "available"
        if self.image_color_count(
            SHOP_REFRESH.button, color=self._SHOP_REFRESH_UNAVAILABLE_COLOR, threshold=221, count=50
        ):
            return "unavailable"

        self.interval_clear(SHOP_REFRESH)
        return None

    def _open_shop_refresh_confirm(self):
        for _ in self.loop():
            if self.appear(POPUP_CONFIRM, offset=(30, 30)):
                return

            state = self._shop_refresh_state()
            if state == "available":
                self.device.click(SHOP_REFRESH)
                continue
            if state == "unavailable":
                logger.info("Refresh not available")
                return

    def _handle_shop_refresh_mistake(self):
        if not self.appear(SHOP_BUY_CONFIRM_MISTAKE, interval=3, offset=(200, 200)):
            return False
        logger.warning("SHOP_BUY_CONFIRM_MISTAKE")
        self.ui_click(
            SHOP_CLICK_SAFE_AREA,
            appear_button=POPUP_CONFIRM,
            check_button=SHOP_BACK_ARROW,
            offset=(20, 30),
            skip_first_screenshot=True,
        )
        return True

    def _confirm_shop_refresh(self):
        refreshed = False
        for _ in self.loop():
            if self.appear(SHOP_BACK_ARROW, offset=(30, 30)):
                return refreshed
            if self._handle_shop_refresh_mistake():
                return False
            if self.handle_popup_confirm("SHOP_REFRESH_CONFIRM"):
                refreshed = True
                continue
        return refreshed

    def shop_refresh(self):
        """
        Returns:
            bool: If refreshed
        """
        logger.info("Shop refresh")
        self._open_shop_refresh_confirm()
        refreshed = self._confirm_shop_refresh()
        self.handle_info_bar()
        return refreshed

    def ui_goto_shop(self):
        """
        Goes to page_munitions
        This route guarantees start
        in general shop

        Pages:
            in: Any
            out: page_munitions
        """
        if self.ui_get_current_page() == page_munitions:
            logger.info(f"Already at {page_munitions}")
            return

        self.ui_ensure(page_academy)

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(page_munitions.check_button, offset=(20, 20)):
                break

            # Large offset cause it camera in academy can be move around
            if self.appear_then_click(ACADEMY_GOTO_MUNITIONS, offset=(200, 200), interval=5):
                continue
