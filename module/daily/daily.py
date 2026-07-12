from typing import TYPE_CHECKING, cast

import numpy as np

from module.base.utils import get_color
from module.combat.assets import BATTLE_PREPARATION
from module.combat.combat import Combat
from module.daily import assets as daily_assets
from module.daily.equipment import DailyEquipment
from module.logger import logger
from module.ocr.ocr import Digit
from module.ui.assets import BACK_ARROW, DAILY_CHECK
from module.ui.page import page_campaign_menu, page_daily
from module.ui.ui import UiIndexControls

if TYPE_CHECKING:
    from module.base.button import Button

DAILY_MISSION_LIST = [
    daily_assets.DAILY_MISSION_1,
    daily_assets.DAILY_MISSION_2,
    daily_assets.DAILY_MISSION_3,
]
OCR_REMAIN = Digit(daily_assets.OCR_REMAIN, threshold=128, alphabet="01234")
OCR_DAILY_FLEET_INDEX = Digit(
    daily_assets.OCR_DAILY_FLEET_INDEX, letter=(90, 154, 255), threshold=128, alphabet="123456"
)


class Daily(Combat, DailyEquipment):
    daily_current: int
    daily_checked: list[int]
    emergency_module_development = False

    def is_active(self) -> bool:
        color = get_color(image=self.device.image, area=daily_assets.DAILY_ACTIVE.area)
        color = np.array(color).astype(float)
        color = (np.max(color) + np.min(color)) / 2
        active = color > 30
        if active:
            logger.attr(f"Daily_{self.daily_current}", "active")
        else:
            logger.attr(f"Daily_{self.daily_current}", "inactive")
        return active

    def _wait_daily_switch(self) -> None:
        self.device.sleep((1, 1.2))

    def next(self) -> None:
        self.daily_current += 1
        logger.info(f"Switch to {self.daily_current}")
        self.device.click(daily_assets.DAILY_NEXT)
        self._wait_daily_switch()
        self.device.screenshot()

    def prev(self) -> None:
        self.daily_current -= 1
        logger.info(f"Switch to {self.daily_current}")
        self.device.click(daily_assets.DAILY_PREV)
        self._wait_daily_switch()
        self.device.screenshot()

    def handle_daily_additional(self) -> bool:
        return bool(self.handle_guild_popup_cancel())

    def get_daily_stage_and_fleet(self) -> tuple[int, int]:
        """返回 (关卡 0～3, 舰队 0～6)；0 表示跳过、手动处理或无配置。"""
        if self.emergency_module_development:
            # 索引依次为限时兵装、商船护送、海域突进、斩首、战术研修、破交、兵装训练。
            fleets = [
                0,
                self.config.Daily_EmergencyModuleDevelopmentFleet,
                self.config.Daily_EscortMissionFleet,
                self.config.Daily_AdvanceMissionFleet,
                self.config.Daily_FierceAssaultFleet,
                self.config.Daily_TacticalTrainingFleet,
                0,  # 破交作战需要手动完成，或通过每日跳过完成。
                self.config.Daily_ModuleDevelopmentFleet,
                0,
            ]
            stages = [
                0,
                self.config.Daily_EmergencyModuleDevelopment,
                self.config.Daily_EscortMission,
                self.config.Daily_AdvanceMission,
                self.config.Daily_FierceAssault,
                self.config.Daily_TacticalTraining,
                self.config.Daily_SupplyLineDisruption,
                self.config.Daily_ModuleDevelopment,
                0,
            ]
        else:
            # 索引依次为战术研修、破交、兵装训练、未开放、商船护送、海域突进、斩首。
            fleets = [
                0,
                self.config.Daily_TacticalTrainingFleet,
                0,  # 破交作战需要手动完成，或通过每日跳过完成。
                self.config.Daily_ModuleDevelopmentFleet,
                0,  # 空位。
                self.config.Daily_EscortMissionFleet,
                self.config.Daily_AdvanceMissionFleet,
                self.config.Daily_FierceAssaultFleet,
                0,
            ]
            stages = [
                0,
                self.config.Daily_TacticalTraining,
                self.config.Daily_SupplyLineDisruption,
                self.config.Daily_ModuleDevelopment,
                0,  # 空位。
                self.config.Daily_EscortMission,
                self.config.Daily_AdvanceMission,
                self.config.Daily_FierceAssault,
                0,
            ]
        dic = {
            "skip": 0,
            "first": 1,
            "second": 2,
            "third": 3,
        }
        fleet = fleets[self.daily_current]
        stage = stages[self.daily_current]

        if stage not in dic:
            logger.warning(f"Unknown daily stage `{stage}` from daily_current={self.daily_current}")
        stage = dic.get(stage, 0)
        return int(stage), int(fleet)

    @property
    def supply_line_disruption_index(self) -> int:
        return 2

    @property
    def empty_index(self) -> int:
        return 4

    def daily_execute(self, remain: int = 3, stage: int = 1, fleet: int = 1) -> bool:
        """在每日页执行剩余次数；stage 为 1～3、fleet 为 1～6，锁定时返回 False。"""
        logger.hr(f"Daily {self.daily_current}", level=2)
        logger.info(f"remain={remain}, stage={stage}, fleet={fleet}")

        def daily_enter_check() -> bool:
            return self.appear(daily_assets.DAILY_ENTER_CHECK, threshold=30)

        def daily_end() -> bool:
            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
                self.device.click(BACK_ARROW)
            return self.appear(daily_assets.DAILY_ENTER_CHECK, threshold=30) or self.appear(BACK_ARROW, offset=(30, 30))

        self.ui_click(
            click_button=daily_assets.DAILY_ENTER,
            check_button=daily_enter_check,
            appear_button=DAILY_CHECK,
            skip_first_screenshot=True,
        )
        if self.appear(daily_assets.DAILY_LOCKED):
            logger.info("Daily locked")
            self.ui_click(click_button=BACK_ARROW, check_button=DAILY_CHECK)
            self.device.sleep((1, 1.2))
            return False

        button = DAILY_MISSION_LIST[stage - 1]
        for n in range(remain):
            logger.hr(f"Count {n + 1}")
            result = self.daily_enter(button)
            if not result:
                break
            if self.daily_current == self.supply_line_disruption_index:
                logger.info("Submarine daily skip not unlocked, skip")
                self.ui_click(click_button=BACK_ARROW, check_button=daily_enter_check, skip_first_screenshot=True)
                break
            self.ui_ensure_index(
                fleet,
                UiIndexControls(
                    letter=OCR_DAILY_FLEET_INDEX,
                    prev_button=daily_assets.DAILY_FLEET_PREV,
                    next_button=daily_assets.DAILY_FLEET_NEXT,
                    fast=False,
                ),
                skip_first_screenshot=True,
            )
            self.combat(emotion_reduce=False, expected_end=daily_end, balance_hp=False)

        self.ui_click(
            click_button=BACK_ARROW,
            check_button=DAILY_CHECK,
            additional=self.handle_daily_additional,
            skip_first_screenshot=True,
        )
        self.device.sleep((1, 1.2))
        return True

    def daily_enter(self, button: Button, *, skip_first_screenshot: bool = True) -> bool:
        """从 DAILY_ENTER_CHECK 进入任务；出现战斗返回 True，跳过或领奖完成返回 False。"""
        reward_received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._click_daily_entry_if_ready(button):
                continue
            if self.handle_get_items():
                reward_received = True
                continue
            if self._handle_daily_run_choice():
                continue
            if self._handle_daily_enter_popup():
                continue

            result = self._daily_enter_result(reward_received=reward_received)
            if result is not None:
                return result
        return False

    def _click_daily_entry_if_ready(self, button: Button) -> bool:
        if not self.appear(daily_assets.DAILY_ENTER_CHECK, threshold=30, interval=5):
            return False
        self.device.click(button)
        return True

    def _handle_daily_run_choice(self) -> bool:
        if self.config.Daily_UseDailySkip:
            return self.appear_then_click(daily_assets.DAILY_SKIP, offset=(20, 20), interval=5)
        return self.appear_then_click(daily_assets.DAILY_NORMAL_RUN, offset=(20, 20), interval=5)

    def _handle_daily_enter_popup(self) -> bool:
        return (
            self.handle_combat_automation_confirm()
            or self.handle_daily_additional()
            or self.handle_popup_confirm("DAILY_SKIP")
        )

    def _daily_enter_result(self, *, reward_received: bool) -> bool | None:
        if self.appear(daily_assets.DAILY_SKIP, offset=(20, 20)):
            if reward_received:
                return False
            if self.info_bar_count():
                return False
        if self.appear(daily_assets.DAILY_ENTER_CHECK, threshold=30) and self.info_bar_count():
            return False
        if self.combat_appear():
            return True
        return None

    def daily_check(self, n: int | None = None) -> None:
        if not n:
            n = self.daily_current
        self.daily_checked.append(n)
        logger.info(f"Checked daily {n}")
        logger.info(f"Checked_list: {self.daily_checked}")

    def daily_run_one(self) -> None:
        logger.hr("Daily run one", level=1)
        self.ui_ensure(page_daily)
        self.device.sleep(0.2)
        self.device.screenshot()
        self.daily_current = 1
        self.emergency_module_development = self.appear(
            daily_assets.ENTRANCE_EMERGENCY_MODULE_DEVELOPMENT, offset=(25, 50)
        )
        logger.attr("emergency_module_development", self.emergency_module_development)

        logger.info(f"Checked_list: {self.daily_checked}")
        for _ in range(max(self.daily_checked)):
            self.next()

        while 1:
            if self.daily_current > 7:
                break
            if self.daily_current == self.empty_index:
                logger.info("This daily is not open now")
                self.daily_check()
                self.next()
                continue
            stage, fleet = self.get_daily_stage_and_fleet()
            if self.daily_current == self.supply_line_disruption_index and not self.config.Daily_UseDailySkip:
                logger.info("Skip supply line disruption if UseDailySkip disabled")
                self.daily_check()
                self.next()
                continue
            if not stage:
                logger.info(f"No stage set on daily_current: {self.daily_current}, skip")
                self.daily_check()
                self.next()
                continue
            if self.daily_current != self.supply_line_disruption_index and not fleet:
                logger.info(f"No fleet set on daily_current: {self.daily_current}, skip")
                self.daily_check()
                self.next()
                continue
            if not self.is_active():
                self.daily_check()
                self.next()
                continue
            remain = cast("int", OCR_REMAIN.ocr(self.device.image))
            if remain == 0:
                self.daily_check()
                self.next()
                continue
            self.daily_execute(remain=remain, stage=stage, fleet=fleet)
            self.daily_check()
            # 打完一次之后每日任务的顺序会乱掉，退出再进入来重置顺序。
            self.ui_goto(page_campaign_menu)
            break

    def daily_run(self) -> None:
        self.daily_checked = [0]

        while 1:
            self.daily_run_one()

            if self.emergency_module_development and self.config.Daily_EmergencyModuleDevelopment != "skip":
                self.daily_checked = [0]

            if max(self.daily_checked) >= 7:
                logger.info("Daily clear complete.")
                break

    def run(self) -> None:
        """从任意页面处理每日任务，结束于每日页或战役菜单。"""
        self.daily_run()

        # 不能停留在 page_daily，因为顺序已经乱掉。
        self.config.task_delay(server_update=True)
