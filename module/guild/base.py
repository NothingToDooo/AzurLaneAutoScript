from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.logger import logger
from module.ui.navbar import Navbar, NavbarColorRule, NavbarTarget, NavbarVisualRules
from module.ui.ui import UI


class GuildBase(UI):
    @cached_property
    def _guild_side_navbar(self) -> Navbar:
        return self._build_guild_side_navbar()

    @staticmethod
    def _build_guild_side_navbar() -> Navbar:
        """会长侧栏依次为大厅、成员、申请、后勤、科技、作战；成员侧栏没有申请。"""
        guild_side_navbar = ButtonGrid(
            origin=(21, 118), delta=(0, 94.5), button_shape=(60, 75), grid_shape=(1, 6), name="GUILD_SIDE_NAVBAR"
        )

        return Navbar(
            grids=guild_side_navbar,
            visual=NavbarVisualRules(active=NavbarColorRule(color=(247, 255, 173))),
        )

    def guild_side_navbar_ensure(self, *, upper: int | None = None, bottom: int | None = None) -> bool:
        """按顶部或底部索引切换侧栏；页面完全加载仍由调用方确认。

        会长/成员顶部索引：大厅 1/1、成员 2/2、申请 3/无、后勤 4/3、科技 5/4、作战 6/5；
        底部索引：大厅 6/5、成员 5/4、申请 4/无、后勤 3/3、科技 2/2、作战 1/1。
        """
        if self._guild_side_navbar.get_total(main=self) == 6 and (upper == 3 or bottom == 4):
            logger.warning('Transitions to "apply" is not supported')
            return False

        return self._guild_side_navbar.set(self, NavbarTarget(upper=upper, bottom=bottom))
