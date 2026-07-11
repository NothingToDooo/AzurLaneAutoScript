from datetime import UTC, datetime
from time import sleep
from typing import TYPE_CHECKING, Literal

from module.base.decorator import cached_property
from module.base.utils import random_normal_distribution_int
from module.exception import RequestHumanTakeover, ScriptEnd, ScriptError
from module.logger import logger

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig

DIC_LIMIT = {
    "keep_exp_bonus": 120,
    "prevent_green_face": 40,
    "prevent_yellow_face": 30,
    "prevent_red_face": 2,
}
DIC_RECOVER = {
    "not_in_dormitory": 20,
    "dormitory_floor_1": 40,
    "dormitory_floor_2": 50,
}
DIC_RECOVER_MAX = {
    "not_in_dormitory": 119,
    "dormitory_floor_1": 150,
    "dormitory_floor_2": 150,
}
OATH_RECOVER = 10
UNKNOWN_FLEET_ORDER_TEMPLATE = "Unknown fleet order: {method}"
EMOTION_CONTROL_DELAY_MESSAGE = "Emotion control"


class FleetEmotion:
    def __init__(self, config: AzurLaneConfig, fleet: Literal[1, 2]) -> None:
        self.config = config
        self.fleet = fleet
        self.current = 0

    @property
    def value(self) -> int:
        """返回 0～150 的当前心情值。"""
        if self.fleet == 1:
            return self.config.Emotion_Fleet1Value
        return self.config.Emotion_Fleet2Value

    @property
    def value_name(self) -> str:
        return f"Emotion_Fleet{self.fleet}Value"

    @property
    def record(self) -> datetime:
        """返回上次记录心情值的时间。"""
        if self.fleet == 1:
            return self.config.Emotion_Fleet1Record
        return self.config.Emotion_Fleet2Record

    @property
    def recover(self) -> str:
        """返回 not_in_dormitory、dormitory_floor_1 或 dormitory_floor_2。"""
        if self.fleet == 1:
            return self.config.Emotion_Fleet1Recover
        return self.config.Emotion_Fleet2Recover

    @property
    def control(self) -> str:
        """返回 keep_exp_bonus、prevent_green_face、prevent_yellow_face 或 prevent_red_face。"""
        if self.fleet == 1:
            return self.config.Emotion_Fleet1Control
        return self.config.Emotion_Fleet2Control

    @property
    def oath(self) -> bool:
        if self.fleet == 1:
            return self.config.Emotion_Fleet1Oath
        return self.config.Emotion_Fleet2Oath

    @property
    def speed(self) -> int:
        """返回每 6 分钟恢复的心情点数。"""
        speed = DIC_RECOVER[self.recover]
        if self.oath:
            speed += OATH_RECOVER
        return speed // 10

    @property
    def limit(self) -> int:
        """返回控制模式要求的最低心情点数。"""
        return DIC_LIMIT[self.control]

    @property
    def max(self) -> int:
        """返回当前恢复位置允许的最高心情点数。"""
        return DIC_RECOVER_MAX[self.recover]

    def update(self) -> None:
        recover_count = int(int(datetime.now().timestamp()) // 360 - int(self.record.timestamp()) // 360)
        recover_count = max(recover_count, 0)
        self.current = min(max(self.value, 0) + self.speed * recover_count, self.max)

    def get_recovered(self, expected_reduce: int = 0) -> datetime:
        """返回达到控制阈值的时间；已满足时可能返回过去时间。"""
        if self.control == "keep_exp_bonus" and self.recover == "not_in_dormitory":
            logger.critical(
                f'Fleet {self.fleet} Emotion Control="Keep Happy Bonus" and '
                f'Fleet {self.fleet} Recover Location="Docks" can not be used together, '
                "please check your emotion settings"
            )
            raise RequestHumanTakeover
        # 14-4 使用双倍书时预计消耗 32 点，无法保持大于 120；这里限为 29，避免任务无限延迟。
        if self.control == "keep_exp_bonus" and expected_reduce >= 29:
            expected_reduce = 29
            logger.info(f'Fleet {self.fleet} expected_reduce is limited to 29 when Emotion Control="Keep Happy Bonus"')

        recover_count = (self.limit + expected_reduce - self.current) // self.speed
        recovered = (int(datetime.now().timestamp()) // 360 + recover_count + 1) * 360
        return datetime.fromtimestamp(recovered, tz=UTC).astimezone().replace(tzinfo=None)


class Emotion:
    total_reduced = 0
    map_is_2x_book = False
    BUG_THRESHOLD_RANGE = (55, 105)

    def __init__(self, config: AzurLaneConfig) -> None:
        self.config = config
        self.fleet_1 = FleetEmotion(self.config, fleet=1)
        self.fleet_2 = FleetEmotion(self.config, fleet=2)
        self.fleets = [self.fleet_1, self.fleet_2]

    @property
    def is_calculate(self) -> bool:
        return "calculate" in self.config.Emotion_Mode

    @property
    def is_ignore(self) -> bool:
        return "ignore" in self.config.Emotion_Mode

    def update(self) -> None:
        """按记录时间更新心情值；其他心情操作前必须先调用。"""
        for fleet in self.fleets:
            fleet.update()

    def record(self) -> None:
        """把当前心情值写回配置记录。"""
        self.config.set_record(
            Emotion_Fleet1Value=self.fleet_1.current,
            Emotion_Fleet2Value=self.fleet_2.current,
        )

    def show(self) -> None:
        for fleet in self.fleets:
            logger.attr(f"Emotion fleet_{fleet.fleet}", fleet.value)

    @property
    def reduce_per_battle(self) -> int:
        if self.map_is_2x_book:
            return 4
        return 2

    @property
    def reduce_per_battle_before_entering(self) -> int:
        if self.map_is_2x_book or self.config.Campaign_Use2xBook:
            return 4
        return 2

    def check_reduce(self, battle: int) -> None:
        """进图前按预计战斗数检查心情；不足时延迟任务并抛出 ScriptEnd。"""
        if not self.is_calculate:
            return

        method = self.config.Fleet_FleetOrder

        if method == "fleet1_mob_fleet2_boss":
            battles = (battle - 1, 1)
        elif method == "fleet1_boss_fleet2_mob":
            battles = (1, battle - 1)
        elif method == "fleet1_all_fleet2_standby":
            battles = (battle, 0)
        elif method == "fleet1_standby_fleet2_all":
            battles = (0, battle)
        else:
            message = UNKNOWN_FLEET_ORDER_TEMPLATE.format(method=method)
            raise ScriptError(message)

        reductions = (
            battles[0] * self.reduce_per_battle_before_entering,
            battles[1] * self.reduce_per_battle_before_entering,
        )
        logger.info(f"Expect emotion reduce: {reductions}")

        self.update()
        self.record()
        self.show()
        recovered = max(
            fleet.get_recovered(reduction) for fleet, reduction in zip(self.fleets, reductions, strict=True)
        )
        if recovered > datetime.now():
            logger.info("Delay current task to prevent emotion control in the future")
            self.config.task_delay(target=recovered)
            raise ScriptEnd(EMOTION_CONTROL_DELAY_MESSAGE)

    def wait(self, fleet_index: int) -> None:
        """进入战斗前等待 1 或 2 号舰队恢复到控制阈值。"""
        self.update()
        self.record()
        self.show()
        fleet = self.fleets[fleet_index - 1]
        recovered = fleet.get_recovered(expected_reduce=self.reduce_per_battle)
        if recovered > datetime.now():
            logger.hr("Emotion wait")
            logger.info(f"Emotion of fleet {fleet_index} will recover to {fleet.limit} at {recovered}")

            while 1:
                if datetime.now() > recovered:
                    break

                logger.attr("Wait until", recovered)
                sleep(60)

    def reduce(self, fleet_index: int) -> None:
        """战斗加载完成后扣减 1 或 2 号舰队心情，并写回配置。"""
        logger.hr("Emotion reduce")
        self.update()

        fleet = self.fleets[fleet_index - 1]
        fleet.current -= self.reduce_per_battle
        self.total_reduced += self.reduce_per_battle
        self.record()
        self.show()

    @cached_property
    def bug_threshold(self) -> int:
        return random_normal_distribution_int(*self.BUG_THRESHOLD_RANGE, n=2)

    def bug_threshold_reset(self) -> None:
        """触发客户端心情同步 bug 后重置随机阈值。"""
        del self.__dict__["bug_threshold"]

    def triggered_bug(self) -> bool:
        """长时间运行后客户端心情会不同步；达到阈值时要求重启以刷新。"""
        logger.attr("Emotion_bug", f"{self.total_reduced}/{self.bug_threshold}")
        if self.total_reduced >= self.bug_threshold:
            logger.info(
                "Azur Lane client does not calculate emotion correctly, which is a bug. "
                "After a long run, we have to restart game client and let the client update it."
            )
            self.total_reduced = 0
            self.bug_threshold_reset()
            return True
        return False
