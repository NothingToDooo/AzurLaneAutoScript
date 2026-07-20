from module.base.timer import Timer
from module.campaign.campaign_status import CampaignStatus
from module.combat.assets import (
    BATTLE_STATUS_A,
    BATTLE_STATUS_B,
    BATTLE_STATUS_S,
    EXP_INFO_A,
    EXP_INFO_B,
    EXP_INFO_S,
)
from module.combat.combat import Combat
from module.exception import CampaignEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_ON
from module.logger import logger
from module.map.map_operation import MapOperation

AUTO_SEARCH_COMBAT_END_CHECKS = (
    BATTLE_STATUS_S,
    BATTLE_STATUS_A,
    BATTLE_STATUS_B,
    EXP_INFO_S,
    EXP_INFO_A,
    EXP_INFO_B,
)


class AutoSearchCombat(MapOperation, Combat, CampaignStatus):
    _auto_search_in_stage_timer = Timer(3, count=6)
    _auto_search_status_confirm = False
    AUTO_SEARCH_COMBAT_END_DEFAULT = False
    auto_search_oil_limit_triggered = False
    auto_search_coin_limit_triggered = False

    def _handle_auto_search_menu_missing(self) -> bool:
        """处理 Boss 战后不显示自律寻敌菜单的游戏 bug；关卡页停留超时即视为寻敌结束。"""
        if self.is_in_stage():
            if self._auto_search_in_stage_timer.reached():
                logger.info("Catch auto search menu missing")
                return True
        else:
            self._auto_search_in_stage_timer.reset()

        return False

    def map_offensive_auto_search(self) -> None:
        """页面状态：in_map/MAP_OFFENSIVE → is_combat_loading。"""
        self.interval_reset(AUTO_SEARCH_MAP_OPTION_ON)
        for _ in self.loop():
            if self.handle_auto_search_map_option():
                self.interval_reset(AUTO_SEARCH_MAP_OPTION_ON)
                continue
            # 退出退役后立即开启寻敌时，图标可能显示运行但实际卡住；从第 3 秒起每 3 秒关闭一次。
            if self.appear(
                AUTO_SEARCH_MAP_OPTION_ON, offset=self._auto_search_offset, interval=3
            ) and self.appear_then_click(AUTO_SEARCH_MAP_OPTION_ON):
                continue
            if self.handle_combat_low_emotion():
                continue
            if self.handle_retirement():
                continue

            if self.is_combat_loading():
                break

    def auto_search_watch_fleet(self, *, checked: bool = False) -> bool:
        """监控舰队索引和等级；checked 为 True 时跳过本轮重复记录。"""
        prev = self.fleet_current_index
        self.get_fleet_show_index()
        self.get_fleet_current_index()
        if self.fleet_current_index == prev:
            if not checked:
                logger.info(f"Fleet: {self.fleet_show_index}, fleet_current_index: {self.fleet_current_index}")
                checked = True
                self.lv_get(after_battle=True)
        else:
            logger.info(f"Fleet: {self.fleet_show_index}, fleet_current_index: {self.fleet_current_index}")
            checked = True
            self.lv_get(after_battle=False)

        return checked

    def auto_search_watch_oil(self, *, checked: bool = False) -> bool:
        """监控油量并更新 auto_search_oil_limit_triggered。"""
        if not checked:
            oil = self._get_oil()
            if oil == 0:
                logger.warning("Oil not found")
            else:
                if oil < max(500, self.config.StopCondition_OilLimit):
                    logger.info("Reach oil limit")
                    self.auto_search_oil_limit_triggered = True
                else:
                    if self.auto_search_oil_limit_triggered:
                        logger.warning(
                            "auto_search_oil_limit_triggered but oil recovered, "
                            "probably because of wrong OCR result before"
                        )
                    self.auto_search_oil_limit_triggered = False
                checked = True

        return checked

    def auto_search_watch_coin(self, *, checked: bool = False) -> bool:
        """监控物资并更新 auto_search_coin_limit_triggered。"""
        if not checked:
            limit = self.config.TaskBalancer_CoinLimit
            coin = self.get_coin()
            if coin == 0:
                logger.warning("Coin not found")
            else:
                if self.is_balancer_task():
                    if coin < limit:
                        logger.info("Reach coin limit")
                        self.auto_search_coin_limit_triggered = True
                    else:
                        self.auto_search_coin_limit_triggered = False
                else:
                    if self.auto_search_coin_limit_triggered:
                        logger.warning(
                            "auto_search_coin_limit_triggered but coin recovered, "
                            "probably because of wrong OCR result before"
                        )
                    self.auto_search_coin_limit_triggered = False
                checked = True

        return checked

    def _wait_until_in_map(self) -> None:
        """规避退出退役或强化后寻敌假运行的游戏 bug；页面退出为 in_map()。"""
        timeout = Timer(3, count=6).start()
        for _ in self.loop():
            if self.is_in_map():
                break
            if timeout.reached():
                logger.warning("Wait in_map after retirement timeout, assume it is in_map")
                break

    def _watch_auto_search_resources(
        self,
        *,
        checked_fleet: bool,
        checked_oil: bool,
        checked_coin: bool,
    ) -> tuple[bool, bool, bool]:
        if not self.is_auto_search_running():
            return checked_fleet, checked_oil, checked_coin

        checked_fleet = self.auto_search_watch_fleet(checked=checked_fleet)
        if not checked_oil or not checked_coin:
            checked_oil = self.auto_search_watch_oil(checked=checked_oil)
            checked_coin = self.auto_search_watch_coin(checked=checked_coin)
        return checked_fleet, checked_oil, checked_coin

    def _handle_auto_search_moving_event(self) -> tuple[bool, bool]:
        if self.handle_retirement():
            self.map_offensive_auto_search()
            return True, True
        if self.handle_auto_search_map_option():
            return True, False
        if self.handle_combat_low_emotion():
            self._auto_search_status_confirm = True
            return True, False
        for handler in (self.handle_story_skip, self.handle_map_cat_attack, self.handle_vote_popup):
            if handler():
                return True, False
        return False, False

    def _is_auto_search_moving_finished(self) -> bool:
        if self.is_combat_loading():
            return True
        if self.is_combat_executing():
            logger.info("is_combat_executing")
            return True
        if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
            raise CampaignEnd
        return False

    def auto_search_moving(self) -> None:
        """页面状态：map → is_combat_loading()。"""
        logger.info("Auto search moving")
        self.device.stuck_record_clear()
        checked_fleet = False
        checked_oil = False
        checked_coin = False
        for _ in self.loop():
            checked_fleet, checked_oil, checked_coin = self._watch_auto_search_resources(
                checked_fleet=checked_fleet,
                checked_oil=checked_oil,
                checked_coin=checked_coin,
            )
            handled, should_break = self._handle_auto_search_moving_event()
            if should_break:
                break
            if handled:
                continue

            if self._is_auto_search_moving_finished():
                break

    def _wait_auto_search_combat_execute(self) -> None:
        logger.info("Auto search combat loading")
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        self.device.screenshot_interval_set("combat")
        for _ in self.loop():
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_story_skip():
                continue
            if self.handle_vote_popup():
                continue

            if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
                raise CampaignEnd
            pause = self.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                break

    def _get_submarine_mode(self) -> str:
        if self.config.Submarine_Fleet:
            return self.config.Submarine_Mode
        return "do_not_use"

    def _prepare_auto_search_combat_execute(
        self,
        *,
        emotion_reduce: bool,
        fleet_index: int,
    ) -> tuple[str, str]:
        logger.info("Auto Search combat execute")
        self.submarine_call_reset()
        submarine_mode = self._get_submarine_mode()
        self.combat_auto_reset()
        self.combat_manual_reset()
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        if emotion_reduce:
            self.emotion.reduce(fleet_index)
        auto = self.config.Fleet_Fleet1Mode if fleet_index == 1 else self.config.Fleet_Fleet2Mode
        return submarine_mode, auto

    def _handle_auto_search_combat_controls(self, *, submarine_mode: str, auto: str) -> bool:
        if self.handle_submarine_call(submarine_mode):
            return True
        if self.handle_combat_auto(auto):
            return True
        if self.handle_combat_manual(auto):
            return True
        return bool(
            auto != "combat_auto"
            and self.auto_mode_checked
            and self.is_combat_executing()
            and self.handle_combat_weapon_release()
        )

    def _handle_auto_search_combat_execute_popups(self) -> bool:
        if self.handle_popup_confirm("AUTO_SEARCH_COMBAT_EXECUTE"):
            return True
        if self.handle_urgent_commission():
            return True
        if self.handle_story_skip():
            return True
        if self.handle_guild_popup_cancel():
            return True
        if self.handle_vote_popup():
            return True
        return self.handle_mission_popup_ack()

    def auto_search_combat_end(self) -> bool:
        return self.AUTO_SEARCH_COMBAT_END_DEFAULT

    def _handle_auto_search_combat_execute_end(self) -> tuple[bool, bool]:
        if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
            self.device.screenshot_interval_set()
            raise CampaignEnd
        if self.is_combat_executing():
            return True, False
        if self.handle_get_ship():
            return True, False
        if any(self.appear(button) for button in AUTO_SEARCH_COMBAT_END_CHECKS) or self.is_auto_search_running():
            self.device.screenshot_interval_set()
            return True, True
        if self.auto_search_combat_end():
            return True, True
        return False, False

    def auto_search_combat_execute(self, *, emotion_reduce: bool, fleet_index: int) -> None:
        """页面状态：is_combat_loading() → combat status。"""
        self._wait_auto_search_combat_execute()
        submarine_mode, auto = self._prepare_auto_search_combat_execute(
            emotion_reduce=emotion_reduce,
            fleet_index=fleet_index,
        )

        for _ in self.loop():
            if self._handle_auto_search_combat_controls(submarine_mode=submarine_mode, auto=auto):
                continue
            if self._handle_auto_search_combat_execute_popups():
                continue

            handled, should_break = self._handle_auto_search_combat_execute_end()
            if should_break:
                break
            if handled:
                continue

    def _is_auto_search_combat_status_finished(self) -> bool:
        if self.is_auto_search_running():
            self._auto_search_status_confirm = False
            return True
        if self.is_in_auto_search_menu() or self._handle_auto_search_menu_missing():
            raise CampaignEnd
        return False

    def _handle_auto_search_combat_status_popups(self) -> bool:
        if self.handle_get_ship():
            return True
        if self.handle_auto_search_map_option():
            self._auto_search_status_confirm = False
            return True
        handlers = (
            lambda: self.handle_popup_confirm("AUTO_SEARCH_COMBAT_STATUS"),
            self.handle_urgent_commission,
            self.handle_story_skip,
            self.handle_guild_popup_cancel,
            self.handle_vote_popup,
            self.handle_mission_popup_ack,
        )
        return any(handler() for handler in handlers)

    def _handle_auto_search_status_confirm(self, *, exp_info: bool) -> tuple[bool, bool]:
        if not self._auto_search_status_confirm:
            return False, exp_info
        if not exp_info and self.handle_get_ship():
            return True, exp_info
        for handler in (
            self.handle_get_items,
            self.handle_battle_status,
            lambda: self.handle_popup_confirm("combat_status"),
        ):
            if handler():
                return True, exp_info
        if self._combat_result_ui.handle_experience_result(self):
            return True, True
        return False, exp_info

    def auto_search_combat_status(self) -> None:
        """页面状态：任意页面 → is_auto_search_running()。"""
        logger.info("Auto Search combat status")
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        exp_info = False  # 处理游戏白屏问题。

        for _ in self.loop():
            if self._is_auto_search_combat_status_finished():
                break

            if self._handle_auto_search_combat_status_popups():
                continue

            handled, exp_info = self._handle_auto_search_status_confirm(exp_info=exp_info)
            if handled:
                continue

    def auto_search_combat(self, *, emotion_reduce: bool | None = None, fleet_index: int = 1) -> None:
        """执行战斗；fleet_index 的 1/2 表示道中/Boss 队，不是编队或寻敌设置中的舰队编号。"""
        emotion_reduce = emotion_reduce if emotion_reduce is not None else self.emotion.is_calculate

        self.auto_search_combat_execute(emotion_reduce=emotion_reduce, fleet_index=fleet_index)
        self.auto_search_combat_status()

        logger.info("Combat end.")
