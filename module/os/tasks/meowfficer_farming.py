from typing import TYPE_CHECKING

from module.exception import HumanTakeoverRequiredError, ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.os.map import OSMap

if TYPE_CHECKING:
    from module.os.globe_zone import Zone

WRONG_ZONE_INPUT_MESSAGE = "wrong input, task stopped"


class OpsiMeowfficerFarming(OSMap):
    def _apply_meowfficer_action_point_preserve(self, preserve: int) -> None:
        self.config.OS_ACTION_POINT_PRESERVE = preserve
        if self._should_ignore_action_point_for_ash():
            logger.info("Ash beacon not fully collected, ignore action point limit temporarily")
            self.config.OS_ACTION_POINT_PRESERVE = 0
        logger.attr("OS_ACTION_POINT_PRESERVE", self.config.OS_ACTION_POINT_PRESERVE)

    def _should_ignore_action_point_for_ash(self) -> bool:
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

    def _next_meowfficer_farming_zone(self) -> tuple[Zone, bool]:
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

    def _configured_meowfficer_farming_zone(self) -> Zone:
        try:
            return self.name_to_zone(self.config.OpsiMeowfficerFarming_TargetZone)
        except ScriptError as e:
            logger.warning(f"wrong zone_id input:{self.config.OpsiMeowfficerFarming_TargetZone}")
            raise HumanTakeoverRequiredError(WRONG_ZONE_INPUT_MESSAGE) from e

    def _run_meowfficer_farming_zone(self, zone: Zone, *, refresh: bool) -> None:
        logger.hr(f"OS meowfficer farming, zone_id={zone.zone_id}", level=1)
        if refresh:
            self.globe_goto(zone, refresh=True)
        else:
            self.globe_goto(zone)
        self.fleet_set(self.config.OpsiFleet_Fleet)
        self.os_order_execute(recon_scan=False, submarine_call=self.config.OpsiFleet_Submarine)
        self.run_auto_search()
        self.handle_after_auto_search()
