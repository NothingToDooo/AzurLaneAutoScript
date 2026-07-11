from typing import TYPE_CHECKING

from module.base.utils import area_pad, crop, rgb2gray
from module.research import assets as research_assets

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.base.button import Button
    from module.base.type_alias import ImageArray

RESEARCH_SERIES = (
    research_assets.SERIES_1,
    research_assets.SERIES_2,
    research_assets.SERIES_3,
    research_assets.SERIES_4,
    research_assets.SERIES_5,
)
RESEARCH_SCALING = [
    424 / 558,
    491 / 558,
    1.0,
    491 / 558,
    424 / 558,
]
RESEARCH_SERIES_TEMPLATES = (
    (research_assets.TEMPLATE_S9, 9),
    (research_assets.TEMPLATE_S8, 8),
    (research_assets.TEMPLATE_S7, 7),
    (research_assets.TEMPLATE_S6, 6),
    (research_assets.TEMPLATE_S4_2, 4),
    (research_assets.TEMPLATE_S4, 4),
    (research_assets.TEMPLATE_S5, 5),
    (research_assets.TEMPLATE_S3, 3),
    (research_assets.TEMPLATE_S2, 2),
    (research_assets.TEMPLATE_S1, 1),
)


def match_series(image: ImageArray, scaling: float) -> int:
    image = rgb2gray(image)

    for template, series in RESEARCH_SERIES_TEMPLATES:
        if template.match(image, scaling=scaling):
            return series
    return 0


def get_research_series_3(
    image: ImageArray,
    series_button: Sequence[Button] = RESEARCH_SERIES,
) -> list[int]:
    return [
        match_series(crop(image, area_pad(button.area, pad=-10), copy=False), scaling)
        for scaling, button in zip(RESEARCH_SCALING, series_button, strict=True)
    ]


def get_detail_series(image: ImageArray) -> int:
    return match_series(crop(image, area_pad(research_assets.SERIES_DETAIL.area, pad=-30), copy=False), scaling=1.0)
