from module.combat import assets as combat_assets
from module.combat.combat import Combat as Combat_
from module.logger import logger
from module.os_combat import assets as os_combat_assets
from module.os_handler import assets as os_assets
from module.os_handler.map_event import MapEventHandler


class ContinuousCombat(Exception):
    pass


class Combat(Combat_, MapEventHandler):
    def combat_appear(self):
        """
        Returns:
            bool: If enter combat.
        """
        if self.is_in_map():
            return False

        if self.is_combat_loading():
            return True

        if self.appear(os_combat_assets.BATTLE_PREPARATION):
            return True
        if self.appear(os_combat_assets.SIREN_PREPARATION, offset=(20, 20)):
            return True
        return self.appear(combat_assets.BATTLE_PREPARATION_WITH_OVERLAY) and self.handle_combat_automation_confirm()

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

            # 结束。
            pause = self.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                break

    def handle_exp_info(self):
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
        if self.appear_then_click(combat_assets.EXP_INFO_C):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(combat_assets.EXP_INFO_D):
            self.device.sleep((0.25, 0.5))
            return True

        return False

    def handle_get_items(self):
        """
        Click CLICK_SAFE_AREA instead of button itself.

        Returns:
            bool:
        """
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

    def _os_combat_expected_end(self):
        if self.handle_map_event():
            return False
        if self.combat_appear():
            raise ContinuousCombat

        return self.handle_os_in_map()

    def combat_status(self, expected_end=None):
        if expected_end is None:
            expected_end = self._os_combat_expected_end
        # 禁用普通掉落处理，只使用地图掉落处理。
        self._disable_handle_get_items = True
        try:
            super().combat_status(expected_end=expected_end)
        finally:
            self._disable_handle_get_items = False

    def combat(self, *args, save_get_items=False, **kwargs):
        """
        处理大世界中的连续战斗。

        塞壬扫描装置可能连续触发两场伏击，中间没有间隔。这里在继承普通 combat
        流程的基础上额外识别第二场战斗，避免停在战斗确认阶段。
        """
        for count in range(3):
            if count >= 2:
                logger.warning("Too many continuous combat")

            try:
                super().combat(*args, save_get_items=save_get_items, **kwargs)
                break
            except ContinuousCombat:
                logger.info("Continuous combat detected")
                continue

    def handle_auto_search_battle_status(self):
        if self.appear(combat_assets.BATTLE_STATUS_C, interval=self.battle_status_click_interval):
            logger.warning("Battle Status C")
            # raise GameStuckError("Battle status C")
            self.device.sleep((0.25, 0.5))
            self.device.click(combat_assets.BATTLE_STATUS_C)
            return True
        if self.appear(combat_assets.BATTLE_STATUS_D, interval=self.battle_status_click_interval):
            logger.warning("Battle Status D")
            # raise GameStuckError("Battle Status D")
            self.device.sleep((0.25, 0.5))
            self.device.click(combat_assets.BATTLE_STATUS_D)
            return True

        return False

    def handle_auto_search_exp_info(self):
        if self.appear_then_click(combat_assets.EXP_INFO_C):
            self.device.sleep((0.25, 0.5))
            return True
        if self.appear_then_click(combat_assets.EXP_INFO_D):
            self.device.sleep((0.25, 0.5))
            return True

        return False

    def auto_search_combat(self):
        """
        Returns:
            bool: True if enemy cleared, False if fleet died.

        Pages:
            in: is_combat_loading()
            out: combat status
        """
        logger.info("Auto search combat loading")
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        self.device.screenshot_interval_set("combat")
        while 1:
            self.device.screenshot()

            if self.handle_combat_automation_confirm():
                continue

            # 结束。
            if self.handle_os_auto_search_map_option():
                break
            pause = self.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                break
            if self.is_in_map():
                break

        logger.info("Auto Search combat execute")
        self.submarine_call_reset()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        submarine_mode = "do_not_use"
        if self.config.Submarine_Fleet:
            submarine_mode = self.config.Submarine_Mode

        success = True
        while 1:
            self.device.screenshot()

            if self.handle_submarine_call(submarine_mode):
                continue
            # 失败时不要改变自动搜索选项。
            enable = success if success is not None else None
            if self.handle_os_auto_search_map_option(enable=enable):
                continue

            # 结束。
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

        logger.info("Combat end.")
        return success
