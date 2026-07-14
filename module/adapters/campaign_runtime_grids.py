from typing import TYPE_CHECKING, ClassVar, override

from module.base.utils import color_similarity_2d
from module.map_detection.grid import Grid
from module.map_detection.grid_info import GridInfo
from module.template.assets import TEMPLATE_ENEMY_BOSS, TEMPLATE_FLEET_CURRENT

if TYPE_CHECKING:
    from module.map.type_alias import GridMode


class W15BossAsSirenGrid(GridInfo):
    """十五图把海面上的 Boss 图标并入 Siren 识别结果。"""

    @override
    def merge(self, info: GridInfo, mode: GridMode = "normal") -> bool:
        if info.is_boss and not self.is_land and self.may_siren:
            self.is_siren = True
            self.enemy_scale = 0
            self.enemy_genre = ""
            return True
        return super().merge(info, mode=mode)


class BossIconAsSirenGrid(Grid):
    """把活动小型 Boss 图标识别为 Siren，避免后续 Boss 二次判定。"""

    BOSS_ICON_COLOR: ClassVar[tuple[int, int, int]] = (255, 150, 24)

    @override
    def predict_enemy_genre(self) -> str | None:
        if self.enemy_scale:
            return ""

        image = self.relative_crop((0, -0.2, 0.8, 0.2), shape=(40, 20))
        image = color_similarity_2d(image, color=self.BOSS_ICON_COLOR)
        if image[image > 221].shape[0] > 30 and TEMPLATE_ENEMY_BOSS.match(
            image,
            similarity=0.6,
            scaling=0.5,
        ):
            return "Siren_Siren"
        return super().predict_enemy_genre()

    @override
    def predict_boss(self) -> bool:
        if self.enemy_genre == "Siren_Siren":
            return False
        return super().predict_boss()


class WarmBossIconAsSirenGrid(BossIconAsSirenGrid):
    """使用偏暖颜色的活动小型 Boss 图标。"""

    BOSS_ICON_COLOR = (255, 190, 84)


class BossIconAsSirenWithCurrentFleetGrid(BossIconAsSirenGrid):
    """同时处理大型 Boss 遮挡当前舰队模板的地图。"""

    @override
    def predict_current_fleet(self) -> bool:
        count = self.relative_hsv_count(
            area=(-0.5, -3.5, 0.5, -2.5),
            h=(138, 151),
            shape=(50, 50),
        )
        return count >= 200


class CurrentFleetColorGrid(Grid):
    """只使用当前舰队标识的颜色像素数进行识别。"""

    CURRENT_FLEET_MIN_PIXELS: ClassVar[int] = 200

    @override
    def predict_current_fleet(self) -> bool:
        count = self.relative_hsv_count(
            area=(-0.5, -3.5, 0.5, -2.5),
            h=(138, 151),
            shape=(50, 50),
        )
        return count >= self.CURRENT_FLEET_MIN_PIXELS


class StrongCurrentFleetColorGrid(CurrentFleetColorGrid):
    """活动底图噪声较强时使用更高的颜色像素阈值。"""

    CURRENT_FLEET_MIN_PIXELS = 600


class WeakCurrentFleetTemplateGrid(Grid):
    """弱舰队标识先用颜色预筛，再用模板确认。"""

    @override
    def predict_current_fleet(self) -> bool:
        count = self.relative_hsv_count(
            area=(-0.5, -3.5, 0.5, -2.5),
            h=(138, 151),
            shape=(50, 50),
        )
        if count < 150:
            return False

        image = self.relative_crop((-0.5, -3.5, 0.5, -2.5), shape=(60, 60))
        image = color_similarity_2d(image, color=(24, 255, 107))
        return TEMPLATE_FLEET_CURRENT.match(image)
