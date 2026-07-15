from module.logger import logger
from module.os.fleet import BossFleet
from module.os.map import OSMap


class OpsiStronghold(OSMap):
    def run_stronghold_one_fleet(self, fleet: BossFleet) -> bool:
        """使用指定舰队清理一次要塞，并返回是否全部完成。"""
        self.config.override(OpsiGeneral_DoRandomMapEvent=False, HOMO_EDGE_DETECT=False, STORY_OPTION=0)
        # 舰队可能卡在迷雾中，最多尝试三次。
        for _ in range(3):
            self.fleet_set(fleet.fleet_index)
            self.run_auto_search(question=False, rescan=False)
            self.hp_reset()
            self.hp_get()

            if self.get_stronghold_percentage() == "0":
                logger.info("BOSS clear")
                return True
            if any(self.need_repair):
                logger.info("Auto search stopped, because fleet died")
                # 重新进入以重置舰队位置。
                prev = self.zone
                self.globe_goto(self.zone_nearest_azur_port(self.zone))
                self.handle_fog_block(repair=True)
                self.globe_goto(prev, types=("STRONGHOLD",))
                return False
            logger.info("Auto search stopped, because fleet stuck")
            # 重新进入以重置舰队位置。
            prev = self.zone
            self.globe_goto(self.zone_nearest_azur_port(self.zone))
            self.handle_fog_block(repair=False)
            self.globe_goto(prev, types=("STRONGHOLD",))
            continue
        return False

    def run_stronghold(self) -> bool:
        """让各舰队轮流攻击要塞；成功后进入危险或安全海域，失败时仍在要塞。"""
        logger.hr("Stronghold clear", level=1)
        fleets = self.parse_fleet_filter()
        for fleet in fleets:
            logger.hr(f"Turn: {fleet}", level=2)
            if not isinstance(fleet, BossFleet):
                self.os_order_execute(recon_scan=False, submarine_call=True)
                continue

            result = self.run_stronghold_one_fleet(fleet)
            if result:
                return True
            continue

        logger.critical("Unable to clear boss, fleets exhausted")
        return False
