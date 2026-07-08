from module.base.runtime_random import runtime_random
from module.logger import logger
from module.os.map import OSMap


class OpsiDaily(OSMap):
    def os_port_mission(self):
        """
        访问所有港口并完成港口日常任务。
        """
        logger.hr("OS port mission", level=1)
        ports = [0, 7, 5, 2, 6, 1, 4, 3]
        if runtime_random.chance():
            ports.reverse()

        for port_id in ports:
            port = self.name_to_zone(port_id)
            logger.hr(f"OS port daily in {port}", level=2)
            self.globe_goto(port)

            self.run_auto_search()
            self.handle_after_auto_search()

    def os_finish_daily_mission(self, question=True, rescan=None):
        """
        Finish all daily mission in Operation Siren.
        Suggest to run os_port_daily to accept missions first.

        Args:
            question (bool): refer to run_auto_search
            rescan (None, bool): refer to run_auto_search

        Returns:
            int: Number of missions finished
        """
        logger.hr("OS finish daily mission", level=1)
        count = 0
        while True:
            result = self.os_get_next_mission()
            if not result:
                break

            if result != "pinned_at_archive_zone":
                # The name of archive zone is "archive zone", which is not an existing zone.
                # After archive zone, it go back to previous zone automatically.
                self.zone_init()
            if result == "already_at_mission_zone":
                self.globe_goto(self.zone, refresh=True)
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(
                recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine and result != "pinned_at_archive_zone"
            )
            self.run_auto_search(question, rescan)
            self.handle_after_auto_search()
            count += 1
            self.config.check_task_switch()

        return count

    def os_daily(self):
        # os_mission_overview_accept() 已经能处理旧任务，不需要先完成已有任务。

        # 每日清理调适样本。
        if self.config.OpsiDaily_UseTuningSample:
            self.tuning_sample_use()

        while True:
            # If unable to receive more dailies, finish them and try again.
            success = self.os_mission_overview_accept()
            # Re-init zone name
            # MISSION_ENTER appear from the right,
            # need to confirm that the animation has ended,
            # or it will click on MAP_GOTO_GLOBE
            self.zone_init()
            self.os_finish_daily_mission()
            if self.is_in_opsi_explore():
                self.os_port_mission()
                break
            if success:
                break

        self.config.task_delay(server_update=True)
