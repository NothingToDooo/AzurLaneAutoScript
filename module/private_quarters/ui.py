from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.shop.ui import ShopUI
from module.ui.navbar import Navbar, NavbarColorRule, NavbarTarget, NavbarVisualRules


class PQShopUI(ShopUI):
    @cached_property
    def _shop_bottom_navbar(self):
        """商店底栏依次为全部、礼物、家具、杂项。"""
        shop_navgrid = ButtonGrid(
            origin=(465, 600),
            delta=(200, 0),
            button_shape=(20, 20),
            grid_shape=(4, 1),
            name="PRIVATE_QUARTERS_BOTTOM_BUTTON_GRID",
        )

        return Navbar(
            grids=shop_navgrid,
            visual=NavbarVisualRules(
                active=NavbarColorRule(color=(186, 226, 245), threshold=221, count=350),
                inactive=NavbarColorRule(color=(236, 237, 243), threshold=221, count=350),
            ),
            name="PRIVATE_QUARTERS_BOTTOM_NAVBAR",
        )

    def shop_bottom_navbar_ensure(self, left=None, right=None):
        return self._shop_bottom_navbar.set(self, NavbarTarget(left=left, right=right))

    @cached_property
    def _shop_left_navbar(self):
        """商店左栏依次为主页、天狼星、能代、安克雷奇、新泽西。"""
        shop_navgrid = ButtonGrid(
            origin=(152, 158),
            delta=(0, 105),
            button_shape=(15, 15),
            grid_shape=(1, 5),
            name="PRIVATE_QUARTERS_LEFT_BUTTON_GRID",
        )

        return Navbar(
            grids=shop_navgrid,
            visual=NavbarVisualRules(
                active=NavbarColorRule(color=(255, 255, 255), threshold=221, count=200),
                inactive=NavbarColorRule(color=(176, 245, 250), threshold=221, count=200),
            ),
            name="PRIVATE_QUARTERS_LEFT_NAVBAR",
        )

    def shop_left_navbar_ensure(self, upper=None, bottom=None):
        return self._shop_left_navbar.set(self, NavbarTarget(upper=upper, bottom=bottom))
