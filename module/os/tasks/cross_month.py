from datetime import datetime, timedelta

from module.config.utils import get_os_next_reset
from module.exception import ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap

INVALID_OPSI_NEXT_RESET_TEMPLATE = "Invalid OpsiNextReset: {next_reset} < {now}"


class OpsiCrossMonth(OSMap):
    def os_cross_month_end(self):
        self.config.task_delay(target=get_os_next_reset() - timedelta(minutes=10))
        self.config.task_stop()

    def os_cross_month(self):
        """执行大世界跨月清理流程。"""
        next_reset = get_os_next_reset()
        self._validate_opsi_cross_month_start(next_reset)
        self._wait_until_opsi_reset(next_reset)
        self._disable_opsi_cross_month_switches()
        self._clear_opsi_daily_after_reset()
        self._clear_opsi_monthly_items()
        self._run_opsi_meowfficer_farming_after_reset()

    def _validate_opsi_cross_month_start(self, next_reset):
        now = datetime.now()
        logger.attr("OpsiNextReset", next_reset)

        if next_reset < now:
            message = INVALID_OPSI_NEXT_RESET_TEMPLATE.format(next_reset=next_reset, now=now)
            raise ScriptError(message)
        remain = next_reset - now
        if remain > timedelta(days=3):
            logger.error(
                "Too long to next reset, OpSi might reset already. Running OpsiCrossMonth is meaningless, stopped."
            )
            self.os_cross_month_end()
        if remain > timedelta(minutes=10):
            logger.error(
                "Too long to next reset, too far from OpSi reset. Running OpsiCrossMonth is meaningless, stopped."
            )
            self.os_cross_month_end()

    def _wait_until_opsi_reset(self, next_reset):
        logger.hr("Wait until OpSi reset", level=1)
        logger.warning("ALAS is now waiting for next OpSi reset, please DO NOT touch the game during wait")
        while True:
            logger.info(f"Wait until {next_reset}")
            now = datetime.now()
            remain = (next_reset - now).total_seconds()
            if remain <= 0:
                break
            self.device.sleep(min(remain, 60))

        logger.hr("OpSi reset", level=3)

    def _disable_opsi_cross_month_switches(self):
        def false_func(*_args, **_kwargs):
            return False

        self.is_in_opsi_explore = false_func
        self.config.task_switched = false_func

    def _clear_opsi_daily_after_reset(self):
        logger.hr("OpSi clear daily", level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiFleet_Fleet=self.config.cross_get("OpsiDaily.OpsiFleet.Fleet"),
            OpsiFleet_Submarine=False,
        )
        count = 0
        empty_trial = 0
        while True:
            # 如果不能继续领取每日任务，先完成已有任务后再重试。
            success = self.os_mission_overview_accept()
            # MISSION_ENTER 从右侧出现，要等待动画结束再初始化海域名。
            self.zone_init()
            if empty_trial >= 5:
                logger.warning("No Opsi dailies found within 5 min, stop waiting")
                break
            count += self.os_finish_daily_mission()
            if not count:
                logger.warning(
                    "Did not receive any OpSi dailies, probably game dailies are not refreshed, wait 1 minute"
                )
                empty_trial += 1
                self.device.sleep(60)
                continue
            if success:
                break

    def _clear_opsi_monthly_items(self):
        logger.hr("OS clear abyssal", level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
            OpsiGeneral_UseLogger=True,
            OpsiObscure_ForceRun=True,
            OpsiFleet_Fleet=self.config.cross_get("OpsiObscure.OpsiFleet.Fleet"),
            OpsiFleet_Submarine=False,
            OpsiFleetFilter_Filter=self.config.cross_get("OpsiAbyssal.OpsiFleetFilter.Filter"),
            OpsiAbyssal_ForceRun=True,
        )
        self._clear_opsi_abyssal_items()

        logger.hr("OS clear obscure", level=1)
        self._clear_opsi_obscure_items()

    def _clear_opsi_abyssal_items(self):
        while self.storage_get_next_item("ABYSSAL", use_logger=True):
            self.zone_init()
            result = self.run_abyssal()
            if not result:
                self.map_exit()
            self.fleet_repair(revert=False)

    def _clear_opsi_obscure_items(self):
        while self.storage_get_next_item("OBSCURE", use_logger=True):
            self.zone_init()
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(recon_scan=True, submarine_call=False)
            self.run_auto_search(rescan="current")
            self.map_exit()
            self.handle_after_auto_search()

    def _run_opsi_meowfficer_farming_after_reset(self):
        logger.hr("OS meowfficer farming, hazard_level=3", level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiGeneral_BuyActionPointLimit=0,
            HOMO_EDGE_DETECT=True,
            STORY_OPTION=-2,
            OpsiFleet_Fleet=self.config.cross_get("OpsiMeowfficerFarming.OpsiFleet.Fleet"),
            OpsiFleet_Submarine=False,
            OpsiMeowfficerFarming_ActionPointPreserve=0,
            OpsiMeowfficerFarming_HazardLevel=3,
            OpsiMeowfficerFarming_TargetZone=0,
        )
        while True:
            zones = (
                self.zone_select(hazard_level=3)
                .delete(SelectedGrids([self.zone]))
                .delete(SelectedGrids(self.zones.select(is_port=True)))
                .sort_by_clock_degree(center=(1252, 1012), start=self.zone.location)
            )
            logger.hr(f"OS meowfficer farming, zone_id={zones[0].zone_id}", level=1)
            self.globe_goto(zones[0])
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(recon_scan=False, submarine_call=False)
            self.run_auto_search()
            self.handle_after_auto_search()
