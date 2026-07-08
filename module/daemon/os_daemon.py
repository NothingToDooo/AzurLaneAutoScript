from module.combat.assets import EXP_INFO_C, EXP_INFO_D
from module.daemon.daemon_base import DaemonBase
from module.exception import CampaignEnd
from module.logger import logger
from module.os.config import OSConfig
from module.os.fleet import OSFleet
from module.os_combat.combat import ContinuousCombat
from module.os_handler.assets import AUTO_SEARCH_REWARD, PORT_ENTER
from module.os_handler.port import PortHandler


class AzurLaneDaemon(DaemonBase, OSFleet, PortHandler):
    def _os_combat_expected_end(self):
        if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=2):
            return False

        return super()._os_combat_expected_end()

    def prepare_os_daemon_config(self):
        self.config.merge(OSConfig())
        self.config.override(HOMO_EDGE_DETECT=False)

    def handle_os_daemon_combat(self):
        # 战斗中只保持截图轮询，不插入其他操作。
        if self.is_combat_executing():
            return True

        if self.combat_appear():
            self.combat_preparation()
        try:
            if self.handle_battle_status():
                self.combat_status(expected_end="no_searching")
                return True
        except CampaignEnd, ContinuousCombat:
            return True
        return False

    def handle_os_daemon_exp_info(self):
        if self.appear_then_click(EXP_INFO_C, interval=2):
            return True
        return bool(self.appear_then_click(EXP_INFO_D, interval=2))

    def handle_os_daemon_map_event(self):
        if not self.handle_map_event():
            return False
        self._nearest_object_click_timer.clear()
        return True

    def handle_os_daemon_auto_search_reward(self):
        return bool(self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=2))

    def handle_os_daemon_port_repair(self):
        if not self.config.OpsiDaemon_RepairShip:
            return False
        if not self.appear(PORT_ENTER, offset=(20, 20), interval=30):
            return False

        self.port_enter()
        self.port_dock_repair()
        self.port_quit()
        self.interval_reset(PORT_ENTER)
        logger.info("Port repair finished, please move your fleet out of the port in 30s to avoid repairing again")
        return True

    def handle_os_daemon_enemy_selection(self):
        return bool(self.config.OpsiDaemon_SelectEnemy and self.click_nearest_object())

    def run(self):
        self.prepare_os_daemon_config()
        while 1:
            self.device.screenshot()

            if self.handle_os_daemon_combat():
                continue
            if self.handle_os_daemon_exp_info():
                continue
            if self.handle_os_daemon_map_event():
                continue
            if self.handle_os_daemon_auto_search_reward():
                continue

            self.handle_os_daemon_port_repair()
            if self.handle_os_daemon_enemy_selection():
                continue

            # 没有自动结束条件，需要手动停止。

        return True


if __name__ == "__main__":
    b = AzurLaneDaemon("alas", task="OpsiDaemon")
    b.run()
