from dataclasses import dataclass, field

from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_SHIP
from module.logger import logger
from module.shop.assets import SHOP_CLICK_SAFE_AREA


@dataclass(slots=True, frozen=True)
class NavbarColorRule:
    color: tuple[int, int, int]
    threshold: int = 180
    count: int = 100


@dataclass(slots=True, frozen=True)
class NavbarVisualRules:
    active: NavbarColorRule = field(default_factory=lambda: NavbarColorRule(color=(247, 251, 181)))
    inactive: NavbarColorRule = field(default_factory=lambda: NavbarColorRule(color=(140, 162, 181), count=50))


@dataclass(slots=True, frozen=True)
class NavbarTarget:
    left: int | None = None
    right: int | None = None
    upper: int | None = None
    bottom: int | None = None

    @property
    def left_index(self):
        if self.left is not None:
            return self.left
        return self.upper

    @property
    def right_index(self):
        if self.right is not None:
            return self.right
        return self.bottom

    def format(self):
        return " ".join(
            f"{key}={value}"
            for key, value in [
                ("left", self.left),
                ("right", self.right),
                ("upper", self.upper),
                ("bottom", self.bottom),
            ]
            if value is not None
        )

    def is_empty(self):
        return self.left is None and self.right is None and self.upper is None and self.bottom is None


class Navbar:
    def __init__(self, grids, *, visual=None, name=None):
        self.grids = grids
        self.visual = visual if visual is not None else NavbarVisualRules()
        self.name = name if name is not None else grids.name

    def is_button_active(self, button, main):
        active = self.visual.active
        return main.image_color_count(button, color=active.color, threshold=active.threshold, count=active.count)

    def is_button_inactive(self, button, main):
        inactive = self.visual.inactive
        return main.image_color_count(button, color=inactive.color, threshold=inactive.threshold, count=inactive.count)

    def get_info(self, main):
        """返回活动项、最左可见项和最右可见项的索引。"""
        total = []
        active = []
        for index, button in enumerate(self.grids.buttons):
            if self.is_button_active(button, main=main):
                total.append(index)
                active.append(index)
            elif self.is_button_inactive(button, main=main):
                total.append(index)

        if len(active) == 0:
            active = None
        elif len(active) == 1:
            active = active[0]
        else:
            logger.warning(f"Too many active nav items found in {self.name}, items: {active}")
            active = active[0]

        if len(total) < 2:
            logger.warning(f"Too few nav items found in {self.name}, items: {total}")
        if len(total) == 0:
            left, right = None, None
        else:
            left, right = min(total), max(total)

        return active, left, right

    def get_active(self, main):
        return self.get_info(main=main)[0]

    def get_total(self, main):
        _, left, right = self.get_info(main=main)
        if left is None or right is None:
            return 0
        return right - left + 1

    def _shop_obstruct_handle(self, main):
        """仅商店导航栏需要先关闭遮挡项。"""
        if self.name not in ["SHOP_BOTTOM_NAVBAR", "GUILD_SIDE_NAVBAR"]:
            return False

        if main.appear(GET_SHIP, interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        if main.appear(GET_ITEMS_1, offset=(30, 30), interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True
        if main.appear(GET_ITEMS_2, offset=(30, 30), interval=1):
            main.device.click(SHOP_CLICK_SAFE_AREA)
            return True

        return False

    def _resolve_set_target(self, target):
        if target.is_empty():
            logger.warning("Invalid index to set, must set an index from 1 direction")
            return None
        return target.left_index, target.right_index, target.format()

    def _index_from_visible_range(self, minimum, maximum, left, right):
        if minimum is None or maximum is None:
            return None
        if left is not None:
            return minimum + left - 1
        if right is not None:
            return maximum - right + 1
        return None

    def _target_index_to_set(self, minimum, maximum, left, right, text):
        index = self._index_from_visible_range(minimum=minimum, maximum=maximum, left=left, right=right)
        if index is None:
            return None
        if not minimum <= index <= maximum:
            logger.warning(
                f"{self.name} target {text} resolved to index ({index}) "
                f"outside nav items that appear ({minimum}, {maximum})"
            )
            return None
        return index

    def set(self, main, target, skip_first_screenshot=True):
        """target 从指定边缘开始按 1 计数，返回是否成功切换。"""
        resolved = self._resolve_set_target(target)
        if resolved is None:
            return False
        left, right, text = resolved
        logger.info(f"{self.name} set to {text}")

        interval = Timer(2, count=4)
        timeout = Timer(10, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            if timeout.reached():
                logger.warning(f"{self.name} failed to set {text.strip()}")
                return False

            if self._shop_obstruct_handle(main=main):
                interval.reset()
                timeout.reset()
                continue

            active, minimum, maximum = self.get_info(main=main)
            logger.info(f"Nav item active: {active} from range ({minimum}, {maximum})")
            # 纯黑截图或动画期间会识别不到导航项。
            index = self._target_index_to_set(minimum=minimum, maximum=maximum, left=left, right=right, text=text)
            if active is None or index is None:
                continue

            if active == index:
                return True

            if interval.reached():
                main.device.click(self.grids.buttons[index])
                interval.reset()
        return False
