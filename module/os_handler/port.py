from module.base.timer import Timer
from module.logger import logger
from module.os_handler import assets as os_assets
from module.os_shop.assets import PORT_SUPPLY_CHECK
from module.os_shop.shop import OSShop

# 蓝色港口有 PORT_GOTO_MISSION、PORT_GOTO_SUPPLY、PORT_GOTO_DOCK。
# 赤色港口只有 PORT_GOTO_SUPPLY。
# 使用 PORT_GOTO_SUPPLY 作为港口检查按钮。
PORT_CHECK = os_assets.PORT_GOTO_SUPPLY


class PortHandler(OSShop):
    def port_enter(self) -> None:
        """从区域地图进入港口。"""
        logger.info("Port enter")
        for _ in self.loop():
            if self.appear(PORT_CHECK, offset=(20, 20)):
                break
            if self.appear_then_click(os_assets.PORT_ENTER, offset=(20, 20), interval=5):
                continue
            if self.handle_map_event():
                continue
        # 底部按钮有出现动画。
        # ui_click 已经确保等待完成。

    def port_quit(self, *, skip_first_screenshot: bool = True) -> None:
        """从港口返回区域地图，并等待底部按钮动画结束。"""
        logger.info("Port quit")
        self.ui_back(appear_button=PORT_CHECK, check_button=self.is_in_map, skip_first_screenshot=skip_first_screenshot)
        # 底部按钮有出现动画。
        self.wait_os_map_buttons()

    def port_mission_accept(self) -> bool:
        """在港口领取全部任务；2022-01-13 后任务已只显示在总览中。

        达到任务上限时返回 False，页面保持在港口。
        """
        if not self.appear(os_assets.PORT_MISSION_RED_DOT):
            logger.info("No available missions in this port")
            return True

        self.ui_click(
            os_assets.PORT_GOTO_MISSION,
            appear_button=PORT_CHECK,
            check_button=os_assets.PORT_MISSION_CHECK,
            skip_first_screenshot=True,
        )

        confirm_timer = Timer(1.5, count=3).start()
        success = True
        for _ in self.loop():
            if self.appear_then_click(os_assets.PORT_MISSION_ACCEPT, offset=(20, 20), interval=0.2):
                confirm_timer.reset()
                continue
            if confirm_timer.reached():
                success = True
                break

            if self.info_bar_count():
                logger.info("Unable to accept missions, because reached the maximum number of missions")
                success = False
                break

        self.ui_back(appear_button=os_assets.PORT_MISSION_CHECK, check_button=PORT_CHECK, skip_first_screenshot=True)
        return success

    def port_shop_enter(self) -> None:
        """从港口进入补给商店，并等待商品动画结束。"""
        self.ui_click(
            os_assets.PORT_GOTO_SUPPLY,
            appear_button=PORT_CHECK,
            check_button=PORT_SUPPLY_CHECK,
            skip_first_screenshot=True,
        )
        # 港口商店物品有出现动画。
        self.device.sleep(0.5)
        self.device.screenshot()

    def port_shop_quit(self) -> None:
        """从补给商店返回港口。"""
        self.ui_back(appear_button=PORT_SUPPLY_CHECK, check_button=PORT_CHECK, skip_first_screenshot=True)

    def port_dock_repair(self) -> None:
        """在港口维修全部舰船，页面保持在港口。"""
        self.ui_click(
            os_assets.PORT_GOTO_DOCK,
            appear_button=PORT_CHECK,
            check_button=os_assets.PORT_DOCK_CHECK,
            skip_first_screenshot=True,
        )

        repaired = False
        for _ in self.loop():
            if self.info_bar_count():
                break
            if repaired and self.appear(os_assets.PORT_DOCK_CHECK, offset=(20, 20)):
                break

            # PORT_DOCK_CHECK 是一键维修按钮。
            if self.appear_then_click(os_assets.PORT_DOCK_CHECK, offset=(20, 20), interval=2):
                continue
            if self.handle_popup_confirm("DOCK_REPAIR"):
                repaired = True
                continue

        self.ui_back(appear_button=os_assets.PORT_DOCK_CHECK, check_button=PORT_CHECK, skip_first_screenshot=True)
