from typing import TYPE_CHECKING

import numpy as np

from module.map.map_base import CampaignMap
from module.map.map_layout import CampaignMapLayout
from module.map_detection.os_grid import OSGridInfo

if TYPE_CHECKING:
    from module.map.type_alias import GridLocation, GridMode
    from module.map_detection.view import View

OS_MAP_UPDATE_MODE_MESSAGE = "OS map update only supports normal scan mode"


class OSCampaignMap(CampaignMap):
    def __init__(self, name: str | None = None) -> None:
        super().__init__(
            name,
            layout=CampaignMapLayout(
                grid_class=OSGridInfo,
                camera_sight=(-4, -1, 3, 3),
            ),
        )

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
            if loca in self.layout:
                self.layout[loca].merge(grid, mode=mode)
        return True
