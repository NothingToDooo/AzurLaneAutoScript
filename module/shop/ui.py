from typing import Literal

from module.base.button import Button, ButtonGrid
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
from module.ui.navbar import Navbar, NavbarColorRule, NavbarTarget, NavbarVisualRules
from module.ui.page import page_academy, page_munitions
from module.ui.switch import Switch
from module.ui.ui import UI

_SHOP_BOTTOM_NAVBAR = Navbar(
    grids=ButtonGrid(
        origin=(399, 619),
        delta=(182, 0),
        button_shape=(56, 42),
        grid_shape=(5, 1),
        name="SHOP_BOTTOM_NAVBAR",
    ),
    visual=NavbarVisualRules(
        active=NavbarColorRule(color=(33, 195, 239)),
        inactive=NavbarColorRule(color=(181, 178, 181), count=50),
    ),
)

type ShopRefreshState = Literal["available", "unavailable"]
type ShopNavState = Literal["general", "monthly"]
type ShopTabState = Literal[
    "general",
    "merit",
    "guild",
    "meta",
    "prize",
    "core_limited",
    "core_monthly",
    "medal",
    "prototype",
]


class ShopUI(UI):
    _SHOP_REFRESH_ACTIVE_COLORS = ((49, 142, 207), (54, 117, 161))
    _SHOP_REFRESH_UNAVAILABLE_COLOR = (52, 74, 94)

    _SHOP_NAV_STATES: tuple[tuple[ShopNavState, Button], ...] = (
        ("general", NAV_GENERAL),
        ("monthly", NAV_MONTHLY),
    )
    _SHOP_TAB_STATES: tuple[tuple[ShopTabState, Button], ...] = (
        ("general", TAB_GENERAL),
        ("merit", TAB_MERIT),
        ("guild", TAB_GUILD),
        ("meta", TAB_META),
        ("prize", TAB_PRIZE),
        ("core_limited", TAB_CORE_LIMITED),
        ("core_monthly", TAB_CORE_MONTHLY),
        ("medal", TAB_MEDAL),
        ("prototype", TAB_PROTOTYPE),
    )

    def shop_bottom_navbar_ensure(self, left: int | None = None, right: int | None = None) -> bool:
        """底部导航从左到右为勋章、舰队、原型、核心、功勋。"""
        return _SHOP_BOTTOM_NAVBAR.set(self, NavbarTarget(left=left, right=right))

    @cached_property
    def shop_nav_250814(self) -> Switch:
        switch = Switch("shop_nav_250814", is_selector=True, offset=(20, 20))
        for state, button in self._SHOP_NAV_STATES:
            switch.add_state(state, check_button=button)
        return switch

    @cached_property
    def shop_tab_250814(self) -> Switch:
        switch = Switch("shop_tab_250814", is_selector=True, offset=(20, 20))
        for state, button in self._SHOP_TAB_STATES:
            switch.add_state(state, check_button=button)
        return switch

    def _shop_refresh_state(self) -> ShopRefreshState | None:
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

    def _open_shop_refresh_confirm(self) -> None:
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

    def _handle_shop_refresh_mistake(self) -> bool:
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

    def _confirm_shop_refresh(self) -> bool:
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

    def shop_refresh(self) -> bool:
        logger.info("Shop refresh")
        self._open_shop_refresh_confirm()
        refreshed = self._confirm_shop_refresh()
        self.handle_info_bar()
        return refreshed

    def ui_goto_shop(self) -> None:
        """从任意页面进入军需商店，并保证落在普通商店。"""
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

            # 学院镜头可移动，因此使用较大匹配偏移。
            if self.appear_then_click(ACADEMY_GOTO_MUNITIONS, offset=(200, 200), interval=5):
                continue
