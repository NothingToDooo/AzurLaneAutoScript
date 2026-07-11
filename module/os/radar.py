from typing import TYPE_CHECKING, ClassVar

import numpy as np

from module.base.mask import Mask
from module.base.utils import area_offset, color_similarity_2d, crop, point_limit
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.map_detection.utils import fit_points

if TYPE_CHECKING:
    import builtins

MASK_RADAR = Mask("./assets/mask/MASK_OS_RADAR.png")


class RadarGrid:
    is_enemy = False  # 红色炮口。
    is_resource = False  # 绿色物资箱。
    is_exclamation = False  # 黄色感叹号。
    is_meowfficer = False  # 蓝色猫指挥官。
    is_question = False  # 白色问号。
    is_ally = False  # 每日任务中的黄色感叹号友军运输船。
    is_akashi = False  # 白色问号明石。
    is_archive = False  # 紫色档案。
    is_port = False

    enemy_scale = 0
    enemy_genre = None  # Light、Main、Carrier、Treasure 或 Enemy（未知）。

    is_fleet = False

    dic_encode: ClassVar[dict[builtins.str, builtins.str]] = {
        "EN": "is_enemy",
        "RE": "is_resource",
        "AR": "is_archive",
        "EX": "is_exclamation",
        "ME": "is_meowfficer",
        "PO": "is_port",
        "QU": "is_question",
        "FL": "is_fleet",
    }

    def __init__(self, location, image, center, config):
        """location 是相对雷达中心的格子坐标；center 是该格中心的截图像素坐标。"""
        self.location = location
        self.image: np.ndarray = image
        self.center = center
        self.config = config
        self.is_fleet = np.sum(np.abs(location)) == 0

    def encode(self):
        for key, value in self.dic_encode.items():
            if getattr(self, value):
                return key

        return "--"

    @property
    def str(self):
        return self.encode()

    def reset(self):
        self.is_enemy = False
        self.is_resource = False
        self.is_exclamation = False
        self.is_meowfficer = False
        self.is_question = False
        self.is_port = False

        self.is_ally = False
        self.is_akashi = False

        self.enemy_scale = 0
        self.enemy_genre = None

    def predict(self):
        if self.is_fleet:
            return

        self.is_enemy = self.predict_enemy() or self.predict_boss()
        self.is_resource = self.predict_resource()
        self.is_meowfficer = self.predict_meowfficer()
        self.is_exclamation = self.predict_exclamation()
        self.is_port = self.predict_port()
        self.is_question = self.predict_question()
        self.is_archive = self.predict_archive()

        if self.enemy_genre:
            self.is_enemy = True
        if self.enemy_scale:
            self.is_enemy = True
        if self.is_enemy and not self.enemy_genre:
            self.enemy_genre = "Enemy"
        if self.config.MAP_HAS_SIREN and self.enemy_genre is not None and self.enemy_genre.startswith("Siren"):
            self.is_siren = True
            self.enemy_scale = 0

    def image_color_count(self, area, color, threshold=221, count=50):
        """统计中心相对区域内的近似 RGB 像素；threshold 越接近 255，颜色要求越严格。"""
        image = crop(self.image, area_offset(area, self.center), copy=False)
        mask = color_similarity_2d(image, color=color) > threshold
        return np.sum(mask) >= count

    def predict_enemy(self):
        return self.image_color_count(area=(-3, -3, 3, 3), color=(247, 89, 49), threshold=221, count=10)

    def predict_resource(self):
        return self.image_color_count(area=(-3, -3, 3, 3), color=(66, 231, 165), threshold=221, count=10)

    def predict_meowfficer(self):
        return self.image_color_count(area=(-3, 0, 3, 6), color=(33, 186, 255), threshold=221, count=10)

    def predict_exclamation(self):
        return self.image_color_count(area=(-3, -3, 3, 3), color=(255, 203, 49), threshold=221, count=10)

    def predict_boss(self):
        return self.image_color_count(area=(-3, -3, 3, 3), color=(147, 12, 8), threshold=221, count=10)

    def predict_port(self):
        return self.image_color_count(area=(-3, -3, 3, 3), color=(255, 255, 255), threshold=235, count=9)

    def predict_question(self):
        return self.image_color_count(area=(0, -7, 6, 0), color=(255, 255, 255), threshold=235, count=9)

    def predict_archive(self):
        return self.image_color_count(area=(-3, -3, 3, 3), color=(173, 113, 255), threshold=235, count=10)


class Radar:
    grids: dict
    center_loca = (0, 0)
    port_loca = (0, 0)

    def __init__(self, config, center=(1140, 226), delta=(11.7, 11.7), radius=5.15):
        self.grids = {}
        self.config = config
        self.center = center
        self.delta = delta

        center = np.array(center)
        delta = np.array(delta)
        radius_int = int(radius)
        self.shape = [[-radius_int, radius_int + 1], [-radius_int, radius_int + 1]]
        for x in range(*self.shape[0]):
            for y in range(*self.shape[1]):
                if np.linalg.norm([x, y]) > radius:
                    continue
                grid_center = np.round(delta * (x, y) + center).astype(int)
                self.grids[(x, y)] = RadarGrid(location=(x, y), image=None, center=grid_center, config=self.config)

    def __iter__(self):
        return iter(self.grids.values())

    def __getitem__(self, item):
        return self.grids[tuple(item)]

    def __contains__(self, item):
        return tuple(item) in self.grids

    def show(self):
        for y in range(*self.shape[1]):
            text = " ".join([self[(x, y)].str if (x, y) in self else "  " for x in range(*self.shape[0])])
            logger.info(text)

    def predict(self, image):
        """根据雷达截图更新格子预测结果。"""
        image = MASK_RADAR.apply(image)
        for grid in self:
            grid.image = image
            grid.reset()
            grid.predict()
        # 港口旁的白色像素可能被误识别为问号，需要纠正。
        for port in self.select(is_port=True):
            for grid in self.select(is_question=True):
                if np.sum(np.abs(np.subtract(port.location, grid.location))) == 1:
                    logger.warning(
                        f"Wrong radar prediction is_question {grid.location} {grid.encode()} "
                        f"near {port.location} {port.encode()}"
                    )
                    grid.is_question = False

    def select(self, **kwargs):
        result = []
        for grid in self:
            flag = True
            for k, v in kwargs.items():
                if getattr(grid, k) != v:
                    flag = False
            if flag:
                result.append(grid)

        return SelectedGrids(result)

    def predict_port_outside(self, image):
        """返回港口图标中心相对雷达中心的像素坐标；未找到时返回 None。"""
        radius = (15, 82)
        image = crop(image, area_offset((-radius[1], -radius[1], radius[1], radius[1]), self.center), copy=False)
        points = np.where(color_similarity_2d(image, color=(255, 255, 255)) > 250)
        points = np.array(points).T[:, ::-1] - (radius[1], radius[1])
        distance = np.linalg.norm(points, axis=1)
        points = points[np.all([distance < radius[1], distance > radius[0]], axis=0)]
        if len(points):
            point = fit_points(points, mod=(1000, 1000), encourage=5)
            point[point > 500] -= 1000
            self.port_loca = point
            return point
        return None

    def predict_port_inside(self, image):
        """返回雷达内港口中心旁的可接近格子坐标；未找到时返回 None。"""
        self.predict(image)
        for grid in self:
            if grid.is_port:
                # 港口中心不可点击，改走相邻格。
                location = np.array(grid.location) - np.sign(grid.location) * (1, 1)
                self.port_loca = location
                return location

        return None

    @staticmethod
    def port_outside_to_inside(point):
        """把雷达外港口的相对像素坐标投影为雷达边缘格子坐标。"""
        sight = (-4, -2, 3, 2)
        grids = [(x, y) for x in range(sight[0], sight[2] + 1) for y in [sight[1], sight[3]]] + [
            (x, y) for x in [sight[0], sight[2]] for y in range(sight[1] + 1, sight[3])
        ]
        grids = np.array(list(grids))
        distance = np.linalg.norm(grids, axis=1)
        degree = np.sum(grids * point, axis=1) / distance / np.linalg.norm(point)
        return grids[np.argmax(degree)]

    def port_predict(self, image):
        """返回港口格或可接近港口的格子坐标；未找到时返回 None。"""
        port = self.predict_port_inside(image)
        if port is not None:
            return port

        point = self.predict_port_outside(image)
        if point is not None:
            return self.port_outside_to_inside(point)

        return None

    def predict_akashi(self, image):
        """返回雷达上的明石格子坐标；未找到时返回 None。"""
        self.predict(image)
        for location in [(0, 1), (-1, 0), (1, 0), (0, -1)]:
            grid = self[location]
            if grid.is_question and not grid.predict_port():
                return location

        return None

    def predict_question(self, image, in_port=True):
        """返回问号格子坐标；未找到时返回 None，in_port=False 时把港口也视作问号。"""
        self.predict(image)
        self.show()
        for location in [(0, 1), (-1, 0), (1, 0), (0, -1), (0, -2), (0, -3)]:
            grid = self[location]
            if in_port:
                if grid.is_question and not grid.is_port:
                    return location
            elif grid.is_question or grid.is_port:
                return location

        return None

    def nearest_object(self, camera_sight=(-4, -3, 3, 3)):
        """返回视野限制内最接近的可处理对象；没有对象时返回 None。"""
        objects = []
        for grid in self:
            if grid.is_port:
                continue
            if (
                grid.is_enemy
                or grid.is_resource
                or grid.is_meowfficer
                or grid.is_exclamation
                or grid.is_question
                or grid.is_archive
            ):
                objects.append(grid)
        objects = SelectedGrids(objects).sort_by_camera_distance((0, 0))
        if not objects:
            return None

        nearest = objects[0]
        limited = point_limit(nearest.location, area=camera_sight)
        if nearest.location == limited:
            return nearest
        return self[limited]
