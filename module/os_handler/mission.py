from datetime import datetime, timedelta
from typing import Literal

import numpy as np

from module.base.timer import Timer
from module.base.utils import color_similarity_2d
from module.config.utils import DEFAULT_TIME, get_os_next_reset
from module.logger import logger
from module.map_detection.utils import fit_points
from module.os.assets import GLOBE_GOTO_MAP
from module.os.globe_detection import GLOBE_MAP_SHAPE
from module.os.globe_operation import GlobeOperation
from module.os.globe_zone import Zone, ZoneManager
from module.os_handler import assets as os_assets

type MissionCheckoutResult = Literal[
    False,
    "pinned_at_archive_zone",
    "pinned_at_mission_zone",
    "already_at_mission_zone",
]


class MissionHandler(GlobeOperation, ZoneManager):
    _os_mission_submitted = False

    def get_mission_zone(self) -> Zone:
        area = (341, 72, 1217, 648)
        # 黄色感叹号的像素点。
        image = color_similarity_2d(self.image_crop(area, copy=False), color=(255, 207, 66))
        points = np.array(np.where(image > 235)).T[:, ::-1]
        if not len(points):
            logger.warning("Unable to find mission on OS mission map")

        point = np.add(fit_points(points, mod=(1000, 1000), encourage=5), (0, 11))
        # 作战海域坐标。
        # GLOBE_MAP_SHAPE 是 os_globe_map.png 的尺寸。
        point *= np.array(GLOBE_MAP_SHAPE) / np.subtract(area[2:], area[:2])

        return self.camera_to_zone(tuple(point))

    def is_in_os_mission(self) -> bool:
        return self.appear(os_assets.MISSION_CHECK, offset=(20, 20))

    def os_mission_enter(self) -> None:
        """从 MISSION_ENTER 进入任务列表并领取奖励，结束于 MISSION_CHECK。"""
        logger.info("OS mission enter")
        confirm_timer = Timer(2, count=6).start()
        for _ in self.loop():
            if self._os_mission_enter_finished(confirm_timer):
                break
            if self._os_mission_enter_step(confirm_timer):
                continue

    def _os_mission_enter_finished(self, confirm_timer: Timer) -> bool:
        if not self.is_in_os_mission():
            confirm_timer.reset()
            return False

        has_finish = self.appear(os_assets.MISSION_FINISH, offset=(20, 20))
        has_checkout = self.match_template_color(os_assets.MISSION_CHECKOUT, offset=(20, 20))
        if not has_finish and not has_checkout:
            # 没有任务时也等一下，避免列表还没加载完。
            if confirm_timer.reached():
                logger.info("No OS mission found.")
                return True
            return False
        if has_checkout:
            logger.info("Found at least one OS missions.")
            return True

        confirm_timer.reset()
        return False

    def _os_mission_enter_step(self, confirm_timer: Timer) -> bool:
        if self._os_mission_click_entry_buttons(confirm_timer):
            return True
        if self.handle_popup_confirm("MISSION_FINISH"):
            confirm_timer.reset()
            return True
        if self.handle_map_get_items() or self.handle_info_bar():
            confirm_timer.reset()
            return True
        if self.appear_then_click(GLOBE_GOTO_MAP, offset=(20, 20), interval=2):
            # 意外进入了大世界海图。
            confirm_timer.reset()
            return True
        return False

    def _os_mission_click_entry_buttons(self, confirm_timer: Timer) -> bool:
        for button, offset, interval in (
            (os_assets.MISSION_ENTER, (200, 5), 5),
            (os_assets.MISSION_FINISH, (20, 20), 2),
        ):
            if self.appear_then_click(button, offset=offset, interval=interval):
                confirm_timer.reset()
                return True
        return False

    def os_mission_quit(self) -> None:
        logger.info("OS mission quit")
        for _ in self.loop():
            # 部分任务弹窗没有黑色模糊背景，此时 MISSION_QUIT 和地图会同时出现。
            if not self.appear(os_assets.MISSION_QUIT, offset=(20, 20)) and self.is_in_map():
                break
            if self.appear_then_click(os_assets.MISSION_QUIT, offset=(20, 20), interval=3):
                continue

    def os_get_next_mission(self) -> MissionCheckoutResult:
        """领取后游戏会直接切换至目标海域，已在目标海域时只显示信息栏。

        返回 pinned_at_mission_zone、already_at_mission_zone 或 pinned_at_archive_zone；
        没有任务时返回 False。
        """
        self.os_mission_enter()

        checkout_offset = (20, 20)
        if self.appear(os_assets.MISSION_MONTHLY_BOSS, offset=(20, 20)):
            # 月度 BOSS 未击败时任务会一直存在，需检查其下方任务。
            logger.info("Monthly BOSS mission found, checking missions bellow it")
            checkout_offset = (-20, 100, 20, 150)

        if not self.match_template_color(os_assets.MISSION_CHECKOUT, offset=checkout_offset):
            # 材料不足时仍有透明的 MISSION_CHECKOUT，必须同时检查模板与颜色。
            logger.info("No more OS missions")
            self.os_mission_quit()
            return False

        if self.is_in_opsi_explore():
            logger.info("OpsiExplore is under scheduling, accept missions and receive rewards only")
            self.os_mission_quit()
            return False

        logger.info("Checkout os mission")
        for _ in self.loop():
            if self.is_zone_pinned():
                if self.get_zone_pinned_name() == "ARCHIVE":
                    logger.info("Pinned at archive zone")
                    self.globe_enter(zone=self.name_to_zone(72))
                    return "pinned_at_archive_zone"
                logger.info("Pinned at mission zone")
                self.globe_enter(zone=self.name_to_zone(72))
                return "pinned_at_mission_zone"
            if self.is_in_map() and self.info_bar_count():
                logger.info("Already at mission zone")
                return "already_at_mission_zone"

            if self.appear_then_click(os_assets.MISSION_CHECKOUT, offset=checkout_offset, interval=2):
                continue
            if self.handle_popup_confirm("OS_MISSION_CHECKOUT"):
                # 离开当前区域会触发潜艇撤退确认。
                continue
        return False

    def os_mission_overview_accept(self) -> bool:
        """在区域地图领取任务总览中的全部任务；达到任务上限时返回 False。"""
        logger.hr("OS mission overview accept", level=1)
        self.os_map_goto_globe(unpin=False)
        self.ui_click(
            os_assets.MISSION_OVERVIEW_ENTER,
            check_button=os_assets.MISSION_OVERVIEW_CHECK,
            offset=(200, 20),
            retry_wait=3,
            additional=self.handle_manjuu,
            skip_first_screenshot=True,
        )

        timeout = 5
        accept_button_timer = Timer(timeout)
        self.interval_timer[os_assets.MISSION_OVERVIEW_ACCEPT_SINGLE.name] = accept_button_timer
        self.interval_timer[os_assets.MISSION_OVERVIEW_ACCEPT.name] = accept_button_timer
        success = True
        for _ in self.loop():
            if self.appear(os_assets.MISSION_OVERVIEW_EMPTY, offset=(20, 20)):
                success = True
                break
            if self.info_bar_count():
                logger.info("Unable to accept missions, because reached the maximum number of missions")
                success = False
                break

            if self.handle_manjuu():
                continue
            if self.appear_then_click(os_assets.MISSION_OVERVIEW_ACCEPT, offset=(20, 20), interval=timeout):
                continue
            if self.appear_then_click(os_assets.MISSION_OVERVIEW_ACCEPT_SINGLE, offset=(20, 20), interval=timeout):
                continue

        self.ui_back(
            appear_button=os_assets.MISSION_OVERVIEW_CHECK, check_button=self.is_in_globe, skip_first_screenshot=True
        )
        self.os_globe_goto_map()
        return success

    def is_in_opsi_explore(self) -> bool:
        enable = self.config.is_task_enabled("OpsiExplore")
        next_run = self.config.cross_get(keys="OpsiExplore.Scheduler.NextRun", default=DEFAULT_TIME)
        if not isinstance(next_run, datetime):
            next_run = DEFAULT_TIME
        next_reset = get_os_next_reset()
        logger.attr("OpsiNextReset", next_reset)
        logger.attr("OpsiExplore", (enable, next_run))
        # 向前偏移 12 小时兼容跨夏令时计算的 next_run。
        # 2023-03-14 11:15:28.423 | INFO | [OpsiNextReset] 2023-04-01 03:00:00
        # 2023-03-14 11:15:28.425 | INFO | [OpsiExplore] (True, datetime.datetime(2023, 4, 1, 2, 0))
        # 2023-03-14 11:15:28.426 | INFO | OpsiExplore is still running, accept missions only...
        if enable and next_run < next_reset - timedelta(hours=12):
            logger.info(
                "OpsiExplore is still running, accept missions only. "
                "Missions will be finished when OpsiExplore visits every zones, "
                "no need to worry they are left behind."
            )
            return True
        logger.info("Not in OpsiExplore, able to do OpsiDaily")
        return False
