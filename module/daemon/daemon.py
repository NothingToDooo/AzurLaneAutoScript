from module.campaign.campaign_engine import CampaignEngine
from module.exception import CampaignEnd
from module.handler.assets import MAP_AMBUSH_EVADE
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION


class AzurLaneDaemon(CampaignEngine):
    def advance_once(self) -> bool:
        """推进一个可中断步骤；公会弹窗关闭后返回已完成。"""
        with self.device.suspend_stuck_detection():
            self.device.screenshot()
            handlers = (
                self.handle_daemon_combat,
                self.handle_daemon_map_operation,
                self.handle_daemon_map_preparation,
                self.handle_daemon_misc,
            )
            for handler in handlers:
                if handler():
                    return False
            return bool(self.handle_guild_popup_cancel())

    def handle_daemon_combat(self) -> bool:
        # 战斗中只保持截图轮询，不插入其他操作。
        if self.is_combat_executing():
            return True

        if self.combat_appear():
            self.combat_preparation()
        try:
            if self.handle_battle_status():
                self.combat_status(expected_end="no_searching")
                return True
        except CampaignEnd:
            return True
        return False

    def handle_daemon_map_operation(self) -> bool:
        if self.appear_then_click(MAP_AMBUSH_EVADE, offset=(20, 20)):
            self.device.sleep(1)
            return True
        return bool(self.handle_mystery_items())

    def handle_daemon_map_preparation(self) -> bool:
        if not self.config.Daemon_EnterMap:
            return False
        if self.appear_then_click(MAP_PREPARATION, offset=(20, 20), interval=2):
            return True
        return bool(self.appear_then_click(FLEET_PREPARATION, offset=(20, 50), interval=2))

    def handle_daemon_misc(self) -> bool:
        if self.handle_retirement():
            return True
        if self.handle_urgent_commission():
            return True
        if self.handle_vote_popup():
            return True
        return bool(self.story_skip())
