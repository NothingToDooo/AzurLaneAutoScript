from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_SHIP
from module.logger import logger
from module.shop.assets import SHOP_CLICK_SAFE_AREA


class Navbar:
    def __init__(
        self,
        grids,
        active_color=(247, 251, 181),
        inactive_color=(140, 162, 181),
        active_threshold=180,
        inactive_threshold=180,
        active_count=100,
        inactive_count=50,
        name=None,
    ):
        """
        Args:
            grids (ButtonGrid):
            active_color (tuple[int, int, int]):
            inactive_color (tuple[int, int, int]):
            active_threshold (int):
            inactive_threshold (int):
            active_count (int):
            inactive_count (int):
            name (str):
        """
        self.grids = grids
        self.active_color = active_color
        self.inactive_color = inactive_color
        self.active_threshold = active_threshold
        self.inactive_threshold = inactive_threshold
        self.active_count = active_count
        self.inactive_count = inactive_count
        self.name = name if name is not None else grids.name

    def is_button_active(self, button, main):
        """
        Args:
            button (Button):
            main (ModuleBase):

        Returns:
            bool:
        """
        return main.image_color_count(
            button, color=self.active_color, threshold=self.active_threshold, count=self.active_count
        )

    def is_button_inactive(self, button, main):
        """
        Args:
            button (Button):
            main (ModuleBase):

        Returns:
            bool:
        """
        return main.image_color_count(
            button, color=self.inactive_color, threshold=self.inactive_threshold, count=self.inactive_count
        )

    def get_info(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            int, int, int: Index of the active nav item, leftmost nav item, and rightmost nav item.
        """
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
        """
        Args:
            main (ModuleBase):

        Returns:
            int: Index of the active nav item.
        """
        return self.get_info(main=main)[0]

    def get_total(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            int: Numbers of nav items that appears
        """
        _, left, right = self.get_info(main=main)
        if left is None or right is None:
            return 0
        return right - left + 1

    def _shop_obstruct_handle(self, main):
        """
        IFF in shop, then remove obstructions
        in shop view if any

        Args:
            main (ModuleBase):

        Returns:
            bool:
        """
        # Check name, identifies if NavBar
        # instance belongs to shop module
        if self.name not in ["SHOP_BOTTOM_NAVBAR", "GUILD_SIDE_NAVBAR"]:
            return False

        # Handle shop obstructions
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

    def _format_set_target(self, left, right, upper, bottom):
        return " ".join(
            f"{key}={value}"
            for key, value in [
                ("left", left),
                ("right", right),
                ("upper", upper),
                ("bottom", bottom),
            ]
            if value is not None
        )

    def _resolve_set_target(self, left, right, upper, bottom):
        if left is None and right is None and upper is None and bottom is None:
            logger.warning("Invalid index to set, must set an index from 1 direction")
            return None

        if left is None and upper is not None:
            left = upper
        if right is None and bottom is not None:
            right = bottom

        text = self._format_set_target(left=left, right=right, upper=upper, bottom=bottom)
        return left, right, text

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

    def set(self, main, left=None, right=None, upper=None, bottom=None, skip_first_screenshot=True):
        """
        Set nav bar from 1 direction.

        Args:
            main (ModuleBase):
            left (int): Index of nav item counted from left. Start from 1.
            right (int): Index of nav item counted from right. Start from 1.
            upper (int): Index of nav item counted from upper. Start from 1.
            bottom (int): Index of nav item counted from bottom. Start from 1.
            skip_first_screenshot (bool):

        Returns:
            bool: If success
        """
        target = self._resolve_set_target(left=left, right=right, upper=upper, bottom=bottom)
        if target is None:
            return False
        left, right, text = target
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

            # 已到目标项。
            if active == index:
                return True

            if interval.reached():
                main.device.click(self.grids.buttons[index])
                interval.reset()
        return False
