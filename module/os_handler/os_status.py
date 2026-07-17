from dataclasses import dataclass
from datetime import datetime, timedelta

from module.base.timer import Timer
from module.config.deep import DeepValue, deep_get
from module.config.utils import get_server_next_update
from module.logger import logger
from module.ocr.ocr import Digit
from module.os_shop.assets import OS_SHOP_CHECK, OS_SHOP_PURPLE_COINS, SHOP_PURPLE_COINS, SHOP_YELLOW_COINS
from module.ui.ui import UI

_COOLDOWN_TASKS = ("OpsiObscure", "OpsiAbyssal", "OpsiStronghold", "OpsiDaily")


@dataclass(frozen=True, slots=True)
class OpsiCooldown:
    command: str
    ready_at: datetime


def nearest_opsi_cooldown(
    data: DeepValue,
    *,
    now: datetime,
    server_update: datetime,
) -> OpsiCooldown | None:
    """返回未来一小时内最先到期、且不等于日服重置点的大世界任务。"""
    deadline = now + timedelta(minutes=60)
    candidates: list[OpsiCooldown] = []
    for command in _COOLDOWN_TASKS:
        enabled = deep_get(data, keys=f"{command}.Scheduler.Enable", default=False)
        ready_at = deep_get(data, keys=f"{command}.Scheduler.NextRun")
        if (
            enabled is True
            and isinstance(ready_at, datetime)
            and ready_at != server_update
            and now <= ready_at <= deadline
        ):
            candidates.append(OpsiCooldown(command=command, ready_at=ready_at))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item.ready_at)


OCR_SHOP_YELLOW_COINS = Digit(SHOP_YELLOW_COINS, letter=(239, 239, 239), threshold=160, name="OCR_SHOP_YELLOW_COINS")
OCR_SHOP_PURPLE_COINS = Digit(SHOP_PURPLE_COINS, letter=(255, 255, 255), name="OCR_SHOP_PURPLE_COINS")
OCR_OS_SHOP_PURPLE_COINS = Digit(OS_SHOP_PURPLE_COINS, letter=(255, 255, 255), name="OCR_OS_SHOP_PURPLE_COINS")


class OSStatus(UI):
    _shop_yellow_coins = 0
    _shop_purple_coins = 0

    @property
    def is_in_task_explore(self) -> bool:
        return self.config.task.command == "OpsiExplore"

    @property
    def is_in_task_cl1_leveling(self) -> bool:
        return self.config.task.command == "OpsiHazard1Leveling"

    @property
    def is_cl1_enabled(self) -> bool:
        return self.config.is_task_enabled("OpsiHazard1Leveling")

    @property
    def nearest_task_cooldown(self) -> OpsiCooldown | None:
        return nearest_opsi_cooldown(
            self.config.data,
            now=datetime.now(),
            server_update=get_server_next_update("00:00"),
        )

    def get_yellow_coins(self) -> int:
        yellow_coins = 0
        timeout = Timer(2, count=3).start()
        for _ in self.loop():
            yellow_coins = OCR_SHOP_YELLOW_COINS.ocr_single(self.device.image)
            if timeout.reached():
                logger.warning("Get yellow coins timeout")
                break

            if yellow_coins < 100:
                # 金币尚未加载时 OCR 可能误读为 0 或 1。
                logger.info("Yellow coins less than 100, assuming it is an ocr error")
                continue
            break

        return yellow_coins

    def get_purple_coins(self) -> int:
        if self.appear(OS_SHOP_CHECK):
            return OCR_OS_SHOP_PURPLE_COINS.ocr_single(self.device.image)
        return OCR_SHOP_PURPLE_COINS.ocr_single(self.device.image)

    def os_shop_get_coins(self) -> None:
        self._shop_yellow_coins = self.get_yellow_coins()
        self._shop_purple_coins = self.get_purple_coins()
        logger.info(f"Yellow coins: {self._shop_yellow_coins}, purple coins: {self._shop_purple_coins}")
