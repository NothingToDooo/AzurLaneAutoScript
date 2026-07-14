from typing import ClassVar

from module.base.timer import Timer
from module.logger import logger
from module.private_quarters.assets import (
    PRIVATE_QUARTERS_SHOP_BACK,
    PRIVATE_QUARTERS_SHOP_CHECK,
    PRIVATE_QUARTERS_SHOP_ENTER,
)
from module.private_quarters.interact import PQInteract
from module.private_quarters.shop import PQShop
from module.ui.page import page_dormmenu, page_private_quarters


class PrivateQuarters(PQInteract, PQShop):
    not_supported_ships: ClassVar[tuple[str, ...]] = ("nakhimov",)

    def pq_get_daily_count(self, retry: int = 3) -> int:
        """快速设备的首张截图可能模糊或滞后，有限重试后才确认每日次数为 0。"""
        count = self.status_get_daily_count()
        get_timer = Timer(1.5, count=3).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if count != 0 or retry == 0:
                return count

            if get_timer.reached():
                count = self.status_get_daily_count()
                get_timer.reset()
                retry -= 1
        return count

    def _pq_shop_enter(self) -> None:
        self.ui_click(
            click_button=PRIVATE_QUARTERS_SHOP_ENTER,
            check_button=PRIVATE_QUARTERS_SHOP_CHECK,
            appear_button=page_private_quarters.check_button,
            offset=(20, 20),
            skip_first_screenshot=True,
        )

        self.shop_left_navbar_ensure(2)

        self.shop_bottom_navbar_ensure(2)

    def _pq_shop_exit(self) -> None:
        self.ui_click(
            click_button=PRIVATE_QUARTERS_SHOP_BACK,
            check_button=page_private_quarters.check_button,
            appear_button=PRIVATE_QUARTERS_SHOP_CHECK,
            offset=(20, 20),
            skip_first_screenshot=True,
        )

    def pq_shop_weekly_items(self) -> None:
        """购买每周商品；玫瑰需 24000 金币，蛋糕需 210 钻石，不足时次日再试。"""
        logger.hr("Get Weekly Items", level=2)

        self._pq_shop_enter()

        self.shop_buy()

        self._pq_shop_exit()

    def pq_execute_interact(self, target_ship: str) -> None:
        target_title = target_ship.title().replace("_", " ")
        if target_ship not in self.available_targets:
            logger.error(f"Unsupported target ship: {target_title}, cannot continue subtask")
            return

        if not self.pq_goto_room(target_ship, retry=3):
            return

        self.pq_interact()

    def pq_run(self) -> None:
        """执行每周商店购买和每日目标舰船互动。"""
        logger.hr("Private Quarters Run", level=1)
        target_interact = self.config.PrivateQuarters_TargetInteract
        target_ship = self.config.PrivateQuarters_TargetShip
        target_title = target_ship.title().replace("_", " ")
        logger.info(
            f"Task configured for Buy_Roses={self.config.PrivateQuarters_BuyRoses}, "
            f"Buy_Cake={self.config.PrivateQuarters_BuyCake}, "
            f"Interact_ShipGirl={target_interact}, "
            f"Target_ShipGirl={target_title}"
        )

        if self.shop_filter:
            self.pq_shop_weekly_items()

        if target_interact:
            if target_ship in self.not_supported_ships:
                logger.info(f"Target ship:{target_ship} not supported.")
                return

            count = self.pq_get_daily_count(retry=3)
            if count == 0:
                logger.info("Daily intimacy count exhausted, exit subtask")
                return

            self.pq_execute_interact(target_ship)

    def run(self) -> None:
        """从任意页面执行私宅任务，结束于可能带 info_bar 的主页。"""
        self.ui_ensure(page_dormmenu)
        self.ui_goto(page_private_quarters, get_ship=False)
        self.handle_info_bar()
        self.pq_run()

        self.config.task_delay(server_update=True)
