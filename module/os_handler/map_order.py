from typing import TYPE_CHECKING

import numpy as np

from module.base.timer import Timer
from module.base.utils import color_similarity_2d
from module.logger import logger
from module.map.assets import MAP_CAT_ATTACK
from module.map.map_operation import MapOperation
from module.os.globe_zone import Zone, ZoneManager
from module.os_handler import assets as os_assets
from module.os_handler.action_point import ActionPointHandler
from module.os_handler.map_event import MapEventHandler

if TYPE_CHECKING:
    from module.base.button import Button


class MapOrderHandler(MapOperation, ActionPointHandler, MapEventHandler, ZoneManager):
    def is_in_map_order(self) -> bool:
        return self.appear(os_assets.ORDER_CHECK, offset=(20, 20))

    def order_enter(self) -> None:
        """从区域地图进入指令页。"""
        logger.info("Order enter")
        for _ in self.loop():
            if self.is_in_map_order():
                break

            if self.is_in_map() and self.appear_then_click(os_assets.ORDER_ENTER, offset=(20, 20), interval=2):
                continue
            # 上一个已清理海域的自动搜索奖励有时会延迟弹出。
            if self.appear_then_click(os_assets.AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
            # 用户游戏设置不正确时，跳过 TB 引导。
            if self.handle_map_event():
                continue

    def order_quit(self) -> None:
        """从指令页返回区域地图。"""
        logger.info("Order quit")
        self.ui_click(
            os_assets.ORDER_CHECK,
            appear_button=self.is_in_map_order,
            check_button=self.is_in_map,
            skip_first_screenshot=True,
        )

    def order_execute(self, button: Button) -> bool:
        """在区域地图执行一项导航指令，结束后仍在区域地图。"""
        logger.hr(button)
        self.order_enter()

        missing_timer = Timer(1, count=3).start()
        confirm_timer = Timer(1.2, count=4).start()
        assume_zone = self.name_to_zone(11)

        for _ in self.loop():
            if self._order_execute_finished(confirm_timer):
                return True
            if self._order_missing(button, missing_timer):
                self.order_quit()
                return False
            if self._order_execute_step(button, assume_zone, confirm_timer, missing_timer):
                continue
        return False

    def _order_execute_finished(self, confirm_timer: Timer) -> bool:
        if self.is_in_map():
            return confirm_timer.reached()

        confirm_timer.reset()
        return False

    def _order_missing(self, button: Button, missing_timer: Timer) -> bool:
        if not self.is_in_map_order() or self.appear(button):
            missing_timer.reset()
            return False

        if not missing_timer.reached():
            return False

        logger.info(f"Map order not available: {button}")
        return True

    def _order_execute_step(
        self,
        button: Button,
        assume_zone: Zone,
        confirm_timer: Timer,
        missing_timer: Timer,
    ) -> bool:
        if self.appear_then_click(button, interval=3):
            return True
        if self.handle_popup_confirm(button.name):
            return True
        if self.handle_map_event() or self.handle_map_cat_attack():
            return True
        if not self.handle_action_point(zone=assume_zone, pinned="OBSCURE"):
            return False

        # 点击行动力取消后，游戏会关闭指令页面，需要重新进入并执行指令。
        self.order_enter()
        confirm_timer.reset()
        missing_timer.reset()
        return True

    def wait_until_order_finished(self) -> None:
        for _ in self.loop():
            if self.is_in_map() and self.appear(os_assets.ORDER_ENTER, offset=(20, 20)):
                break

            if self.handle_map_event():
                continue
            if self.handle_map_cat_attack():
                continue

    def os_order_execute(self, *, recon_scan: bool = True, submarine_call: bool = True) -> None:
        """在区域地图执行指令，侦察与潜艇冷却分别为 30、60 分钟。

        冷却中会强制消耗行动力箱，最多分别消耗 10、39 行动力。
        """
        if recon_scan:
            recon_scan = self.order_execute(os_assets.ORDER_SCAN)
        if submarine_call:
            submarine_call = self.order_execute(os_assets.ORDER_SUBMARINE)
            if submarine_call:
                self.wait_until_order_finished()

        self.config.opsi_task_delay(recon_scan=recon_scan, submarine_call=submarine_call)

    def handle_map_cat_attack(self) -> bool:
        """猫攻击按钮与大世界 MAP_EXIT 重叠，因此覆盖普通地图处理。"""
        if not self.map_cat_attack_timer.reached():
            return False
        if np.sum(color_similarity_2d(self.image_crop(MAP_CAT_ATTACK, copy=False), (255, 231, 123)) > 221) > 100:
            logger.info("Skip map cat attack")
            self.device.click(os_assets.CLICK_SAFE_AREA)
            self.map_cat_attack_timer.reset()
            return True

        return False
