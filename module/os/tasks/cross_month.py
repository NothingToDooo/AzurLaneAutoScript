from datetime import datetime

from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap


class OpsiCrossMonth(OSMap):
    def _wait_until_opsi_reset(self, next_reset: datetime) -> None:
        logger.hr("Wait until OpSi reset", level=1)
        logger.warning("ALAS is now waiting for next OpSi reset, please DO NOT touch the game during wait")
        while True:
            logger.info(f"Wait until {next_reset}")
            remain = (next_reset - datetime.now()).total_seconds()
            if remain <= 0:
                break
            self.device.sleep(min(remain, 60))
        logger.hr("OpSi reset", level=3)

    def _clear_opsi_monthly_items(self, *, obscure_fleet: int, abyssal_fleet_filter: str) -> None:
        logger.hr("OS clear abyssal", level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=False,
            HOMO_EDGE_DETECT=False,
            STORY_OPTION=0,
            OpsiGeneral_UseLogger=True,
            OpsiObscure_ForceRun=True,
            OpsiFleet_Fleet=obscure_fleet,
            OpsiFleet_Submarine=False,
            OpsiFleetFilter_Filter=abyssal_fleet_filter,
            OpsiAbyssal_ForceRun=True,
        )
        self._clear_opsi_abyssal_items()

        logger.hr("OS clear obscure", level=1)
        self._clear_opsi_obscure_items()

    def _clear_opsi_abyssal_items(self) -> None:
        while self.storage_get_next_item("ABYSSAL", use_logger=True):
            self.zone_init()
            if not self.run_abyssal():
                self.map_exit()
            self.fleet_repair(revert=False)

    def _clear_opsi_obscure_items(self) -> None:
        while self.storage_get_next_item("OBSCURE", use_logger=True):
            self.zone_init()
            self.fleet_set(self.config.OpsiFleet_Fleet)
            self.os_order_execute(recon_scan=True, submarine_call=False)
            self.run_auto_search(rescan="current")
            self.map_exit()
            self.handle_after_auto_search()

    def _run_opsi_meowfficer_farming_after_reset(self, *, fleet_index: int) -> None:
        logger.hr("OS meowfficer farming, hazard_level=3", level=1)
        self.config.override(
            OpsiGeneral_DoRandomMapEvent=True,
            OpsiGeneral_BuyActionPointLimit=0,
            HOMO_EDGE_DETECT=True,
            STORY_OPTION=-2,
            OpsiFleet_Fleet=fleet_index,
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
            self.fleet_set(fleet_index)
            self.os_order_execute(recon_scan=False, submarine_call=False)
            self.run_auto_search()
            self.handle_after_auto_search()
