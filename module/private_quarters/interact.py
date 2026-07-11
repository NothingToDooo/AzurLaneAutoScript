from typing import ClassVar

from module.base.timer import Timer
from module.base.utils import random_rectangle_vector
from module.handler.assets import POPUP_CANCEL
from module.logger import logger
from module.private_quarters import assets as pq_assets
from module.ui.page import page_private_quarters
from module.ui.ui import UI


class PQInteract(UI):
    # 目标舰船映射到 (房间入口, 所在页面)；后续元素可保存特定气泡位置。
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
        """推进对话；加入大凤后偶尔会卡顿，因此多个房间状态都会调用。"""

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
        """以 100px 偏移检查目标气泡；新舰船可在 available_targets 追加特定气泡位置。"""
        settle_timer = Timer(1.5, count=3).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CHECK_1, offset=(100, 100)):
                return True
            if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CHECK_2, offset=(100, 100)):
                return True
            if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CHECK_3, offset=(100, 100)):
                return True

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
                self.device.drag(p1, p2, point_random=(0, 0, 0, 0))
                settle_timer.reset()
            else:
                # 检查点不存在通常表示仍在对话中。
                self._pq_handle_dialogue()
                settle_timer.reset()
        return False

    def _pq_goto_room_seek(self, target_ship):
        """从当前位置向两侧查找目标舰船所在页面。"""
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

        skip_first_screenshot = True
        self.interval_clear(directions)
        settle_timer = Timer(1.5, count=3).start()
        for direction in directions:
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

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
        if self.appear(pq_assets.PRIVATE_QUARTERS_LOADING_CHECK, offset=(20, 20)):
            return True
        return bool(self.appear(POPUP_CANCEL, offset=(20, 20)))

    def _pq_goto_room_enter(self, target_ship):
        """进入目标房间；资源未下载或亲密度已满时返回 False。"""
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

        if self.handle_popup_cancel("PRIVATE_QUARTERS_DOWNLOAD_ASSET", offset=(20, 20)):
            logger.error(f"Cannot enter {target_title}'s room, please download the necessary assets first")
            return False

        self._pq_handle_dialogue()

        if self.appear(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_INTIMACY_MAX, offset=(20, 20)):
            logger.warning(
                f"{target_title}'s intimacy is maxed, configure to new target or turn off subtask altogether"
            )
            return False

        return True

    def _pq_goto_room_exit(self):
        """退出房间；少数情况下仍在对话，需先推进完毕。"""
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
        """执行三轮互动；检查按钮时用 60px 纵向偏移兼容不同亲密度布局。"""
        logger.hr("Interact Start", level=2)
        self._pq_wait_interact_button()

        for index in range(1, 4):
            logger.hr(f"Interact Loop {index}/3", level=3)
            self._pq_interact_once()

        logger.hr("Interact End", level=2)
        self._pq_goto_room_exit()

    def _pq_wait_interact_button(self):
        click_timer = Timer(1.5, count=3).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(pq_assets.PRIVATE_QUARTERS_INTERACT, offset=(0, 60)):
                break

            if click_timer.reached():
                self.device.click(pq_assets.PRIVATE_QUARTERS_ROOM_TARGET_CLICK_AREA)
                click_timer.reset()

    def _pq_interact_once(self):
        self.interval_clear([pq_assets.PRIVATE_QUARTERS_INTERACT_CHECK, pq_assets.PRIVATE_QUARTERS_INTERACT])
        self._pq_enter_interact_confirm()
        self._pq_leave_interact_confirm()

    def _pq_enter_interact_confirm(self):
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(pq_assets.PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20)):
                break

            if self.appear_then_click(pq_assets.PRIVATE_QUARTERS_INTERACT, offset=(0, 60), interval=1):
                continue

    def _pq_leave_interact_confirm(self):
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(pq_assets.PRIVATE_QUARTERS_INTERACT, offset=(0, 60)):
                break

            if self.appear(pq_assets.PRIVATE_QUARTERS_INTERACT_CHECK, offset=(20, 20), interval=1):
                self.device.click(pq_assets.PRIVATE_QUARTERS_ROOM_BACK)
                continue

    def pq_goto_room(self, target_ship, retry=3):
        """进入目标房间并返回是否成功；初始加载后目标不存在时最多重试 retry 次。"""
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
