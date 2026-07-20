from collections.abc import Callable
from typing import Literal

from module.combat import assets as combat_assets
from module.combat.combat import Combat as Combat_
from module.logger import logger
from module.os_combat import assets as os_combat_assets
from module.os_handler import assets as os_assets
from module.os_handler.map_event import MapEventHandler

type CombatEnd = Literal["in_stage", "with_searching", "no_searching", "in_ui"] | Callable[[], bool]

_OS_EXP_INFO_BUTTONS = (
    combat_assets.EXP_INFO_S,
    combat_assets.EXP_INFO_A,
    combat_assets.EXP_INFO_B,
    combat_assets.EXP_INFO_C,
    combat_assets.EXP_INFO_D,
)
_OS_AUTO_SEARCH_EXP_INFO_BUTTONS = (
    combat_assets.EXP_INFO_C,
    combat_assets.EXP_INFO_D,
)
_OS_AUTO_SEARCH_BATTLE_STATUS_BUTTONS = (
    (combat_assets.BATTLE_STATUS_C, "Battle Status C"),
    (combat_assets.BATTLE_STATUS_D, "Battle Status D"),
)


class ContinuousCombat(Exception):  # ruff:ignore[error-suffix-on-exception-name] - 表示连续战斗需要进入下一轮。
    pass


class Combat(Combat_, MapEventHandler):
    def combat_appear(self) -> bool:
        if self.is_in_map():
            return False

        if self.is_combat_loading():
            return True

        if self.appear(os_combat_assets.BATTLE_PREPARATION):
            return True
        if self.appear(os_combat_assets.SIREN_PREPARATION, offset=(20, 20)):
            return True
        return self.appear(combat_assets.BATTLE_PREPARATION_WITH_OVERLAY) and self.handle_combat_automation_confirm()

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
        # OS 战斗保留基类调用签名，但不执行普通战斗的心情等待和血量平衡。
        del balance_hp, emotion_reduce, fleet_index

        for _ in self.loop():
            if self.appear(os_combat_assets.BATTLE_PREPARATION) and self.handle_combat_automation_set(
                auto=auto == "combat_auto"
            ):
                continue
            if self.handle_retirement():
                continue
            # OS 战斗不处理低心情和紧急维修弹窗。
            if self.appear_then_click(os_combat_assets.BATTLE_PREPARATION, interval=2):
                continue
            if self.appear_then_click(os_combat_assets.SIREN_PREPARATION, offset=(20, 20), interval=2):
                continue
            if self.handle_popup_confirm("ENHANCED_ENEMY"):
                continue
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue

            pause = self.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                break

    def handle_exp_info(self) -> bool:
        if self.is_combat_executing():
            return False
        for button in _OS_EXP_INFO_BUTTONS:
            if self.appear_then_click(button):
                self.device.sleep((0.25, 0.5))
                return True

        return False

    def handle_get_items(self) -> bool:
        """识别掉落后点击安全区域，避免直接点击掉落按钮。"""
        if getattr(self, "_disable_handle_get_items", False):
            return False
        if self.appear(combat_assets.GET_ITEMS_1, offset=5, interval=self.battle_status_click_interval):
            self.device.click(os_assets.CLICK_SAFE_AREA)
            self.interval_reset(combat_assets.BATTLE_STATUS_S)
            self.interval_reset(combat_assets.BATTLE_STATUS_A)
            self.interval_reset(combat_assets.BATTLE_STATUS_B)
            return True
        if self.appear(combat_assets.GET_ITEMS_2, offset=5, interval=self.battle_status_click_interval):
            self.device.click(os_assets.CLICK_SAFE_AREA)
            self.interval_reset(combat_assets.BATTLE_STATUS_S)
            self.interval_reset(combat_assets.BATTLE_STATUS_A)
            self.interval_reset(combat_assets.BATTLE_STATUS_B)
            return True
        if self.appear(os_assets.GET_ADAPTABILITY, offset=5, interval=self.battle_status_click_interval):
            self.device.click(os_assets.CLICK_SAFE_AREA)
            self.interval_reset(combat_assets.BATTLE_STATUS_S)
            self.interval_reset(combat_assets.BATTLE_STATUS_A)
            self.interval_reset(combat_assets.BATTLE_STATUS_B)
            return True

        return False

    def _os_combat_expected_end(self) -> bool:
        if self.handle_map_event():
            return False
        if self.combat_appear():
            raise ContinuousCombat

        return self.handle_os_in_map()

    def combat_status(self, expected_end: CombatEnd | None = None) -> None:
        if expected_end is None:
            expected_end = self._os_combat_expected_end
        # 禁用普通掉落处理，只使用地图掉落处理。
        self._disable_handle_get_items = True
        try:
            super().combat_status(expected_end=expected_end)
        finally:
            self._disable_handle_get_items = False

    def combat(
        self,
        *,
        balance_hp: bool | None = None,
        emotion_reduce: bool | None = None,
        submarine_mode: str | None = None,
        expected_end: CombatEnd | None = None,
        fleet_index: int = 1,
    ) -> None:
        """塞壬扫描装置可能无间隔触发两场伏击，因此额外识别连续战斗。"""
        for count in range(3):
            if count >= 2:
                logger.warning("Too many continuous combat")

            try:
                super().combat(
                    balance_hp=balance_hp,
                    emotion_reduce=emotion_reduce,
                    submarine_mode=submarine_mode,
                    expected_end=expected_end,
                    fleet_index=fleet_index,
                )
                break
            except ContinuousCombat:
                logger.info("Continuous combat detected")
                continue

    def handle_auto_search_battle_status(self) -> bool:
        for button, warning in _OS_AUTO_SEARCH_BATTLE_STATUS_BUTTONS:
            if self.appear(button, interval=self.battle_status_click_interval):
                logger.warning(warning)
                self.device.sleep((0.25, 0.5))
                self.device.click(button)
                return True

        return False

    def handle_auto_search_exp_info(self) -> bool:
        for button in _OS_AUTO_SEARCH_EXP_INFO_BUTTONS:
            if self.appear_then_click(button):
                self.device.sleep((0.25, 0.5))
                return True

        return False

    def _auto_search_combat_wait_execute(self) -> None:
        while 1:
            self.device.screenshot()

            if self.handle_combat_automation_confirm():
                continue

            if self.handle_os_auto_search_map_option():
                break
            pause = self.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                break
            if self.is_in_map():
                break

    def _auto_search_combat_execute(self, submarine_mode: str) -> bool | None:
        success = True
        while 1:
            self.device.screenshot()

            if self.handle_submarine_call(submarine_mode):
                continue
            # 失败时不要改变自动搜索选项。
            enable = success if success is not None else None
            if self.handle_os_auto_search_map_option(enable=enable):
                continue

            if self.is_in_map():
                self.device.screenshot_interval_set()
                break
            if self.is_combat_executing():
                continue
            if self.handle_auto_search_battle_status():
                success = None
                continue
            if self.handle_auto_search_exp_info():
                success = None
                continue
            if self.handle_map_event():
                continue

        return success

    def auto_search_combat(self) -> bool | None:
        """从战斗加载推进到结算；返回 True，无法确认结果时返回 None。"""
        logger.info("Auto search combat loading")
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        self.device.screenshot_interval_set("combat")
        self._auto_search_combat_wait_execute()

        logger.info("Auto Search combat execute")
        self.submarine_call_reset()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        submarine_mode = "do_not_use"
        if self.config.Submarine_Fleet:
            submarine_mode = self.config.Submarine_Mode

        success = self._auto_search_combat_execute(submarine_mode=submarine_mode)
        logger.info("Combat end.")
        return success
