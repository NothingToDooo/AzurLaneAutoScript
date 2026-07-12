from module.base.utils import color_similarity_2d
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.map_detection.grid import Grid
from module.template.assets import TEMPLATE_ENEMY_BOSS


class EventGrid(Grid):
    def predict_enemy_genre(self) -> str | None:
        if self.enemy_scale:
            return ""

        image = self.relative_crop((-0, -0.2, 0.8, 0.2), shape=(40, 20))
        image = color_similarity_2d(image, color=(255, 150, 24))
        if image[image > 221].shape[0] > 30 and TEMPLATE_ENEMY_BOSS.match(image, similarity=0.6, scaling=0.5):
            return "Siren_Siren"

        return super().predict_enemy_genre()

    def predict_boss(self) -> bool:
        if self.enemy_genre == "Siren_Siren":
            return False
        return super().predict_boss()

    def predict_current_fleet(self) -> bool:
        count = self.relative_hsv_count(area=(-0.5, -3.5, 0.5, -2.5), h=(141 - 3, 141 + 10), shape=(50, 50))
        # B1 的大型首领会遮住舰队模板，这里只用颜色阈值判断。
        return count >= 200


class CampaignBase(CampaignBase_):
    grid_class = EventGrid
