from module.base.button import ButtonGrid
from module.shop.ui import ShopUI
from module.ui.navbar import Navbar, NavbarColorRule, NavbarTarget, NavbarVisualRules

SHOP_BOTTOM_NAVBAR = Navbar(
    grids=ButtonGrid(
        origin=(465, 600),
        delta=(200, 0),
        button_shape=(20, 20),
        grid_shape=(4, 1),
        name="PRIVATE_QUARTERS_BOTTOM_BUTTON_GRID",
    ),
    visual=NavbarVisualRules(
        active=NavbarColorRule(color=(186, 226, 245), threshold=221, count=350),
        inactive=NavbarColorRule(color=(236, 237, 243), threshold=221, count=350),
    ),
    name="PRIVATE_QUARTERS_BOTTOM_NAVBAR",
)
SHOP_LEFT_NAVBAR = Navbar(
    grids=ButtonGrid(
        origin=(152, 158),
        delta=(0, 105),
        button_shape=(15, 15),
        grid_shape=(1, 5),
        name="PRIVATE_QUARTERS_LEFT_BUTTON_GRID",
    ),
    visual=NavbarVisualRules(
        active=NavbarColorRule(color=(255, 255, 255), threshold=221, count=200),
        inactive=NavbarColorRule(color=(176, 245, 250), threshold=221, count=200),
    ),
    name="PRIVATE_QUARTERS_LEFT_NAVBAR",
)


class PQShopUI(ShopUI):
    def shop_bottom_navbar_ensure(self, left: int | None = None, right: int | None = None) -> bool:
        """商店底栏依次为全部、礼物、家具、杂项。"""
        return SHOP_BOTTOM_NAVBAR.set(self, NavbarTarget(left=left, right=right))

    def shop_left_navbar_ensure(self, upper: int | None = None, bottom: int | None = None) -> bool:
        """商店左栏依次为主页、天狼星、能代、安克雷奇、新泽西。"""
        return SHOP_LEFT_NAVBAR.set(self, NavbarTarget(upper=upper, bottom=bottom))
