from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.gacha.assets import (
    BUILD_FINISH_ORDERS,
    BUILD_SUBMIT_ORDERS,
    BUILD_SUBMIT_WW_ORDERS,
    BUILD_WW_CHECK,
    SHOP_MEDAL_CHECK,
)
from module.logger import logger
from module.ui.navbar import Navbar, NavbarColorRule, NavbarTarget, NavbarVisualRules
from module.ui.page import page_build
from module.ui.ui import UI

GACHA_LOAD_ENSURE_BUTTONS = [
    SHOP_MEDAL_CHECK,
    BUILD_SUBMIT_ORDERS,
    BUILD_SUBMIT_WW_ORDERS,
    BUILD_FINISH_ORDERS,
    BUILD_WW_CHECK,
]


class GachaUI(UI):
    def gacha_load_ensure(self, *, skip_first_screenshot: bool = True) -> bool:
        """侧栏切换后等待延迟资源加载，超时返回 False。"""
        ensure_timeout = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            results = [self.appear(button) for button in GACHA_LOAD_ENSURE_BUTTONS]
            if any(results):
                return True

            if ensure_timeout.reached():
                logger.warning("Wait for loaded assets is incomplete, ensure not guaranteed")
                return False
        return False

    @staticmethod
    def _gacha_side_navbar() -> Navbar:
        """限时侧栏依次为建造、限时建造、订单、商店、退役；常规侧栏没有限时建造。"""
        gacha_side_navbar = ButtonGrid(
            origin=(21, 126), delta=(0, 98), button_shape=(60, 80), grid_shape=(1, 5), name="GACHA_SIDE_NAVBAR"
        )

        return Navbar(
            grids=gacha_side_navbar,
            visual=NavbarVisualRules(
                active=NavbarColorRule(color=(247, 255, 173), threshold=221),
                inactive=NavbarColorRule(color=(140, 162, 181), threshold=221, count=50),
            ),
        )

    def gacha_side_navbar_ensure(self, *, upper: int | None = None, bottom: int | None = None) -> bool:
        """按顶部或底部索引切换侧栏并等待加载。

        限时/常规顶部索引：建造 1/1、限时建造 2/无、订单 3/2、商店 4/3、退役 5/4；
        底部索引：建造 5/4、限时建造 4/无、订单 3/3、商店 2/2、退役 1/1。
        """
        retire_upper = 5 if self._gacha_side_navbar().get_total(main=self) == 5 else 4
        if upper == retire_upper or bottom == 1:
            logger.warning('Transitions to "retire" is not supported')
            return False

        return (
            self._gacha_side_navbar().set(self, NavbarTarget(upper=upper, bottom=bottom)) and self.gacha_load_ensure()
        )

    @staticmethod
    def _construct_bottom_navbar() -> Navbar:
        """限时建造栏为活动、轻型、重型、特型；常规布局没有活动池。"""
        construct_bottom_navbar = ButtonGrid(
            origin=(262, 615), delta=(209, 0), button_shape=(70, 49), grid_shape=(4, 1), name="CONSTRUCT_BOTTOM_NAVBAR"
        )

        return Navbar(
            grids=construct_bottom_navbar,
            visual=NavbarVisualRules(
                active=NavbarColorRule(color=(247, 227, 148)),
                inactive=NavbarColorRule(color=(189, 231, 247), count=50),
            ),
        )

    @staticmethod
    def _exchange_bottom_navbar() -> Navbar:
        """兑换栏依次为舰船和物品。"""
        exchange_bottom_navbar = ButtonGrid(
            origin=(569, 637), delta=(208, 0), button_shape=(70, 49), grid_shape=(2, 1), name="EXCHANGE_BOTTOM_NAVBAR"
        )

        return Navbar(
            grids=exchange_bottom_navbar,
            visual=NavbarVisualRules(
                active=NavbarColorRule(color=(247, 227, 148)),
                inactive=NavbarColorRule(color=(189, 231, 247), count=50),
            ),
        )

    @staticmethod
    def _gacha_bottom_navbar(*, is_build: bool = True) -> Navbar:
        if is_build:
            return GachaUI._construct_bottom_navbar()
        return GachaUI._exchange_bottom_navbar()

    def gacha_bottom_navbar_ensure(
        self, *, left: int | None = None, right: int | None = None, is_build: bool = True
    ) -> bool:
        """按左右索引切换建造或兑换底栏并等待加载。

        限时/常规建造左索引：活动 1/无、轻型 2/1、重型 3/2、特型 4/3；
        右索引：活动 4/无、轻型 3/3、重型 2/2、特型 1/1。兑换栏舰船/物品左索引为 1/2，右索引为 2/1。
        """
        gacha_bottom_navbar = self._gacha_bottom_navbar(is_build=is_build)
        if is_build and gacha_bottom_navbar.get_total(main=self) == 3:
            if left == 1 or right == 4:
                logger.info("Construct event not available, default to light")
                left = 1
                right = None
            if left == 4:
                left = 3

        return gacha_bottom_navbar.set(self, NavbarTarget(left=left, right=right)) and self.gacha_load_ensure()

    def ui_goto_gacha(self) -> None:
        self.ui_ensure(page_build)
