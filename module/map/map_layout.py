from typing import TYPE_CHECKING, cast

import numpy as np

from module.base.utils import location2node, node2location
from module.map.map_grids import SelectedGrids
from module.map.utils import camera_2d, location_ensure
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from module.base.type_alias import Point
    from module.map.type_alias import GridLocation


def parse_grid_text(text: str) -> Iterator[tuple[GridLocation, str]]:
    """按行列顺序解析以空格分隔的地图文本。"""
    for y, raw_row in enumerate(text.strip().split("\n")):
        for x, data in enumerate(raw_row.strip().split(" ")):
            yield (x, y), data


class CampaignMapLayout:
    """持有地图格子的几何、创建方式及所有空间投影。"""

    def __init__(
        self,
        *,
        grid_class: type[GridInfo] = GridInfo,
        camera_sight: tuple[int, int, int, int] = (-3, -1, 3, 2),
    ) -> None:
        self.grid_class = grid_class
        self.camera_sight = camera_sight
        self.grids: dict[GridLocation, GridInfo] = {}
        self._shape: GridLocation = (0, 0)
        self._camera_data = SelectedGrids[GridInfo]([])
        self._camera_data_spawn_point = SelectedGrids[GridInfo]([])
        self._weight_data = ""
        self._manual_coverage = SelectedGrids[GridInfo]([])

    def __iter__(self) -> Iterator[GridInfo]:
        return iter(self.grids.values())

    def __getitem__(self, item: Point) -> GridInfo:
        return self.grids[location_ensure(item)]

    def __contains__(self, item: object) -> bool:
        if isinstance(item, np.ndarray):
            if item.shape != (2,) or not np.issubdtype(item.dtype, np.integer):
                return False
            values = cast("list[int]", np.asarray(item, dtype=int).tolist())
            return (values[0], values[1]) in self.grids
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            return False
        x, y = item
        if not isinstance(x, (int, np.integer)) or not isinstance(y, (int, np.integer)):
            return False
        return (int(x), int(y)) in self.grids

    @property
    def shape(self) -> GridLocation:
        return self._shape

    @property
    def camera_data(self) -> SelectedGrids[GridInfo]:
        return self._camera_data

    @property
    def camera_data_spawn_point(self) -> SelectedGrids[GridInfo]:
        """返回用于检测出生点舰队的额外相机位置。"""
        return self._camera_data_spawn_point

    @property
    def weight_data(self) -> str:
        return self._weight_data

    @property
    def manual_coverage(self) -> SelectedGrids[GridInfo]:
        return self._manual_coverage

    @property
    def covered_grids(self) -> SelectedGrids[GridInfo]:
        covered = SelectedGrids[GridInfo]([])
        for grid in self:
            covered = covered.add(self.covered_by(grid))
        return covered.add(self._manual_coverage)

    def initialize(self, scale: str) -> None:
        """按右下角格子名重建地图布局及默认空间投影。"""
        self._shape = node2location(scale.upper())
        self.grids.clear()
        for y in range(self._shape[1] + 1):
            for x in range(self._shape[0] + 1):
                grid = self.grid_class()
                grid.location = (x, y)
                grid.weight = 10.0
                self.grids[(x, y)] = grid

        self.set_camera_data(
            [location2node(location) for location in camera_2d((0, 0, *self._shape), sight=self.camera_sight)]
        )
        self.set_camera_data_spawn_point(())
        self._weight_data = ""
        self._manual_coverage = SelectedGrids([])

    def set_camera_data(self, nodes: Sequence[str]) -> None:
        self._camera_data = SelectedGrids([self[node2location(node)] for node in nodes])

    def set_camera_data_spawn_point(self, nodes: Sequence[str]) -> None:
        self._camera_data_spawn_point = SelectedGrids([self[node2location(node)] for node in nodes])

    def apply_weights(self, text: str) -> None:
        self._weight_data = text
        for location, data in parse_grid_text(text):
            self[location].weight = float(data)

    def set_manual_coverage(self, nodes: Sequence[str]) -> None:
        self._manual_coverage = SelectedGrids([self[node2location(node)] for node in nodes])

    def covered_by(
        self,
        grid: GridInfo,
        offsets: Sequence[GridLocation] | None = None,
    ) -> SelectedGrids[GridInfo]:
        """按相对坐标返回格子覆盖的有效位置；默认使用格子自身覆盖范围。"""
        location = location_ensure(grid)
        relative = grid.covered_grid() if offsets is None else offsets
        covered = [(location[0] + offset[0], location[1] + offset[1]) for offset in relative]
        return SelectedGrids([self[candidate] for candidate in covered if candidate in self])

    def select(self, **criteria: object) -> SelectedGrids[GridInfo]:
        return SelectedGrids(
            [grid for grid in self if all(getattr(grid, name) == value for name, value in criteria.items())]
        )

    def to_selected(self, grids: Iterable[GridInfo | str | Point]) -> SelectedGrids[GridInfo]:
        return SelectedGrids([self[location_ensure(grid)] for grid in grids])
