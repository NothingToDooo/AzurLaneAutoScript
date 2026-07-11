from contextlib import suppress
from datetime import datetime, timedelta

from module.base.utils import image_left_strip
from module.combat.assets import BATTLE_PREPARATION
from module.combat.combat import Combat
from module.config.utils import DEFAULT_TIME
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.os_ash import assets as ash_assets
from module.os_handler.map_event import MapEventHandler
from module.ui.assets import BACK_ARROW
from module.ui.ui import UI


class DailyDigitCounter(DigitCounter):
    def pre_process(self, image):
        image = super().pre_process(image)
        return image_left_strip(image, threshold=120, length=35)


class AshBeaconFinished(Exception):
    pass


class AshCombat(Combat):
    def handle_battle_status(self):
        if self.is_combat_executing():
            return False
        if self.appear(ash_assets.BATTLE_STATUS, offset=(120, 20), interval=self.battle_status_click_interval):
            self.device.sleep((0.25, 0.5))
            self.device.click(ash_assets.BATTLE_STATUS)
            return True
        if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
            self.device.click(BACK_ARROW)
            return True
        return bool(super().handle_battle_status())

    def handle_exp_info(self):
        """META 战斗不掉落经验；随机结算背景可能误触发经验识别，因此不处理。"""
        return False

    def handle_battle_preparation(self):
        if super().handle_battle_preparation():
            return True

        if self.appear_then_click(ash_assets.ASH_START, offset=(30, 30), interval=2):
            return True
        if self.handle_get_items():
            return True
        if self.appear(ash_assets.BEACON_REWARD):
            logger.info("Ash beacon already finished.")
            raise AshBeaconFinished
        if self.appear(ash_assets.BEACON_EMPTY, offset=(20, 20)):
            logger.info("Ash beacon already empty.")
            raise AshBeaconFinished
        if self.appear(ash_assets.ASH_SHOWDOWN, offset=(20, 20)):
            logger.info("Ash beacon already at ASH_SHOWDOWN.")
            raise AshBeaconFinished

        return False

    def combat(self, *args, expected_end=None, **kwargs):
        with suppress(AshBeaconFinished):
            super().combat(*args, expected_end=expected_end, **kwargs)


class OSAsh(UI, MapEventHandler):
    _ash_fully_collected = False

    def ash_collect_status(self):
        """返回当前信标收集进度，范围为 0 至 100。"""
        if self._ash_fully_collected:
            return 0
        if self.image_color_count(ash_assets.ASH_COLLECT_STATUS, color=(235, 235, 235), threshold=221, count=20):
            logger.info("Ash beacon status: light")
            ocr_collect = DigitCounter(
                ash_assets.ASH_COLLECT_STATUS, letter=(235, 235, 235), threshold=160, name="OCR_ASH_COLLECT_STATUS"
            )
            ocr_daily = DailyDigitCounter(
                ash_assets.ASH_DAILY_STATUS, letter=(235, 235, 235), threshold=160, name="OCR_ASH_DAILY_STATUS"
            )
        elif self.image_color_count(ash_assets.ASH_COLLECT_STATUS, color=(140, 142, 140), threshold=221, count=20):
            logger.info("Ash beacon status: gray")
            ocr_collect = DigitCounter(
                ash_assets.ASH_COLLECT_STATUS, letter=(140, 142, 140), threshold=160, name="OCR_ASH_COLLECT_STATUS"
            )
            ocr_daily = DailyDigitCounter(
                ash_assets.ASH_DAILY_STATUS, letter=(140, 142, 140), threshold=160, name="OCR_ASH_DAILY_STATUS"
            )
        else:
            # 大世界每日任务领取或完成时，弹窗会遮住信标状态。
            logger.info("Ash beacon status is covered, will check next time")
            return 0

        status, _, _ = ocr_collect.ocr(self.device.image)
        daily, _, _ = ocr_daily.ocr(self.device.image)

        if daily >= 200:
            logger.info("Ash beacon fully collected today")
            self._ash_fully_collected = True
        elif status >= 200:
            logger.info("Ash beacon data reached the holding limit")
            self._ash_fully_collected = True

        return max(status, 0)

    def _support_call_ash_beacon_task(self):
        next_run = self.config.cross_get(keys="OpsiAshBeacon.Scheduler.NextRun", default=DEFAULT_TIME)
        # 距离下次执行还有 30 分钟以上时，可以支援调用。
        return next_run - datetime.now() > timedelta(minutes=30)

    def handle_ash_beacon_attack(self):
        """在区域地图处理信标攻击；结束后仍在区域地图，返回是否发起攻击。"""
        if self.ash_collect_status() >= 100 and self._support_call_ash_beacon_task():
            self.config.task_call(task="OpsiAshBeacon")
            return True

        return False
