from datetime import datetime
from typing import TYPE_CHECKING

from module.config.utils import DEFAULT_TIME, get_os_next_reset
from module.exception import GameStuckError, ScriptError
from module.logger import logger
from module.os.globe_operation import OSExploreError
from module.os.map import OSMap

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.device.device import Device

INVALID_LAST_ZONE_TEMPLATE = "Invalid last_zone: {last_zone}"


class OpsiExplore(OSMap):
    def __init__(
        self,
        config: AzurLaneConfig | str,
        device: Device | str | None = None,
        task: str | None = None,
    ) -> None:
        self._os_explore_failed_zone: list[int] = []
        super().__init__(config, device=device, task=task)

    def _os_explore_task_delay(self) -> None:
        """探索期间推迟其他大世界任务。"""
        logger.info("Delay other OpSi tasks during OpsiExplore")
        with self.config.multi_set():
            next_run = self.config.Scheduler_NextRun
            for task in [
                "OpsiObscure",
                "OpsiAbyssal",
                "OpsiArchive",
                "OpsiStronghold",
                "OpsiMeowfficerFarming",
                "OpsiMonthBoss",
                "OpsiShop",
                "OpsiHazard1Leveling",
            ]:
                keys = f"{task}.Scheduler.NextRun"
                current = self.config.cross_get(keys=keys, default=DEFAULT_TIME)
                if not isinstance(current, datetime):
                    current = DEFAULT_TIME
                if current < next_run:
                    logger.info(f"Delay task `{task}` to {next_run}")
                    self.config.cross_set(keys=keys, value=next_run)

    def _finish_os_explore(self) -> None:
        logger.info("OS explore finished, delay to next reset")
        next_reset = get_os_next_reset()
        logger.attr("OpsiNextReset", next_reset)
        logger.info("To run again, clear OpsiExplore.Scheduler.NextRun and set OpsiExplore.OpsiExplore.LastZone=0")
        with self.config.multi_set():
            self.config.OpsiExplore_LastZone = 0
            self.config.OpsiExplore_SpecialRadar = False
            self.config.task_delay(target=next_reset)
            self.config.task_call("OpsiDaily", force_call=False)
            self.config.task_call("OpsiShop", force_call=False)
            self.config.task_call("OpsiHazard1Leveling", force_call=False)
        self.config.task_stop()

    def _last_os_explore_zone(self) -> int:
        try:
            return self.name_to_zone(self.config.OpsiExplore_LastZone).zone_id
        except ScriptError:
            logger.warning(f"Invalid OpsiExplore_LastZone={self.config.OpsiExplore_LastZone}, re-explore")
            return 0

    def _os_explore_order(self) -> list[int]:
        order = [int(f.strip(" \t\r\n")) for f in self.config.OS_EXPLORE_FILTER.split(">")]
        last_zone = self._last_os_explore_zone()
        if last_zone in order:
            order = order[order.index(last_zone) + 1 :]
            logger.info(f"Last zone: {self.name_to_zone(last_zone)}, next zone: {order[:1]}")
        elif last_zone == 0:
            logger.info(f"First run, next zone: {order[:1]}")
        else:
            message = INVALID_LAST_ZONE_TEMPLATE.format(last_zone=last_zone)
            raise ScriptError(message)
        return order

    def _skip_cleared_os_explore_zone(self, zone: int) -> bool:
        if self.globe_goto(zone, stop_if_safe=True):
            return False
        logger.info(f"Zone cleared: {self.name_to_zone(zone)}")
        self.config.OpsiExplore_LastZone = zone
        return True

    def _prepare_os_explore_zone(self) -> None:
        if not self.config.OpsiExplore_SpecialRadar:
            self.tuning_sample_use()
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(
            recon_scan=not self.config.OpsiExplore_SpecialRadar, submarine_call=self.config.OpsiFleet_Submarine
        )
        self._os_explore_task_delay()

    def _run_os_explore_zone(self, zone: int) -> None:
        logger.hr(f"OS explore {zone}", level=1)
        self._prepare_os_explore_zone()

        finished_combat = self.run_auto_search()
        self.config.OpsiExplore_LastZone = zone
        logger.info(f"Zone cleared: {self.name_to_zone(zone)}")
        if finished_combat == 0:
            logger.warning("Zone cleared but did not finish any combat")
            self._os_explore_failed_zone.append(zone)
        self.handle_after_auto_search()
        self.config.check_task_switch()

    def _os_explore(self) -> None:
        """月初探索全部危险海域，并把失败海域编号写入 _os_explore_failed_zone。"""
        logger.hr("OS explore", level=1)
        order = self._os_explore_order()
        if not len(order):
            self._finish_os_explore()
            return

        self._os_explore_failed_zone = []
        for zone in order:
            if self._skip_cleared_os_explore_zone(zone):
                continue
            self._run_os_explore_zone(zone)

            if zone == order[-1]:
                self._finish_os_explore()

    def os_explore(self) -> None:
        for _ in range(2):
            try:
                self._os_explore()
            except OSExploreError:
                logger.info("Go back to NY, explore again")
                self.config.OpsiExplore_LastZone = 0
                self.globe_goto(0)

        failed_zone = [self.name_to_zone(zone) for zone in self._os_explore_failed_zone]
        logger.error(
            f"OpsiExplore failed at these zones, please check you game settings "
            f"and check if there is any unfinished event in them: {failed_zone}"
        )
        logger.critical("Failed to solve the locked zone")
        raise GameStuckError
