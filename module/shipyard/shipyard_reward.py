from datetime import datetime
from typing import Literal

from module.base.timer import Timer
from module.config.utils import get_server_last_update
from module.exception import ScriptError
from module.logger import logger
from module.shipyard.ui import ShipyardUI
from module.ui.page import page_main, page_shipyard

PRBP_BUY_PRIZE = {
    (1, 2): 0,
    (3, 4): 150,
    (5, 6, 7): 300,
    (8, 9, 10): 600,
    (11, 12, 13, 14, 15): 1050,
}
DRBP_BUY_PRIZE = {
    (1, 2): 0,
    (3, 4, 5, 6): 600,
    (7, 8, 9, 10): 1200,
    (11, 12, 13, 14, 15): 3000,
}
INVALID_SHIPYARD_RARITY_TEMPLATE = "Invalid rarity in _shipyard_get_cost: {rarity}"

type ShipyardRarity = Literal["PR", "DR"]


class RewardShipyard(ShipyardUI):
    _shipyard_bp_rarity: ShipyardRarity = "PR"
    _coin_count = 0

    def _shipyard_get_cost(self, amount: int, rarity: ShipyardRarity | None = None) -> int:
        """返回指定购买序号与 DR/PR 稀有度的单张蓝图价格。"""
        if rarity is None:
            rarity = self._shipyard_bp_rarity

        if rarity == "PR":
            cost = [v for k, v in PRBP_BUY_PRIZE.items() if amount in k]
            if cost:
                return cost[0]
            return 1500
        if rarity == "DR":
            cost = [v for k, v in DRBP_BUY_PRIZE.items() if amount in k]
            if cost:
                return cost[0]
            return 6000
        message = INVALID_SHIPYARD_RARITY_TEMPLATE.format(rarity=rarity)
        raise ScriptError(message)

    def _shipyard_calculate(self, start: int, count: int, *, pay: bool = False) -> tuple[int, int]:
        """返回下一购买序号和当前可买数量；pay=True 时同时扣减 _coin_count。"""
        if start <= 0 or count <= 0:
            return start, count

        total = 0
        i = start
        for i in range(start, (start + count)):
            cost = self._shipyard_get_cost(i)

            if (total + cost) > self._coin_count:
                if pay:
                    self._coin_count -= total
                else:
                    logger.info(f"Can only buy up to {(i - start)} of the {count} BPs")
                return i, i - start
            total += cost

        if pay:
            self._coin_count -= total
        else:
            logger.info(f"Can buy all {count} BPs")
        return i + 1, count

    def _shipyard_buy_calc(self, start: int, count: int) -> tuple[int, int]:
        return self._shipyard_calculate(start, count, pay=False)

    def _shipyard_pay_calc(self, start: int, count: int) -> tuple[int, int]:
        return self._shipyard_calculate(start, count, pay=True)

    def _shipyard_buy(self, count: int) -> None:
        """在 DEV 或 FATE 中购买最多 count 张蓝图。"""
        logger.hr("shipyard_buy")
        prev = 1
        start, count = self._shipyard_buy_calc(prev, count)
        while count > 0:
            if not self._shipyard_buy_enter() or self._shipyard_cannot_strengthen():
                break

            remain = self._shipyard_ensure_index(count)
            if remain is None:
                break

            if self._shipyard_bp_rarity == "DR":
                self.config.ShipyardDr_LastRun = datetime.now().replace(microsecond=0)
            else:
                self.config.Shipyard_LastRun = datetime.now().replace(microsecond=0)

            self._shipyard_buy_confirm("BP_BUY")

            start, _ = self._shipyard_pay_calc(prev, (count - remain))
            prev = start

            start, count = self._shipyard_buy_calc(start, remain)

    def _shipyard_use(self, index: int) -> None:
        """在 DEV 或 FATE 中消耗指定舰船的剩余蓝图。"""
        logger.hr("shipyard_use")
        count = self._shipyard_get_bp_count(index)
        while count > 0:
            if not self._shipyard_buy_enter() or self._shipyard_cannot_strengthen():
                break

            remain = self._shipyard_ensure_index(count)
            if remain is None:
                break
            self._shipyard_buy_confirm("BP_USE")

            count = self._shipyard_get_bp_count(index)

    def shipyard_run(self, series: int, index: int, count: int) -> bool:
        """运行系列 1～4、舰船 1～6 的蓝图使用和购买；发生页面跳转即返回 True。"""
        if count <= 0:
            return False

        # 船坞页金币标签和数字共同右对齐，OCR 困难，改从主页读取。
        self.ui_ensure(page_main)
        timeout = Timer(1, count=1).start()
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            self._coin_count = self._shipyard_get_coin()

            if self._coin_count > 0:
                break
            if timeout.reached():
                logger.warning("Assumes that OCR_COIN is in the right place")
                break

        self.ui_goto(page_shipyard)
        if (
            not self.shipyard_set_focus(series=series, index=index)
            or not self._shipyard_buy_enter()
            or self._shipyard_cannot_strengthen()
        ):
            return True

        self._shipyard_use(index=index)
        self._shipyard_buy(count=count)

        return True

    def run(self) -> None:
        """从任意页面执行船坞蓝图任务，结束于船坞页。"""
        if self.config.Shipyard_BuyAmount <= 0 and self.config.ShipyardDr_BuyAmount <= 0:
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        logger.hr("Shipyard DR", level=1)
        logger.attr("ShipyardDr_LastRun", self.config.ShipyardDr_LastRun)
        if self.config.ShipyardDr_LastRun > get_server_last_update("04:00"):
            logger.warning("Task Shipyard DR has already been run today, skip")
        else:
            self._shipyard_bp_rarity = "DR"
            self.shipyard_run(
                series=self.config.ShipyardDr_ResearchSeries,
                index=self.config.ShipyardDr_ShipIndex,
                count=self.config.ShipyardDr_BuyAmount,
            )

        logger.hr("Shipyard PR", level=1)
        logger.attr("Shipyard_LastRun", self.config.Shipyard_LastRun)
        if self.config.Shipyard_LastRun > get_server_last_update("04:00"):
            logger.warning("Task Shipyard PR has already been run today, stop")
            self.config.task_delay(server_update=True)
            self.config.task_stop()
        else:
            self._shipyard_bp_rarity = "PR"
            self.shipyard_run(
                series=self.config.Shipyard_ResearchSeries,
                index=self.config.Shipyard_ShipIndex,
                count=self.config.Shipyard_BuyAmount,
            )

        self.config.task_delay(server_update=True)
