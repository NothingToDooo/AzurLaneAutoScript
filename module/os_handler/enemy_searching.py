from module.handler.enemy_searching import EnemySearchingHandler as EnemySearchingHandler_
from module.logger import logger
from module.os.assets import MAP_GOTO_GLOBE_FOG
from module.os_handler.assets import AUTO_SEARCH_REWARD, IN_MAP, ORDER_ENTER


class EnemySearchingHandler(EnemySearchingHandler_):
    def is_in_map(self) -> bool:
        if IN_MAP.match_luma(self.device.image, offset=(200, 5)):
            return True
        return self.match_template_color(MAP_GOTO_GLOBE_FOG, offset=(5, 5))

    def wait_os_map_buttons(self) -> None:
        """进入区域地图时，等待雷达和右侧按钮滑动到最终位置。"""
        for _ in self.loop(timeout=1):
            if self.appear(ORDER_ENTER, offset=(20, 20)):
                break
            # 游戏可能延迟弹出上一个已清理海域的自动搜索奖励。
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
        else:
            logger.warning("wait_os_map_buttons timeout, assume waited")
