from module.base.decorator import cached_property
from module.map_detection.grid_info import GridInfo
from module.map_detection.grid_predictor import GridPredictor
from module.map_detection.utils import trapezoid2area


class Grid(GridInfo, GridPredictor):
    def __init__(self, location, image, corner, config):
        """corner 顺序为左上、右上、左下、右下。"""
        self.location = location
        super().__init__(location, image, corner, config)

    @cached_property
    def inner(self):
        """返回梯形最大内接矩形 (x1, y1, x2, y2)。"""
        return trapezoid2area(self.corner, pad=5)

    @cached_property
    def outer(self):
        """返回梯形最小外接矩形 (x1, y1, x2, y2)。"""
        return trapezoid2area(self.corner, pad=-5)

    @cached_property
    def button(self):
        """暴露可点击的 button 区域。"""
        return self.inner
