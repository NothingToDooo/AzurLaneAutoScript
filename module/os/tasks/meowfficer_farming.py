from module.config.utils import get_os_reset_remain
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap

WRONG_ZONE_INPUT_MESSAGE = "wrong input, task stopped"


class OpsiMeowfficerFarming(OSMap):
    def os_meowfficer_farming(self):
        """执行大世界猫窝刷图。"""
        logger.hr(f"OS meowfficer farming, hazard_level={self.config.OpsiMeowfficerFarming_HazardLevel}", level=1)
        preserve = self._prepare_meowfficer_farming()
        self._delay_if_opsi_explore_running()

        ap_checked = False
        while True:
            self._apply_meowfficer_action_point_preserve(preserve)
            if not ap_checked:
                self._check_meowfficer_action_points()
                ap_checked = True

            zone, refresh = self._next_meowfficer_farming_zone()
            self._run_meowfficer_farming_zone(zone, refresh=refresh)

    def _prepare_meowfficer_farming(self):
        if self.is_cl1_enabled and self.config.OpsiMeowfficerFarming_ActionPointPreserve < 1000:
            logger.info("With CL1 leveling enabled, set action point preserve to 1000")
            self.config.OpsiMeowfficerFarming_ActionPointPreserve = 1000
        preserve = min(self.get_action_point_limit(), self.config.OpsiMeowfficerFarming_ActionPointPreserve, 2000)
        if preserve == 0:
            self.config.override(OpsiFleet_Submarine=False)
        if self.is_cl1_enabled:
            self._prepare_cl1_meowfficer_farming()
        return preserve

    def _prepare_cl1_meowfficer_farming(self) -> None:
        # 没有这些配置时，CL1 练级收益为 0。
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiGeneral_AkashiShopFilter="ActionPoint",
            OpsiFleet_Submarine=False,
        )
        cd = self.nearest_task_cooling_down
        logger.attr("Task cooling down", cd)
        # 每月最后一天 OpsiObscure 和 OpsiAbyssal 调度很密，避免排到它们后面。
        remain = get_os_reset_remain()
        if cd is not None and remain > 0:
            logger.info("Having task cooling down, delay OpsiMeowfficerFarming after it")
            self.config.task_delay(target=cd.next_run)
            self.config.task_stop()

    def _delay_if_opsi_explore_running(self) -> None:
        if self.is_in_opsi_explore():
            logger.warning(f"OpsiExplore is still running, cannot do {self.config.task.command}")
            self.config.task_delay(server_update=True)
            self.config.task_stop()

    def _apply_meowfficer_action_point_preserve(self, preserve) -> None:
        self.config.OS_ACTION_POINT_PRESERVE = preserve
        if self._should_ignore_action_point_for_ash():
            logger.info("Ash beacon not fully collected, ignore action point limit temporarily")
            self.config.OS_ACTION_POINT_PRESERVE = 0
        logger.attr("OS_ACTION_POINT_PRESERVE", self.config.OS_ACTION_POINT_PRESERVE)

    def _should_ignore_action_point_for_ash(self):
        return (
            self.config.is_task_enabled("OpsiAshBeacon")
            and not self._ash_fully_collected
            and self.config.OpsiAshBeacon_EnsureFullyCollected
        )

    def _check_meowfficer_action_points(self) -> None:
        # 先检查行动力，避免今天用掉明天每日任务需要保留的 AP。
        keep_current_ap = True
        check_rest_ap = True
        if self.is_cl1_enabled and self.get_yellow_coins() >= self.config.OS_CL1_YELLOW_COINS_PRESERVE:
            check_rest_ap = False
        if not self.is_cl1_enabled and self.config.OpsiGeneral_BuyActionPointLimit > 0:
            keep_current_ap = False
        self.action_point_set(cost=0, keep_current_ap=keep_current_ap, check_rest_ap=check_rest_ap)

    def _next_meowfficer_farming_zone(self):
        if self.config.OpsiMeowfficerFarming_TargetZone != 0:
            return self._configured_meowfficer_farming_zone(), True

        # (1252, 1012) 是 os_globe_map.png 中 134 中心海域的坐标。
        zones = (
            self.zone_select(hazard_level=self.config.OpsiMeowfficerFarming_HazardLevel)
            .delete(SelectedGrids([self.zone]))
            .delete(SelectedGrids(self.zones.select(is_port=True)))
            .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)
        )
        return zones[0], False

    def _configured_meowfficer_farming_zone(self):
        try:
            return self.name_to_zone(self.config.OpsiMeowfficerFarming_TargetZone)
        except ScriptError as e:
            logger.warning(f"wrong zone_id input:{self.config.OpsiMeowfficerFarming_TargetZone}")
            raise RequestHumanTakeover(WRONG_ZONE_INPUT_MESSAGE) from e

    def _run_meowfficer_farming_zone(self, zone, *, refresh) -> None:
        logger.hr(f"OS meowfficer farming, zone_id={zone.zone_id}", level=1)
        if refresh:
            self.globe_goto(zone, refresh=True)
        else:
            self.globe_goto(zone)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)
        self.run_auto_search()
        self.handle_after_auto_search()
        self.config.check_task_switch()
