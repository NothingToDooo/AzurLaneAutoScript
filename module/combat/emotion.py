from datetime import UTC, datetime
from time import sleep

import numpy as np

from module.base.decorator import cached_property
from module.base.utils import random_normal_distribution_int
from module.exception import RequestHumanTakeover, ScriptEnd, ScriptError
from module.logger import logger

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
    def __init__(self, config, fleet):
        self.config = config
        self.fleet = fleet
        self.current = 0

    @property
    def value(self):
        """返回 0～150 的当前心情值。"""
        return getattr(self.config, f"Emotion_Fleet{self.fleet}Value")

    @property
    def value_name(self):
        return f"Emotion_Fleet{self.fleet}Value"

    @property
    def record(self):
        """返回上次记录心情值的时间。"""
        return getattr(self.config, f"Emotion_Fleet{self.fleet}Record")

    @property
    def recover(self):
        """返回 not_in_dormitory、dormitory_floor_1 或 dormitory_floor_2。"""
        return getattr(self.config, f"Emotion_Fleet{self.fleet}Recover")

    @property
    def control(self):
        """返回 keep_exp_bonus、prevent_green_face、prevent_yellow_face 或 prevent_red_face。"""
        return getattr(self.config, f"Emotion_Fleet{self.fleet}Control")

    @property
    def oath(self):
        return getattr(self.config, f"Emotion_Fleet{self.fleet}Oath")

    @property
    def speed(self):
        """返回每 6 分钟恢复的心情点数。"""
        speed = DIC_RECOVER[self.recover]
        if self.oath:
            speed += OATH_RECOVER
        return speed // 10

    @property
    def limit(self):
        """返回控制模式要求的最低心情点数。"""
        return DIC_LIMIT[self.control]

    @property
    def max(self):
        """返回当前恢复位置允许的最高心情点数。"""
        return DIC_RECOVER_MAX[self.recover]

    def update(self):
        recover_count = int(int(datetime.now().timestamp()) // 360 - int(self.record.timestamp()) // 360)
        recover_count = max(recover_count, 0)
        self.current = min(max(self.value, 0) + self.speed * recover_count, self.max)

    def get_recovered(self, expected_reduce=0):
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

    def __init__(self, config):
        self.config = config
        self.fleet_1 = FleetEmotion(self.config, fleet=1)
        self.fleet_2 = FleetEmotion(self.config, fleet=2)
        self.fleets = [self.fleet_1, self.fleet_2]

    @property
    def is_calculate(self):
        return "calculate" in self.config.Emotion_Mode

    @property
    def is_ignore(self):
        return "ignore" in self.config.Emotion_Mode

    def update(self):
        """按记录时间更新心情值；其他心情操作前必须先调用。"""
        for fleet in self.fleets:
            fleet.update()

    def record(self):
        """把当前心情值写回配置记录。"""
        value = {}
        for fleet in self.fleets:
            value[fleet.value_name] = fleet.current

        self.config.set_record(**value)

    def show(self):
        for fleet in self.fleets:
            logger.attr(f"Emotion fleet_{fleet.fleet}", fleet.value)

    @property
    def reduce_per_battle(self):
        if self.map_is_2x_book:
            return 4
        return 2

    @property
    def reduce_per_battle_before_entering(self):
        if self.map_is_2x_book or self.config.Campaign_Use2xBook:
            return 4
        return 2

    def check_reduce(self, battle):
        """进图前按预计战斗数检查心情；不足时延迟任务并抛出 ScriptEnd。"""
        if not self.is_calculate:
            return

        method = self.config.Fleet_FleetOrder

        if method == "fleet1_mob_fleet2_boss":
            battle = (battle - 1, 1)
        elif method == "fleet1_boss_fleet2_mob":
            battle = (1, battle - 1)
        elif method == "fleet1_all_fleet2_standby":
            battle = (battle, 0)
        elif method == "fleet1_standby_fleet2_all":
            battle = (0, battle)
        else:
            message = UNKNOWN_FLEET_ORDER_TEMPLATE.format(method=method)
            raise ScriptError(message)

        battle = tuple(np.array(battle) * self.reduce_per_battle_before_entering)
        logger.info(f"Expect emotion reduce: {battle}")

        self.update()
        self.record()
        self.show()
        recovered = max(f.get_recovered(b) for f, b in zip(self.fleets, battle, strict=True))
        if recovered > datetime.now():
            logger.info("Delay current task to prevent emotion control in the future")
            self.config.task_delay(target=recovered)
            raise ScriptEnd(EMOTION_CONTROL_DELAY_MESSAGE)

    def wait(self, fleet_index):
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

    def reduce(self, fleet_index):
        """战斗加载完成后扣减 1 或 2 号舰队心情，并写回配置。"""
        logger.hr("Emotion reduce")
        self.update()

        fleet = self.fleets[fleet_index - 1]
        fleet.current -= self.reduce_per_battle
        self.total_reduced += self.reduce_per_battle
        self.record()
        self.show()

    @cached_property
    def bug_threshold(self):
        return random_normal_distribution_int(55, 105, n=2)

    def bug_threshold_reset(self):
        """触发客户端心情同步 bug 后重置随机阈值。"""
        del self.__dict__["bug_threshold"]

    def triggered_bug(self):
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
