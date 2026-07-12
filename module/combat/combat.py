from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Literal

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

if TYPE_CHECKING:
    from module.base.button import MatchOffset
    from module.base.type_alias import ImageArray

type CombatEnd = Literal["in_stage", "with_searching", "no_searching", "in_ui"] | Callable[[], bool]
type CombatUiMatcher = Literal["match_luma", "match_template_color"]

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


def _match_first_combat_ui_button(
    image: ImageArray,
    buttons: Sequence[tuple[Button, CombatUiMatcher]],
    offset: MatchOffset,
) -> Button | Literal[False]:
    for button, matcher in buttons:
        if matcher == "match_luma":
            matched = button.match_luma(image, offset=offset)
        else:
            matched = button.match_template_color(image, offset=offset)
        if matched:
            return button
    return False


class Combat(Level, HPBalancer, Retirement, SubmarineCall, CombatAuto, CombatManual, AutoSearchHandler):
    _automation_set_timer = Timer(1)
    battle_status_click_interval = 0

    def combat_appear(self) -> bool:
        if self.config.Campaign_UseFleetLock and not self.is_in_map() and self.is_combat_loading():
            return True

        if self.appear(combat_assets.BATTLE_PREPARATION, offset=(30, 20)):
            return True
        return (
            self.appear(combat_assets.BATTLE_PREPARATION_WITH_OVERLAY, threshold=30)
            and self.handle_combat_automation_confirm()
        )

    def map_offensive(self, *, skip_first_screenshot: bool = True) -> None:
        """页面状态：地图内或 MAP_OFFENSIVE → 战斗入口。"""
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

    def is_combat_loading(self) -> bool:
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

    def is_combat_executing(self) -> Button | Literal[False]:
        """返回当前匹配到的暂停按钮；未匹配时返回 False。"""
        self.device.stuck_record_add(combat_ui_assets.PAUSE)
        return _match_first_combat_ui_button(self.device.image, _COMBAT_EXECUTING_BUTTONS, offset=(10, 10))

    def handle_combat_quit(self, offset: MatchOffset = (20, 20), interval: float = 3) -> bool:
        timer = self.get_interval_timer(combat_ui_assets.QUIT, interval=interval)
        if not timer.reached():
            return False
        for button in _COMBAT_QUIT_BUTTONS:
            if button.match_luma(self.device.image, offset=offset):
                self.device.click(button)
                timer.reset()
                return True
        return False

    def handle_combat_quit_reconfirm(self, interval: float = 2) -> bool:
        # QUIT_RECONFIRM 的间隔必须短于 QUIT，才能在一次 QUIT 间隔内重试。
        if self.appear_then_click(combat_assets.QUIT_RECONFIRM, offset=(20, 20), interval=interval):
            # 重置 QUIT 计时，避免重复点击取消重确认。
            self.interval_reset(combat_ui_assets.QUIT)
            return True
        return False

    def ensure_combat_oil_loaded(self) -> None:
        self.wait_until_stable(combat_assets.COMBAT_OIL_LOADING)

    def handle_combat_automation_confirm(self) -> bool:
        if self.appear(combat_assets.AUTOMATION_CONFIRM_CHECK, threshold=30, interval=1):
            self.appear_then_click(combat_assets.AUTOMATION_CONFIRM, offset=(20, 20))
            return True

        return False

    def _handle_combat_preparation_action(self, *, auto: str, balance_hp: bool) -> bool:
        return (
            (
                self.appear(combat_assets.BATTLE_PREPARATION, offset=(20, 20))
                and self.handle_combat_automation_set(auto=auto == "combat_auto")
            )
            or self.handle_retirement()
            or self.handle_combat_low_emotion()
            or (balance_hp and self.handle_emergency_repair_use())
            or self.handle_battle_preparation()
            or self.handle_combat_automation_confirm()
            or self.handle_story_skip()
        )

    def combat_preparation(
        self,
        *,
        balance_hp: bool = False,
        emotion_reduce: bool = False,
        auto: str = "combat_auto",
        fleet_index: int = 1,
    ) -> None:
        logger.info("Combat preparation.")
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        interval_set = False

        if emotion_reduce:
            self.emotion.wait(fleet_index=fleet_index)
        if balance_hp:
            self.hp_balance()

        for _ in self.loop():
            if self._handle_combat_preparation_action(auto=auto, balance_hp=balance_hp):
                continue
            # 提前降低截图间隔。
            if not interval_set and self.is_combat_loading():
                self.device.screenshot_interval_set("combat")
                interval_set = True

            pause = self.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                if emotion_reduce:
                    self.emotion.reduce(fleet_index)
                # 未识别到 is_combat_loading() 时兜底降低截图间隔。
                if not interval_set:
                    self.device.screenshot_interval_set("combat")
                break

    def handle_battle_preparation(self) -> bool:
        return self.appear_then_click(combat_assets.BATTLE_PREPARATION, offset=(20, 20), interval=2)

    def handle_combat_automation_set(self, *, auto: bool) -> bool:
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

    def _emergency_repair_available(self) -> bool:
        if not self.appear(combat_assets.BATTLE_PREPARATION, offset=(20, 20)):
            return False
        if not self.appear(combat_assets.EMERGENCY_REPAIR_AVAILABLE):
            return False

        # 进入战斗准备页或刚维修后，维修图标会短暂保持可用状态，要等舰队战力稳定后再复查。
        self.wait_until_disappear(combat_assets.MAIN_FLEET_POWER_ZERO, offset=(20, 20))
        stable_checker = Button(
            area=combat_assets.MAIN_FLEET_POWER_ZERO.area,
            color=(),
            button=combat_assets.MAIN_FLEET_POWER_ZERO.button,
            name="STABLE_CHECKER",
        )
        self.wait_until_stable(stable_checker)
        return self.appear(combat_assets.EMERGENCY_REPAIR_AVAILABLE)

    def _emergency_repair_hp_valid(self) -> bool:
        if not len(self.hp):
            return False
        if max(self.hp[:3]) <= 0.001 or max(self.hp[3:]) <= 0.001:
            logger.warning(f"Invalid HP to use emergency repair: {self.hp}")
            return False
        return True

    def _emergency_repair_needed(self) -> bool:
        hp = np.array(self.hp)
        hp = hp[hp > 0.001]
        return bool(
            (len(hp) and np.min(hp) < self.config.HpControl_RepairUseSingleThreshold)
            or max(self.hp[:3]) < self.config.HpControl_RepairUseMultiThreshold
            or max(self.hp[3:]) < self.config.HpControl_RepairUseMultiThreshold
        )

    def handle_emergency_repair_use(self) -> bool:
        if not self.config.HpControl_UseEmergencyRepair:
            return False

        if self.appear_then_click(combat_assets.EMERGENCY_REPAIR_CONFIRM, offset=True, interval=3):
            return True
        if not self._emergency_repair_available():
            return False

        logger.info("EMERGENCY_REPAIR_AVAILABLE")
        if not self._emergency_repair_hp_valid() or not self._emergency_repair_needed():
            return False

        logger.info("Use emergency repair")
        self.device.click(combat_assets.EMERGENCY_REPAIR_AVAILABLE)
        self.interval_clear(combat_assets.EMERGENCY_REPAIR_CONFIRM)
        return True

    def _handle_common_combat_popup(self, popup: str) -> bool:
        return (
            self.handle_popup_confirm(popup)
            or self.handle_urgent_commission()
            or self.handle_guild_popup_cancel()
            or self.handle_vote_popup()
            or self.handle_mission_popup_ack()
        )

    def _handle_manual_weapon_release(self, auto: str) -> bool:
        return (
            auto != "combat_auto"
            and self.auto_mode_checked
            and bool(self.is_combat_executing())
            and self.handle_combat_weapon_release()
        )

    def _handle_combat_execute_action(self, auto: str, submarine: str, confirm_timer: Timer) -> bool:
        return (
            (not confirm_timer.reached() and self.handle_combat_automation_confirm())
            or self.handle_story_skip()
            or self.handle_combat_auto(auto)
            or self.handle_combat_manual(auto)
            or self._handle_manual_weapon_release(auto)
            or self.handle_submarine_call(submarine)
            or self._handle_common_combat_popup("COMBAT_EXECUTE")
        )

    def combat_execute(self, *, auto: str = "combat_auto", submarine: str = "do_not_use") -> None:
        """auto 接受 combat_auto、combat_manual、stand_still_in_the_middle、hide_in_bottom_left。

        submarine 接受 do_not_use、hunt_only、every_combat。
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
            if self._handle_combat_execute_action(auto=auto, submarine=submarine, confirm_timer=confirm_timer):
                continue

            if self.handle_battle_status() or self.handle_get_items():
                break

    def handle_battle_status(self) -> bool:
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

    def handle_get_items(self) -> bool:
        for button in _GET_ITEM_CHECKS:
            if self.appear(button, offset=5, interval=self.battle_status_click_interval):
                self.device.click(combat_assets.GET_ITEMS_1)
                self.interval_reset(combat_assets.BATTLE_STATUS_S)
                self.interval_reset(combat_assets.BATTLE_STATUS_A)
                self.interval_reset(combat_assets.BATTLE_STATUS_B)
                return True

        return False

    def handle_exp_info(self) -> bool:
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

    def handle_get_ship(self) -> bool:
        if self.appear_then_click(combat_assets.GET_SHIP, interval=1):
            if self.appear(combat_assets.NEW_SHIP):
                logger.info("Get a new SHIP")
                self.config.GET_SHIP_TRIGGERED = True
            return True

        return False

    def handle_combat_mis_click(self) -> bool:
        if self.appear(MUNITIONS_CHECK, offset=(20, 20), interval=5):
            logger.info(f"{MUNITIONS_CHECK} -> {BACK_ARROW}")
            self.device.click(BACK_ARROW)
            return True
        if self.appear(EXERCISE_CHECK, offset=(20, 20), interval=5):
            logger.info(f"{EXERCISE_CHECK} -> {BACK_ARROW}")
            self.device.click(BACK_ARROW)
            return True

        return False

    def _combat_status_expected_end_reached(self, expected_end: CombatEnd | None) -> bool:
        if expected_end == "in_stage":
            return self.handle_in_stage()
        if expected_end == "with_searching":
            return self.handle_in_map_with_enemy_searching()
        if expected_end == "no_searching":
            return self.handle_in_map_no_enemy_searching()
        if expected_end == "in_ui":
            return self.appear(BACK_ARROW, offset=(30, 30))
        if callable(expected_end):
            return expected_end()
        return False

    def _handle_combat_status_progress(self, *, battle_status: bool, exp_info: bool) -> tuple[bool, bool, bool]:
        if battle_status:
            if self.handle_exp_info():
                return True, battle_status, True
            if not exp_info and self.handle_battle_status():
                return True, True, exp_info
            return False, battle_status, exp_info

        if not exp_info and self.handle_battle_status():
            return True, True, exp_info
        if self.handle_exp_info():
            return True, battle_status, True
        return False, battle_status, exp_info

    def _handle_combat_status_result(self, *, battle_status: bool, exp_info: bool) -> tuple[bool, bool, bool]:
        if not exp_info and self.handle_get_ship():
            return True, battle_status, exp_info
        if self.handle_get_items():
            return True, battle_status, exp_info
        if self.handle_popup_confirm("COMBAT_STATUS"):
            if battle_status and not exp_info:
                logger.info("Locking a new ship")
                self.config.GET_SHIP_TRIGGERED = True
            return True, battle_status, exp_info
        return self._handle_combat_status_progress(battle_status=battle_status, exp_info=exp_info)

    def combat_status(self, expected_end: CombatEnd | None = None) -> None:
        """expected_end 可为 in_stage、with_searching、no_searching、in_ui、回调或 None。"""
        logger.info("Combat status")
        expected_end_name = (
            getattr(expected_end, "__name__", type(expected_end).__name__) if callable(expected_end) else expected_end
        )
        logger.attr("expected_end", expected_end_name)
        self.device.screenshot_interval_set()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        battle_status = False
        exp_info = False  # 规避游戏白屏时结算信息延迟出现。
        for _ in self.loop():
            if self._combat_status_expected_end_reached(expected_end):
                break

            if self.handle_story_skip():
                continue
            handled, battle_status, exp_info = self._handle_combat_status_result(
                battle_status=battle_status, exp_info=exp_info
            )
            if handled:
                continue
            if self._handle_common_combat_popup("COMBAT_STATUS"):
                continue
            if self.handle_auto_search_exit():
                continue
            if self.handle_combat_mis_click():
                continue

            if self.handle_in_stage():
                break
            if expected_end is None and self.handle_in_map_with_enemy_searching():
                break

    def combat(
        self,
        *,
        balance_hp: bool | None = None,
        emotion_reduce: bool | None = None,
        submarine_mode: str | None = None,
        expected_end: CombatEnd | None = None,
        fleet_index: int = 1,
    ) -> None:
        """执行战斗；None 参数回退用户配置，fleet_index 为 1 或 2。

        submarine_mode 接受 do_not_use、hunt_only、every_combat；expected_end 的值域同 combat_status。
        """
        balance_hp = balance_hp if balance_hp is not None else self.config.HpControl_UseHpBalance
        emotion_reduce = emotion_reduce if emotion_reduce is not None else self.emotion.is_calculate
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
