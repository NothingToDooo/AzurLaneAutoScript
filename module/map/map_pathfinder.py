import heapq
from itertools import pairwise
from typing import TYPE_CHECKING

from module.base.utils import location2node
from module.logger import logger
from module.map.utils import location_ensure

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from module.base.type_alias import Point
    from module.map.map_topology import CampaignMapTopology
    from module.map.type_alias import GridLocation
    from module.map_detection.grid_info import GridInfo


class CampaignPathfinder:
    """在拓扑连接上投影路径代价，并生成实际点击路线。"""

    def __init__(
        self,
        grids: dict[GridLocation, GridInfo],
        topology: CampaignMapTopology,
    ) -> None:
        self._grids = grids
        self._topology = topology
        self._predecessors: dict[GridLocation, GridLocation | None] = {}

    @staticmethod
    def _require_grid_location(grid: GridInfo) -> GridLocation:
        if grid.location is None:
            message = "地图格子缺少位置"
            raise RuntimeError(message)
        return grid.location

    def show_cost(self) -> None:
        shape = self._shape
        logger.info("   " + " ".join(["   " + chr(x + 65) for x in range(shape[0] + 1)]))
        for y in range(shape[1] + 1):
            text = (
                str(y + 1).rjust(2)
                + " "
                + " ".join(
                    [
                        str(self._grids[(x, y)].cost).rjust(4) if (x, y) in self._grids else "    "
                        for x in range(shape[0] + 1)
                    ]
                )
            )
            logger.info(text)

    @property
    def _shape(self) -> GridLocation:
        if not self._grids:
            return 0, 0
        return max(x for x, _y in self._grids), max(y for _x, y in self._grids)

    def _reset_costs(self, start: GridLocation) -> None:
        self._predecessors = dict.fromkeys(self._grids)
        for grid in self._grids.values():
            grid.cost = 9999
        self._grids[start].cost = 0

    def project(
        self,
        start: GridInfo | str | Point,
        *,
        has_ambush: bool = True,
        has_enemy: bool = True,
    ) -> None:
        """从 start 计算并写入通用 cost 与前驱 connection。"""
        start_location = location_ensure(start)
        ambush_cost = 10 if has_ambush else 1
        self._reset_costs(start_location)
        frontier: list[tuple[int, GridLocation]] = [(0, start_location)]

        while frontier:
            cost, location = heapq.heappop(frontier)
            if cost != self._grids[location].cost:
                continue
            for neighbor_location in sorted(self._topology.neighbors(location)):
                neighbor = self._grids[neighbor_location]
                if neighbor.is_land or neighbor.is_mechanism_block:
                    continue
                candidate = cost + (ambush_cost if neighbor.may_ambush else 1)
                if candidate < neighbor.cost:
                    neighbor.cost = candidate
                    self._predecessors[neighbor_location] = location
                    if neighbor.is_sea or not has_enemy:
                        heapq.heappush(frontier, (candidate, neighbor_location))
                elif candidate == neighbor.cost and abs(neighbor_location[0] - location[0]) == 1:
                    self._predecessors[neighbor_location] = location

    def project_fleets(
        self,
        locations: Mapping[int, GridLocation | tuple[()]],
        current: GridLocation | tuple[()],
        *,
        has_ambush: bool,
    ) -> None:
        """写入 cost_<fleet>，并让当前舰队投影最后保留在通用 cost。"""
        ordered = sorted(locations.items(), key=lambda item: int(item[1] == current))
        for fleet, location in ordered:
            if location == ():
                continue
            self.project(location, has_ambush=has_ambush)
            attribute = f"cost_{fleet}"
            for grid in self._grids.values():
                setattr(grid, attribute, grid.cost)

    def _full_route(self, destination: GridLocation) -> list[GridLocation] | None:
        grid = self._grids[destination]
        if grid.cost == 0:
            return [destination]
        predecessor = self._predecessors.get(destination)
        if predecessor is None:
            return None
        result = [destination]
        current = predecessor
        while current is not None:
            if len(result) > 30:
                logger.warning("Route too long")
                logger.warning(result)
            result.append(current)
            current = self._predecessors[current]
        result.reverse()
        return result

    @staticmethod
    def _append_avoid_indexes(
        index: int,
        route: Sequence[GridLocation],
        base_indexes: Collection[int],
        inserted: list[int],
    ) -> None:
        if index > 1 and index - 1 not in base_indexes:
            inserted.append(index - 1)
        if index < len(route) - 2 and index + 1 not in base_indexes:
            inserted.append(index + 1)

    def _turning_route_indexes(self, route: Sequence[GridLocation]) -> list[int]:
        result: list[int] = []
        indexes = [
            index
            for index in range(1, len(route) - 1)
            if (route[index - 1][0] == route[index][0]) != (route[index][0] == route[index + 1][0])
        ]
        for index in indexes:
            if not self._grids[route[index]].is_fleet:
                result.append(index)
                continue

            logger.info(f"Path_node_avoid: {self._grids[route[index]]}")
            self._append_avoid_indexes(index, route, indexes, result)
        result.append(len(route) - 1)
        return result

    def _step_route_indexes(self, route: Sequence[GridLocation], indexes: list[int], step: int) -> list[int]:
        indexes.insert(0, 0)
        inserted: list[int] = []
        for left, right in pairwise(indexes):
            for index in list(range(left, right, step))[1:]:
                way_node = self._grids[route[index]]
                if (
                    way_node.is_fleet
                    or self._topology.portal_destination(route[index]) is not None
                    or way_node.is_flare
                ):
                    logger.info(f"Path_node_avoid: {way_node}")
                    self._append_avoid_indexes(index, route, indexes, inserted)
                else:
                    inserted.append(index)
            inserted.append(right)
        return inserted

    def _route_node_indexes(
        self,
        route: Sequence[GridLocation],
        step: int,
        *,
        turning_optimize: bool,
    ) -> list[int]:
        if turning_optimize:
            indexes = self._turning_route_indexes(route)
            if step == 0:
                return indexes
        else:
            if step == 0:
                return [len(route) - 1]
            indexes = [max(len(route) - 1, 0)]
        return self._step_route_indexes(route, indexes, step)

    def _route_nodes(
        self,
        route: Sequence[GridLocation],
        step: int = 0,
        *,
        turning_optimize: bool = False,
    ) -> list[GridLocation]:
        return [route[index] for index in self._route_node_indexes(route, step, turning_optimize=turning_optimize)]

    def route(
        self,
        destination: GridInfo | str | Point,
        step: int = 0,
        *,
        turning_optimize: bool = False,
    ) -> list[GridLocation]:
        destination_location = location_ensure(destination)
        path = self._full_route(destination_location)
        if path is None or not path:
            logger.warning("No path found. Return destination.")
            return [destination_location]
        full_path = ", ".join(location2node(grid) for grid in path)
        logger.info(f"Full path: [{full_path}]")

        portal_path: list[GridLocation] = []
        indexes = [0]
        for index, (current, next_location) in enumerate(pairwise(path)):
            if self._topology.portal_destination(current) == next_location:
                indexes += [index, index + 1]
            if self._grids[current].is_maze and index != 0:
                indexes.append(index)
        if len(path) not in indexes:
            indexes.append(len(path))
        for start, end in pairwise(indexes):
            if end - start == 1 and self._topology.portal_destination(path[start]) == path[end]:
                continue
            local_path = path[start : end + 1]
            local_path = self._route_nodes(local_path, step=step, turning_optimize=turning_optimize)
            portal_path += local_path
            route = ", ".join(location2node(grid) for grid in local_path)
            logger.info(f"Path: [{route}]")
        return portal_path
