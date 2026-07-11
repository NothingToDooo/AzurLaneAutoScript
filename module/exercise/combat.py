from module.base.timer import Timer
from module.combat.assets import (
    BATTLE_PREPARATION,
    BATTLE_STATUS_D,
    BATTLE_STATUS_S,
    EXP_INFO_D,
    EXP_INFO_S,
    GET_ITEMS_1,
    OPTS_INFO_D,
)
from module.combat.combat import Combat
from module.exercise.assets import CLICK_SAFE_AREA, EXERCISE_PREPARATION
from module.exercise.equipment import ExerciseEquipment
from module.exercise.hp_daemon import HpDaemon
from module.exercise.opponent import OPPONENT, OpponentChoose
from module.logger import logger
from module.ui.assets import EXERCISE_CHECK


class ExerciseCombat(HpDaemon, OpponentChoose, ExerciseEquipment, Combat):
    def _in_exercise(self):
        return self.appear(EXERCISE_CHECK, offset=(20, 20))

    def _combat_preparation(self, skip_first_screenshot=True):
        logger.info("Combat preparation")
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
                self.device.click(BATTLE_PREPARATION)
                continue

            pause = self.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                break

    def _exercise_combat_ended(self, end):
        if not (self._in_exercise() or self.appear(BATTLE_PREPARATION, offset=(20, 20))):
            return False
        logger.hr("Combat end")
        if not end:
            logger.warning("Combat ended without end conditions detected")
        return True

    def _handle_exercise_battle_status(self):
        if self.appear(BATTLE_STATUS_S, interval=1):
            logger.info(f"{BATTLE_STATUS_S} -> {CLICK_SAFE_AREA}")
            self.device.click(CLICK_SAFE_AREA)
            return True
        if self.appear(BATTLE_STATUS_D, interval=1):
            logger.info(f"{BATTLE_STATUS_D} -> {CLICK_SAFE_AREA}")
            self.device.click(CLICK_SAFE_AREA)
            logger.info("Exercise LOST")
            return True
        return False

    def _handle_exercise_reward_screens(self, battle_status_detected):
        if battle_status_detected and self.appear(GET_ITEMS_1, offset=(30, 30), interval=1):
            logger.info(f"{GET_ITEMS_1} -> {CLICK_SAFE_AREA}")
            self.device.click(CLICK_SAFE_AREA)
            return True, False
        if self.appear(EXP_INFO_S, interval=1):
            logger.info(f"{EXP_INFO_S} -> {CLICK_SAFE_AREA}")
            self.device.click(CLICK_SAFE_AREA)
            return True, False
        if self.appear(EXP_INFO_D, interval=1):
            logger.info(f"{EXP_INFO_D} -> {CLICK_SAFE_AREA}")
            self.device.click(CLICK_SAFE_AREA)
            return True, False
        if self.appear_then_click(OPTS_INFO_D, offset=(30, 30), interval=1):
            logger.info("Exercise LOST")
            return True, True
        return False, False

    def _handle_exercise_quit(self, pause_interval):
        if self.handle_combat_quit():
            pause_interval.reset()
            return True, True
        if self.handle_combat_quit_reconfirm():
            pause_interval.reset()
            return None, True
        return None, False

    def _handle_exercise_low_hp(self, p, pause, pause_interval, show_hp_timer):
        if p and self._at_low_hp(image=self.device.image, pause=pause):
            logger.info("Exercise quit")
            if pause_interval.reached():
                self.device.click(p)
                pause_interval.reset()
                return True
        elif show_hp_timer.reached():
            show_hp_timer.reset()
            self._show_hp()
        return False

    def _handle_exercise_combat_popups(self):
        return (
            self.handle_popup_confirm("EXERCISE_COMBAT_EXECUTE")
            or self.handle_urgent_commission()
            or self.handle_guild_popup_cancel()
            or self.handle_vote_popup()
            or self.handle_mission_popup_ack()
        )

    def _update_exercise_combat_pause(self, pause, end):
        p = self.is_combat_executing()
        if p:
            if end:
                end = False
            if pause is None:
                pause = p
        else:
            self.low_hp_confirm_timer.reset()
        return p, pause, end

    def _handle_exercise_reward_result(self, battle_status_detected):
        handled_reward, reward_end = self._handle_exercise_reward_screens(battle_status_detected)
        if not handled_reward:
            return None
        return reward_end

    def _combat_execute(self):
        """正常结算时返回 True；低血量主动退出时返回 False。"""
        logger.info("Combat execute")
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        self.low_hp_confirm_timer = Timer(1.5, count=2).start()
        show_hp_timer = Timer(5)
        pause_interval = Timer(0.5, count=1)
        # 暂停按钮皮肤决定血条布局。
        pause = None
        success = True
        end = False
        battle_status_detected = False
        while 1:
            self.device.screenshot()
            if self._exercise_combat_ended(end):
                break
            p, pause, end = self._update_exercise_combat_pause(pause, end)
            if not p and self._handle_exercise_battle_status():
                success = True
                end = True
                battle_status_detected = True
                continue

            # 仅在识别到战斗结算后处理 GET_ITEMS_1，避免误判。
            reward_end = self._handle_exercise_reward_result(battle_status_detected)
            if reward_end is not None:
                if reward_end:
                    success = True
                    end = True
                continue
            quit_success, handled = self._handle_exercise_quit(pause_interval)
            if handled:
                if quit_success is not None:
                    success = quit_success
                    end = True
                continue
            if not end and self._handle_exercise_low_hp(p, pause, pause_interval, show_hp_timer):
                continue
            if self._handle_exercise_combat_popups():
                continue
        return success

    def _choose_opponent(self, index, skip_first_screenshot=True):
        """按从左到右的 0～3 索引进入对手准备页。"""
        logger.hr(f"Opponent: {index}")
        opponent_timer = Timer(5)
        preparation_timer = Timer(5)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if opponent_timer.reached() and self._in_exercise():
                self.device.click(OPPONENT[index, 0])
                opponent_timer.reset()

            if preparation_timer.reached() and self.appear_then_click(EXERCISE_PREPARATION):
                preparation_timer.reset()
                opponent_timer.reset()
                continue

            if self.appear(BATTLE_PREPARATION, offset=(20, 20)):
                break

    def _preparation_quit(self):
        logger.info("Preparation quit")
        self.ui_back(check_button=self._in_exercise, appear_button=BATTLE_PREPARATION, skip_first_screenshot=True)

    def _combat(self, opponent):
        """挑战索引 0～3 的对手；低血量退出重试耗尽后返回 False。"""
        self._choose_opponent(opponent)

        trial = self.config.Exercise_OpponentTrial
        if not isinstance(trial, int) or trial < 1:
            logger.warning(f"Invalid Exercise.OpponentTrial: {trial}, revise to 1")
            self.config.Exercise_OpponentTrial = 1

        for n in range(1, self.config.Exercise_OpponentTrial + 1):
            logger.hr(f"Try: {n}")
            self._combat_preparation()
            success = self._combat_execute()
            if success:
                return success

        self._preparation_quit()
        return False

    def equipment_take_off_when_finished(self):
        if self.config.EXERCISE_FLEET_EQUIPMENT is None:
            return False
        if not self.equipment_has_take_on:
            return False

        self._choose_opponent(0)
        self.equipment_take_off()
        self._preparation_quit()
        return True

    def equipment_take_on(self):
        if self.config.EXERCISE_FLEET_EQUIPMENT is None:
            return False
        if self.equipment_has_take_on:
            return False

        self._choose_opponent(0)
        super().equipment_take_on()
        self._preparation_quit()
        return True
