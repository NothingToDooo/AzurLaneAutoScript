import copy
from itertools import pairwise
from typing import TYPE_CHECKING, cast

import numpy as np

from module.base.utils import location2node, node2location
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.map.utils import camera_2d, location_ensure
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence, ValuesView

    from module.base.type_alias import Point
    from module.map.type_alias import GridLocation, GridMode
    from module.map_detection.view import View


type SpawnRule = dict[str, int]
type FortressItem = GridInfo | str
type FortressGroup = FortressItem | tuple[FortressItem, ...] | list[FortressItem] | SelectedGrids[GridInfo]


class CampaignMap:  # ruff:ignore[too-many-public-methods] - 待拆分布局、寻路与缺口推断。
    def __init__(self, name: str | None = None) -> None:
        self.name = name
        self.grid_class: type[GridInfo] = GridInfo
        self.grids: dict[GridLocation, GridInfo] = {}
        self._shape: GridLocation = (0, 0)
        self._map_data = ""
        self._map_data_loop = ""
        self._weight_data = ""
        self._wall_data = ""
        self._portal_data: list[tuple[GridLocation, GridLocation]] = []
        self._land_based_data: list[tuple[str, str]] = []
        self._maze_data: list[tuple[str, ...]] = []
        self.maze_round = 9
        self._fortress_data = (SelectedGrids[GridInfo]([]), SelectedGrids[GridInfo]([]))
        self._bouncing_enemy_data: list[SelectedGrids[GridInfo]] = []
        self._spawn_data: list[SpawnRule] = []
        self._spawn_data_stack: list[dict[str, int]] = []
        self._spawn_data_loop: list[SpawnRule] = []
        self._spawn_data_use_loop = False
        self._camera_data = SelectedGrids[GridInfo]([])
        self._camera_data_spawn_point = SelectedGrids[GridInfo]([])
        self._map_covered = SelectedGrids[GridInfo]([])
        self._ignore_prediction: list[tuple[GridLocation, dict[str, object]]] = []
        self.in_map_swipe_preset_data: GridLocation | None = None
        self.poor_map_data = False
        self.camera_sight = (-3, -1, 3, 2)
        self.grid_connection: dict[GridLocation, set[GridLocation]] = {}

    @staticmethod
    def _require_grid_location(grid: GridInfo) -> GridLocation:
        if grid.location is None:
            msg = "地图格子缺少位置"
            raise RuntimeError(msg)
        return grid.location

    def __iter__(self) -> Iterator[GridInfo]:
        return iter(self.grids.values())

    def __getitem__(self, item: Point) -> GridInfo:
        location = location_ensure(item)
        return self.grids[location]

    def __contains__(self, item: object) -> bool:
        if isinstance(item, np.ndarray):
            if item.shape != (2,):
                return False
            values = cast("list[int]", np.asarray(item, dtype=int).tolist())
            return (values[0], values[1]) in self.grids
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            return False
        x, y = item
        if not isinstance(x, (int, np.integer)) or not isinstance(y, (int, np.integer)):
            return False
        return (int(x), int(y)) in self.grids

    @staticmethod
    def _parse_text(text: str) -> Iterator[tuple[GridLocation, str]]:
        text = text.strip()
        for y, raw_row in enumerate(text.split("\n")):
            row = raw_row.strip()
            for x, data in enumerate(row.split(" ")):
                yield (x, y), data

    @property
    def shape(self) -> GridLocation:
        return self._shape

    @shape.setter
    def shape(self, scale: str) -> None:
        self._shape = node2location(scale.upper())
        for y in range(self._shape[1] + 1):
            for x in range(self._shape[0] + 1):
                grid = self.grid_class()
                grid.location = (x, y)
                self.grids[(x, y)] = grid

        # camera_data 可自动生成，但手动设置通常更稳定。
        self.camera_data = [location2node(loca) for loca in camera_2d((0, 0, *self._shape), sight=self.camera_sight)]
        self.camera_data_spawn_point = []
        for grid in self:
            grid.weight = 10.0

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
        if not len(self.grids.keys()):
            grids = np.array([loca for loca, _ in self._parse_text(text)])
            self.shape = location2node(tuple(np.max(grids, axis=0)))

        for loca, data in self._parse_text(text):
            self.grids[loca].decode(data)

    @property
    def wall_data(self) -> str:
        return self._wall_data

    @wall_data.setter
    def wall_data(self, text: str) -> None:
        self._wall_data = text

    @property
    def portal_data(self) -> list[tuple[GridLocation, GridLocation]]:
        return self._portal_data

    @portal_data.setter
    def portal_data(self, portal_list: Sequence[tuple[str, str]]) -> None:
        """portal_list 形如 [(起点, 终点), ...]。"""
        for nodes in portal_list:
            node1, node2 = location_ensure(nodes[0]), location_ensure(nodes[1])
            self._portal_data.append((node1, node2))
            self[node1].is_portal = True

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
            grid = self.grids[location_ensure(grid)]
            trigger = self.grid_covered(grid=grid, location=[(0, -1), (0, 1), (-1, 0), (1, 0)]).select(is_land=False)
            block = self.grid_covered(grid=grid, location=rotation_dict[rotation]).select(is_land=False)
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
            maze = self.to_selected(raw_maze)
            maze.set(is_maze=True, maze_round=tuple(range(index * 3, index * 3 + 3)))
            for grid in maze:
                self.find_path_initial(grid, has_ambush=False)
                grid.maze_nearby = self.select(cost=1).add(self.select(cost=2)).select(is_land=False)

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
            return self.to_selected((group,))
        if isinstance(group, SelectedGrids):
            return cast("SelectedGrids[GridInfo]", group)
        return self.to_selected(group)

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
        self._bouncing_enemy_data = [self.to_selected(route) for route in data]

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

    def _init_grid_connection(self) -> None:
        total = set(self.grids.keys())
        for grid in self:
            grid_location = self._require_grid_location(grid)
            connection: set[GridLocation] = set()
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                arr = (grid_location[0] + dx, grid_location[1] + dy)
                if arr in total:
                    connection.add(arr)
            self.grid_connection[grid_location] = connection

    def _parse_wall_disconnects(self) -> list[tuple[GridLocation, GridLocation]]:
        wall = []
        for y, line in enumerate(filter(None, self._wall_data.splitlines())):
            for x, letter in enumerate(line[4:-2]):
                if letter != " ":
                    wall.append((x, y))
        if not wall:
            return []

        wall = np.array(wall)
        vert = wall[np.all([wall[:, 0] % 4 == 2, wall[:, 1] % 2 == 0], axis=0)]
        hori = wall[np.all([wall[:, 0] % 4 == 0, wall[:, 1] % 2 == 1], axis=0)]
        disconnect: list[tuple[GridLocation, GridLocation]] = []
        for raw_location in (vert - (2, 0)) // (4, 2):
            location = (int(raw_location[0]), int(raw_location[1]))
            disconnect.append((location, (location[0] + 1, location[1])))
        for raw_location in (hori - (0, 1)) // (4, 2):
            location = (int(raw_location[0]), int(raw_location[1]))
            disconnect.append((location, (location[0], location[1] + 1)))
        return disconnect

    def _apply_wall_connections(self) -> None:
        for g1, g2 in self._parse_wall_disconnects():
            self.grid_connection[g1].remove(g2)
            self.grid_connection[g2].remove(g1)

    def _apply_portal_connections(self, *, portal: bool) -> None:
        for start, end in self._portal_data:
            if portal:
                self.grid_connection[start].add(end)
                self[start].is_portal = True
                self[start].portal_link = end
                continue
            if end in self.grid_connection[start]:
                self.grid_connection[start].remove(end)
            self[start].is_portal = False
            self[start].portal_link = None

    def grid_connection_initial(self, *, wall: bool = False, portal: bool = False) -> bool:
        """按开关应用墙和传送门连接。"""
        logger.info(f"grid_connection: wall={wall}, portal={portal}")

        self._init_grid_connection()
        if wall and self._wall_data:
            self._apply_wall_connections()
        self._apply_portal_connections(portal=portal)

        return True

    def fixup_submarine_fleet(self) -> None:
        # 潜艇和下方格共享弹药图标，下方格可能被误识别为舰队。
        for grid in self.select(is_fleet=True):
            if grid.is_spawn_point:
                continue
            for upper in self.grid_covered(grid, location=[(0, -1)]):
                if upper.is_submarine_spawn_point:
                    logger.info(f"Fixup submarine spawn point, fleet={grid} -> submarine={upper}")
                    grid.is_fleet = False
                    grid.is_current_fleet = False
                    upper.is_submarine = True
        # 初始化时格子不能同时为敌人和舰队；这种冲突也可能来自上方潜艇。
        for grid in self.select(is_enemy=True, is_fleet=True):
            grid.is_fleet = False
            grid.is_current_fleet = False

    def show(self) -> None:
        logger.info("   " + " ".join([" " + chr(x + 64 + 1) for x in range(self.shape[0] + 1)]))
        for y in range(self.shape[1] + 1):
            text = (
                str(y + 1).rjust(2)
                + " "
                + " ".join([self[(x, y)].str if (x, y) in self else "  " for x in range(self.shape[0] + 1)])
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
            if loca in self.grids:
                if self.ignore_prediction_match(globe=loca, local=grid):
                    continue
                if not copy.copy(self.grids[loca]).merge(grid, mode=mode):
                    logger.warning(f"Wrong Prediction. {self.grids[loca]} = '{grid.str}'")
                    failed_count += 1

        if failed_count < 2:
            for grid in grids.grids.values():
                grid_location = self._require_grid_location(grid)
                raw_location = offset + grid_location
                loca = (int(raw_location[0]), int(raw_location[1]))
                if loca in self.grids:
                    if self.ignore_prediction_match(globe=loca, local=grid):
                        continue
                    self.grids[loca].merge(grid, mode=mode)
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
    def camera_data(self) -> SelectedGrids[GridInfo]:
        return self._camera_data

    @camera_data.setter
    def camera_data(self, nodes: Sequence[str]) -> None:
        self._camera_data = SelectedGrids([self[node2location(node)] for node in nodes])

    @property
    def camera_data_spawn_point(self) -> SelectedGrids[GridInfo]:
        """返回用于检测出生点舰队的额外相机位置。"""
        return self._camera_data_spawn_point

    @camera_data_spawn_point.setter
    def camera_data_spawn_point(self, nodes: Sequence[str]) -> None:
        """nodes 为格子名列表。"""
        self._camera_data_spawn_point = SelectedGrids([self[node2location(node)] for node in nodes])

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

    @property
    def weight_data(self) -> str:
        return self._weight_data

    @weight_data.setter
    def weight_data(self, text: str) -> None:
        self._weight_data = text
        for loca, data in self._parse_text(text):
            self[loca].weight = float(data)

    @property
    def map_covered(self) -> SelectedGrids[GridInfo]:
        covered = []
        for grid in self:
            covered += self.grid_covered(grid).grids
        return SelectedGrids(covered).add(self._map_covered)

    @property
    def manual_map_covered(self) -> SelectedGrids[GridInfo]:
        return self._map_covered

    @map_covered.setter
    def map_covered(self, nodes: Sequence[str]) -> None:
        self._map_covered = SelectedGrids([self[node2location(node)] for node in nodes])

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
        if not self.select(may_enemy=True) or not self.select(may_boss=True) or not self.select(is_spawn_point=True):
            return False
        return bool(self.spawn_data)

    def show_cost(self) -> None:
        logger.info("   " + " ".join(["   " + chr(x + 64 + 1) for x in range(self.shape[0] + 1)]))
        for y in range(self.shape[1] + 1):
            text = (
                str(y + 1).rjust(2)
                + " "
                + " ".join(
                    [str(self[(x, y)].cost).rjust(4) if (x, y) in self else "    " for x in range(self.shape[0] + 1)]
                )
            )
            logger.info(text)

    def show_connection(self) -> None:
        logger.info("   " + " ".join([" " + chr(x + 64 + 1) for x in range(self.shape[0] + 1)]))
        for y in range(self.shape[1] + 1):
            text = (
                str(y + 1).rjust(2)
                + " "
                + " ".join(
                    [self._connection_text(self[(x, y)]) if (x, y) in self else "  " for x in range(self.shape[0] + 1)]
                )
            )
            logger.info(text)

    @staticmethod
    def _connection_text(grid: GridInfo) -> str:
        return location2node(grid.connection) if grid.connection is not None else "  "

    def _reset_path_costs(self, start_location: GridLocation) -> set[GridInfo]:
        for grid in self:
            grid.cost = 9999
            grid.connection = None
        start = self[start_location]
        start.cost = 0
        return {start}

    def _update_path_neighbor(
        self, grid: GridInfo, location: GridLocation, ambush_cost: int, *, has_enemy: bool
    ) -> GridInfo | None:
        neighbor = self[location]
        if neighbor.is_land or neighbor.is_mechanism_block:
            return None

        cost = ambush_cost if neighbor.may_ambush else 1
        cost += grid.cost
        if cost < neighbor.cost:
            neighbor.cost = cost
            neighbor.connection = self._require_grid_location(grid)
        elif cost == neighbor.cost:
            neighbor_location = self._require_grid_location(neighbor)
            grid_location = self._require_grid_location(grid)
            if abs(neighbor_location[0] - grid_location[0]) == 1:
                neighbor.connection = grid_location
        if neighbor.is_sea or not has_enemy:
            return neighbor
        return None

    def find_path_initial(
        self,
        location: GridInfo | str | Point,
        *,
        has_ambush: bool = True,
        has_enemy: bool = True,
    ) -> None:
        """从 location 计算路径代价；has_enemy=False 时只区分海面与陆地。"""
        location = location_ensure(location)
        ambush_cost = 10 if has_ambush else 1
        visited = self._reset_path_costs(location)

        while 1:
            new = visited.copy()
            for grid in visited:
                grid_location = self._require_grid_location(grid)
                for location in self.grid_connection[grid_location]:
                    neighbor = self._update_path_neighbor(grid, location, ambush_cost, has_enemy=has_enemy)
                    if neighbor is not None:
                        new.add(neighbor)
            if len(new) == len(visited):
                break
            visited = new

    def find_path_initial_multi_fleet(
        self,
        location_dict: Mapping[int, GridLocation | tuple[()]],
        current: GridLocation | tuple[()],
        *,
        has_ambush: bool,
    ) -> None:
        """按舰队位置写入 cost_<fleet>；当前舰队最后计算并保留在通用 cost 中。"""
        locations = sorted(location_dict.items(), key=lambda kv: (int(kv[1] == current),))
        for fleet, location in locations:
            if location == ():
                continue
            self.find_path_initial(location, has_ambush=has_ambush)
            attr = f"cost_{fleet}"
            for grid in self:
                setattr(grid, attr, grid.cost)

    def _find_path(self, location: GridLocation) -> list[GridLocation] | None:
        """从目标格沿 connection 回溯，返回起点到目标格的坐标路线。"""
        if self[location].cost == 0:
            return [location]
        if self[location].connection is None:
            return None
        res = [location]
        current = self[location].connection
        while current is not None:
            if len(res) > 30:
                logger.warning("Route too long")
                logger.warning(res)
            res.append(current)
            current = self[current].connection
        res.reverse()
        return res

    @staticmethod
    def _append_avoid_indexes(
        index: int,
        route: Sequence[GridLocation],
        base_indexes: Collection[int],
        inserted: list[int],
    ) -> None:
        if (index > 1) and (index - 1 not in base_indexes):
            inserted.append(index - 1)
        if (index < len(route) - 2) and (index + 1 not in base_indexes):
            inserted.append(index + 1)

    def _turning_route_indexes(self, route: Sequence[GridLocation]) -> list[int]:
        res: list[int] = []
        diff = np.abs(np.diff(route, axis=0))
        turning = np.diff(diff, axis=0)[:, 0]
        indexes = np.where(turning == -1)[0] + 1
        for index in indexes:
            if not self[route[index]].is_fleet:
                res.append(index)
                continue

            logger.info(f"Path_node_avoid: {self[route[index]]}")
            self._append_avoid_indexes(index, route, indexes, res)
        res.append(len(route) - 1)
        return res

    def _step_route_indexes(self, route: Sequence[GridLocation], indexes: list[int], step: int) -> list[int]:
        indexes.insert(0, 0)
        inserted = []
        for left, right in pairwise(indexes):
            for index in list(range(left, right, step))[1:]:
                way_node = self[route[index]]
                if way_node.is_fleet or way_node.is_portal or way_node.is_flare:
                    logger.info(f"Path_node_avoid: {way_node}")
                    self._append_avoid_indexes(index, route, indexes, inserted)
                else:
                    inserted.append(index)
            inserted.append(right)
        return inserted

    def _route_node_indexes(self, route: Sequence[GridLocation], step: int, *, turning_optimize: bool) -> list[int]:
        if turning_optimize:
            indexes = self._turning_route_indexes(route)
            if step == 0:
                return indexes
        else:
            if step == 0:
                return [len(route) - 1]
            indexes = [max(len(route) - 1, 0)]
        return self._step_route_indexes(route, indexes, step)

    def _find_route_node(
        self, route: Sequence[GridLocation], step: int = 0, *, turning_optimize: bool = False
    ) -> list[GridLocation]:
        """从路线选取实际点击节点；step 限制步长，turning_optimize 减少转弯伏击。"""
        return [route[index] for index in self._route_node_indexes(route, step, turning_optimize=turning_optimize)]

    def find_path(
        self, location: GridInfo | str | Point, step: int = 0, *, turning_optimize: bool = False
    ) -> list[GridLocation]:
        location = location_ensure(location)

        path = self._find_path(location)
        if path is None or not len(path):
            logger.warning("No path found. Return destination.")
            return [location]
        full_path = ", ".join(location2node(grid) for grid in path)
        logger.info(f"Full path: [{full_path}]")

        portal_path = []
        index = [0]
        for i, (current, next_location) in enumerate(pairwise(path)):
            grid = self[current]
            if grid.is_portal and grid.portal_link == next_location:
                index += [i, i + 1]
            if grid.is_maze and i != 0:
                index += [i]
        if len(path) not in index:
            index.append(len(path))
        for start, end in pairwise(index):
            if end - start == 1 and self[path[start]].is_portal and self[path[start]].portal_link == path[end]:
                continue
            local_path = path[start : end + 1]
            local_path = self._find_route_node(local_path, step=step, turning_optimize=turning_optimize)
            portal_path += local_path
            route = ", ".join(location2node(grid) for grid in local_path)
            logger.info(f"Path: [{route}]")
        return portal_path

    def grid_covered(self, grid: GridInfo, location: Sequence[GridLocation] | None = None) -> SelectedGrids[GridInfo]:
        """按相对坐标 location 返回 grid 覆盖的有效格子；默认使用其覆盖范围。"""
        grid_location = self._require_grid_location(grid)
        if location is None:
            covered = [(grid_location[0] + upper[0], grid_location[1] + upper[1]) for upper in grid.covered_grid()]
        else:
            covered = [(grid_location[0] + upper[0], grid_location[1] + upper[1]) for upper in location]
        covered = [self[upper] for upper in covered if upper in self]
        return SelectedGrids(covered)

    def _get_spawn_missing(self, battle_count: int) -> dict[str, int]:
        try:
            return self.spawn_data_stack[battle_count].copy()
        except IndexError:
            return self.spawn_data_stack[-1].copy()

    def _apply_seen_grid_missing(self, missing: dict[str, int]) -> None:
        for grid in self:
            for attr in ["enemy", "mystery", "siren", "boss"]:
                if getattr(grid, "is_" + attr):
                    missing[attr] -= 1

    def _apply_dynamic_enemy_missing(self, missing: dict[str, int]) -> None:
        missing["enemy"] += len(self.fortress_data[0]) - self.select(is_fortress=True).count
        for route in self.bouncing_enemy_data:
            if not route.select(may_bouncing_enemy=True):
                # 弹跳敌人已被清理，重新补一个敌人缺口。
                missing["enemy"] += 1

    def _get_may_missing(self, mode: GridMode) -> dict[str, int]:
        may = {"enemy": 0, "mystery": 0, "siren": 0, "boss": 0, "carrier": 0}
        for upper in self.map_covered:
            if (upper.may_enemy or mode == "movable") and not upper.is_enemy:
                may["enemy"] += 1
            if upper.may_mystery and not upper.is_mystery:
                may["mystery"] += 1
            if (upper.may_siren or mode == "movable") and not upper.is_siren:
                may["siren"] += 1
            if upper.may_boss and not upper.is_boss:
                may["boss"] += 1
            if upper.may_carrier:
                may["carrier"] += 1
        return may

    def missing_get(
        self,
        battle_count: int,
        mystery_count: int = 0,
        siren_count: int = 0,
        carrier_count: int = 0,
        mode: GridMode = "normal",
    ) -> tuple[dict[str, int], dict[str, int]]:
        missing = self._get_spawn_missing(battle_count)
        missing["enemy"] -= battle_count - siren_count
        missing["mystery"] -= mystery_count
        missing["siren"] -= siren_count
        missing["carrier"] = (
            carrier_count - self.select(is_enemy=True, may_enemy=False).count if mode == "carrier" else 0
        )
        self._apply_seen_grid_missing(missing)
        self._apply_dynamic_enemy_missing(missing)
        may = self._get_may_missing(mode)

        logger.attr(
            "enemy_missing",
            ", ".join([f"{k[:2].upper()}:{str(v).rjust(2)}" for k, v in missing.items() if k != "battle"]),
        )
        logger.attr("enemy_may____", ", ".join([f"{k[:2].upper()}:{str(v).rjust(2)}" for k, v in may.items()]))
        return may, missing

    def missing_is_none(
        self,
        battle_count: int,
        mystery_count: int = 0,
        siren_count: int = 0,
        carrier_count: int = 0,
        mode: GridMode = "normal",
    ) -> bool:
        if self.poor_map_data:
            return False

        may, missing = self.missing_get(battle_count, mystery_count, siren_count, carrier_count, mode)

        return all(missing[key] == 0 for key in may)

    def missing_predict(
        self,
        battle_count: int,
        mystery_count: int = 0,
        siren_count: int = 0,
        carrier_count: int = 0,
        mode: GridMode = "normal",
    ) -> None:
        if self.poor_map_data:
            return

        may, missing = self.missing_get(battle_count, mystery_count, siren_count, carrier_count, mode)

        # 推断。
        for upper in self.map_covered:
            for attr in ["enemy", "mystery", "siren", "boss"]:
                if getattr(upper, "may_" + attr) and missing[attr] > 0 and missing[attr] == may[attr]:
                    logger.info(f"Predict {location2node(self._require_grid_location(upper))} to be {attr}")
                    setattr(upper, "is_" + attr, True)
            if carrier_count and upper.may_carrier and missing["carrier"] > 0 and missing["carrier"] == may["carrier"]:
                logger.info(f"Predict {location2node(self._require_grid_location(upper))} to be enemy")
                upper.is_enemy = True

    def select(self, **kwargs: object) -> SelectedGrids[GridInfo]:
        result = []
        for grid in self:
            flag = True
            for k, v in kwargs.items():
                if getattr(grid, k) != v:
                    flag = False
            if flag:
                result.append(grid)

        return SelectedGrids(result)

    def to_selected(self, grids: Iterable[GridInfo | str | Point]) -> SelectedGrids[GridInfo]:
        return SelectedGrids([self[location_ensure(loca)] for loca in grids])

    def flatten(self) -> ValuesView[GridInfo]:
        return self.grids.values()
