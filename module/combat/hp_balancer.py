import numpy as np

from module.base.base import ModuleBase
from module.base.button import ButtonGrid
from module.base.decorator import Config
from module.base.utils import color_bar_percentage
from module.config.utils import to_list
from module.logger import logger

# Color that shows on HP bar.
COLOR_HP_GREEN = (156, 235, 57)
COLOR_HP_RED = (99, 44, 24)
SCOUT_POSITION = [(403, 421), (625, 369), (821, 326)]


class HPBalancer(ModuleBase):
    fleet_current_index = 1
    fleet_show_index = 1

    def __init__(self, *args, **kwargs):
        self._hp: dict[int, list[float]] = {}
        self._hp_has_ship: dict[int, list[bool]] = {}
        super().__init__(*args, **kwargs)

    @property
    def hp(self):
        """
        Returns:
            list[float]:
        """
        return self._hp[self.fleet_current_index]

    @hp.setter
    def hp(self, value):
        """
        Args:
            value (list[float]):
        """
        self._hp[self.fleet_current_index] = value

    @property
    def hp_has_ship(self):
        """
        Returns:
            list[bool]:
        """
        return self._hp_has_ship[self.fleet_current_index]

    @hp_has_ship.setter
    def hp_has_ship(self, value):
        """
        Args:
            value (list[float]):
        """
        self._hp_has_ship[self.fleet_current_index] = value

    def _calculate_hp(self, area):
        """Calculate hp according to color.

        Args:
            area (tuple):

        Returns:
            float: HP.
        """
        return max(
            color_bar_percentage(self.device.image, area=area, prev_color=COLOR_HP_RED),
            color_bar_percentage(self.device.image, area=area, prev_color=COLOR_HP_GREEN),
        )

    def _hp_grid(self):
        return ButtonGrid(origin=(35, 206), delta=(0, 100), button_shape=(66, 4), grid_shape=(1, 6))

    def hp_get(self):
        """Get current HP from screenshot.

        Returns:
            list: HP(float) of 6 ship.

        Logs:
            [HP]  98% ____ ____  98%  98%  98%
        """
        # Chinese comma
        weight = self.config.HpControl_HpBalanceWeight
        if "，" in self.config.HpControl_HpBalanceWeight:
            weight = self.config.HpControl_HpBalanceWeight.replace("，", ",")
            logger.info(f"HpControl_HpBalanceWeight {self.config.HpControl_HpBalanceWeight} is revised to {weight}")
            self.config.HpControl_HpBalanceWeight = weight

        hp = [self._calculate_hp(button.area) for button in self._hp_grid().buttons]
        weight = to_list(weight)
        scout = np.array(hp[3:]) * np.array(weight) / np.max(weight)

        self.hp = hp[:3] + scout.tolist()
        if self.fleet_current_index not in self._hp_has_ship:
            self.hp_has_ship = [bool(hp > 0.3) for hp in self.hp]

        logger.attr(
            "HP",
            " ".join(
                [
                    str(int(data * 100)).rjust(3) + "%" if use else "____"
                    for data, use in zip(hp, self.hp_has_ship, strict=True)
                ]
            ),
        )
        if np.sum(np.abs(np.diff(weight))) > 0:
            logger.attr("HP_weight", " ".join([str(int(data * 100)).rjust(3) + "%" for data in self.hp]))

        return self.hp

    def hp_reset(self):
        """
        Call this method after enter map.
        """
        self._hp = {}
        self._hp_has_ship = {}

    def _scout_position_change(self, p1, p2):
        """Exchange KAN-SEN's position.
        It need to move up and down a little, even though it moves to the right location.

        Args:
            p1 (int): Origin position [0, 2].
            p2 (int): Target position [0, 2].
        """
        logger.info(f"scout_position_change ({p1}, {p2})")
        self.device.drag(p1=SCOUT_POSITION[p1], p2=SCOUT_POSITION[p2])

    def _expected_scout_order(self, hp):
        count = np.count_nonzero(hp)
        threshold = self.config.HpControl_HpBalanceThreshold

        if count == 3:
            descending = np.sort(hp)[::-1]
            sort = np.argsort(hp)[::-1]
            if descending[0] - descending[2] <= threshold:
                # 90% 80% 70%
                order = [0, 1, 2]
            elif descending[1] - descending[2] <= threshold / 2:
                # 95% 80% 70%
                order = [sort[0], 1, 2]
                order[sort[0]] = 0
            elif descending[0] - descending[1] <= threshold / 2:
                # 90% 80% 65%
                order = [0, sort[2], 2]
                order[sort[2]] = 1
            else:
                # 95% 80% 65%
                order = [sort[0], sort[2], sort[1]]
        elif count == 2:
            order = [1, 0, 2] if hp[1] - hp[0] > threshold else [0, 1, 2]
        elif count == 1:
            # 80% 0% 0%
            order = [0, 1, 2]
        else:
            logger.warning(f"HP invalid: {hp}")
            order = [0, 1, 2]

        return order

    @Config.when(DEVICE_CONTROL_METHOD="minitouch")
    def _gen_exchange_step(self, target):
        """
        minitouch 拖动更接近人的手势。

        把第一艘船拖到第三艘时，[0, 1, 2] 会变成 [1, 2, 0]。

        Args:
            target: 目标顺序，例如 [2, 0, 1]。
        """
        diff = np.array(target) - np.array((0, 1, 2))
        count = np.count_nonzero(diff)
        if count == 3:
            if np.argsort(target)[0] == 1:
                # [0, 1, 2] -> [2, 0, 1]
                yield (2, 0)
            else:
                # [0, 1, 2] -> [1, 2, 0]
                yield (0, 2)
        elif count == 2:
            if np.argsort(target)[0] == 2:
                # 从原始顺序变为 1、2、0，再变为 2、1、0。
                yield (0, 2)
                yield (1, 0)
            else:
                # 两个错位时直接交换错位位置，可覆盖 0、2、1 和 1、0、2。
                yield tuple(np.nonzero(diff)[0])
        elif count == 0:
            # 目标顺序与原始顺序相同，不需要交换。
            pass

    @Config.when(DEVICE_CONTROL_METHOD=None)
    def _gen_exchange_step(self, target):
        """
        Args:
            target (list[int]): Such as [2, 0, 1].
        """
        diff = np.array(target) - np.array((0, 1, 2))
        count = np.count_nonzero(diff)
        if count == 3:
            yield (2, 0)
            if np.argsort(target)[0] == 1:
                # 从原始顺序变为 2、1、0，再变为 2、0、1。
                yield (2, 1)
            else:
                # 从原始顺序变为 2、1、0，再变为 1、2、0。
                yield (1, 0)
        elif count == 2:
            # 两个错位时直接交换错位位置，可覆盖 0、2、1、1、0、2 和 2、1、0。
            yield tuple(np.nonzero(diff)[0])
        elif count == 0:
            # 目标顺序与原始顺序相同，不需要交换。
            pass

    def hp_balance(self):
        if self.config.Campaign_UseFleetLock:
            return False

        target = self._expected_scout_order(self.hp[3:])
        for step in self._gen_exchange_step(target):
            self._scout_position_change(*step)
            self.device.sleep(0.5)

        return True

    def hp_retreat_triggered(self):
        if self.config.HpControl_UseLowHpRetreat:
            hp = np.array(self.hp)[self.hp_has_ship]
            if np.any(hp < self.config.HpControl_LowHpRetreatThreshold):
                logger.info("Low HP retreat triggered.")
                return True

        return False
