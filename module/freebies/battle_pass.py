from module.base.timer import Timer
from module.base.utils import get_color
from module.combat.combat import Combat
from module.freebies.assets import (
    BATTLE_PASS_RED_DOT,
    PURCHASE_POPUP,
    REWARD_RECEIVE,
    REWARD_RECEIVE_SP,
    REWARD_RECEIVE_WHITE,
)
from module.logger import logger
from module.ui.assets import BATTLE_PASS_CHECK, REWARD_GOTO_BATTLE_PASS
from module.ui.page import page_reward
from module.ui.ui import UI
from module.ui_white.assets import POPUP_CONFIRM_WHITE_BATTLEPASS


class BattlePass(Combat, UI):
    def battle_pass_red_dot_appear(self) -> bool:
        """在 page_reward 判断战令入口红点是否出现。"""
        if self.appear(REWARD_GOTO_BATTLE_PASS, offset=(50, 150)):
            # 从 REWARD_GOTO_BATTLE_PASS 读取偏移，因为入口可能不在最上方。
            BATTLE_PASS_RED_DOT.load_offset(REWARD_GOTO_BATTLE_PASS)
            # 红点是透明素材，背景不同会影响颜色，所以不使用 self.appear()。
            r, _, _ = get_color(self.device.image, BATTLE_PASS_RED_DOT.button)
            if r > BATTLE_PASS_RED_DOT.color[0] - 40:
                logger.info("Found battle pass red dot")
                return True
            logger.info("No battle pass red dot")
            return False
        logger.warning("No battle pass entrance")
        return False

    def handle_battle_pass_popup(self) -> bool:
        return self.appear_then_click(PURCHASE_POPUP, offset=(20, 20), interval=2)

    def battle_pass_enter(self) -> None:
        """从 page_reward 进入战令页。"""

        def appear_button() -> bool:
            return self.appear(REWARD_GOTO_BATTLE_PASS, offset=(50, 150))

        self.ui_click(
            REWARD_GOTO_BATTLE_PASS,
            appear_button=appear_button,
            check_button=BATTLE_PASS_CHECK,
            additional=self.handle_battle_pass_popup,
            skip_first_screenshot=True,
        )

    def _handle_battle_pass_reward_button(self, confirm_timer: Timer) -> bool:
        if self.appear_then_click(REWARD_RECEIVE, offset=(20, 20), interval=3):
            confirm_timer.reset()
            return True
        if self.match_template_color(REWARD_RECEIVE_SP, offset=(20, 20), interval=3, threshold=15):
            self.device.click(REWARD_RECEIVE_SP)
            confirm_timer.reset()
            return True
        if self.appear_then_click(REWARD_RECEIVE_WHITE, offset=(20, 20), interval=3):
            confirm_timer.reset()
            return True
        return False

    def _handle_battle_pass_confirm_popup(self, confirm_timer: Timer) -> bool:
        if self.handle_battle_pass_popup():
            confirm_timer.reset()
            return True
        if self.appear_then_click(POPUP_CONFIRM_WHITE_BATTLEPASS, offset=(20, 20), interval=3):
            confirm_timer.reset()
            return True
        # 新 META 舰船锁定确认。
        if self.handle_popup_confirm("BATTLE_PASS"):
            confirm_timer.reset()
            return True
        return False

    def _handle_battle_pass_reward_result(self, confirm_timer: Timer) -> bool:
        if self.handle_get_items() or self.handle_get_ship() or self.handle_get_skin():
            confirm_timer.reset()
            return True
        return False

    def _battle_pass_receive_finished(self, confirm_timer: Timer) -> bool:
        if (
            self.appear(BATTLE_PASS_CHECK, offset=(20, 20))
            and not self.appear(REWARD_RECEIVE, offset=(20, 20))
            and not self.appear(REWARD_RECEIVE_WHITE, offset=(20, 20))
        ):
            return confirm_timer.reached()
        confirm_timer.reset()
        return False

    def battle_pass_receive(self, *, skip_first_screenshot: bool = True) -> bool:
        """在战令页领取全部可领奖励，返回是否实际领取。"""
        logger.hr("Battle pass receive", level=1)
        self.battle_status_click_interval = 2
        confirm_timer = Timer(1, count=3).start()
        received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._handle_battle_pass_reward_button(confirm_timer):
                continue
            if self._handle_battle_pass_confirm_popup(confirm_timer):
                continue
            if self._handle_battle_pass_reward_result(confirm_timer):
                received = True
                continue

            if self._battle_pass_receive_finished(confirm_timer):
                break

        logger.info(f"Battle pass receive finished, received={received}")
        return received

    def run(self) -> None:
        self.ui_ensure(page_reward)

        if self.battle_pass_red_dot_appear():
            self.battle_pass_enter()
            self.battle_pass_receive()
