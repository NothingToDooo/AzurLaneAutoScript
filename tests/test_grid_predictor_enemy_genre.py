from typing import ClassVar

import numpy as np

from module.map_detection import grid_predictor
from module.map_detection.grid_predictor import GridPredictor


class FakeConfig:
    MAP_SIREN_HAS_BOSS_ICON = False
    MAP_SIREN_HAS_BOSS_ICON_SMALL = False
    MAP_ENEMY_GENRE_DETECTION_SCALING: ClassVar[dict[str, object]] = {}
    MAP_ENEMY_GENRE_SIMILARITY = 0.93


class FakeTemplate:
    def __init__(self, matches=False):
        self.matches = matches
        self.calls = []

    def match(self, image, similarity=None):
        self.calls.append((image, similarity))
        if isinstance(self.matches, set):
            return image in self.matches
        return self.matches


class FakePredictor(GridPredictor):
    def __init__(self, config, templates, hsv_count=0):
        self.config = config
        self.template_enemy_genre = templates
        self.enemy_scale = 0
        self.hsv_count = hsv_count
        self.crops = []
        self.hsv_kwargs = None

    def relative_crop(self, area, shape):
        normalized_shape = tuple(int(value) for value in shape)
        self.crops.append((area, normalized_shape))
        return normalized_shape

    def relative_hsv_count(self, **kwargs):
        self.hsv_kwargs = kwargs
        return self.hsv_count


def test_predict_enemy_genre_detects_siren_boss_icon(monkeypatch) -> None:
    class BossConfig(FakeConfig):
        MAP_SIREN_HAS_BOSS_ICON = True

    boss_template = FakeTemplate(matches=True)

    def fake_color_similarity(image, color):
        assert image == (50, 20)
        assert color == (255, 150, 24)
        return np.full((50, 20), 255, dtype=np.uint8)

    monkeypatch.setattr(grid_predictor.template_assets, "TEMPLATE_ENEMY_BOSS", boss_template)
    monkeypatch.setattr(grid_predictor, "color_similarity_2d", fake_color_similarity)
    predictor = FakePredictor(BossConfig, templates={"Enemy": FakeTemplate(matches=False)})

    assert predictor.predict_enemy_genre() == "Siren_Siren"
    assert len(boss_template.calls) == 1
    image, similarity = boss_template.calls[0]
    assert np.array_equal(image, np.full((50, 20), 255, dtype=np.uint8))
    assert similarity == 0.6


def test_predict_enemy_genre_reuses_scaled_detection_image(monkeypatch) -> None:
    class ScalingConfig(FakeConfig):
        MAP_ENEMY_GENRE_DETECTION_SCALING: ClassVar[dict[str, object]] = {"Light": (1, 2), "Main": 1}

    monkeypatch.setattr(grid_predictor, "rgb2gray", lambda image: image)
    templates = {
        "Siren_Light": FakeTemplate(matches=False),
        "Main": FakeTemplate(matches={(60, 60)}),
    }
    predictor = FakePredictor(ScalingConfig, templates=templates)

    assert predictor.predict_enemy_genre() == "Main"
    assert [shape for _, shape in predictor.crops] == [(60, 60), (120, 120)]
    assert templates["Main"].calls == [((60, 60), 0.93)]
