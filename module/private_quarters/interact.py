from typing import ClassVar

from module.base.timer import Timer
from module.base.utils import random_rectangle_vector
from module.handler.assets import POPUP_CANCEL
from module.logger import logger
from module.private_quarters import assets as pq_assets
from module.ui.page import page_private_quarters
from module.ui.ui import UI


class PQInteract(UI):
    # Key：目标舰船名称。
    # Value：按钮元组，格式为 (Room_Entrance, Page_Locale)。
    available_targets: ClassVar[dict[str, tuple[object, ...]]] = {
        "anchorage": (pq_assets.PRIVATE_QUARTERS_SHIP_ANCHORAGE, pq_assets.PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        "noshiro": (pq_assets.PRIVATE_QUARTERS_SHIP_NOSHIRO, pq_assets.PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        "sirius": (pq_assets.PRIVATE_QUARTERS_SHIP_SIRIUS, pq_assets.PRIVATE_QUARTERS_PAGE_LOCALE_BEACH),
        "new_jersey": (pq_assets.PRIVATE_QUARTERS_SHIP_NEW_JERSEY, pq_assets.PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
        "taihou": (pq_assets.PRIVATE_QUARTERS_SHIP_TAIHOU, pq_assets.PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
        "aegir": (pq_assets.PRIVATE_QUARTERS_SHIP_AEGIR, pq_assets.PRIVATE_QUARTERS_PAGE_LOCALE_LOFT),
        "nakhimov": (pq_assets.PRIVATE_QUARTERS_SHIP_NAKHIMOV, pq_assets.PRIVATE_QUARTERS_PAGE_LOCALE_VILLA),
    }

    def _pq_handle_dialogue(self):
        """
        处理目标舰船的对话流程。

        加入大凤后，少数情况下这段对话会卡顿，所以除了进房间外，其他状态也会调用它。
        """

        # 加载态消失前避免连续点击。
        def after_loading_state():
            return not self.appear(pq_assets.PRIVATE_QUARTERS_LOADING_CHECK, offset=(20, 20))

        def additional():
            return True

        self.ui_click(
            click_button=pq_assets.PRIVATE_QUARTERS_ROOM_SAFE_CLICK_AREA,
            check_button=pq_assets.PRIVATE_QUARTERS_ROOM_CHECK,
            appear_button=after_loading_state,
            additional=additional,
            confirm_wait=3,
            offset=(20, 20),
            retry_wait=1.5,
        )

    def _pq_target_appear(self):
        """
        检查目标舰船是否出现。

        offset=(100, 100) 可检测安克雷奇、能代、天狼星、新泽西和大凤。后续加入更多舰船时，
        可以把特定气泡位置也存入 available_targets 元组。

        Returns:
            bool
        """
        settle_timer = Timer(1.5, count=3).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 目标已出现。
            if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CHECK_1, offset=(100, 100)):
                return True
            if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CHECK_2, offset=(100, 100)):
                return True
            if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CHECK_3, offset=(100, 100)):
                return True

            # 等待超时。
            if settle_timer.reached():
                return False

            if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_CHECK, offset=(20, 20)):
                # 用几次上拖抵消目标默认距离或缩放异常。
                p1, p2 = random_rectangle_vector(
                    (0, -30),
                    box=pq_assets.PRIVATE_QUARTERS_ROOM_SAFE_CLICK_AREA.area,
                    random_range=(-10, -10, 10, 10),
                    padding=5,
                )
                self.device.drag(
                    p1, p2, segments=2, shake=(0, 25), point_random=(0, 0, 0, 0), shake_random=(0, -5, 0, 5)
                )
                settle_timer.reset()
            else:
                # 检查点不存在通常表示仍在对话中。
                self._pq_handle_dialogue()
                settle_timer.reset()
        return False

    def _pq_goto_room_seek(self, target_ship):
        """
        查找目标房间所在页面。

        Args:
            target_ship (str):

        Returns:
            bool
        """
        target_title = target_ship.title().replace("_", " ")
        if target_ship not in self.available_targets:
            logger.error(f"Unsupported target ship: {target_title}, cannot continue subtask")
            return False
        if len(self.available_targets[target_ship]) < 2:
            logger.error(f"Missing tuple info page locale for target ship: {target_title}, cannot continue subtask")
            return False

        page_btn = self.available_targets[target_ship][1]
        logger.hr(f"Seek {target_title}'s Page", level=2)

        # 根据当前页面位置决定先向左还是先向右查找。
        directions = [pq_assets.PRIVATE_QUARTERS_PAGE_LEFT, pq_assets.PRIVATE_QUARTERS_PAGE_RIGHT]
        if not self.appear(pq_assets.PRIVATE_QUARTERS_PAGE_LEFT, offset=(20, 20)):
            directions.reverse()

        # 执行页面查找。
        skip_first_screenshot = True
        self.interval_clear(directions)
        settle_timer = Timer(1.5, count=3).start()
        for direction in directions:
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # 已到达目标页面。
                if self.appear(page_btn, offset=(20, 20)):
                    logger.info(f"Reached {target_title}'s page")
                    return True

                # 点击后保留间隔，用来确认页面切换。
                if self.appear_then_click(direction, offset=(20, 20), interval=1):
                    settle_timer.reset()
                    continue

                # 超过间隔后不再继续当前方向，切换到另一个方向查找。
                if settle_timer.reached():
                    break

        logger.warning(f"{target_title}'s page cannot be found")
        return False

    def _pq_goto_room_check(self):
        """
        检查是否正在加载，或被资源下载弹窗阻挡。
        """
        if self.appear(pq_assets.PRIVATE_QUARTERS_LOADING_CHECK, offset=(20, 20)):
            return True
        return bool(self.appear(POPUP_CANCEL, offset=(20, 20)))

    def _pq_goto_room_enter(self, target_ship):
        """
        进入目标房间。

        Args:
            target_ship (str):

        Returns:
            bool
        """
        # 点击目标房间入口后，等待加载或弹窗出现。
        target_title = target_ship.title().replace("_", " ")
        if target_ship not in self.available_targets:
            logger.error(f"Unsupported target ship: {target_title}, cannot continue subtask")
            return False
        if len(self.available_targets[target_ship]) < 1:
            logger.error(f"Missing tuple info room entrance for target ship: {target_title}, cannot continue subtask")
            return False

        target_btn = self.available_targets[target_ship][0]
        self.ui_click(
            click_button=target_btn,
            check_button=self._pq_goto_room_check,
            appear_button=page_private_quarters.check_button,
            offset=(20, 20),
            skip_first_screenshot=True,
        )

        # 如果出现资源下载弹窗，终止本轮。
        if self.handle_popup_cancel("PRIVATE_QUARTERS_DOWNLOAD_ASSET", offset=(20, 20)):
            logger.error(f"Cannot enter {target_title}'s room, please download the necessary assets first")
            return False

        # 通过点击推进，完全进入目标房间。
        self._pq_handle_dialogue()

        # 目标亲密度已满时终止本轮。
        if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_INTIMACY_MAX, offset=(20, 20)):
            logger.warning(
                f"{target_title}'s intimacy is maxed, configure to new target or turn off subtask altogether"
            )
            return False

        return True

    def _pq_goto_room_exit(self):
        """
        退出目标房间。
        """
        # 少数情况下仍在对话中，退出前先处理掉。
        if not self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_CHECK, offset=(20, 20)) and not self.appear(
            pq_assets.PRIVATE_QUARTERS_INTERACT, offset=(0, 60)
        ):
            self._pq_handle_dialogue()

        self.interval_clear(pq_assets.PRIVATE_QUARTERS_ROOM_BACK)
        self.ui_click(
            click_button=pq_assets.PRIVATE_QUARTERS_ROOM_BACK,
            check_button=page_private_quarters.check_button,
            offset=(20, 20),
            retry_wait=3,
            skip_first_screenshot=True,
        )
        self.handle_info_bar()

    def pq_interact(self):
        """
        执行目标互动流程。

        offset=(0, 60) 用于兼容资产纵向位置；不同亲密度下资产可能偏移。
        """
        # 点击目标舰船，进入第一阶段。
        logger.hr("Interact Start", level=2)
        click_timer = Timer(1.5, count=3).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 已出现互动按钮。
            if self.appear(pq_assets.PRIVATE_QUARTERS_INTERACT, offset=(0, 60)):
                break

            if click_timer.reached():
                self.device.click(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CLICK_AREA)
                click_timer.reset()

        # 重复第二、第三阶段，共三轮。
        for i in range(1, 4):
            logger.hr(f"Interact Loop {i}/3", level=3)
            self.interval_clear([pq_assets.PRIVATE_QUARTERS_INTERACT_CHECK, pq_assets.PRIVATE_QUARTERS_INTERACT])
            skip_first_screenshot = True
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # 已进入互动确认页。
                if self.appear(pq_assets.PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20)):
                    break

                if self.appear_then_click(pq_assets.PRIVATE_QUARTERS_INTERACT, offset=(0, 60), interval=1):
                    continue

            skip_first_screenshot = True
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                # 已回到互动按钮状态。
                if self.appear(pq_assets.PRIVATE_QUARTERS_INTERACT, offset=(0, 60)):
                    break

                if self.appear(pq_assets.PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20), interval=1):
                    self.device.click(pq_assets.PRIVATE_QUARTERS_ROOM_BACK)
                    continue

        logger.hr("Interact End", level=2)
        self._pq_goto_room_exit()

    def pq_goto_room(self, target_ship, retry=3):
        """
        进入目标房间。

        初始加载后目标不存在时会重试，最多重试 retry 次。

        Args:
            target_ship (str):
            retry  (int):

        Returns:
            bool
        """
        success = False
        target_title = target_ship.title().replace("_", " ")
        logger.hr(f"Enter {target_title}'s Room", level=1)

        if not self._pq_goto_room_seek(target_ship):
            return success

        for _ in range(retry):
            if not self._pq_goto_room_enter(target_ship):
                break

            if self._pq_target_appear():
                logger.info(f"{target_title} is waiting and excited for your arrival!")
                success = True
                break
            logger.warning(f"{target_title} is not ready, exit and try again; retry={retry - (_ + 1)}")

            self._pq_goto_room_exit()

        return success
