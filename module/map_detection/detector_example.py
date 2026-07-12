from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.type_alias import ImageArray, NumericArray
    from module.config.config import AzurLaneConfig
    from module.map.type_alias import GridLocation


class DetectionBackendExample:
    """地图检测后端实现模板。"""

    grid_shape = (8, 5)

    def __init__(self, config: AzurLaneConfig) -> None:
        self.config = config

    def load(self, image: ImageArray) -> None:
        """加载 (720, 1280, 3) 截图。"""
        self.image = image
        # 在这里执行地图检测。

    image: ImageArray
    config: AzurLaneConfig
    # 四条边可为 bool，或实现 __bool__。
    left_edge: bool
    right_edge: bool
    lower_edge: bool
    upper_edge: bool

    def generate(self) -> Iterator[tuple[GridLocation, NumericArray]]:
        """逐格产出 ((x, y), [左上, 右上, 左下, 右下])。"""
        corner = np.array([(0, 0), (100, 0), (0, 100), (100, 100)])
        for x in range(self.grid_shape[0]):
            for y in range(self.grid_shape[1]):
                yield (x, y), corner
