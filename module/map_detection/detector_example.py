from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from module.config.config import AzurLaneConfig


class DetectionBackendExample:
    """地图检测后端实现模板。"""

    def __init__(self, config):
        self.config = config

    def load(self, image):
        """加载 (720, 1280, 3) 截图。"""
        self.image = image
        # 在这里执行地图检测。

    image: np.ndarray
    config: AzurLaneConfig
    # 四条边可为 bool，或实现 __bool__。
    left_edge: bool
    right_edge: bool
    lower_edge: bool
    upper_edge: bool

    def generate(self):
        """逐格产出 ((x, y), [左上, 右上, 左下, 右下])。"""
        for x in range(8):
            for y in range(5):
                yield (x, y), [(0, 0), (100, 0), (0, 100), (100, 100)]
