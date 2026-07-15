from typing import TYPE_CHECKING

from module.exception import ScriptError
from module.logger import logger
from module.os.map import OSMap

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.device.device import Device

INVALID_LAST_ZONE_TEMPLATE = "Invalid last_zone: {last_zone}"


class OpsiExplore(OSMap):
    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
    ) -> None:
        self._os_explore_failed_zone: list[int] = []
        super().__init__(config, device=device)

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
