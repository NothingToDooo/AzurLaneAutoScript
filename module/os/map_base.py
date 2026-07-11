from typing import TYPE_CHECKING

import numpy as np

from module.base.utils import location2node, node2location
from module.map.map_base import CampaignMap, camera_2d
from module.map_detection.os_grid import OSGridInfo

if TYPE_CHECKING:
    from module.map.type_alias import GridLocation, GridMode
    from module.map_detection.view import View

OS_MAP_UPDATE_MODE_MESSAGE = "OS map update only supports normal scan mode"


class OSCampaignMap(CampaignMap):
    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self.camera_sight = (-4, -1, 3, 3)

    @property
    def shape(self) -> GridLocation:
        return self._shape

    @shape.setter
    def shape(self, scale: str) -> None:
        self._shape = node2location(scale.upper())
        for y in range(self._shape[1] + 1):
            for x in range(self._shape[0] + 1):
                grid = OSGridInfo()
                grid.location = (x, y)
                self.grids[(x, y)] = grid

        # camera_data 虽可自动生成，但手动固定可避免扫描路径漂移。
        self.camera_data = [location2node(loca) for loca in camera_2d((0, 0, *self._shape), sight=self.camera_sight)]
        self.camera_data_spawn_point = []
        for grid in self:
            grid.weight = 10.0

    def update(self, grids: View, camera: GridLocation, mode: GridMode = "normal") -> bool:
        """按镜头坐标合并扫描格子；大世界仅支持 normal 模式。"""
        if mode != "normal":
            message = f"{OS_MAP_UPDATE_MODE_MESSAGE}: {mode}"
            raise ValueError(message)

        offset = np.array(camera) - np.array(grids.center_loca)
        grids.show()

        for grid in grids.grids.values():
            if grid.location is None:
                message = "OS view grid has no location"
                raise ValueError(message)
            raw_location = offset + grid.location
            loca = (int(raw_location[0]), int(raw_location[1]))
            if loca in self.grids:
                self.grids[loca].merge(grid, mode=mode)
        return True
