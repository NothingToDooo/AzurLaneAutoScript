from typing import TYPE_CHECKING, ClassVar

import numpy as np

from module.base.template import Template
from module.map_detection import grid_predictor
from module.map_detection.grid_predictor import GridPredictor

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest

    from module.base.type_alias import Area, Color, ImageArray, Size


class FakeConfig:
    MAP_SIREN_HAS_BOSS_ICON = False
    MAP_SIREN_HAS_BOSS_ICON_SMALL = False
    MAP_ENEMY_GENRE_DETECTION_SCALING: ClassVar[dict[str, object]] = {}
    MAP_ENEMY_GENRE_SIMILARITY = 0.93


class FakeTemplate(Template):
    def __init__(self, *, matches: bool | set[tuple[int, int]] = False) -> None:
        self.matches = matches
        self.calls: list[tuple[tuple[int, ...], float]] = []

    def match(self, image: ImageArray, scaling: float = 1.0, similarity: float = 0.85) -> bool:
        del scaling
        shape = tuple(int(value) for value in image.shape)
        self.calls.append((shape, similarity))
        if isinstance(self.matches, set):
            return shape in self.matches
        return self.matches


class FakePredictor(GridPredictor):
    def __init__(
        self,
        config: type[FakeConfig],
        templates: Mapping[str, Template | None],
        hsv_count: int = 0,
    ) -> None:
        self.config = config
        self.template_enemy_genre = dict(templates)
        self.enemy_scale = 0
        self.hsv_count = hsv_count
        self.crops = []
        self.hsv_kwargs = None

    def relative_crop(
        self,
        area: Area,
        shape: Size | None = None,
    ) -> ImageArray:
        if shape is None:
            shape = (1, 1)
        normalized_shape = tuple(int(value) for value in shape)
        self.crops.append((area, normalized_shape))
        return np.zeros(normalized_shape, dtype=np.uint8)

    def relative_hsv_count(
        self,
        area: Area,
        h: tuple[float, float] = (0, 360),
        s: tuple[float, float] = (0, 100),
        v: tuple[float, float] = (0, 100),
        shape: Size = (50, 50),
    ) -> int:
        self.hsv_kwargs = {"area": area, "h": h, "s": s, "v": v, "shape": shape}
        return self.hsv_count


def test_predict_enemy_genre_detects_siren_boss_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    class BossConfig(FakeConfig):
        MAP_SIREN_HAS_BOSS_ICON = True

    boss_template = FakeTemplate(matches=True)

    def fake_color_similarity(image: ImageArray, color: Color) -> ImageArray:
        assert image.shape == (50, 20)
        assert color == (255, 150, 24)
        return np.full((50, 20), 255, dtype=np.uint8)

    monkeypatch.setattr(grid_predictor.template_assets, "TEMPLATE_ENEMY_BOSS", boss_template)
    monkeypatch.setattr(grid_predictor, "color_similarity_2d", fake_color_similarity)
    predictor = FakePredictor(BossConfig, templates={"Enemy": FakeTemplate(matches=False)})

    assert predictor.predict_enemy_genre() == "Siren_Siren"
    assert len(boss_template.calls) == 1
    image_shape, similarity = boss_template.calls[0]
    assert image_shape == (50, 20)
    assert similarity == 0.6


def test_predict_enemy_genre_reuses_scaled_detection_image(monkeypatch: pytest.MonkeyPatch) -> None:
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
