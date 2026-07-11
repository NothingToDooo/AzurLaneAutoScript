from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.base.utils import random_rectangle_vector
from module.exception import GameStuckError
from module.logger import logger
from module.os_shop.assets import OS_SHOP_CHECK, OS_SHOP_SAFE_AREA, OS_SHOP_SCROLL_AREA
from module.ui.navbar import Navbar, NavbarColorRule, NavbarTarget, NavbarVisualRules
from module.ui.scroll import AdaptiveScroll
from module.ui.ui import UI

OS_SHOP_SCROLL = AdaptiveScroll(
    OS_SHOP_SCROLL_AREA.button,
    parameters={
        "height": 255 - 99,
        "prominence": 40,
    },
    name="OS_SHOP_SCROLL",
)
OS_SHOP_SCROLL.drag_threshold = 0.1
OS_SHOP_SCROLL.edge_threshold = 0.1

OS_SHOP_LOAD_TIMEOUT_MESSAGE = "Waiting too long for OpsiShop to appear."
SCROLL_DRAG_PAGE_ERROR_MESSAGE = "Scroll drag page error."


class OSShopUI(UI):
    def os_shop_load_ensure(self, skip_first_screenshot=True):
        """侧栏切换后等待商店加载；超时抛出 GameStuckError。"""
        ensure_timeout = Timer(3, count=6).start()
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(OS_SHOP_CHECK):
                return True
            logger.warning("OpsiShop is not appear, retrying.")

            if ensure_timeout.reached():
                raise GameStuckError(OS_SHOP_LOAD_TIMEOUT_MESSAGE)

    @cached_property
    def _os_shop_side_navbar(self):
        """侧栏从上到下为纽约、利物浦、直布罗陀、圣彼得堡。"""
        os_shop_side_navbar = ButtonGrid(
            origin=(44, 266), delta=(0, 87), button_shape=(231, 46), grid_shape=(1, 4), name="OS_SHOP_SIDE_NAVBAR"
        )

        return Navbar(
            grids=os_shop_side_navbar,
            visual=NavbarVisualRules(
                active=NavbarColorRule(color=(43, 94, 248), threshold=221),
                inactive=NavbarColorRule(color=(12, 58, 86), threshold=221, count=50),
            ),
        )

    def os_shop_side_navbar_ensure(self, upper=None, bottom=None):
        """在港口补给页按上序或下序 1 至 4 切换港口侧栏，并等待加载完成。"""
        logger.info(f"OpsiShop side navbar set to {upper or bottom}")
        self.os_shop_load_ensure()
        self._os_shop_side_navbar.set(self, NavbarTarget(upper=upper, bottom=bottom))

    def init_slider(self) -> tuple[float, float]:
        """把滚动条置顶并返回 `(前次位置, 当前位置)`；无法恢复时抛出 GameStuckError。"""
        if not OS_SHOP_SCROLL.appear(main=self):
            logger.warning("Scroll does not appear, try to rescue slider")
            self.rescue_slider()
        retry = Timer(0, count=3)
        retry.start()
        while not OS_SHOP_SCROLL.at_top(main=self):
            logger.info("Scroll does not at top, try to scroll")
            OS_SHOP_SCROLL.set_top(main=self)
            if retry.reached():
                raise GameStuckError(SCROLL_DRAG_PAGE_ERROR_MESSAGE)
        return -1.0, 0.0

    def rescue_slider(self, distance=200):
        detection_area = (1130, 230, 1170, 710)
        direction_vector = (0, distance)
        p1, p2 = random_rectangle_vector(
            direction_vector, box=detection_area, random_range=(-10, -40, 10, 40), padding=10
        )
        self.device.drag(p1, p2, point_random=(0, 0, 0, 0))
        self.device.click(OS_SHOP_SAFE_AREA)
        self.device.screenshot()

    def pre_scroll(self, pre_pos, cur_pos) -> float:
        """滚动位置未变化时尝试恢复；连续失败抛出 GameStuckError。"""
        if pre_pos == cur_pos:
            logger.warning("Scroll drag page failed")
            if not OS_SHOP_SCROLL.appear(main=self):
                logger.warning("Scroll does not appear, try to rescue slider")
                self.rescue_slider()
                OS_SHOP_SCROLL.set(cur_pos, main=self)
            retry = Timer(0, count=3)
            retry.start()
            while True:
                logger.warning("Scroll does not drag success, retrying scroll")
                OS_SHOP_SCROLL.next_page(main=self, page=0.5, skip_first_screenshot=False)
                cur_pos = OS_SHOP_SCROLL.cal_position(main=self)
                if pre_pos != cur_pos:
                    logger.info(f"Scroll success drag page to {cur_pos}")
                    return cur_pos
                if retry.reached():
                    raise GameStuckError(SCROLL_DRAG_PAGE_ERROR_MESSAGE)
        else:
            return cur_pos
