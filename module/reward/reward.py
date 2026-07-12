from typing import Literal

from module.base.button import Button, ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.combat import assets as combat_assets
from module.logger import logger
from module.reward import assets as reward_assets
from module.ui.navbar import Navbar, NavbarColorRule, NavbarTarget, NavbarVisualRules
from module.ui.page import page_main, page_mission, page_reward
from module.ui.ui import UI
from module.ui_white.assets import MISSION_NOTICE_WHITE

type MissionState = Button | Literal["timeout"]


class Reward(UI):
    def reward_receive(self, *, oil: bool, coin: bool, exp: bool) -> bool:
        """在奖励页按开关领取资源；全部关闭返回 False，否则完成轮询后返回 True。"""
        if not oil and not coin and not exp:
            return False

        logger.hr("Reward receive")
        logger.info(f"oil={oil}, coin={coin}, exp={exp}")
        confirm_timer = Timer(1, count=3).start()
        # 点击间隔设为 0.3 秒，避免游戏响应不过来。
        click_timer = Timer(0.3)
        for _ in self.loop():
            if (
                oil
                and click_timer.reached()
                and self.appear_then_click(reward_assets.OIL, offset=(20, 50), interval=60)
            ):
                confirm_timer.reset()
                click_timer.reset()
                continue
            if (
                coin
                and click_timer.reached()
                and self.appear_then_click(reward_assets.COIN, offset=(25, 50), interval=60)
            ):
                confirm_timer.reset()
                click_timer.reset()
                continue
            if (
                exp
                and click_timer.reached()
                and self.appear_then_click(reward_assets.EXP, offset=(30, 50), interval=60)
            ):
                confirm_timer.reset()
                click_timer.reset()
                continue

            if confirm_timer.reached():
                break

        logger.info("Reward receive end")
        return True

    def _reward_get_state(self) -> Button | None:
        """返回四种任务按钮状态之一，无法判断时返回 None。"""
        if self.appear(reward_assets.MISSION_MULTI, offset=(20, 20)):
            return reward_assets.MISSION_MULTI
        if self.match_template_color(reward_assets.MISSION_SINGLE, offset=(50, 200)):
            return reward_assets.MISSION_SINGLE
        if self.appear(reward_assets.MISSION_EMPTY, offset=(20, 20)):
            return reward_assets.MISSION_EMPTY
        if self.appear(reward_assets.MISSION_UNFINISH, offset=(50, 200)):
            return reward_assets.MISSION_UNFINISH
        return None

    def _reward_mission_claim_click(self) -> bool:
        """在任务页点击可领取按钮，返回是否已点击并进入奖励弹窗。"""
        clicked = False
        click_interval = Timer(1, count=2)
        for _ in self.loop():
            if clicked and not self.ui_page_appear(page_mission):
                return clicked
            if click_interval.reached():
                if self.appear_then_click(reward_assets.MISSION_MULTI, offset=(20, 20)):
                    click_interval.reset()
                    clicked = True
                    continue
                if self.match_template_color(reward_assets.MISSION_SINGLE, offset=(50, 200)):
                    self.device.click(reward_assets.MISSION_SINGLE)
                    click_interval.reset()
                    clicked = True
                    continue
                if self.appear(reward_assets.MISSION_UNFINISH, offset=(50, 200)):
                    return clicked
        return clicked

    def _reward_mission_receive_state(self, timeout: Timer) -> MissionState | None:
        if not self.ui_page_appear(page_mission):
            timeout.reset()
            return None

        state = self._reward_get_state()
        if state:
            return state
        if timeout.reached():
            logger.warning("Wait mission receive timeout")
            return "timeout"
        return None

    def _handle_reward_mission_receive_popup(self) -> bool:
        if self._appear_then_click_any(
            [
                (combat_assets.GET_ITEMS_1, {"offset": (30, 30), "interval": 1}),
                (combat_assets.GET_ITEMS_2, {"offset": (30, 30), "interval": 1}),
                (combat_assets.GET_SHIP, {"interval": 1}),
            ]
        ):
            return True
        return (
            self.handle_mission_popup_ack()
            or self.handle_vote_popup()
            or self.handle_story_skip()
            or self.handle_popup_confirm("MISSION_REWARD")
        )

    def _reward_mission_claim_receive(self) -> MissionState:
        """处理奖励弹窗并返回任务按钮状态；两秒超时返回 'timeout'。"""
        logger.info("Mission claim receive")
        timeout = Timer(2, count=6).start()
        for _ in self.loop():
            state = self._reward_mission_receive_state(timeout)
            if state:
                return state
            if self._handle_reward_mission_receive_popup():
                continue
        return "timeout"

    def _reward_wait_mission_list(self) -> MissionState:
        """在任务页等待任一任务状态；一秒超时返回 'timeout'。"""
        timeout = Timer(1, count=2).start()
        for _ in self.loop():
            state = self._reward_get_state()
            if state:
                return state
            if timeout.reached():
                return "timeout"
        return "timeout"

    def _reward_mission_collect(self) -> MissionState:
        """领取当前任务页奖励，返回最终按钮状态或 'timeout'。"""
        state = self._reward_wait_mission_list()
        while 1:
            logger.attr("MissionState", state)
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            if state == "timeout":
                logger.warning("Reward wait mission list timeout")
                return state
            if state in [reward_assets.MISSION_EMPTY, reward_assets.MISSION_UNFINISH]:
                logger.info("Mission collect finished")
                break
            if state in [reward_assets.MISSION_MULTI, reward_assets.MISSION_SINGLE]:
                # 清理下列资产已有的点击间隔。
                self.interval_clear(
                    [
                        combat_assets.GET_ITEMS_1,
                        combat_assets.GET_ITEMS_2,
                        reward_assets.MISSION_MULTI,
                        reward_assets.MISSION_SINGLE,
                        combat_assets.GET_SHIP,
                    ]
                )
                self._reward_mission_claim_click()
                state = self._reward_mission_claim_receive()
                continue
            logger.warning("Empty mission state, mission collect finished")

        return state

    def _reward_mission_all(self) -> MissionState:
        """切到全部任务并返回最终任务状态。"""
        self.reward_side_navbar_ensure(upper=1)
        return self._reward_mission_collect()

    def _reward_mission_weekly(self) -> MissionState | Literal[False]:
        """有周常红点时领取并返回最终状态；无红点返回 False。"""
        if not self.image_color_count(
            reward_assets.MISSION_WEEKLY_RED_DOT, color=(206, 81, 66), threshold=221, count=20
        ):
            logger.info("No MISSION_WEEKLY_RED_DOT")
            return False

        self.reward_side_navbar_ensure(upper=5)
        return self._reward_mission_collect()

    def reward_mission_notice(self) -> bool:
        """在主页判断普通或白色 UI 的任务通知是否出现。"""
        if self.appear(reward_assets.MISSION_NOTICE):
            logger.info("Found mission notice MISSION_NOTICE")
            return True
        if self.image_color_count(MISSION_NOTICE_WHITE, color=(214, 117, 99), threshold=221, count=20):
            logger.info("Found mission notice MISSION_NOTICE_WHITE")
            return True

        return False

    def reward_mission(self, *, daily: bool = True, weekly: bool = True) -> bool:
        """从主页进入任务页按开关领取；该流程固定返回 False。"""
        if not daily and not weekly:
            return False
        logger.hr("Mission reward")
        if not self.reward_mission_notice():
            return False

        self.ui_goto(page_mission, skip_first_screenshot=True)

        if daily:
            self._reward_mission_all()
        if weekly:
            self._reward_mission_weekly()
        return False

    @cached_property
    def _reward_side_navbar(self) -> Navbar:
        """侧栏从上到下依次为全部、主线、支线、日常、周常、活动。"""
        return self._build_reward_side_navbar()

    @staticmethod
    def _build_reward_side_navbar() -> Navbar:
        reward_side_navbar = ButtonGrid(
            origin=(21, 118),
            delta=(0, 94.5),
            button_shape=(60, 75),
            grid_shape=(1, 6),
            name="REWARD_SIDE_NAVBAR",
        )
        return Navbar(
            grids=reward_side_navbar,
            visual=NavbarVisualRules(active=NavbarColorRule(color=(247, 255, 173))),
        )

    def reward_side_navbar_ensure(self, *, upper: int | None = None, bottom: int | None = None) -> bool:
        """按上方 1～6 或下方逆序 1～6 选择侧栏；不等待目标页面加载。"""
        return self._reward_side_navbar.set(self, NavbarTarget(upper=upper, bottom=bottom))

    def run(self) -> None:
        """从任意页面领取资源和任务奖励，结束于主页或任务页。"""
        self.ui_ensure(page_reward)
        self.reward_receive(
            oil=self.config.Reward_CollectOil, coin=self.config.Reward_CollectCoin, exp=self.config.Reward_CollectExp
        )
        self.ui_goto(page_main)
        self.reward_mission(daily=self.config.Reward_CollectMission, weekly=self.config.Reward_CollectWeeklyMission)
        self.config.task_delay(success=True)
