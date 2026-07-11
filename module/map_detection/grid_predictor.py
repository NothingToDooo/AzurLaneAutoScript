from typing import TYPE_CHECKING, cast

import cv2
import numpy as np

from module.base.decorator import cached_property
from module.base.utils import area_offset, area_pad, color_similarity_2d, crop, rgb2gray
from module.exception import ScriptError
from module.logger import logger
from module.map_detection.utils import area2corner, corner2area, perspective_transform
from module.map_detection.utils_assets import ASSETS, DETECTING_AREA, UI_MASK, UI_MASK_OS
from module.template import assets as template_assets

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.base.template import Template
    from module.base.type_alias import Area, Color, ImageArray, NumericArray, Point, Size
    from module.config.config import AzurLaneConfig
    from module.map.type_alias import GridLocation

MISSING_ENEMY_TEMPLATE_DETAIL = (
    "Enemy detection template asset is missing. Update checked-in assets/<server>/template before running this map."
)


class GridPredictor:
    def __init__(self, location: GridLocation, image: ImageArray, corner: NumericArray, config: AzurLaneConfig) -> None:
        """image 形状为 (720, 1280, 3)，corner 形状为 (4, 2)。
        corner 顺序为左上、右上、左下、右下。
        """
        self.location = location
        self.image = image
        self.corner = corner
        self.config = config

        # 直接计算比调用现有函数更快。
        x0, y0, x1, _y1, x2, y2, x3, _y3 = corner.flatten()
        divisor = x0 - x1 + x2 - x3
        x = (x0 * x2 - x1 * x3) / divisor
        y = (x0 * y2 - x1 * y2 + x2 * y0 - x3 * y0) / divisor
        self._image_center = np.array([x, y, x, y])
        self._image_a = (-x0 * x2 + x0 * x3 + x1 * x2 - x1 * x3) / divisor * self.config.GRID_IMAGE_A_MULTIPLY

        self.template_enemy_genre: dict[str, Template | None] = {}
        for name in self.config.MAP_ENEMY_TEMPLATE:
            self.template_enemy_genre[name] = getattr(template_assets, f"TEMPLATE_ENEMY_{name}", None)
        if self.config.MAP_HAS_SIREN:
            for name in self.config.MAP_SIREN_TEMPLATE:
                self.template_enemy_genre[f"Siren_{name}"] = getattr(template_assets, f"TEMPLATE_SIREN_{name}", None)

        self.area = corner2area(self.corner)
        self.homo_data = cast(
            "NumericArray",
            cv2.getPerspectiveTransform(
                src=self.corner.astype(np.float32),
                dst=area2corner((0, 0, *self.config.HOMO_TILE)).astype(np.float32),
            ),
        )
        self.homo_invt = cast("NumericArray", cv2.invert(self.homo_data)[1])

    def screen2grid(self, points: Sequence[Point] | NumericArray) -> NumericArray:
        """把 (n, 2) 屏幕坐标转换为以格子左上角为原点的网格坐标。"""
        return perspective_transform(points, self.homo_data) / self.config.HOMO_TILE

    def grid2screen(self, points: Sequence[Point] | NumericArray) -> NumericArray:
        """把 (n, 2) 网格坐标转换回屏幕坐标。"""
        scaled = np.asarray(points, dtype=float) * np.asarray(self.config.HOMO_TILE, dtype=float)
        return perspective_transform(scaled, self.homo_invt)

    @cached_property
    def image_trans(self) -> ImageArray:
        return cast("ImageArray", cv2.warpPerspective(self.image, self.homo_data, self.config.HOMO_TILE))

    @cached_property
    def image_homo(self) -> ImageArray:
        image_edge = rgb2gray(self.image_trans)
        image_edge = cv2.Canny(image_edge, 100, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cv2.morphologyEx(image_edge, cv2.MORPH_CLOSE, kernel, dst=image_edge)
        return cast("ImageArray", image_edge)

    def predict(self) -> None:
        self.enemy_scale = self.predict_enemy_scale()
        self.enemy_genre = self.predict_enemy_genre()
        self.is_boss = self.predict_boss()
        self.is_submarine = self.predict_submarine()
        if self.is_submarine:
            self.is_fleet = False
        else:
            self.is_fleet = self.predict_fleet()
        if self.config.MAP_HAS_MYSTERY:
            self.is_mystery = self.predict_mystery()
        self.is_current_fleet = self.predict_current_fleet()

        if self.config.MAP_HAS_MISSILE_ATTACK and self.predict_missile_attack():
            self.is_missile_attack = True
        if self.enemy_genre:
            self.is_enemy = True
        if self.enemy_scale:
            self.is_enemy = True
        if self.is_enemy and not self.enemy_genre:
            self.enemy_genre = "Enemy"
        if self.config.MAP_HAS_SIREN and self.enemy_genre is not None and self.enemy_genre.startswith("Siren"):
            self.is_siren = True
            self.enemy_scale = 0

    def relative_crop(self, area: Area, shape: Size | None = None) -> ImageArray:
        """按相对区域 (x1, y1, x2, y2) 裁剪，并消除透视缩放影响。
        shape 按 (width, height) 传入，输出形状为 (height, width, channel)。
        """
        area = self._image_center + np.array(area) * self._image_a
        image = crop(self.image, area=np.rint(area).astype(int), copy=False)
        if shape is not None:
            # 与 Pillow 默认重采样一致，使用双三次插值。
            image = cv2.resize(image, tuple(int(value) for value in shape), interpolation=cv2.INTER_CUBIC)
        return cast("ImageArray", image)

    def relative_rgb_count(self, area: Area, color: Color, shape: Size = (50, 50), threshold: int = 221) -> int:
        """统计相对区域内匹配目标 RGB 的像素数；threshold 范围为 0～255。"""
        mask = color_similarity_2d(self.relative_crop(area, shape=shape), color=color)
        cv2.inRange(mask, threshold, 255, dst=mask)
        return cv2.countNonZero(mask)

    def relative_hsv_count(
        self,
        area: Area,
        h: tuple[float, float] = (0, 360),
        s: tuple[float, float] = (0, 100),
        v: tuple[float, float] = (0, 100),
        shape: Size = (50, 50),
    ) -> int:
        """统计 HSV 范围内像素数；H 为 0～360，S、V 为 0～100。"""
        image = self.relative_crop(area, shape=shape)
        cv2.cvtColor(image, cv2.COLOR_RGB2HSV, dst=image)
        lower = (h[0] / 2, s[0] * 2.55, v[0] * 2.55)
        upper = (h[1] / 2 + 1, s[1] * 2.55 + 1, v[1] * 2.55 + 1)
        # 这里不能设置 dst，输出是二维掩码，原图是三通道图像。
        image = cv2.inRange(image, lower, upper)
        return cv2.countNonZero(image)

    def predict_enemy_scale(self) -> int:
        """返回敌舰规模：1 小型，2 中型，3 大型，0 未知。"""
        image = self.relative_crop((-0.415 - 0.7, -0.62 - 0.7, -0.415, -0.62), shape=(50, 50))
        red = color_similarity_2d(image, (255, 130, 132))
        yellow = color_similarity_2d(image, (255, 235, 156))

        if template_assets.TEMPLATE_ENEMY_L.match(red, similarity=0.75):
            scale = 3
        elif template_assets.TEMPLATE_ENEMY_M.match(yellow):
            scale = 2
        elif template_assets.TEMPLATE_ENEMY_S.match(yellow):
            scale = 1
        else:
            scale = 0

        return scale

    def _predict_siren_with_boss_icon(self) -> bool:
        if not self.config.MAP_SIREN_HAS_BOSS_ICON:
            return False
        if self.enemy_scale:
            return False
        image = self.relative_crop((-0.55, -0.2, 0.45, 0.2), shape=(50, 20))
        image = color_similarity_2d(image, color=(255, 150, 24))
        return image[image > 221].shape[0] > 200 and template_assets.TEMPLATE_ENEMY_BOSS.match(image, similarity=0.6)

    def _predict_siren_with_small_boss_icon(self) -> bool:
        if not self.config.MAP_SIREN_HAS_BOSS_ICON_SMALL:
            return False
        if self.relative_hsv_count(area=(0.03, -0.15, 0.63, 0.15), h=(32 - 3, 32 + 3), shape=(50, 20)) <= 100:
            return False
        image = self.relative_crop((0.03, -0.15, 0.63, 0.15), shape=(50, 20))
        image = color_similarity_2d(image, color=(255, 150, 33))
        return template_assets.TEMPLATE_ENEMY_BOSS.match(image, similarity=0.7)

    @staticmethod
    def _ensure_enemy_genre_template(name: str, template: Template | None) -> Template:
        if template is not None:
            return template
        message = f"Enemy detection template not found: {name}"
        logger.warning(message)
        logger.warning(MISSING_ENEMY_TEMPLATE_DETAIL)
        raise ScriptError(message)

    def _enemy_genre_scaling(self, name: str) -> tuple[float, ...]:
        short_name = name.removeprefix("Siren_")
        scaling = self.config.MAP_ENEMY_GENRE_DETECTION_SCALING.get(short_name, 1)
        values = scaling if isinstance(scaling, tuple) else (scaling,)
        return tuple(float(value) for value in values)

    def _enemy_genre_image(self, image_dic: dict[float, ImageArray], scale: float) -> ImageArray:
        if scale not in image_dic:
            shape = tuple(np.round(np.array((60, 60)) * scale).astype(int))
            image_dic[scale] = rgb2gray(self.relative_crop((-0.5, -1, 0.5, 0), shape=shape))
        return image_dic[scale]

    def predict_enemy_genre(self) -> str | None:
        if self._predict_siren_with_boss_icon() or self._predict_siren_with_small_boss_icon():
            return "Siren_Siren"

        image_dic = {}
        for name, template in self.template_enemy_genre.items():
            resolved_template = self._ensure_enemy_genre_template(name, template)
            for scale in self._enemy_genre_scaling(name):
                if resolved_template.match(
                    self._enemy_genre_image(image_dic, scale), similarity=self.config.MAP_ENEMY_GENRE_SIMILARITY
                ):
                    return name

        return None

    def predict_boss(self) -> bool:
        if self.enemy_genre == "Siren_Siren":
            return False

        image = self.relative_crop((-0.55, -0.2, 0.45, 0.2), shape=(50, 20))
        image = color_similarity_2d(image, color=(255, 77, 82))
        if template_assets.TEMPLATE_ENEMY_BOSS.match(image, similarity=0.75):
            return True

        if self.relative_hsv_count(area=(0.03, -0.15, 0.63, 0.15), h=(358 - 3, 358 + 3), shape=(50, 20)) > 100:
            image = self.relative_crop((0.03, -0.15, 0.63, 0.15), shape=(50, 20))
            image = color_similarity_2d(image, color=(255, 77, 82))
            if template_assets.TEMPLATE_ENEMY_BOSS.match(image, similarity=0.7):
                return True

        return False

    def predict_missile_attack(self) -> bool:
        return self.relative_rgb_count(area=(-0.5, -1, 0.5, 0), color=(255, 255, 60), shape=(50, 50)) > 35

    def predict_fleet(self) -> bool:
        image = self.relative_crop((-1, -2, -0.5, -1.5), shape=(50, 50))
        image = color_similarity_2d(image, color=(255, 255, 255))
        return template_assets.TEMPLATE_FLEET_AMMO.match(image)

    def predict_submarine(self) -> bool:
        image = self.relative_crop((-0.86, 0.08, -0.36, 0.58), shape=(50, 50))
        image = color_similarity_2d(image, color=(255, 243, 156))
        return template_assets.TEMPLATE_SUBMARINE.match(image)

    def predict_caught_by_siren(self) -> bool:
        image = self.relative_crop((-1, -1.5, 1, 0.5), shape=(120, 120))
        return template_assets.TEMPLATE_CAUGHT_BY_SIREN.match(image, similarity=0.6)

    def predict_mystery(self) -> bool:
        return self.relative_rgb_count(area=(-0.3, -2, 0.3, -0.6), color=(148, 255, 247), shape=(20, 50)) > 50

    def predict_current_fleet(self) -> bool:
        count = self.relative_hsv_count(area=(-0.5, -3.5, 0.5, -2.5), h=(141 - 3, 141 + 10), shape=(50, 50))
        if count < 600:
            return False

        image = self.relative_crop((-0.5, -3.5, 0.5, -2.5), shape=(60, 60))
        image = color_similarity_2d(image, color=(24, 255, 107))
        return template_assets.TEMPLATE_FLEET_CURRENT.match(image)

    def predict_sea(self) -> bool:
        area = area_pad((48, 48, 48 + 46, 48 + 46), pad=5)
        res = cv2.matchTemplate(
            ASSETS.tile_center_image, crop(self.image_homo, area=area, copy=False), cv2.TM_CCOEFF_NORMED
        )
        _, sim, _, _ = cv2.minMaxLoc(res)
        if sim > 0.8:
            return True

        tile = 135
        corner = 25
        corner = [
            (5, 5, corner, corner),
            (tile - corner, 5, tile, corner),
            (5, tile - corner, corner, tile),
            (tile - corner, tile - corner, tile, tile),
        ]
        for area, template in zip(corner[::-1], ASSETS.tile_corner_image_list[::-1], strict=True):
            res = cv2.matchTemplate(template, crop(self.image_homo, area=area, copy=False), cv2.TM_CCOEFF_NORMED)
            _, sim, _, _ = cv2.minMaxLoc(res)
            if sim > 0.8:
                return True

        return False

    def predict_submarine_move(self) -> bool:
        # 潜艇移动模式用橙色箭头标识。
        return self.relative_rgb_count((-0.5, -1, 0.5, 0), color=(231, 138, 49), shape=(60, 60)) > 200

    def predict_mob_move_icon(self) -> bool:
        image = rgb2gray(self.relative_crop(area=(-0.5, -0.5, 0.5, 0.5), shape=(60, 60)))
        return template_assets.TEMPLATE_MOB_MOVE_ICON.match(image)

    def predict_air_strike_icon(self) -> bool:
        image = color_similarity_2d(self.image_trans, color=(255, 255, 160))
        cv2.threshold(image, 175, 255, cv2.THRESH_BINARY, dst=image)
        return template_assets.TEMPLATE_AIR_STRIKE_ICON.match(image, similarity=0.7)

    @cached_property
    def _image_similar_piece(self) -> ImageArray:
        return rgb2gray(self.relative_crop(area=(-0.5, -0.5, 0.5, 0.5), shape=(60, 60)))

    @cached_property
    def _image_similar_full(self) -> ImageArray:
        return rgb2gray(self.relative_crop(area=(-0.6, -0.6, 0.6, 0.6), shape=(72, 72)))

    is_os: bool

    @cached_property
    def is_in_detecting_area(self, area: Area = (-0.5, -0.5, 0.5, 0.5)) -> bool:
        detecting_area = self._image_center + np.asarray(area, dtype=float) * self._image_a
        detecting_area = cast("NumericArray", area_offset(detecting_area, offset=DETECTING_AREA[:2]))
        mask = UI_MASK_OS if self.is_os else UI_MASK
        color = cv2.mean(crop(mask.image, area=np.rint(detecting_area).astype(int), copy=False))
        return color[0] > 235

    def is_similar_to(self, grid: GridPredictor, similarity: float = 0.9) -> bool:
        """比较两个格子的截图，相似度阈值范围为 0～1。"""
        if not self.is_in_detecting_area or not grid.is_in_detecting_area:
            return False
        piece_1 = self._image_similar_piece
        piece_2 = grid.image_similar_full
        res = cv2.matchTemplate(piece_2, piece_1, cv2.TM_CCOEFF_NORMED)
        sim = cv2.minMaxLoc(res)[1]
        return sim > similarity

    @property
    def image_similar_full(self) -> ImageArray:
        return self._image_similar_full
