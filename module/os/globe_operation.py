from module.base.timer import Timer
from module.base.utils import area_pad
from module.logger import logger
from module.os import assets as os_assets
from module.os_handler.action_point import ActionPointHandler
from module.os_handler.assets import AUTO_SEARCH_REWARD
from module.os_handler.port import PORT_CHECK
from module.ui.assets import BACK_ARROW

ZONE_TYPES = [
    os_assets.ZONE_DANGEROUS,
    os_assets.ZONE_SAFE,
    os_assets.ZONE_OBSCURE,
    os_assets.ZONE_ABYSSAL,
    os_assets.ZONE_STRONGHOLD,
    os_assets.ZONE_ARCHIVE,
]
ZONE_SELECT = [
    os_assets.SELECT_DANGEROUS,
    os_assets.SELECT_SAFE,
    os_assets.SELECT_OBSCURE,
    os_assets.SELECT_ABYSSAL,
    os_assets.SELECT_STRONGHOLD,
    os_assets.SELECT_ARCHIVE,
]
ASSETS_PINNED_ZONE = ZONE_TYPES + [os_assets.ZONE_ENTRANCE, os_assets.ZONE_SWITCH, os_assets.ZONE_PINNED]


class OSExploreError(Exception):
    pass


class RewardUncollectedError(Exception):
    pass


class GlobeOperation(ActionPointHandler):
    _zone_unpin_interval = Timer(0.5)

    def is_in_globe(self):
        return self.appear(os_assets.GLOBE_GOTO_MAP, offset=(20, 20))

    def get_zone_pinned(self):
        """
        Returns:
            Button:
        """
        for zone in ZONE_TYPES:
            if self.appear(zone, offset=(20, 20)):
                for button in ASSETS_PINNED_ZONE:
                    button.load_offset(zone)

                return zone

        return None

    def is_zone_pinned(self):
        """
        Returns:
            bool:
        """
        return self.get_zone_pinned() is not None

    @staticmethod
    def pinned_to_name(button):
        """
        Args:
            button (Button):

        Returns:
            str: DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD, ARCHIVE.
        """
        return button.name.split("_")[1]

    def get_zone_pinned_name(self):
        """
        Returns:
            str: DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD, ARCHIVE, or ''.
        """
        pinned = self.get_zone_pinned()
        if pinned is not None:
            return self.pinned_to_name(pinned)
        else:
            return ""

    def handle_zone_pinned(self):
        """
        CLose pinned zone info.

        Returns:
            bool: If handled.
        """
        if not self._zone_unpin_interval.reached():
            return False

        if self.is_zone_pinned():
            # 点击不会取消区域固定，滑动才会。
            self.device.swipe_vector(
                (50, -50),
                box=area_pad(os_assets.ZONE_PINNED.area, pad=-80),
                random_range=(-10, -10, 10, 10),
                padding=0,
                name="PINNED_DISABLE",
            )
            self._zone_unpin_interval.reset()
            return True

        return False

    def ensure_no_zone_pinned(self):
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.handle_zone_pinned():
                confirm_timer.reset()
            else:
                if confirm_timer.reached():
                    break

    def zone_has_switch(self):
        """
        Switch is an icon of 4 block, one block in white. White block keeps rotating.
        If detected one white block, consider this is a zone switch.

        2021.07.15 ZONE_SWITCH was downscaled and added text "Change Zone".
            So ZONE_SWITCH changed to detect "Change Zone"

        Returns:
            bool: If current zone has switch.
        """
        # image = self.image_crop(ZONE_SWITCH)
        # center = np.array(image.size) / 2
        # count = 0
        # for corner in area2corner((0, 0, *image.size)):
        #     area = (min(corner[0], center[0]), min(corner[1], center[1]),
        #             max(corner[0], center[0]), max(corner[1], center[1]))
        #     area = area_pad(area, pad=2)
        #     color = np.mean(get_color(image, area))
        #     if color > 235:
        #         count += 1
        #
        # if count == 1:
        #     return True
        # elif count == 0:
        #     return False
        # else:
        #     logger.warning(f'Unexpected zone switch, white block: {count}')

        return self.appear(os_assets.ZONE_SWITCH, offset=(5, 5))

    _zone_select_offset = (20, 200)
    _zone_select_similarity = 0.75

    def get_zone_select(self):
        """
        Returns:
            list[Button]:
        """
        # 降低阈值到 0.75。
        # 原因不明，但字体有时会不同。
        return [
            select
            for select in ZONE_SELECT
            if self.appear(select, offset=self._zone_select_offset, similarity=self._zone_select_similarity)
        ]

    def is_in_zone_select(self):
        """
        Returns:
            bool:
        """
        return len(self.get_zone_select()) > 0

    def ensure_zone_select_expanded(self):
        """
        Returns:
            list[Button]:
        """
        record = 0
        for _ in range(5):
            selection = self.get_zone_select()
            if len(selection) == record and record > 0:
                return selection

            record = len(selection)
            self.device.screenshot()

        logger.warning("Failed to ensure zone selection expanded, assume expanded")
        return self.get_zone_select()

    def zone_select_enter(self):
        """
        Pages:
            in: is_zone_pinned
            out: is_in_zone_select
        """
        self.ui_click(
            os_assets.ZONE_SWITCH,
            appear_button=self.is_zone_pinned,
            check_button=self.is_in_zone_select,
            skip_first_screenshot=True,
        )

    def zone_select_execute(self, button):
        """
        Args:
            button (Button): Button to select, one of the SELECT_* buttons

        Pages:
            in: is_in_zone_select
            out: is_zone_pinned
        """
        logger.info(f"Zone select: {button}")
        for _ in self.loop():
            # 结束。
            if self.is_zone_pinned():
                break
            if self.appear_then_click(
                button, offset=self._zone_select_offset, similarity=self._zone_select_similarity, interval=5
            ):
                continue

    def zone_type_select(self, types=("SAFE", "DANGEROUS")):
        """
        Args:
            types (tuple[str], list[str], str): Zone types, or a list of them.
                Available types: DANGEROUS, SAFE, OBSCURE, ABYSSAL, STRONGHOLD, ARCHIVE.
                Try the the first selection in type list, if not available, try the next one.
                Do nothing if no selection satisfied input.

        Returns:
            bool: If success.

        Pages:
            in: is_zone_pinned
            out: is_zone_pinned
        """
        if not self.zone_has_switch():
            logger.info("Zone has no type to select, skip")
            return True

        if isinstance(types, str):
            types = [types]

        def get_button(selection_):
            for typ in types:
                typ = "SELECT_" + typ
                for sele in selection_:
                    if typ == sele.name:
                        return sele
            return None

        pinned = self.get_zone_pinned_name()
        if pinned in types:
            logger.info(f"Already selected at {pinned}")
            return True

        for _ in range(3):
            self.zone_select_enter()
            selection = self.ensure_zone_select_expanded()
            logger.attr("Zone_selection", selection)

            button = get_button(selection)
            if button is None:
                logger.warning("No such zone type to select, fallback to default")
                types = ("SAFE", "DANGEROUS")
                button = get_button(selection)

            self.zone_select_execute(button)
            if self.pinned_to_name(button) == self.get_zone_pinned_name():
                return True

        logger.warning("Failed to select zone type after 3 trial")
        return False

    def zone_has_safe(self):
        """
        Checks and selects if zone has SAFE otherwise selects DANGEROUS
        which is guaranteed to be present in every zone

        Returns:
            bool: If SAFE is present.

        Pages:
            in: is_zone_pinned
            out: is_zone_pinned
        """
        if self.get_zone_pinned_name() == "SAFE":
            return True
        elif self.zone_has_switch():
            self.zone_select_enter()
            flag = os_assets.SELECT_SAFE in self.ensure_zone_select_expanded()
            button = os_assets.SELECT_SAFE if flag else os_assets.SELECT_DANGEROUS
            self.zone_select_execute(button)
            return flag
        else:
            # 没有 zone_switch，已在 DANGEROUS。
            return False

    def os_globe_goto_map(self, skip_first_screenshot=True):
        """
        Pages:
            in: is_in_globe
            out: is_in_map
        """
        return self.ui_click(
            os_assets.GLOBE_GOTO_MAP,
            check_button=self.is_in_map,
            offset=(20, 20),
            retry_wait=3,
            skip_first_screenshot=skip_first_screenshot,
        )

    def os_map_goto_globe(self, unpin=True):
        """
        Args:
            unpin (bool):

        Pages:
            in: is_in_map
            out: is_in_globe
        """
        click_count = 0
        for _ in self.loop():
            # 结束。
            if self.is_in_globe():
                break

            if self.appear_then_click(os_assets.MAP_GOTO_GLOBE, offset=(200, 5), interval=5):
                # 只是为了初始化 MAP_GOTO_GLOBE_FOG 的间隔计时器。
                self.appear(os_assets.MAP_GOTO_GLOBE_FOG, interval=5)
                self.interval_reset(os_assets.MAP_GOTO_GLOBE_FOG)
                click_count += 1
                if click_count >= 5:
                    # 存在未领取区域探索奖励时，AL 不允许离开。
                    logger.warning(
                        "Unable to goto globe, there might be uncollected zone exploration rewards preventing exit"
                    )
                    raise RewardUncollectedError
                continue
            if self.appear_then_click(os_assets.MAP_GOTO_GLOBE_FOG, interval=5):
                # 只会在据点遇到；即使地图内仍有探索奖励，AL 也不会阻止区域退出。
                self.interval_reset(os_assets.MAP_GOTO_GLOBE)
                continue
            if self.handle_map_event():
                continue
            # 误入港口。
            if self.appear(PORT_CHECK, offset=(20, 20), interval=5):
                logger.info(f"Page switch: {PORT_CHECK} -> {BACK_ARROW}")
                self.device.click(BACK_ARROW)
                continue
            # 弹窗：AUTO_SEARCH_REWARD 出现较慢。
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=5):
                continue
            # 弹窗：离开当前区域会终止指挥喵搜寻。
            # 弹窗：离开当前区域会让潜艇撤退。
            # 搜索奖励会在进入另一个区域后显示。
            if self.handle_popup_confirm("GOTO_GLOBE"):
                continue

        confirm_timer = Timer(1, count=2).start()
        unpinned = 0
        for _ in self.loop():
            if unpin:
                if self.handle_zone_pinned():
                    unpinned += 1
                    confirm_timer.reset()
                else:
                    if unpinned and confirm_timer.reached():
                        break
            else:
                if self.is_zone_pinned():
                    break

    def globe_enter(self, zone):
        """
        Args:
            zone (Zone): Zone to enter.

        Raises:
            OSExploreError: If zone locked.

        Pages:
            in: is_zone_pinned
            out: is_in_map
        """
        click_timer = Timer(10)
        click_count = 0
        pinned = None
        for _ in self.loop():
            if pinned is None:
                pinned = self.get_zone_pinned_name()

            # 结束。
            if self.is_in_map():
                break

            if self.is_zone_pinned():
                if self.appear(os_assets.ZONE_LOCKED, offset=(20, 20)):
                    logger.warning(f"Zone {zone} locked, neighbouring zones may not have been explored")
                    raise OSExploreError
                if click_count > 5:
                    logger.warning(f"Unable to enter zone {zone}, neighbouring zones may not have been explored")
                    raise OSExploreError
                if click_timer.reached():
                    self.device.click(os_assets.ZONE_ENTRANCE)
                    click_count += 1
                    click_timer.reset()
                    continue
            if self.handle_action_point(zone=zone, pinned=pinned):
                click_timer.clear()
                continue
            if self.handle_map_event():
                continue
            if self.handle_popup_confirm("GLOBE_ENTER"):
                continue
            # 游戏 bug：上一个已清理区域的 AUTO_SEARCH_REWARD 会弹出。
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
