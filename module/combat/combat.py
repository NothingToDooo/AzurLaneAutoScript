import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.combat import assets as combat_assets
from module.combat.combat_auto import CombatAuto
from module.combat.combat_manual import CombatManual
from module.combat.hp_balancer import HPBalancer
from module.combat.level import Level
from module.combat.submarine import SubmarineCall
from module.combat_ui import assets as combat_ui_assets
from module.handler.auto_search import AutoSearchHandler
from module.logger import logger
from module.map.assets import MAP_OFFENSIVE
from module.retire.retirement import Retirement
from module.template.assets import TEMPLATE_COMBAT_LOADING
from module.ui.assets import BACK_ARROW, EXERCISE_CHECK, MUNITIONS_CHECK

# 自动战斗暂停按钮皮肤很多，顺序很重要：相似皮肤先用颜色匹配，PAUSE_Star 必须早于 PAUSE_Nurse。
_COMBAT_EXECUTING_BUTTONS = (
    (combat_ui_assets.PAUSE, "match_luma"),
    (combat_ui_assets.PAUSE_New, "match_template_color"),
    (combat_ui_assets.PAUSE_Iridescent_Fantasy, "match_luma"),
    (combat_ui_assets.PAUSE_Christmas, "match_luma"),
    (combat_ui_assets.PAUSE_Neon, "match_template_color"),
    (combat_ui_assets.PAUSE_Cyber, "match_template_color"),
    (combat_ui_assets.PAUSE_HolyLight, "match_template_color"),
    (combat_ui_assets.PAUSE_Pharaoh, "match_luma"),
    (combat_ui_assets.PAUSE_Star, "match_luma"),
    (combat_ui_assets.PAUSE_Nurse, "match_luma"),
    (combat_ui_assets.PAUSE_Devil, "match_template_color"),
    (combat_ui_assets.PAUSE_Seaside, "match_template_color"),
    (combat_ui_assets.PAUSE_Ninja, "match_template_color"),
    (combat_ui_assets.PAUSE_ShadowPuppetry, "match_luma"),
    (combat_ui_assets.PAUSE_MaidCafe, "match_template_color"),
    (combat_ui_assets.PAUSE_Ancient, "match_template_color"),
    (combat_ui_assets.PAUSE_SpringInn, "match_template_color"),
    (combat_ui_assets.PAUSE_ElvenVine, "match_template_color"),
    (combat_ui_assets.PAUSE_GildedReverie, "match_template_color"),
    (combat_ui_assets.PAUSE_AzureCore, "match_template_color"),
)

# 部分暂停皮肤复用 QUIT_New；这里仅列出有独立资源图的退出按钮。
_COMBAT_QUIT_BUTTONS = (
    combat_ui_assets.QUIT,
    combat_ui_assets.QUIT_New,
    combat_ui_assets.QUIT_Iridescent_Fantasy,
    combat_ui_assets.QUIT_Cyber,
    combat_ui_assets.QUIT_Christmas,
    combat_ui_assets.QUIT_Pharaoh,
    combat_ui_assets.QUIT_Nurse,
    combat_ui_assets.QUIT_Seaside,
    combat_ui_assets.QUIT_Ninja,
    combat_ui_assets.QUIT_MaidCafe,
    combat_ui_assets.QUIT_SpringInn,
    combat_ui_assets.QUIT_GildedReverie,
)

_BATTLE_STATUS_BUTTONS = (
    (combat_assets.BATTLE_STATUS_S, ""),
    (combat_assets.BATTLE_STATUS_A, "Battle status A"),
    (combat_assets.BATTLE_STATUS_B, "Battle Status B"),
    (combat_assets.BATTLE_STATUS_C, "Battle Status C"),
    (combat_assets.BATTLE_STATUS_D, "Battle Status D"),
)

_GET_ITEM_CHECKS = (
    combat_assets.GET_ITEMS_1,
    combat_assets.GET_ITEMS_2,
    combat_assets.GET_ITEMS_3,
)


def _match_first_combat_ui_button(image, buttons, offset):
    for button, matcher in buttons:
        if getattr(button, matcher)(image, offset=offset):
            return button
    return False


class Combat(Level, HPBalancer, Retirement, SubmarineCall, CombatAuto, CombatManual, AutoSearchHandler):
    _automation_set_timer = Timer(1)
    battle_status_click_interval = 0

    def combat_appear(self):
        """返回是否已经进入战斗相关页面。"""
        if self.config.Campaign_UseFleetLock and not self.is_in_map() and self.is_combat_loading():
            return True

        if self.appear(combat_assets.BATTLE_PREPARATION, offset=(30, 20)):
            return True
        return (
            self.appear(combat_assets.BATTLE_PREPARATION_WITH_OVERLAY, threshold=30)
            and self.handle_combat_automation_confirm()
        )

    def map_offensive(self, skip_first_screenshot=True):
        """
        Pages:
            in: in_map, MAP_OFFENSIVE
            out: combat_appear
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(MAP_OFFENSIVE, interval=1):
                continue
            if self.handle_combat_low_emotion():
                self.interval_reset(MAP_OFFENSIVE)
                continue
            if self.handle_retirement():
                continue

            # Break
            if self.combat_appear():
                break

    def is_combat_loading(self):
        """
        Returns:
            bool:
        """
        image = self.image_crop((0, 620, 1280, 690), copy=False)
        # 国服、英文服和台服一致，日服字符更小。
        similarity, button = TEMPLATE_COMBAT_LOADING.match_luma_result(image)
        if similarity > 0.85:
            loading = (button.area[0] + 38 - combat_assets.LOADING_BAR.area[0]) / (
                combat_assets.LOADING_BAR.area[2] - combat_assets.LOADING_BAR.area[0]
            )
            logger.attr("Loading", f"{int(loading * 100)}%")
            return True
        return False

    def is_combat_executing(self):
        """
        Returns:
            Button: PAUSE button that appears
        """
        self.device.stuck_record_add(combat_ui_assets.PAUSE)
        return _match_first_combat_ui_button(self.device.image, _COMBAT_EXECUTING_BUTTONS, offset=(10, 10))

    def handle_combat_quit(self, offset=(20, 20), interval=3):
        timer = self.get_interval_timer(combat_ui_assets.QUIT, interval=interval)
        if not timer.reached():
            return False
        for button in _COMBAT_QUIT_BUTTONS:
            if button.match_luma(self.device.image, offset=offset):
                self.device.click(button)
                timer.reset()
                return True
        return False

    def handle_combat_quit_reconfirm(self, interval=2):
        # QUIT_RECONFIRM interval should shorter than QUIT,
        # so multiple retries can be made during the interval of QUIT
        if self.appear_then_click(combat_assets.QUIT_RECONFIRM, offset=(20, 20), interval=interval):
            # reset QUIT timer to avoid duplicate QUIT clicks canceling QUIT_RECONFIRM
            self.interval_reset(combat_ui_assets.QUIT)
            return True
        return False

    def ensure_combat_oil_loaded(self):
        self.wait_until_stable(combat_assets.COMBAT_OIL_LOADING)

    def handle_combat_automation_confirm(self):
        if self.appear(combat_assets.AUTOMATION_CONFIRM_CHECK, threshold=30, interval=1):
            self.appear_then_click(combat_assets.AUTOMATION_CONFIRM, offset=(20, 20))
            return True

        return False

    def combat_preparation(self, balance_hp=False, emotion_reduce=False, auto="combat_auto", fleet_index=1):
        """
        Args:
            balance_hp (bool):
            emotion_reduce (bool):
            auto (str):
            fleet_index (int):
        """
        logger.info("Combat preparation.")
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        interval_set = False

        if emotion_reduce:
            self.emotion.wait(fleet_index=fleet_index)
        if balance_hp:
            self.hp_balance()

        for _ in self.loop():
            if self.appear(combat_assets.BATTLE_PREPARATION, offset=(20, 20)) and self.handle_combat_automation_set(
                auto=auto == "combat_auto"
            ):
                continue
            if self.handle_retirement():
                continue
            if self.handle_combat_low_emotion():
                continue
            if balance_hp and self.handle_emergency_repair_use():
                continue
            if self.handle_battle_preparation():
                continue
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue
            # 提前降低截图间隔。
            if not interval_set and self.is_combat_loading():
                self.device.screenshot_interval_set("combat")
                interval_set = True

            # End
            pause = self.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                if emotion_reduce:
                    self.emotion.reduce(fleet_index)
                # 未识别到 is_combat_loading() 时兜底降低截图间隔。
                if not interval_set:
                    self.device.screenshot_interval_set("combat")
                break

    def handle_battle_preparation(self):
        """返回是否点击了战斗准备按钮。"""
        return self.appear_then_click(combat_assets.BATTLE_PREPARATION, offset=(20, 20), interval=2)

    def handle_combat_automation_set(self, auto):
        """
        Args:
            auto (bool): If use auto.

        Returns:
            bool:
        """
        if not self._automation_set_timer.reached():
            return False

        if self.appear(combat_assets.AUTOMATION_ON):
            logger.info("[Automation] ON")
            if not auto:
                self.device.click(combat_assets.AUTOMATION_SWITCH)
                self.device.sleep(1)
                self._automation_set_timer.reset()
                return True

        if self.appear(combat_assets.AUTOMATION_OFF):
            logger.info("[Automation] OFF")
            if auto:
                self.device.click(combat_assets.AUTOMATION_SWITCH)
                self.device.sleep(1)
                self._automation_set_timer.reset()
                return True

        if self.handle_combat_automation_confirm():
            self._automation_set_timer.reset()
            return True

        return False

    def handle_emergency_repair_use(self):
        if not self.config.HpControl_UseEmergencyRepair:
            return False

        if self.appear_then_click(combat_assets.EMERGENCY_REPAIR_CONFIRM, offset=True, interval=3):
            return True
        if self.appear(combat_assets.BATTLE_PREPARATION, offset=(20, 20)) and self.appear(
            combat_assets.EMERGENCY_REPAIR_AVAILABLE
        ):
            # When entering battle_preparation page (or after emergency repairing),
            # the emergency icon is active by default, even if nothing to use.
            # After a short animation, everything shows as usual.
            # Using fleet power number as a stable checker.
            # First wait for it to be non-zero, then wait for it to be stable.
            self.wait_until_disappear(combat_assets.MAIN_FLEET_POWER_ZERO, offset=(20, 20))
            stable_checker = Button(
                area=combat_assets.MAIN_FLEET_POWER_ZERO.area,
                color=(),
                button=combat_assets.MAIN_FLEET_POWER_ZERO.button,
                name="STABLE_CHECKER",
            )
            self.wait_until_stable(stable_checker)
            if not self.appear(combat_assets.EMERGENCY_REPAIR_AVAILABLE):
                return False

            logger.info("EMERGENCY_REPAIR_AVAILABLE")
            if not len(self.hp):
                return False
            if max(self.hp[:3]) <= 0.001 or max(self.hp[3:]) <= 0.001:
                logger.warning(f"Invalid HP to use emergency repair: {self.hp}")
                return False

            hp = np.array(self.hp)
            hp = hp[hp > 0.001]
            if (
                (len(hp) and np.min(hp) < self.config.HpControl_RepairUseSingleThreshold)
                or max(self.hp[:3]) < self.config.HpControl_RepairUseMultiThreshold
                or max(self.hp[3:]) < self.config.HpControl_RepairUseMultiThreshold
            ):
                logger.info("Use emergency repair")
                self.device.click(combat_assets.EMERGENCY_REPAIR_AVAILABLE)
                self.interval_clear(combat_assets.EMERGENCY_REPAIR_CONFIRM)
                return True

        return False

    def combat_execute(self, auto="combat_auto", submarine="do_not_use"):
        """
        Args:
            auto (str): ['combat_auto', 'combat_manual', 'stand_still_in_the_middle', 'hide_in_bottom_left']
            submarine (str): ['do_not_use', 'hunt_only', 'every_combat']
        """
        logger.info("Combat execute")
        self.submarine_call_reset()
        self.combat_auto_reset()
        self.combat_manual_reset()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        confirm_timer = Timer(10)
        confirm_timer.start()

        for _ in self.loop():
            if not confirm_timer.reached() and self.handle_combat_automation_confirm():
                continue

            if self.handle_story_skip():
                continue
            if self.handle_combat_auto(auto):
                continue
            if self.handle_combat_manual(auto):
                continue
            if (
                auto != "combat_auto"
                and self.auto_mode_checked
                and self.is_combat_executing()
                and self.handle_combat_weapon_release()
            ):
                continue
            if self.handle_submarine_call(submarine):
                continue
            # bunch of popup handlers
            if self.handle_popup_confirm("COMBAT_EXECUTE"):
                continue
            if self.handle_urgent_commission():
                continue
            if self.handle_guild_popup_cancel():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_mission_popup_ack():
                continue

            # End
            if self.handle_battle_status() or self.handle_get_items():
                break

    def handle_battle_status(self):
        """
        Returns:
            bool:
        """
        if self.is_combat_executing():
            return False
        for button, warning in _BATTLE_STATUS_BUTTONS:
            if self.appear(button, interval=self.battle_status_click_interval):
                if warning:
                    logger.warning(warning)
                self.device.sleep((0.25, 0.5))
                self.device.click(button)
                return True

        return False

    def handle_get_items(self):
        """
        Returns:
            bool:
        """
        for button in _GET_ITEM_CHECKS:
            if self.appear(button, offset=5, interval=self.battle_status_click_interval):
                self.device.click(combat_assets.GET_ITEMS_1)
                self.interval_reset(combat_assets.BATTLE_STATUS_S)
                self.interval_reset(combat_assets.BATTLE_STATUS_A)
                self.interval_reset(combat_assets.BATTLE_STATUS_B)
                return True

        return False

    def handle_exp_info(self):
        """
        Returns:
            bool:
        """
        if self.is_combat_executing():
            return False
        if self.appear_then_click(combat_assets.EXP_INFO_S):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(combat_assets.EXP_INFO_A):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(combat_assets.EXP_INFO_B):
            self.device.sleep((0.25, 0.5))
            return True

        return False

    def handle_get_ship(self):
        """
        Returns:
            bool:
        """
        if self.appear_then_click(combat_assets.GET_SHIP, interval=1):
            if self.appear(combat_assets.NEW_SHIP):
                logger.info("Get a new SHIP")
                self.config.GET_SHIP_TRIGGERED = True
            return True

        return False

    def handle_combat_mis_click(self):
        """
        Returns:
            bool:
        """
        if self.appear(MUNITIONS_CHECK, offset=(20, 20), interval=5):
            logger.info(f"{MUNITIONS_CHECK} -> {BACK_ARROW}")
            self.device.click(BACK_ARROW)
            return True
        if self.appear(EXERCISE_CHECK, offset=(20, 20), interval=5):
            logger.info(f"{EXERCISE_CHECK} -> {BACK_ARROW}")
            self.device.click(BACK_ARROW)
            return True

        return False

    def combat_status(self, expected_end=None):
        """
        Args:
            expected_end (str, callable): with_searching, no_searching, in_stage.
        """
        logger.info("Combat status")
        logger.attr("expected_end", expected_end.__name__ if callable(expected_end) else expected_end)
        self.device.screenshot_interval_set()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        battle_status = False
        exp_info = False  # This is for the white screen bug in game
        for _ in self.loop():
            # Expected end
            if isinstance(expected_end, str):
                if expected_end == "in_stage" and self.handle_in_stage():
                    break
                if expected_end == "with_searching" and self.handle_in_map_with_enemy_searching():
                    break
                if expected_end == "no_searching" and self.handle_in_map_no_enemy_searching():
                    break
                if expected_end == "in_ui" and self.appear(BACK_ARROW, offset=(30, 30)):
                    break
            if callable(expected_end) and expected_end():
                break

            if self.handle_story_skip():
                continue
            # Combat status
            if not exp_info and self.handle_get_ship():
                continue
            if self.handle_get_items():
                continue
            if self.handle_popup_confirm("COMBAT_STATUS"):
                if battle_status and not exp_info:
                    logger.info("Locking a new ship")
                    self.config.GET_SHIP_TRIGGERED = True
                continue
            if not battle_status:
                if not exp_info and self.handle_battle_status():
                    battle_status = True
                    continue
                if self.handle_exp_info():
                    exp_info = True
                    continue
            else:
                # Check exp_info first if battle_status has been clicked.
                if self.handle_exp_info():
                    exp_info = True
                    continue
                if not exp_info and self.handle_battle_status():
                    battle_status = True
                    continue
            # bunch of popup handlers
            if self.handle_popup_confirm("COMBAT_STATUS"):
                continue
            if self.handle_urgent_commission():
                continue
            if self.handle_guild_popup_cancel():
                continue
            if self.handle_vote_popup():
                continue
            if self.handle_mission_popup_ack():
                continue
            # additional handlers in combat
            if self.handle_auto_search_exit():
                continue
            if self.handle_combat_mis_click():
                continue

            # End
            if self.handle_in_stage():
                break
            if expected_end is None and self.handle_in_map_with_enemy_searching():
                break

    def combat(
        self,
        balance_hp=None,
        emotion_reduce=None,
        auto_mode=None,
        submarine_mode=None,
        expected_end=None,
        fleet_index=1,
    ):
        """
        Execute a combat.
        Will use user config if argument is None.

        Args:
            balance_hp (bool):
            emotion_reduce (bool):
            auto_mode (str): combat_auto, combat_manual, stand_still_in_the_middle, hide_in_bottom_left
            submarine_mode (str): do_not_use, hunt_only, every_combat
            expected_end (str, callable):
            fleet_index (int): 1 or 2
        """
        balance_hp = balance_hp if balance_hp is not None else self.config.HpControl_UseHpBalance
        emotion_reduce = emotion_reduce if emotion_reduce is not None else self.emotion.is_calculate
        if auto_mode is None:
            auto_mode = self.config.Fleet_Fleet1Mode if fleet_index == 1 else self.config.Fleet_Fleet2Mode
        if submarine_mode is None:
            submarine_mode = "do_not_use"
            if self.config.Submarine_Fleet:
                submarine_mode = self.config.Submarine_Mode

        self.combat_preparation(
            balance_hp=balance_hp, emotion_reduce=emotion_reduce, auto=auto_mode, fleet_index=fleet_index
        )
        self.combat_execute(auto=auto_mode, submarine=submarine_mode)
        self.combat_status(expected_end=expected_end)

        logger.info("Combat end.")
