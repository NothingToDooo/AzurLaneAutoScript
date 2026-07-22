from typing import TYPE_CHECKING

from module.logger import logger
from module.map.type_alias import GridLocation

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

type MapEdge = tuple[GridLocation, GridLocation]


class CampaignMapTopology:
    """持有地图的静态边、墙与单向传送门连接。"""

    def __init__(self, grids: Mapping[GridLocation, object]) -> None:
        self._grids = grids
        self._walls: tuple[MapEdge, ...] = ()
        self._portals: tuple[MapEdge, ...] = ()
        self._connections: dict[GridLocation, set[GridLocation]] = {}
        self._active_portals: dict[GridLocation, GridLocation] = {}

    @property
    def walls(self) -> tuple[MapEdge, ...]:
        return self._walls

    @property
    def portals(self) -> tuple[MapEdge, ...]:
        return self._portals

    def configure(
        self,
        *,
        walls: Iterable[MapEdge] = (),
        portals: Iterable[MapEdge] = (),
    ) -> None:
        """替换地图定义中的墙和传送门边。"""
        configured_walls = tuple(walls)
        configured_portals = tuple(portals)
        self._validate_edges(configured_walls, kind="wall", adjacent=True)
        self._validate_edges(configured_portals, kind="portal", adjacent=False)
        starts = [start for start, _end in configured_portals]
        if len(starts) != len(set(starts)):
            message = "portal sources must be unique"
            raise ValueError(message)
        self._walls = configured_walls
        self._portals = configured_portals
        self._connections.clear()
        self._active_portals.clear()

    def _validate_edges(self, edges: tuple[MapEdge, ...], *, kind: str, adjacent: bool) -> None:
        for start, end in edges:
            if start not in self._grids or end not in self._grids:
                message = f"{kind} edge references a cell outside the map: {start} -> {end}"
                raise ValueError(message)
            if start == end:
                message = f"{kind} edge cannot target its source: {start}"
                raise ValueError(message)
            if adjacent and abs(start[0] - end[0]) + abs(start[1] - end[1]) != 1:
                message = f"wall edge must connect adjacent cells: {start} -> {end}"
                raise ValueError(message)

    def rebuild(self, *, wall: bool = False, portal: bool = False) -> None:
        """从地图格重新建立连接，并按开关投影墙和传送门。"""
        logger.info(f"grid_connection: wall={wall}, portal={portal}")
        locations = set(self._grids)
        self._connections.clear()
        for location in locations:
            x, y = location
            self._connections[location] = {
                neighbor for neighbor in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)) if neighbor in locations
            }

        if wall:
            for start, end in self._walls:
                self._connections[start].remove(end)
                self._connections[end].remove(start)

        self._active_portals.clear()
        if portal:
            for start, end in self._portals:
                self._connections[start] = {end}
                self._active_portals[start] = end

    def neighbors(self, location: GridLocation) -> frozenset[GridLocation]:
        return frozenset(self._connections[location])

    def portal_destination(self, location: GridLocation) -> GridLocation | None:
        return self._active_portals.get(location)
