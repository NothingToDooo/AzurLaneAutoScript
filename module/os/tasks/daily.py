from typing import TYPE_CHECKING

from module.base.runtime_random import runtime_random
from module.logger import logger
from module.os.map import OSMap

if TYPE_CHECKING:
    from module.os.map import RescanMode


class OpsiDaily(OSMap):
    def os_port_mission(self) -> None:
        """访问所有港口并完成港口日常任务。"""
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

    def os_finish_daily_mission(
        self,
        *,
        question: bool = True,
        rescan: RescanMode | bool | None = None,
    ) -> int:
        """完成全部大世界日常任务并返回数量；应先运行港口日常以领取任务。

        question 和 rescan 直接传给 run_auto_search。
        """
        logger.hr("OS finish daily mission", level=1)
        count = 0
        while True:
            result = self.os_get_next_mission()
            if not result:
                break

            if result != "pinned_at_archive_zone":
                # 档案海域名称不是可解析的普通海域；结算后会自动返回原海域。
                self.zone_init()
            if result == "already_at_mission_zone":
                self.globe_goto(self.zone, refresh=True)
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(
                recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine and result != "pinned_at_archive_zone"
            )
            self.run_auto_search(question=question, rescan=rescan)
            self.handle_after_auto_search()
            count += 1
            self.config.check_task_switch()

        return count

    def os_daily(self) -> None:
        # os_mission_overview_accept() 已经能处理旧任务，不需要先完成已有任务。

        # 每日清理调适样本。
        if self.config.OpsiDaily_UseTuningSample:
            self.tuning_sample_use()

        while True:
            # 无法继续领取时先完成已有日常，再重新尝试。
            success = self.os_mission_overview_accept()
            # MISSION_ENTER 从右侧滑入，必须等动画结束后再初始化海域名，避免误点 MAP_GOTO_GLOBE。
            self.zone_init()
            self.os_finish_daily_mission()
            if self.is_in_opsi_explore():
                self.os_port_mission()
                break
            if success:
                break

        self.config.task_delay(server_update=True)
