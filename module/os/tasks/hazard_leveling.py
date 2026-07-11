from module.logger import logger
from module.os.map import OSMap


class OpsiHazard1Leveling(OSMap):
    def os_hazard1_leveling(self):
        logger.hr("OS hazard 1 leveling", level=1)
        # 未启用这些配置时，CL1 没有收益。
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiGeneral_AkashiShopFilter="ActionPoint",
        )
        if not self.config.is_task_enabled("OpsiMeowfficerFarming"):
            self.config.cross_set(keys="OpsiMeowfficerFarming.Scheduler.Enable", value=True)
        while True:
            # 侵蚀 1 刷图最多保留 200 行动力。
            self.config.OS_ACTION_POINT_PRESERVE = 200
            if (
                self.config.is_task_enabled("OpsiAshBeacon")
                and not self._ash_fully_collected
                and self.config.OpsiAshBeacon_EnsureFullyCollected
            ):
                logger.info("Ash beacon not fully collected, ignore action point limit temporarily")
                self.config.OS_ACTION_POINT_PRESERVE = 0
            logger.attr("OS_ACTION_POINT_PRESERVE", self.config.OS_ACTION_POINT_PRESERVE)

            if self.get_yellow_coins() < self.config.OS_CL1_YELLOW_COINS_PRESERVE:
                logger.info(f"Reach the limit of yellow coins, preserve={self.config.OS_CL1_YELLOW_COINS_PRESERVE}")
                with self.config.multi_set():
                    self.config.task_delay(server_update=True)
                    if not self.is_in_opsi_explore():
                        self.config.task_call("OpsiMeowfficerFarming")
                self.config.task_stop()

            self.get_current_zone()

            # CL1 启动行动力固定为 70；此时石油用于 CL1，而非猫窝刷图。
            keep_current_ap = True
            if self.config.OpsiGeneral_BuyActionPointLimit > 0:
                keep_current_ap = False
            self.action_point_set(cost=70, keep_current_ap=keep_current_ap, check_rest_ap=True)
            if self._action_point_total >= 3000:
                with self.config.multi_set():
                    self.config.task_delay(server_update=True)
                    if not self.is_in_opsi_explore():
                        self.config.task_call("OpsiMeowfficerFarming")
                self.config.task_stop()

            zone = self.config.OpsiHazard1Leveling_TargetZone if self.config.OpsiHazard1Leveling_TargetZone != 0 else 22
            logger.hr(f"OS hazard 1 leveling, zone_id={zone}", level=1)
            if self.zone.zone_id != zone or not self.is_zone_name_hidden:
                self.globe_goto(self.name_to_zone(zone), types="SAFE", refresh=True)
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.run_strategic_search()

            self.handle_after_auto_search()
            self.config.check_task_switch()
