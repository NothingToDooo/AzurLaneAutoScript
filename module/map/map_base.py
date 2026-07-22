import copy
from typing import TYPE_CHECKING, cast

import numpy as np

from module.base.utils import location2node
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.map.map_layout import CampaignMapLayout, parse_grid_text
from module.map.map_pathfinder import CampaignPathfinder
from module.map.map_topology import CampaignMapTopology
from module.map.utils import location_ensure
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from module.base.type_alias import Point
    from module.map.type_alias import GridLocation, GridMode
    from module.map_detection.view import View


type SpawnRule = dict[str, int]
type FortressItem = GridInfo | str
type FortressGroup = FortressItem | tuple[FortressItem, ...] | list[FortressItem] | SelectedGrids[GridInfo]


class CampaignMap:
    def __init__(self, name: str | None = None, *, layout: CampaignMapLayout | None = None) -> None:
        self.name = name
        self.layout = CampaignMapLayout() if layout is None else layout
        self.topology = CampaignMapTopology(self.layout.grids)
        self.pathfinder = CampaignPathfinder(self.layout.grids, self.topology)
        self._map_data = ""
        self._map_data_loop = ""
        self._land_based_data: list[tuple[str, str]] = []
        self._maze_data: list[tuple[str, ...]] = []
        self.maze_round = 9
        self._fortress_data = (SelectedGrids[GridInfo]([]), SelectedGrids[GridInfo]([]))
        self._bouncing_enemy_data: list[SelectedGrids[GridInfo]] = []
        self._spawn_data: list[SpawnRule] = []
        self._spawn_data_stack: list[dict[str, int]] = []
        self._spawn_data_loop: list[SpawnRule] = []
        self._spawn_data_use_loop = False
        self._ignore_prediction: list[tuple[GridLocation, dict[str, object]]] = []
        self.in_map_swipe_preset_data: GridLocation | None = None
        self.poor_map_data = False

    @staticmethod
    def _require_grid_location(grid: GridInfo) -> GridLocation:
        if grid.location is None:
            msg = "地图格子缺少位置"
            raise RuntimeError(msg)
        return grid.location

    def __iter__(self) -> Iterator[GridInfo]:
        return iter(self.layout)

    def __getitem__(self, item: Point) -> GridInfo:
        return self.layout[item]

    def __contains__(self, item: object) -> bool:
        return item in self.layout

    @property
    def map_data(self) -> str:
        return self._map_data

    @map_data.setter
    def map_data(self, text: str) -> None:
        self._map_data = text
        self._load_map_data(text)

    @property
    def map_data_loop(self) -> str:
        return self._map_data_loop

    @map_data_loop.setter
    def map_data_loop(self, text: str) -> None:
        self._map_data_loop = text

    def load_map_data(self, *, use_loop: bool = False) -> None:
        """use_loop 表示清理模式；旧 Alas 称 fast forward，Lua 文件称 loop。"""
        has_loop = bool(len(self.map_data_loop))
        logger.info(f"Load map_data, has_loop={has_loop}, use_loop={use_loop}")
        if has_loop and use_loop:
            self._load_map_data(self.map_data_loop)
        else:
            self._load_map_data(self.map_data)

    def _load_map_data(self, text: str) -> None:
        if not self.layout.grids:
            grids = np.array([location for location, _ in parse_grid_text(text)])
            self.layout.initialize(location2node(tuple(np.max(grids, axis=0))))

        for location, data in parse_grid_text(text):
            self.layout[location].decode(data)

    @property
    def land_based_data(self) -> list[tuple[str, str]]:
        return self._land_based_data

    @land_based_data.setter
    def land_based_data(self, data: Sequence[Sequence[str]]) -> None:
        self._land_based_data = [(entry[0], entry[1]) for entry in data]

    def _load_land_base_data(self, data: Sequence[Sequence[str]]) -> None:
        """在 map_data 之后加载陆基单位；data 形如 [['H7', 'up'], ['D5', 'left']]。"""
        rotation_dict = {
            "up": [(0, -1), (0, -2), (0, -3)],
            "down": [(0, 1), (0, 2), (0, 3)],
            "left": [(-1, 0), (-2, 0), (-3, 0)],
            "right": [(1, 0), (2, 0), (3, 0)],
        }
        self._land_based_data = [(entry[0], entry[1]) for entry in data]
        for land_based in data:
            grid, rotation = land_based
            grid = self.layout[location_ensure(grid)]
            trigger = self.layout.covered_by(grid, offsets=[(0, -1), (0, 1), (-1, 0), (1, 0)]).select(is_land=False)
            block = self.layout.covered_by(grid, offsets=rotation_dict[rotation]).select(is_land=False)
            trigger.set(is_mechanism_trigger=True, mechanism_trigger=trigger, mechanism_block=block)
            block.set(is_mechanism_block=True)

    @property
    def maze_data(self) -> list[tuple[str, ...]]:
        return self._maze_data

    @maze_data.setter
    def maze_data(self, data: Sequence[Sequence[str]]) -> None:
        self._maze_data = [tuple(group) for group in data]

    def _load_maze_data(self, data: Sequence[Sequence[str]]) -> None:
        """data 由迷宫格组构成，例如 [('D5', 'I4', 'J6'), ('C4', 'E4', 'D8')]。"""
        self._maze_data = [tuple(group) for group in data]
        self.maze_round = len(data) * 3
        for index, raw_maze in enumerate(data):
            maze = self.layout.to_selected(raw_maze)
            maze.set(is_maze=True, maze_round=tuple(range(index * 3, index * 3 + 3)))
            for grid in maze:
                self.pathfinder.project(grid, has_ambush=False)
                grid.maze_nearby = self.layout.select(cost=1).add(self.layout.select(cost=2)).select(is_land=False)

    @property
    def fortress_data(self) -> tuple[SelectedGrids[GridInfo], SelectedGrids[GridInfo]]:
        return self._fortress_data

    @fortress_data.setter
    def fortress_data(self, data: Sequence[FortressGroup]) -> None:
        enemy, block = data
        enemy = self._to_fortress_group(enemy)
        block = self._to_fortress_group(block)
        self._fortress_data = (enemy, block)

    def _to_fortress_group(self, group: FortressGroup) -> SelectedGrids[GridInfo]:
        if isinstance(group, (GridInfo, str)):
            return self.layout.to_selected((group,))
        if isinstance(group, SelectedGrids):
            return cast("SelectedGrids[GridInfo]", group)
        return self.layout.to_selected(group)

    def _load_fortress_data(self, data: tuple[SelectedGrids[GridInfo], SelectedGrids[GridInfo]]) -> None:
        """data 为 [要塞敌人, 阻挡格]，两项均可为格子名或格子名序列。"""
        self._fortress_data = data
        enemy, block = data
        enemy.set(is_fortress=True)
        block.set(is_mechanism_block=True)

    @property
    def bouncing_enemy_data(self) -> list[SelectedGrids[GridInfo]]:
        return self._bouncing_enemy_data

    @bouncing_enemy_data.setter
    def bouncing_enemy_data(self, data: Sequence[Iterable[GridInfo | str | Point]]) -> None:
        self._bouncing_enemy_data = [self.layout.to_selected(route) for route in data]

    @staticmethod
    def _load_bouncing_enemy_data(data: Sequence[SelectedGrids[GridInfo]]) -> None:
        """data 为弹跳敌人的路线列表，例如 [(C2, C3, C4)]。"""
        for route in data:
            route.set(may_bouncing_enemy=True)

    def load_mechanism(
        self,
        *,
        land_based: bool = False,
        maze: bool = False,
        fortress: bool = False,
        bouncing_enemy: bool = False,
    ) -> None:
        logger.info(
            f"Load mechanism, land_base={land_based}, maze={maze}, fortress={fortress}, bouncing_enemy={bouncing_enemy}"
        )
        if land_based:
            self._load_land_base_data(self.land_based_data)
        if maze:
            self._load_maze_data(self.maze_data)
        if fortress:
            self._load_fortress_data(self._fortress_data)
        if bouncing_enemy:
            self._load_bouncing_enemy_data(self._bouncing_enemy_data)

    def fixup_submarine_fleet(self) -> None:
        # 潜艇和下方格共享弹药图标，下方格可能被误识别为舰队。
        for grid in self.layout.select(is_fleet=True):
            if grid.is_spawn_point:
                continue
            for upper in self.layout.covered_by(grid, offsets=[(0, -1)]):
                if upper.is_submarine_spawn_point:
                    logger.info(f"Fixup submarine spawn point, fleet={grid} -> submarine={upper}")
                    grid.is_fleet = False
                    grid.is_current_fleet = False
                    upper.is_submarine = True
        # 初始化时格子不能同时为敌人和舰队；这种冲突也可能来自上方潜艇。
        for grid in self.layout.select(is_enemy=True, is_fleet=True):
            grid.is_fleet = False
            grid.is_current_fleet = False

    def show(self) -> None:
        logger.info("   " + " ".join([" " + chr(x + 64 + 1) for x in range(self.layout.shape[0] + 1)]))
        for y in range(self.layout.shape[1] + 1):
            text = (
                str(y + 1).rjust(2)
                + " "
                + " ".join([self[(x, y)].str if (x, y) in self else "  " for x in range(self.layout.shape[0] + 1)])
            )
            logger.info(text)

    def update(self, grids: View, camera: GridLocation, mode: GridMode = "normal") -> bool:
        """mode 接受 init、normal、carrier 或 movable。"""
        offset = np.array(camera) - np.array(grids.center_loca)

        failed_count = 0
        for grid in grids.grids.values():
            grid_location = self._require_grid_location(grid)
            raw_location = offset + grid_location
            loca = (int(raw_location[0]), int(raw_location[1]))
            if loca in self.layout:
                if self.ignore_prediction_match(globe=loca, local=grid):
                    continue
                if not copy.copy(self.layout[loca]).merge(grid, mode=mode):
                    logger.warning(f"Wrong Prediction. {self.layout[loca]} = '{grid.str}'")
                    failed_count += 1

        if failed_count < 2:
            for grid in grids.grids.values():
                grid_location = self._require_grid_location(grid)
                raw_location = offset + grid_location
                loca = (int(raw_location[0]), int(raw_location[1]))
                if loca in self.layout:
                    if self.ignore_prediction_match(globe=loca, local=grid):
                        continue
                    self.layout[loca].merge(grid, mode=mode)
            if mode == "init":
                self.fixup_submarine_fleet()
            return True
        logger.warning("Too many wrong prediction")
        return False

    def reset(self) -> None:
        for grid in self:
            grid.reset()

    def reset_fleet(self) -> None:
        for grid in self:
            grid.is_current_fleet = False

    @property
    def spawn_data(self) -> list[SpawnRule]:
        """返回当前模式的刷新规则字典列表。"""
        if self._spawn_data_use_loop:
            return self._spawn_data_loop
        return self._spawn_data

    @spawn_data.setter
    def spawn_data(self, data_list: Sequence[Mapping[str, int]]) -> None:
        self._spawn_data = [dict(rule) for rule in data_list]

    @property
    def spawn_data_loop(self) -> list[SpawnRule]:
        return self._spawn_data_loop

    @spawn_data_loop.setter
    def spawn_data_loop(self, data_list: Sequence[Mapping[str, int]]) -> None:
        self._spawn_data_loop = [dict(rule) for rule in data_list]

    @property
    def spawn_data_stack(self) -> list[dict[str, int]]:
        return self._spawn_data_stack

    def load_spawn_data(self, *, use_loop: bool = False) -> None:
        has_loop = bool(len(self._spawn_data_loop))
        logger.info(f"Load spawn_data, has_loop={has_loop}, use_loop={use_loop}")
        if has_loop and use_loop:
            self._spawn_data_use_loop = True
            self._load_spawn_data(self._spawn_data_loop)
        else:
            self._spawn_data_use_loop = False
            self._load_spawn_data(self._spawn_data)

    def _load_spawn_data(self, data_list: Sequence[Mapping[str, int]]) -> None:
        spawn = {"battle": 0, "enemy": 0, "mystery": 0, "siren": 0, "boss": 0}
        for data in data_list:
            spawn["battle"] = data["battle"]
            spawn["enemy"] += data.get("enemy", 0)
            spawn["mystery"] += data.get("mystery", 0)
            spawn["siren"] += data.get("siren", 0)
            spawn["boss"] += data.get("boss", 0)
            self._spawn_data_stack.append(spawn.copy())

    def ignore_prediction(self, globe: GridInfo | str | Point, **local: object) -> None:
        """忽略 globe 格上匹配 local 属性的预测；例如 D5 上的 1E 敌人。"""
        globe = location_ensure(globe)
        self._ignore_prediction.append((globe, local))

    def ignore_prediction_match(self, globe: GridLocation, local: GridInfo) -> bool:
        for wrong_globe, wrong_local in self._ignore_prediction:
            if wrong_globe == globe and all(getattr(local, k) == v for k, v in wrong_local.items()):
                return True

        return False

    @property
    def is_map_data_poor(self) -> bool:
        if (
            not self.layout.select(may_enemy=True)
            or not self.layout.select(may_boss=True)
            or not self.layout.select(is_spawn_point=True)
        ):
            return False
        return bool(self.spawn_data)
