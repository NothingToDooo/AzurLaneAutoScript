from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.base.utils import random_rectangle_vector
from module.event_hospital import assets as hospital_assets
from module.event_hospital.clue import HospitalClue
from module.event_hospital.combat import HospitalCombat
from module.logger import logger
from module.ui.page import page_hospital
from module.ui.switch import Switch

if TYPE_CHECKING:
    from module.base.base import ModuleBase


class HospitalSwitch(Switch):
    def get(self, main: ModuleBase) -> str:
        """返回当前页签状态；无法识别时返回 unknown。"""
        for data in self.state_list:
            if main.image_color_count(data["check_button"], color=(33, 77, 189), threshold=221, count=100):
                return data["state"]

        return "unknown"


HOSPITAL_TAB = HospitalSwitch("HOSPITAL_ASIDE", is_selector=True)
HOSPITAL_TAB.add_state("LOCATION", check_button=hospital_assets.TAB_LOCATION)
HOSPITAL_TAB.add_state("CHARACTER", check_button=hospital_assets.TAB_CHARACTER)


class Hospital(HospitalClue, HospitalCombat):
    def daily_red_dot_appear(self) -> bool:
        return self.image_color_count(hospital_assets.DAILY_RED_DOT, color=(189, 69, 66), threshold=221, count=35)

    def daily_reward_receive_appear(self) -> bool:
        return self.image_color_count(
            hospital_assets.DAILY_REWARD_RECEIVE, color=(41, 73, 198), threshold=221, count=200
        )

    def is_in_daily_reward(self, interval: float = 0) -> bool:
        return self.match_template_color(hospital_assets.HOSIPITAL_CLUE_CHECK, offset=(30, 30), interval=interval)

    def daily_reward_receive(self) -> bool:
        """在医院主页领取每日奖励并返回是否成功，结束后仍在医院主页。"""
        if not self._daily_reward_available():
            return False

        logger.hr("Daily reward receive", level=2)
        self._enter_daily_reward()
        self._claim_daily_reward()
        self._exit_daily_reward()
        return True

    def _daily_reward_available(self) -> bool:
        if self.daily_red_dot_appear():
            logger.info("Daily red dot appear")
            return True

        logger.info("No daily red dot")
        return False

    def _enter_daily_reward(self) -> None:
        logger.info("Daily reward enter")
        skip_first_screenshot = True
        self.interval_clear(page_hospital.check_button)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.is_in_daily_reward():
                break
            if self.ui_page_appear(page_hospital, interval=2):
                logger.info(f"{page_hospital} -> {hospital_assets.HOSPITAL_GOTO_DAILY}")
                self.device.click(hospital_assets.HOSPITAL_GOTO_DAILY)
                continue

    def _claim_daily_reward(self) -> None:
        logger.info("Daily reward receive")
        skip_first_screenshot = True
        self.interval_clear(hospital_assets.HOSIPITAL_CLUE_CHECK)
        timeout = Timer(1.5, count=6).start()
        clicked = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if timeout.reached():
                logger.warning("Daily reward receive timeout")
                break
            if clicked and self.is_in_daily_reward() and not self.daily_reward_receive_appear():
                break
            if self.is_in_daily_reward(interval=2) and self.daily_reward_receive_appear():
                self.device.click(hospital_assets.DAILY_REWARD_RECEIVE)
                continue
            if self.handle_get_items():
                timeout.reset()
                clicked = True
                continue

    def _exit_daily_reward(self) -> None:
        logger.info("Daily reward exit")
        skip_first_screenshot = True
        self.interval_clear(hospital_assets.HOSIPITAL_CLUE_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_page_appear(page_hospital):
                break
            if self.is_in_daily_reward(interval=2):
                self.device.click(hospital_assets.HOSIPITAL_CLUE_CHECK)
                logger.info(f"is_in_daily_reward -> {hospital_assets.HOSIPITAL_CLUE_CHECK}")
                continue

    def execute_selected_investigation_once(self, *, check_emotion: bool = True) -> bool:
        """完成当前侧栏任务的一次调查；无可调查项目时返回 False。"""
        self.config.apply_runtime_overlay(Fleet_FleetOrder="fleet1_all_fleet2_standby")
        if check_emotion:
            self.emotion.check_reduce(battle=1)
        if not self.invest_enter():
            return False
        self.hospital_combat()
        self.claim_invest_reward()
        return True

    def invest_reward_appear(self) -> bool:
        return self.image_color_count(
            hospital_assets.INVEST_REWARD_RECEIVE, color=(33, 77, 189), threshold=221, count=100
        )

    def claim_invest_reward(self) -> bool:
        """在线索页领取调查奖励，并返回是否成功。"""
        if self.invest_reward_appear():
            logger.info("Invest reward appear")
        else:
            logger.info("No invest reward")
            return False
        skip_first_screenshot = True
        clicked = True
        self.interval_clear(hospital_assets.HOSIPITAL_CLUE_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if clicked and self.is_in_clue() and not self.invest_reward_appear():
                return True
            if self.handle_get_items():
                clicked = True
                continue
            if self.is_in_clue(interval=2) and self.invest_reward_appear():
                self.device.click(hospital_assets.INVEST_REWARD_RECEIVE)
                continue
        return False

    def aside_swipe_down(self, *, skip_first_screenshot: bool = True) -> None:
        logger.info("Aside swipe down")
        swiped = False
        interval = Timer(2, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if swiped and not self.appear(hospital_assets.ASIDE_NEXT_PAGE, offset=(20, 20)):
                logger.info("Aside reached end")
                break
            if interval.reached():
                p1, p2 = random_rectangle_vector(
                    vector=(0, -200),
                    box=hospital_assets.CLUE_LIST.area,
                    random_range=(-20, -10, 20, 10),
                )
                self.device.swipe(p1, p2)
                interval.reset()
                swiped = True
                continue
