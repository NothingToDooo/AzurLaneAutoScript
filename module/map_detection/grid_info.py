from typing import TYPE_CHECKING

from module.base.utils import location2node

if TYPE_CHECKING:
    from module.map.map_grids import SelectedGrids

_PRIMARY_GRID_CODES = {
    "++": "is_land",
    "BO": "is_boss",
}
_SECONDARY_GRID_CODES = {
    "FL": "is_current_fleet",
    "Fc": "is_caught_by_siren",
    "Fl": "is_fleet",
    "ss": "is_submarine",
    "MY": "is_mystery",
    "AM": "is_ammo",
    "FR": "is_fortress",
    "MI": "is_missile_attack",
    "BE": "may_bouncing_enemy",
    "==": "is_cleared",
}


class GridInfo:
    """汇总普通地图单格的静态地图属性与动态识别状态。"""

    is_os = False

    # -- 表示海面。
    is_land = False  # ++
    is_spawn_point = False  # SP
    is_submarine_spawn_point = False  # __

    may_enemy = False  # ME
    may_boss = False  # MB
    may_mystery = False  # MM
    may_ammo = False  # MA
    may_siren = False  # MS
    may_ambush = False

    is_enemy = False  # 例如：0L、1M、2C、3T、3E。
    is_boss = False  # BO
    is_mystery = False  # MY
    is_ammo = False  # AM
    is_fleet = False  # FL
    is_current_fleet = False
    is_submarine = False  # ss
    is_siren = False  # SI
    is_portal = False
    portal_link = ()
    is_maze = False
    maze_round = (0, 1, 2)
    maze_nearby = None  # 类型为 SelectedGrids。

    enemy_scale = 0
    enemy_genre = None  # Light、Main、Carrier、Treasure 或 Enemy（未知类型）。

    is_cleared = False
    is_caught_by_siren = False
    is_carrier = False  # 神秘点刷出的航母。
    is_movable = False
    is_mechanism_trigger = False
    is_mechanism_block = False
    mechanism_trigger: SelectedGrids | None = None
    mechanism_block: SelectedGrids | None = None
    mechanism_wait = 2  # 等待机关解锁动画的秒数。
    is_fortress = False
    is_flare = False
    is_missile_attack = False
    may_bouncing_enemy = False
    cost = 9999
    cost_1 = 9999
    cost_2 = 9999
    connection = None
    weight = 1

    location = None

    def decode(self, text):
        text = text.upper()
        dic = {
            "++": "is_land",
            "SP": "is_spawn_point",
            "__": "is_submarine_spawn_point",
            "ME": "may_enemy",
            "MB": "may_boss",
            "MM": "may_mystery",
            "MA": "may_ammo",
            "MS": "may_siren",
        }
        valid = text in dic
        for k, v in dic.items():
            setattr(self, v, valid and bool(k == text))

        self.may_ambush = not (self.may_enemy or self.may_boss or self.may_mystery or self.may_mystery)

    def _encode_flag(self, flags):
        for key, value in flags.items():
            if getattr(self, value):
                return key
        return ""

    def _encode_siren(self):
        if not self.enemy_genre:
            return "SU"
        # enemy_genre 形如 "Siren_xxx"。
        name = self.enemy_genre[6:]
        if "_" in name:
            _, _, name = name.partition("_")
        name = name[:2].upper()
        if len(name) == 2:
            return name
        if len(name) == 1:
            return f"{name} "
        return "SU"

    def _encode_enemy(self):
        scale = self.enemy_scale or 0
        genre = self.enemy_genre[0].upper() if self.enemy_genre else "E"
        return f"{scale}{genre}"

    def encode(self):
        primary = self._encode_flag(_PRIMARY_GRID_CODES)
        if primary:
            return primary
        if self.is_siren:
            return self._encode_siren()
        if self.is_enemy:
            return self._encode_enemy()

        secondary = self._encode_flag(_SECONDARY_GRID_CODES)
        return secondary or "--"

    def __str__(self):
        return location2node(self.location)

    __repr__ = __str__

    def __hash__(self):
        return hash(self.location)

    def __eq__(self, other):
        return self.location == other.location

    @property
    def str(self):
        return self.encode()

    @property
    def is_sea(self):
        return not (self.is_land or self.is_enemy or self.is_siren or self.is_fortress or self.is_boss)

    @property
    def may_carrier(self):
        return self.is_sea and not self.may_enemy

    @property
    def is_accessible(self):
        return self.cost < 9999

    @property
    def is_accessible_1(self):
        return self.cost_1 < 9999

    @property
    def is_accessible_2(self):
        return self.cost_2 < 9999

    @property
    def is_nearby(self):
        return self.cost < 20

    def merge(self, info, mode="normal"):
        """按 init、normal、carrier 或 movable 模式合并识别结果。"""
        self._merge_submarine(info)

        result = self._merge_caught_by_siren(info)
        if result is None:
            result = self._merge_fleet(info, mode)
        if result is None:
            result = self._merge_boss(info)
        if result is None:
            result = self._merge_siren(info, mode)
        if result is None:
            result = self._merge_enemy(info, mode)
        if result is None:
            result = self._merge_mystery(info)
        if result is None:
            result = self._merge_ammo(info)
        if result is None:
            result = self._merge_missile_attack(info)

        return True if result is None else result

    def _merge_submarine(self, info):
        if info.is_submarine and self.is_submarine_spawn_point:
            self.is_submarine = True

    def _merge_caught_by_siren(self, info):
        if not info.is_caught_by_siren:
            return None
        if not self.is_sea:
            return False

        self.is_fleet = True
        self.is_caught_by_siren = True
        return None

    def _merge_fleet(self, info, mode):
        if not info.is_fleet:
            return None
        if not self.is_sea:
            return False

        self.is_fleet = True
        if info.is_current_fleet:
            self.is_current_fleet = True
        if mode == "init" and info.is_enemy:
            # 初始扫描允许同一格同时保留舰队和敌人，供潜艇舰队修正继续判断。
            return None
        return True

    def _merge_boss(self, info):
        if not info.is_boss:
            return None
        if not self.is_land and self.may_boss:
            self.is_boss = True
            return True
        return False

    def _merge_siren(self, info, mode):
        if not info.is_siren:
            return None
        if not self._can_merge_siren(mode):
            return False

        self.is_siren = True
        self.enemy_scale = 0
        self.enemy_genre = info.enemy_genre
        return True

    def _can_merge_siren(self, mode):
        return not self.is_land and (self.may_siren or mode == "movable" or self.is_movable)

    def _merge_enemy(self, info, mode):
        if not info.is_enemy:
            return None
        if self.is_fortress:
            # 堡垒可被普通敌人识别命中，但不改变格子状态。
            return True
        if self._can_merge_known_enemy(mode):
            self.is_enemy = True
            self._update_enemy_spawn_info(info)
            return True
        if self._can_merge_carrier_enemy(mode):
            self.is_enemy = True
            self.is_carrier = True
            self._replace_enemy_info(info)
            return True
        if self._can_merge_movable_enemy(mode):
            self.is_enemy = True
            self._replace_enemy_info(info)
            return True
        return False

    def _can_merge_known_enemy(self, mode):
        return not self.is_land and (self.may_enemy or self.is_carrier or mode == "decoy")

    def _can_merge_carrier_enemy(self, mode):
        return mode == "carrier" and not self.is_land and self.may_carrier

    def _can_merge_movable_enemy(self, mode):
        return not self.is_land and (mode == "movable" or self.is_movable)

    def _update_enemy_spawn_info(self, info):
        if info.enemy_scale and not self.enemy_scale:
            self.enemy_scale = info.enemy_scale
        if info.enemy_scale == 3 and self.enemy_scale == 2:
            # 允许大型敌人覆盖中型敌人。
            self.enemy_scale = info.enemy_scale
        self._update_enemy_genre(info)

    def _replace_enemy_info(self, info):
        if info.enemy_scale:
            self.enemy_scale = info.enemy_scale
        self._update_enemy_genre(info)

    def _update_enemy_genre(self, info):
        if info.enemy_genre and not (info.enemy_genre == "Enemy" and self.enemy_genre):
            self.enemy_genre = info.enemy_genre

    def _merge_mystery(self, info):
        if not info.is_mystery:
            return None
        if self.may_mystery:
            self.is_mystery = info.is_mystery
            return True
        return False

    def _merge_ammo(self, info):
        if not info.is_ammo:
            return None
        if self.may_ammo:
            self.is_ammo = info.is_ammo
            return True
        return False

    def _merge_missile_attack(self, info):
        if not info.is_missile_attack:
            return None
        if self.may_siren:
            self.is_siren = True
            return True
        if self.may_enemy:
            self.is_enemy = True
            return True

        # 允许误判，不返回失败。
        return True

    def wipe_out(self):
        """舰队踏入格子后清除该格的动态目标状态。"""
        self.is_enemy = False
        self.enemy_scale = 0
        self.enemy_genre = None
        self.is_mystery = False
        self.is_boss = False
        self.is_ammo = False
        self.is_siren = False
        self.is_fortress = False
        self.is_caught_by_siren = False
        self.is_carrier = False
        self.is_movable = False
        if self.is_mechanism_trigger:
            mechanism_trigger = self.mechanism_trigger
            mechanism_block = self.mechanism_block
            if mechanism_trigger is None or mechanism_block is None:
                msg = "机关格缺少关联格子状态"
                raise RuntimeError(msg)
            mechanism_trigger.set(is_mechanism_trigger=False)
            mechanism_block.set(is_mechanism_block=False)

    def reset(self):
        """进入地图后重置该格的临时状态。"""
        self.wipe_out()
        self.is_fleet = False
        self.is_current_fleet = False
        self.is_submarine = False
        self.is_cleared = False
        self.is_mechanism_trigger = False
        self.is_mechanism_block = False
        self.mechanism_trigger = None
        self.mechanism_block = None
        self.may_bouncing_enemy = False

    def covered_grid(self):
        """返回被大型对象覆盖格子的相对坐标列表。"""
        if self.is_current_fleet:
            return [(0, -1), (0, -2)]
        if self.is_fleet or self.is_siren or self.is_mystery:
            return [(0, -1)]

        return []

    def distance_to(self, other):
        """返回与另一格的曼哈顿距离。"""
        l1 = self.location
        l2 = other.location
        if l1 is None or l2 is None:
            msg = "Grid location is required to calculate distance"
            raise ValueError(msg)
        return abs(l1[0] - l2[0]) + abs(l1[1] - l2[1])
