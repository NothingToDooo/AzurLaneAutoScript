from typing import cast

from module.base.utils import location2node
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger
from module.map.map_base import CampaignMap

from .campaign_base import CampaignBase
from .config_base import ConfigBase

INVALID_SP_MOVEMENT_MESSAGE = "Invalid movement"
FLEET_MOVE_MISMATCH_TEMPLATE = "Fleet{fleet_index} fail to move {src} -> {dst}, now on {fleet_location}"

MAP = CampaignMap("SP")
MAP.shape = "J8"

MAP.camera_data_spawn_point = ["E6"]
MAP.map_data = """
    ++ ++ ++ ME ME ME ME ++ ++ ++
    ++ ME ME ME ME ME ME ME ME ++
    ME ME ME ME ++ ++ ME ME ME ME
    ME ME ME ME ++ ++ ME ME ME ME
    ME ME ME ME MB MB ME ME ME ME
    ME ++ ME ME __ __ ME ME ++ ME
    ME ++ ME ME ME ME ME ME ++ ME
    ME ME ME ME SP SP ME ME ME ME
"""
MAP.weight_data = """
    50 50 50 50 50 50 50 50 50 50
    50 50 50 50 50 50 50 50 50 50
    50 50 50 50 50 50 50 50 50 50
    50 50 50 50 50 50 50 50 50 50
    50 50 50 50 50 50 50 50 50 50
    50 50 50 50 50 50 50 50 50 50
    50 50 50 50 50 50 50 50 50 50
    50 50 50 50 50 50 50 50 50 50
"""
MAP.spawn_data = [
    {"battle": 0, "siren": 4},
    {"battle": 1},
    {"battle": 2},
    {"battle": 3},
    {"battle": 4, "enemy": 14},
    {"battle": 5},
    {"battle": 6},
    {"battle": 7, "boss": 1},
]
(
    A1,
    B1,
    C1,
    D1,
    E1,
    F1,
    G1,
    H1,
    I1,
    J1,
    A2,
    B2,
    C2,
    D2,
    E2,
    F2,
    G2,
    H2,
    I2,
    J2,
    A3,
    B3,
    C3,
    D3,
    E3,
    F3,
    G3,
    H3,
    I3,
    J3,
    A4,
    B4,
    C4,
    D4,
    E4,
    F4,
    G4,
    H4,
    I4,
    J4,
    A5,
    B5,
    C5,
    D5,
    E5,
    F5,
    G5,
    H5,
    I5,
    J5,
    A6,
    B6,
    C6,
    D6,
    E6,
    F6,
    G6,
    H6,
    I6,
    J6,
    A7,
    B7,
    C7,
    D7,
    E7,
    F7,
    G7,
    H7,
    I7,
    J7,
    A8,
    B8,
    C8,
    D8,
    E8,
    F8,
    G8,
    H8,
    I8,
    J8,
) = MAP.flatten()


class Config(ConfigBase):
    # ===== Start of generated config =====
    MAP_HAS_SIREN = False
    MAP_HAS_MOVABLE_ENEMY = False
    MAP_HAS_MOVABLE_NORMAL_ENEMY = False
    MAP_HAS_MAP_STORY = True
    MAP_HAS_FLEET_STEP = True
    MAP_HAS_AMBUSH = False
    MAP_HAS_MYSTERY = False
    STAR_REQUIRE_1 = 0
    STAR_REQUIRE_2 = 0
    STAR_REQUIRE_3 = 0
    # ===== End of generated config =====

    MAP_IS_ONE_TIME_STAGE = True


# 动态寻路不稳定，因此将全图按敌方节点处理并执行预设路线。
actions = {
    4: [
        ["1_R_2_", "1_L_2_", "1_R_2_B"],
        ["2_U_2_", "1_S_0_B"],
        ["1_L_1_B"],
        ["1_U_1_B"],
        ["1_U_2_", "1_R_1_B"],
        ["1_L_2_", "1_L_1_B"],
        ["1_R_2_", "1_R_1_B"],
    ],
    5: [
        ["1_L_2_", "1_R_2_", "1_L_2_B"],
        ["2_U_2_", "1_S_0_B"],
        ["1_RU_2_", "1_RU_2_B"],
        ["1_RD_2_B"],
        ["1_U_2_B"],
        ["1_L_2_", "1_L_1_B"],
        ["1_R_2_", "1_L_2_B"],
    ],
}


def parse_move(movement: str, step: int):
    if step % len(movement) != 0:
        raise ScriptError(INVALID_SP_MOVEMENT_MESSAGE)

    movement *= int(step / len(movement))
    dx, dy = 0, 0
    for direction in movement:
        dx += 1 if direction == "R" else 0
        dx -= 1 if direction == "L" else 0
        dy += 1 if direction == "D" else 0
        dy -= 1 if direction == "U" else 0
    return dx, dy


class Campaign(CampaignBase):
    MAP = MAP
    ENEMY_FILTER = "1L > 1M > 1E > 1C > 2L > 2M > 2E > 2C > 3L > 3M > 3E > 3C"

    def __init__(self, *args, **kwargs):
        self.siren_list = [C7, D6, G6, H7]
        self.patched = False
        self.action = []
        super().__init__(*args, **kwargs)

    def execute_actions(self, step):
        for action in self.action[step]:
            fleet_index, movement, step, battle = action.split("_")
            src = getattr(self, f"fleet_{fleet_index}_location")
            fleet = getattr(self, f"fleet_{fleet_index}")
            step = int(step)
            dx, dy = parse_move(movement, step)
            dst = (src[0] + dx, src[1] + dy)

            logger.info(f"{fleet_index}{movement}({step}): {src} -> {dst}")

            for _ in range(3):
                if battle:
                    fleet.clear_chosen_enemy(location2node(dst))
                else:
                    fleet.goto(location2node(dst))

                fleet_location = getattr(self, f"fleet_{fleet_index}_location")
                if fleet_location not in [src, dst]:
                    message = FLEET_MOVE_MISMATCH_TEMPLATE.format(
                        fleet_index=fleet_index,
                        src=src,
                        dst=dst,
                        fleet_location=fleet_location,
                    )
                    raise RequestHumanTakeover(message)
                if fleet_location == dst:
                    break
                logger.warning(f"Fleet{fleet_index} did not move, retry")

        return True

    def battle_0(self) -> bool:
        if not self.patched:
            for battle_count in range(1, 7):
                setattr(self, f"battle_{battle_count}", self.battle_0)
            self.patched = True

        if self.map_is_clear_mode:
            if self.siren_list:
                self.fleet_1.clear_chosen_enemy(self.siren_list.pop())
                return True
            if self.clear_filter_enemy(self.ENEMY_FILTER, preserve=0):
                return True
            return self.battle_default()

        if not self.action:
            fleet_1_location = cast("tuple[int, int]", self.fleet_1_location)
            fleet_1_x = fleet_1_location[0]
            self.action = actions[fleet_1_x]
        return self.execute_actions(self.battle_count)

    def battle_7(self) -> bool:
        return self.fleet_boss.clear_boss()
